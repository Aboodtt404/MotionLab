/* Bridge to the Track A pipeline (cad_pipeline/server.py). Converts the Studio Spec to
 * the backend contract, POSTs /generate, and returns the REAL verifier report + mesh. */
import type { InspectionRow, Spec } from "./types";

// Same-origin API paths so one reverse proxy (Caddy) + one Cloudflare tunnel serves the whole app:
// the proxy maps /api/cad/* → the cad backend (:8765) and /api/trackb/* → Track B (:8770). Override
// with VITE_CAD_API for a direct-port setup.
const API_BASE = (import.meta as any).env?.VITE_CAD_API || `${location.origin}/api/cad`;

export interface BackendRow {
  name: string; expected: number | string; measured: number | string | null;
  delta: number | null; within_tol: boolean; category: string;
}
export interface GenerateResponse {
  passed: boolean; attempts: number; history: any[]; code: string | null;
  spec?: any; // the interpreted backend spec (when generated from a prompt)
  inspection: BackendRow[]; mesh_stl_b64: string | null; step_b64?: string | null;
}

/** Studio Spec ({type,params}) → backend Spec (flat feature fields). Editor stores position as
 * scalar pos_x/pos_y for the generic number renderer; the backend wants an `at:[x,y]` tuple. */
export function specToBackend(spec: Spec): any {
  const features = spec.features.map((f) => {
    const { pos_x, pos_y, ...rest } = f.params as Record<string, any>;
    const out: any = { type: f.type, ...rest };
    if (pos_x !== undefined && pos_y !== undefined) out.at = [Number(pos_x), Number(pos_y)];
    return out;
  });
  return {
    object: spec.object,
    shape: spec.shape,
    envelope: spec.envelope,
    features,
    tolerance: spec.tolerance,
    ...(spec.fabrication ? { fabrication: spec.fabrication } : {}),
    ...(spec.min_wall ? { min_wall: spec.min_wall } : {}),
    ...(spec.profile ? { profile: spec.profile } : {}),
    ...(spec.path ? { path: spec.path } : {}),
  };
}

/** Backend verifier rows → the flat InspectionRow the ResultCard renders. */
export function toInspection(rows: BackendRow[], tol: number): InspectionRow[] {
  return rows.map((r) => {
    const req = typeof r.expected === "number" ? r.expected.toFixed(2) : String(r.expected);
    const meas = r.measured == null ? "—" : typeof r.measured === "number" ? r.measured.toFixed(2) : String(r.measured);
    const delta = typeof r.delta === "number" ? r.delta : 0;
    const left = Math.max(4, Math.min(96, 50 + (delta / (2 * (tol || 0.1))) * 50));
    return { name: r.name, req, meas, pass: r.within_tol, gaugeLeft: left.toFixed(1) + "%" };
  });
}

// Track A is async too now — the planner + model codegen can exceed Cloudflare's 100s tunnel limit, so
// POST enqueues a job ({job_id}) and we poll GET /job/<id> with short requests until it's done.
async function post(body: any, route = "/generate"): Promise<any> {
  const sub = await fetch(API_BASE + route, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!sub.ok) { const txt = await sub.text().catch(() => ""); throw new Error(`backend ${sub.status}: ${txt.slice(0, 200)}`); }
  const { job_id } = await sub.json();
  for (;;) {
    await new Promise((r) => setTimeout(r, 2000));
    let res: Response;
    try { res = await fetch(`${API_BASE}/job/${job_id}`); } catch { continue; }  // network blip → keep polling
    if (res.status === 404) throw new Error("job expired");
    if (!res.ok) continue;
    const j = await res.json();
    if (j.status === "error") throw new Error(j.error || "generation failed");
    if (j.status === "done") return j;   // running → keep polling
  }
}

/** Generate from a typed spec (right-panel editor / image mode). */
export const generateBackend = (spec: Spec, useModel = false, maxAttempts = 3): Promise<GenerateResponse> =>
  post({ spec: specToBackend(spec), use_model: useModel, max_attempts: maxAttempts });

/** Generate from a natural-language prompt — the model interprets it into a spec (Track A text→spec). */
export const generateFromPrompt = (prompt: string, useModel = false, maxAttempts = 3): Promise<GenerateResponse> =>
  post({ prompt, use_model: useModel, max_attempts: maxAttempts });

export interface AssemblyResponse {
  passed: boolean; assembly: any; components: number; object: string;
  inspection: BackendRow[]; mesh_stl_b64: string | null; step_b64?: string | null;
}
/** PLAN a multi-part assembly from a prompt (the planner). */
export const planAssembly = (prompt: string): Promise<AssemblyResponse> => post({ prompt }, "/plan");
/** EDIT the current assembly with an instruction (the edit-loop). */
export const editAssembly = (assembly: any, instruction: string): Promise<AssemblyResponse> =>
  post({ assembly, instruction }, "/edit");

/* ── Track B (organic): image → 3D mesh via the TRELLIS.2 service (separate port). ───────────── */
const TRACKB_BASE = (import.meta as any).env?.VITE_TRACKB_API || `${location.origin}/api/trackb`;
export interface MeshResponse {
  glb_b64: string | null;
  report: { faces: number; verts: number; watertight: boolean; pbr: string[]; size_mb: number };
  seconds?: number;
  pipeline_type?: string;
  concept_png_b64?: string;   // text→mesh only: the FLUX intermediate the UI can preview
}
export type MeshProgress = (stage: string, elapsed: number) => void;

// Track B generations run minutes (hero TRELLIS tiers), but Cloudflare quick-tunnels cut any single
// request at ~100s. So we SUBMIT a job (returns instantly) then POLL short GET requests until done —
// each round-trip stays under the tunnel limit, so arbitrarily-long generations work over the tunnel.
async function _submit(route: string, body: any): Promise<string> {
  const res = await fetch(TRACKB_BASE + route, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.error || `HTTP ${res.status}`); }
  return (await res.json()).job_id;
}

/** Tell the server to actually abort the running job (not just stop polling). Fire-and-forget. */
function _cancel(jobId: string): void {
  fetch(`${TRACKB_BASE}/cancel/${jobId}`, { method: "POST" }).catch(() => {});
}

async function _poll(jobId: string, onProgress?: MeshProgress, shouldCancel?: () => boolean): Promise<MeshResponse> {
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    if (shouldCancel?.()) { _cancel(jobId); throw new Error("cancelled"); }   // abort the GPU job, not just polling
    let j: any;
    try {
      const res = await fetch(`${TRACKB_BASE}/job/${jobId}`);
      if (!res.ok) { if (res.status === 404) throw new Error("job expired"); continue; } // transient → keep polling
      j = await res.json();
    } catch { continue; }   // network blip → keep polling (the job keeps running server-side)
    if (shouldCancel?.()) { _cancel(jobId); throw new Error("cancelled"); }
    if (j.status === "running" || j.status === "queued") { onProgress?.(j.stage, j.elapsed || 0); continue; }
    if (j.status === "error") throw new Error(j.error || "generation failed");
    if (j.status === "cancelled") throw new Error("cancelled");
    if (j.status === "done") return j as MeshResponse;
  }
}

/** Organic image-to-3D: base64 image → a GLB (with PBR). pipelineType '512' … '1536_cascade' (max). */
export async function generateMesh(imageB64: string, pipelineType = "1536_cascade", onProgress?: MeshProgress, seed?: number, shouldCancel?: () => boolean, multiview = false): Promise<MeshResponse> {
  const jobId = await _submit("/image2mesh", { image_b64: imageB64, pipeline_type: pipelineType, ...(seed != null ? { seed } : {}), ...(multiview ? { multiview: true } : {}) });
  return _poll(jobId, onProgress, shouldCancel);
}

/** Organic text-to-3D: prompt → FLUX concept image → TRELLIS GLB. The chat/description-driven path. */
export async function generateMeshFromText(prompt: string, pipelineType = "1536_cascade", onProgress?: MeshProgress, seed?: number, shouldCancel?: () => boolean, multiview = false): Promise<MeshResponse> {
  const jobId = await _submit("/text2mesh", { prompt, pipeline_type: pipelineType, ...(seed != null ? { seed } : {}), ...(multiview ? { multiview: true } : {}) });
  return _poll(jobId, onProgress, shouldCancel);
}

export interface RenderResponse { beauty_png_b64: string | null; turntable_mp4_b64?: string; seconds?: number; }
/** Cinematic render pass: GLB → headless Blender/Cycles photoreal beauty still + turntable MP4. */
export async function renderAsset(glbB64: string, onProgress?: MeshProgress): Promise<RenderResponse> {
  const jobId = await _submit("/render", { glb_b64: glbB64, samples: 160, res: 1600, turn_frames: 36 });
  return _poll(jobId, onProgress) as unknown as Promise<RenderResponse>;
}

export interface AnimateResponse { animated_mp4_b64: string | null; seconds?: number; variant?: string; }
/** Cinematic MOTION pass: the Cycles turntable + beauty still → photoreal clip via LTX-2.3 · 3DREAL.
 * Async (the 22B render-to-real exceeds the tunnel limit), so submit → poll like the other Track-B jobs. */
export async function animateAsset(turntableMp4B64: string, firstFramePngB64: string, prompt: string,
  variant = "strong", onProgress?: MeshProgress): Promise<AnimateResponse> {
  const jobId = await _submit("/animate", {
    turntable_mp4_b64: turntableMp4B64, first_frame_png_b64: firstFramePngB64, prompt, variant,
  });
  return _poll(jobId, onProgress) as unknown as Promise<AnimateResponse>;
}

/** Backend spec (flat features) → Studio Spec ({type,params}) so the editor reflects the interpretation.
 * Inverse of specToBackend: an `at:[x,y]` tuple becomes scalar pos_x/pos_y for the number-input editor. */
export function backendToSpec(bs: any, base: Spec): Spec {
  const features = (bs.features || []).map((f: any, i: number) => {
    const { type, at, ...rest } = f;
    const params: Record<string, any> = { ...rest };
    if (Array.isArray(at) && at.length >= 2) { params.pos_x = at[0]; params.pos_y = at[1]; }
    return { id: `f${Date.now()}_${i}`, type, params };
  });
  return {
    object: bs.object ?? base.object,
    shape: bs.shape ?? base.shape,
    envelope: bs.envelope ?? base.envelope,
    features,
    tolerance: bs.tolerance ?? base.tolerance,
    fabrication: bs.fabrication ?? base.fabrication,
    min_wall: bs.min_wall ?? base.min_wall,
    profile: bs.profile ?? base.profile,
    path: bs.path ?? base.path,
  } as unknown as Spec;
}
