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
export const image2mesh = (imageB64: string, tier: string, multiview: boolean, onP?: Progress, sc?: ShouldCancel): Promise<MeshResult> =>
  run("/image2mesh", { image_b64: imageB64, pipeline_type: TIER_PTYPE[tier] || "1024", ...(multiview ? { multiview: true } : {}) }, onP, sc);

/** decimate a GLB to a face budget (game-ready). */
export const lowpoly = (glbB64: string, targetFaces: number, onP?: Progress, sc?: ShouldCancel): Promise<MeshResult> =>
  run("/lowpoly", { glb_b64: glbB64, target_faces: targetFaces }, onP, sc);

/** Infinigen terrain tile for a biome → vertex-colored GLB. Heavy (~5–6 min). */
export const terrain = (biome: string, targetFaces: number, onP?: Progress, sc?: ShouldCancel): Promise<MeshResult> =>
  run("/terrain", { biome, target_faces: targetFaces }, onP, sc);

/** photoreal Cycles beauty still + turntable MP4 from a GLB. */
export const render = (glbB64: string, onP?: Progress, sc?: ShouldCancel): Promise<RenderResult> =>
  run("/render", { glb_b64: glbB64, samples: 160, res: 1600, turn_frames: 36 }, onP, sc);

/** LTX render-to-real motion clip from a turntable + its first frame. */
export const animate = (turntableMp4B64: string, firstFramePngB64: string, prompt: string, variant: string, onP?: Progress, sc?: ShouldCancel): Promise<AnimateResult> =>
  run("/animate", { turntable_mp4_b64: turntableMp4B64, first_frame_png_b64: firstFramePngB64, prompt, variant }, onP, sc);
