/* Track B client — the organic image/text→3D pipeline (track_b/server.py).
 *
 * Every action is an ASYNC JOB: POST a route → {job_id}, then poll GET /job/<id> with short requests
 * until {status: done|error|cancelled}. A hero generation runs minutes but Cloudflare quick-tunnels cut
 * any single request at ~100s, so the submit-then-poll shape keeps every round-trip tunnel-safe.
 *
 * Same-origin by default: one Caddy proxy maps /api/trackb/* → the Track B service (:8770). Override the
 * base with VITE_TRACKB_API for a direct-port dev setup. */

const BASE = (import.meta as any).env?.VITE_TRACKB_API || `${location.origin}/api/trackb`;

// Studio quality-tier label → backend pipeline_type (512 fast eval … 1536_cascade hero, 4K PBR).
export const TIER_PTYPE: Record<string, string> = {
  Preview: "512", Standard: "1024", High: "1024_cascade", "Max detail": "1536_cascade",
};

export interface MeshReport { faces: number; verts: number; watertight: boolean; pbr: string[]; size_mb: number; }
export interface MeshResult {
  glb_b64: string; report: MeshReport; pipeline_type?: string; seconds?: number; concept_png_b64?: string; biome?: string;
}
export interface RenderResult { beauty_png_b64: string | null; turntable_mp4_b64?: string; seconds?: number; }
export interface AnimateResult { animated_mp4_b64: string | null; seconds?: number; variant?: string; }

export type Progress = (stage: string, elapsed: number, conceptB64?: string, mvViews?: string[]) => void;
export type ShouldCancel = () => boolean;

async function submit(route: string, body: any): Promise<string> {
  const res = await fetch(BASE + route, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error((e as any).error || `HTTP ${res.status}`); }
  return (await res.json()).job_id;
}

/** Tell the server to abort the running GPU job (not just stop polling). Fire-and-forget. */
function cancelJob(jobId: string): void {
  fetch(`${BASE}/cancel/${jobId}`, { method: "POST" }).catch(() => {});
}

async function poll(jobId: string, onProgress?: Progress, shouldCancel?: ShouldCancel): Promise<any> {
  for (;;) {
    await new Promise((r) => setTimeout(r, 2500));
    if (shouldCancel?.()) { cancelJob(jobId); throw new Error("cancelled"); }
    let j: any;
    try {
      const res = await fetch(`${BASE}/job/${jobId}`);
      if (!res.ok) { if (res.status === 404) throw new Error("job expired"); continue; }  // transient → keep polling
      j = await res.json();
    } catch (e: any) {
      if (e?.message === "job expired") throw e;
      continue;   // network blip → the job keeps running server-side
    }
    if (shouldCancel?.()) { cancelJob(jobId); throw new Error("cancelled"); }
    if (j.status === "running" || j.status === "queued") { onProgress?.(j.stage, j.elapsed || 0, j.concept_png_b64, j.mv_views_b64); continue; }
    if (j.status === "error") throw new Error(j.error || "generation failed");
    if (j.status === "cancelled") throw new Error("cancelled");
    if (j.status === "done") return j;
  }
}

async function run(route: string, body: any, onProgress?: Progress, shouldCancel?: ShouldCancel): Promise<any> {
  const jobId = await submit(route, body);
  return poll(jobId, onProgress, shouldCancel);
}

/** text prompt → FLUX concept → TRELLIS GLB (with PBR). */
export const text2mesh = (prompt: string, tier: string, multiview: boolean, onP?: Progress, sc?: ShouldCancel): Promise<MeshResult> =>
  run("/text2mesh", { prompt, pipeline_type: TIER_PTYPE[tier] || "1024", ...(multiview ? { multiview: true } : {}) }, onP, sc);

/** uploaded reference image (base64) → TRELLIS GLB. */
export const image2mesh = (imageB64: string, tier: string, multiview: boolean, onP?: Progress, sc?: ShouldCancel, prompt?: string): Promise<MeshResult> =>
  // prompt rides along for the MULTI-VIEW stage: MV-Adapter with an empty text falls back to
  // "a detailed high quality sculpture", which visibly DESATURATES the views (measured 06-29)
  run("/image2mesh", { image_b64: imageB64, pipeline_type: TIER_PTYPE[tier] || "1024",
                       ...(multiview ? { multiview: true } : {}), ...(prompt ? { prompt } : {}) }, onP, sc);

/** decimate a GLB to a face budget (game-ready). */
export const lowpoly = (glbB64: string, targetFaces: number, onP?: Progress, sc?: ShouldCancel): Promise<MeshResult> =>
  run("/lowpoly", { glb_b64: glbB64, target_faces: targetFaces }, onP, sc);

/** printability gate + repair loop (Slice 2) → repaired GLB + honest pass/fail + before/after reports. */
export const repair = (glbB64: string, profile: "print" | "render" = "print", onP?: Progress, sc?: ShouldCancel): Promise<any> =>
  run("/repair", { glb_b64: glbB64, profile }, onP, sc);

/** auto-rig a mesh GLB (SkinTokens): skeleton + skin weights → game-ready rigged GLB, gated by
 * deterministic rig rows (single root, bone budget, ≤4 influences/vertex). GPU job, ~1–2 min. */
export const rig = (glbB64: string, onP?: Progress, sc?: ShouldCancel): Promise<any> =>
  run("/rig", { glb_b64: glbB64 }, onP, sc);

/** animation clip on a RIGGED mesh — text prompt (LTX video → motion optimizer) or a reference
 * MP4 → the same rigged GLB with an embedded animation track. */
export const animateClip = (glbB64: string, opts: { prompt?: string; mp4B64?: string }, onP?: Progress, sc?: ShouldCancel): Promise<any> =>
  run("/animate_clip", { glb_b64: glbB64, ...(opts.prompt ? { prompt: opts.prompt } : {}),
                         ...(opts.mp4B64 ? { mp4_b64: opts.mp4B64 } : {}) }, onP, sc);

/** Infinigen terrain tile for a biome → vertex-colored GLB. Heavy (~5–6 min). */
export const terrain = (biome: string, targetFaces: number, onP?: Progress, sc?: ShouldCancel): Promise<MeshResult> =>
  run("/terrain", { biome, target_faces: targetFaces }, onP, sc);

/** photoreal Cycles beauty still + turntable MP4 from a GLB. */
export const render = (glbB64: string, onP?: Progress, sc?: ShouldCancel): Promise<RenderResult> =>
  run("/render", { glb_b64: glbB64, samples: 160, res: 1600, turn_frames: 36 }, onP, sc);

/** LTX render-to-real motion clip from a turntable + its first frame. */
export const animate = (turntableMp4B64: string, firstFramePngB64: string, prompt: string, variant: string, onP?: Progress, sc?: ShouldCancel): Promise<AnimateResult> =>
  run("/animate", { turntable_mp4_b64: turntableMp4B64, first_frame_png_b64: firstFramePngB64, prompt, variant }, onP, sc);

/* ---------------- Track A (CAD) client — the parametric pipeline behind /api/cad ----------------
 * Same async submit→poll shape (Cloudflare-tunnel-safe), but the CAD server's /job/<id> response is
 * FLAT: {status, passed, attempts, history, code, spec, inspection, mesh_stl_b64, step_b64, ...} for
 * parts, plus {assembly, components} for /plan. No server-side cancel exists — shouldCancel stops
 * polling and abandons the job (it finishes harmlessly server-side). */

const CAD_BASE = (import.meta as any).env?.VITE_CAD_API || `${location.origin}/api/cad`;

export interface CadRow { name: string; expected: any; measured: any; delta: number | null; within_tol: boolean; category: string; }
export interface CadJob {
  status: string; passed: boolean; attempts?: number; history?: any[]; fallback?: boolean;
  code?: string | null; spec?: any; inspection: CadRow[]; mesh_stl_b64?: string | null; step_b64?: string | null;
  assembly?: any; components?: number; seconds: number;
  display_name?: string | null;    // LLM-named library-card title (fallback: prompt truncation)
}

/** Ask the serve for a clean 2-4 word library-card name (~1s). Null on any failure. */
export async function cadName(prompt: string): Promise<string | null> {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 28000);
    const res = await fetch(CAD_BASE + "/name", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }), signal: ctl.signal,
    });
    clearTimeout(t);
    if (!res.ok) return null;
    return ((await res.json()) as any).name || null;
  } catch { return null; }
}

/** The dashboard dice — one playful buildable brief from the serve (~1-2s, null on failure). */
export async function cadSuggest(track: string): Promise<string | null> {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 25000);
    const res = await fetch(CAD_BASE + "/suggest", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track }), signal: ctl.signal,
    });
    clearTimeout(t);
    if (!res.ok) return null;
    return ((await res.json()) as any).brief || null;
  } catch { return null; }
}

/** The CAD generation-theater feed — everything the server publishes mid-job:
 * stage/attempt labels, the parsed spec (parts) or the token-streamed assembly spec (planner),
 * the locked assembly JSON, and the per-part STLs as build_assembly places them. */
export interface CadPart { name: string; role?: string | null; stl_b64: string; revised?: boolean; }
export interface CadLive {
  stage: string; elapsed: number; attempt?: number;
  spec?: any;              // /generate: the parsed Spec (published the moment the parser returns)
  specStream?: string;     // /plan, /edit: the assembly JSON growing token by token
  assembly?: any;          // the locked assembly (after plan/patch, before verify)
  newParts?: CadPart[];    // per-part construction stream (only the ones not yet delivered)
}
export type CadLiveFn = (p: CadLive) => void;

export async function cadRun(route: "/generate" | "/plan" | "/edit", body: any,
                             onLive?: CadLiveFn, shouldCancel?: ShouldCancel): Promise<CadJob> {
  const res = await fetch(CAD_BASE + route, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error((e as any).error || `HTTP ${res.status}`); }
  const jobId = (await res.json()).job_id;
  const t0 = Date.now();
  let partsFetched = 0;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    if (shouldCancel?.()) throw new Error("cancelled");
    let j: any;
    try {
      const r = await fetch(`${CAD_BASE}/job/${jobId}?parts_after=${partsFetched}`);
      if (!r.ok) { if (r.status === 404) throw new Error("job expired"); continue; }
      j = await r.json();
    } catch (e: any) {
      if (e?.message === "job expired") throw e;
      continue;   // network blip — the job keeps running server-side
    }
    if (j.status === "running" || j.status === "queued") {
      const newParts: CadPart[] = Array.isArray(j.parts) ? j.parts : [];
      partsFetched += newParts.length;
      onLive?.({
        stage: j.stage || (route === "/plan" ? "planning parts" : route === "/edit" ? "applying edit" : "generating"),
        elapsed: j.elapsed ?? (Date.now() - t0) / 1000,
        attempt: j.attempt, spec: j.spec, specStream: j.spec_stream, assembly: j.assembly,
        newParts: newParts.length ? newParts : undefined,
      });
      continue;
    }
    if (j.status === "error") throw new Error(j.error || "CAD job failed");
    j.seconds = (Date.now() - t0) / 1000;
    return j as CadJob;
  }
}

/* ---------------- Engine (Track A+B merge) client — /engine via /api/cad ----------------
 * The unified router: a prompt (or a full model_brief/assembly_brief) → per-part representation
 * dispatch (CAD / library / TRELLIS / Blender) → per-rep verify → hybrid merge → repair loop.
 * Same async-job contract as cadRun. */
export interface EngineJob {
  status: string; kind: "part" | "assembly"; passed: boolean; seconds: number;
  representation?: string; report?: any; reason?: string;                 // kind: part
  rounds?: number; feedback?: string[]; rows?: CadRow[]; reps?: Record<string, string>; placements?: any;  // kind: assembly
}

/* ---------------- Studio user service (/api/studio → studio_api/server.py :8092) ----------------
 * Real auth + per-user projects/model library. Opaque bearer token in localStorage; every request
 * carries it. Model LIST returns light metadata (thumb + inspection, no meshes); the full artifact
 * payload (STL/STEP/GLB/code/spec/assembly/parts) is fetched per model on open. */

const STUDIO_BASE = (import.meta as any).env?.VITE_STUDIO_API || `${location.origin}/api/studio`;
const TOKEN_KEY = "mlk-token";

export function getToken(): string | null { return localStorage.getItem(TOKEN_KEY); }
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function sreq(method: string, path: string, body?: any, timeoutMs = 30000): Promise<any> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(STUDIO_BASE + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
    });
  } catch (e: any) {
    throw new Error(e?.name === "AbortError" ? "request timed out" : String(e?.message || e));
  } finally {
    clearTimeout(t);
  }
  const j = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err: any = new Error((j as any).error || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return j;
}

export interface StudioUser { email: string; first: string; last: string; }

export const studio = {
  signup: (email: string, password: string, first: string, last: string) =>
    sreq("POST", "/signup", { email, password, first, last }) as Promise<{ token: string; user: StudioUser }>,
  login: (email: string, password: string) =>
    sreq("POST", "/login", { email, password }) as Promise<{ token: string; user: StudioUser }>,
  logout: () => sreq("POST", "/logout").catch(() => ({})),
  me: () => sreq("GET", "/me") as Promise<{ user: StudioUser }>,
  updateMe: (patch: { first?: string; last?: string; password?: string }) =>
    sreq("PATCH", "/me", patch) as Promise<{ user: StudioUser }>,
  projects: () => sreq("GET", "/projects") as Promise<{ projects: { name: string; models: number; ts: number }[] }>,
  createProject: (name: string) => sreq("POST", "/projects", { name }) as Promise<{ name: string }>,
  deleteProject: (name: string) =>
    sreq("DELETE", `/projects/${encodeURIComponent(name)}`, undefined, 60000) as Promise<{ deleted_models: number }>,
  models: (project?: string) =>
    sreq("GET", "/models" + (project ? `?project=${encodeURIComponent(project)}` : "")) as Promise<{ models: any[] }>,
  model: (id: string) => sreq("GET", `/models/${id}`, undefined, 120000) as Promise<any>,
  // artifact payloads can be tens of MB over the tunnel — give uploads a long leash
  saveModel: (m: any) => sreq("POST", "/models", m, 600000) as Promise<{ id: string }>,
  updateModel: (id: string, patch: { project?: string; name?: string }) =>
    sreq("PATCH", `/models/${id}`, patch) as Promise<{}>,
  deleteModel: (id: string) => sreq("DELETE", `/models/${id}`) as Promise<{}>,
  reportBug: (r: { description: string; image_b64?: string | null; mime?: string; context?: any }) =>
    sreq("POST", "/bugs", r, 60000) as Promise<{ id: string }>,
};

/* ---------------- Engine health — drives the header status pills ----------------
 * CAD (:8765) answers {ok, jobs}; Track B (:8770) answers {ok, jobs}. NOTE (ops lesson): Track B's
 * HTTP server binds before the TRELLIS weights finish loading, so ok:true means "reachable", not
 * "warm" — the pill copy says online/offline, and a first job may still queue behind the warmup.
 * The Assembly pill shares the CAD process (same server, /plan route). */
export type EngineHealth = "online" | "offline";
export async function health(base: "cad" | "trackb"): Promise<EngineHealth> {
  const url = (base === "cad" ? CAD_BASE : BASE) + "/health";
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 4000);
    const res = await fetch(url, { signal: ctl.signal });
    clearTimeout(t);
    if (!res.ok) return "offline";
    const j = await res.json().catch(() => ({}));
    return (j as any).ok ? "online" : "offline";
  } catch { return "offline"; }
}

export async function engineRun(input: { prompt?: string; brief?: any }, onProgress?: Progress,
                                shouldCancel?: ShouldCancel): Promise<EngineJob> {
  const res = await fetch(CAD_BASE + "/engine", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error((e as any).error || `HTTP ${res.status}`); }
  const jobId = (await res.json()).job_id;
  const t0 = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 1800));
    if (shouldCancel?.()) throw new Error("cancelled");
    let j: any;
    try {
      const r = await fetch(`${CAD_BASE}/job/${jobId}`);
      if (!r.ok) { if (r.status === 404) throw new Error("job expired"); continue; }
      j = await r.json();
    } catch (e: any) {
      if (e?.message === "job expired") throw e;
      continue;
    }
    if (j.status === "running" || j.status === "queued") { onProgress?.("routing + building parts", (Date.now() - t0) / 1000); continue; }
    if (j.status === "error") throw new Error(j.error || "engine job failed");
    j.seconds = (Date.now() - t0) / 1000;
    return j as EngineJob;
  }
}
