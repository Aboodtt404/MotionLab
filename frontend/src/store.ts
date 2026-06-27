import { create } from "zustand";
import { backendToSpec, editAssembly, generateBackend, generateFromPrompt, generateMesh, generateMeshFromText, planAssembly, renderAsset as apiRenderAsset, toInspection } from "./api";
import type { MeshResponse } from "./api";
import type { Asset, Branch, Fab, FeatureType, InspectionRow, Mode, OrganicCheck, QualityTier, Spec, Team, View } from "./types";

/* ------------------------------------------------------------------ *
 * Pure spec helpers (ported from the prototype's DCLogic methods).
 * ------------------------------------------------------------------ */
export const typeLabel = (t: FeatureType): string =>
  ({ through_hole: "Through-hole", hole_pattern: "Hole pattern", counterbore: "Counterbore",
     countersink: "Countersink", fillet: "Fillet", chamfer: "Chamfer", pocket: "Pocket",
     shell: "Shell (hollow)" }[t] || t);

export const iconPath = (t: FeatureType): string =>
  ({
    through_hole: "M12 4a8 8 0 100 16 8 8 0 000-16zM12 9a3 3 0 100 6 3 3 0 000-6z",
    hole_pattern: "M7 7a1.5 1.5 0 100 0.01M17 7a1.5 1.5 0 100 0.01M7 17a1.5 1.5 0 100 0.01M17 17a1.5 1.5 0 100 0.01",
    counterbore: "M5 4h14v4H5zM9 8v12M15 8v12",
    countersink: "M5 4h14l-4 5v11H9V9z",
    fillet: "M5 19V11a6 6 0 016-6h8",
    chamfer: "M5 19v-7l7-7h8",
    pocket: "M4 5h16v14H4zM9 9h6v6H9z",
    shell: "M4 4h16v16H4zM8 8h8v8H8z",
  }[t] || "M4 4h16v16H4z");

// A parameter is a number input OR an enum (select). Enums carry their option list.
export interface ParamDef { key: string; label: string; min?: number; max?: number; step?: number; kind?: "enum"; options?: string[]; }

export const paramDefs = (t: FeatureType): ParamDef[] => {
  const DIA = { key: "diameter", label: "Diameter", min: 0.5, max: 200, step: 0.5 };
  const POS = [{ key: "pos_x", label: "Pos X", min: -200, max: 200, step: 1 }, { key: "pos_y", label: "Pos Y", min: -200, max: 200, step: 1 }];
  if (t === "through_hole")
    return [DIA, ...POS, { key: "axis", label: "Axis", kind: "enum", options: ["z", "x", "y"] }];
  if (t === "hole_pattern")
    return [DIA, { key: "pattern", label: "Pattern", kind: "enum", options: ["bolt_circle", "linear_x", "grid"] },
      { key: "count", label: "Count", min: 1, max: 64, step: 1 },
      { key: "pitch_diameter", label: "PCD", min: 0, max: 400, step: 1 },
      { key: "spacing", label: "Spacing", min: 0, max: 200, step: 1 },
      { key: "nx", label: "Grid nx", min: 1, max: 32, step: 1 }, { key: "ny", label: "Grid ny", min: 1, max: 32, step: 1 }];
  if (t === "counterbore")
    return [DIA, { key: "cbore_diameter", label: "C'bore ⌀", min: 1, max: 200, step: 0.5 },
      { key: "cbore_depth", label: "C'bore depth", min: 0.5, max: 100, step: 0.5 }, ...POS];
  if (t === "countersink")
    return [DIA, { key: "csk_diameter", label: "C'sink ⌀", min: 1, max: 200, step: 0.5 },
      { key: "csk_angle", label: "Angle°", min: 60, max: 120, step: 1 }, ...POS];
  if (t === "fillet") return [{ key: "radius", label: "Radius", min: 0, max: 60, step: 0.5 }];
  if (t === "chamfer") return [{ key: "distance", label: "Distance", min: 0, max: 60, step: 0.5 }];
  if (t === "pocket")
    return [{ key: "length", label: "Length", min: 1, max: 400, step: 1 },
      { key: "width", label: "Width", min: 1, max: 400, step: 1 },
      { key: "depth", label: "Depth", min: 0.5, max: 200, step: 0.5 }, ...POS];
  if (t === "shell")
    return [{ key: "thickness", label: "Wall", min: 0.4, max: 40, step: 0.1 },
      { key: "open_face", label: "Open face", kind: "enum", options: ["top", "bottom", "none"] }];
  return [];
};

const featureDefaults: Record<FeatureType, Record<string, number | string | number[]>> = {
  through_hole: { diameter: 10, pos_x: 0, pos_y: 0, axis: "z" },
  hole_pattern: { diameter: 6, pattern: "bolt_circle", count: 4, pitch_diameter: 40, spacing: 20, nx: 2, ny: 2 },
  counterbore: { diameter: 6, cbore_diameter: 11, cbore_depth: 4, pos_x: 0, pos_y: 0 },
  countersink: { diameter: 6, csk_diameter: 12, csk_angle: 90, pos_x: 0, pos_y: 0 },
  fillet: { radius: 3 },
  chamfer: { distance: 2 },
  pocket: { length: 24, width: 16, depth: 6, pos_x: 0, pos_y: 0 },
  shell: { thickness: 2, open_face: "top" },
};

const clampNum = (raw: any, mn: number | null, mx: number | null, fb: number) => {
  let v = parseFloat(raw);
  if (isNaN(v)) return fb;
  if (mn != null) v = Math.max(mn, v);
  if (mx != null) v = Math.min(mx, v);
  return v;
};

const clone = (s: Spec): Spec => JSON.parse(JSON.stringify(s));

export function warningsFor(branch: Branch, spec: Spec): string[] {
  if (branch !== "hard") return [];
  const e = spec.envelope,
    w: string[] = [];
  const minFace = spec.shape === "box" ? Math.min(e.length, e.width) : (e.diameter ?? Infinity);
  const N = (v: number | string | number[] | undefined) => (typeof v === "number" ? v : NaN);
  spec.features.forEach((f) => {
    const dia = N(f.params.diameter);
    if (f.type === "through_hole" && dia >= minFace)
      w.push(`Hole ⌀${dia} exceeds the ${minFace} mm face — it won't fit.`);
    if (f.type === "fillet" && N(f.params.radius) > minFace / 2) w.push(`Fillet r${N(f.params.radius)} exceeds half the thinnest wall.`);
    if (f.type === "shell") {
      const th = N(f.params.thickness);
      if (th > 0 && th >= minFace / 2) w.push(`Shell wall ${th} mm leaves no cavity in a ${minFace} mm part.`);
    }
  });
  return w;
}

function descriptors(spec: Spec) {
  const d: { name: string; banner: string; requested: number; cand: boolean }[] = [];
  const e = spec.envelope;
  const D = (n: string, b: string, r: any, c = false) => d.push({ name: n, banner: b, requested: Number(r) || 0, cand: c });
  if (spec.shape === "box") {
    D("Envelope · L", "envelope length", e.length);
    D("Envelope · W", "envelope width", e.width);
    D("Envelope · H", "envelope height", e.height);
  } else {
    D("Envelope · ⌀", "envelope diameter", e.diameter);
    D("Envelope · H", "envelope height", e.height);
  }
  spec.features.forEach((f) => {
    if (f.type === "through_hole") {
      D("Hole · ⌀", "hole diameter", f.params.diameter, true);
      if (f.params.from_edge != null) D("Hole · pos", "hole position", f.params.from_edge);
    } else if (f.type === "fillet") D("Fillet · r", "fillet radius", f.params.radius);
    else if (f.type === "chamfer") D("Chamfer · d", "chamfer distance", f.params.distance);
    else if (f.type === "pocket") {
      D("Pocket · L", "pocket length", f.params.length);
      D("Pocket · W", "pocket width", f.params.width);
      D("Pocket · D", "pocket depth", f.params.depth);
    }
  });
  return d;
}

function makeInspection(spec: Spec): InspectionRow[] {
  const t = spec.tolerance;
  return descriptors(spec).map((r, i) => {
    const off = (i % 2 ? 1 : -1) * t * (0.16 + (i % 3) * 0.15);
    const meas = r.requested + off,
      delta = meas - r.requested,
      pass = Math.abs(delta) <= t + 1e-9;
    const left = Math.max(4, Math.min(96, 50 + (delta / (2 * t)) * 50));
    return { name: r.name, req: r.requested.toFixed(2), meas: meas.toFixed(2), pass, gaugeLeft: left.toFixed(1) + "%" };
  });
}

export function buildCode(spec: Spec): string[] {
  const f = (n: any) => (Number(n) || 0).toFixed(1);
  const L: string[] = ["import cadquery as cq", "# " + spec.object];
  if (spec.shape === "box") {
    L.push(`L,W,H = ${f(spec.envelope.length)},${f(spec.envelope.width)},${f(spec.envelope.height)}`);
    L.push('r = cq.Workplane("XY").box(L,W,H)');
  } else {
    L.push(`D,H = ${f(spec.envelope.diameter)},${f(spec.envelope.height)}`);
    L.push('r = cq.Workplane("XY").circle(D/2).extrude(H)');
  }
  spec.features.forEach((ft) => {
    if (ft.type === "fillet") L.push(`r = r.edges("|Z").fillet(${f(ft.params.radius)})`);
    else if (ft.type === "chamfer") L.push(`r = r.edges("|Z").chamfer(${f(ft.params.distance)})`);
    else if (ft.type === "through_hole") L.push(`r = r.faces(">Z").workplane().hole(${f(ft.params.diameter)})`);
    else if (ft.type === "pocket") L.push(`r = r.faces(">Z").rect(${f(ft.params.length)},${f(ft.params.width)}).cutBlind(-${f(ft.params.depth)})`);
  });
  return L;
}

/* Natural-language → spec is now done by the MODEL (backend /generate with {prompt}),
 * not a brittle regex. See cad_pipeline/nl_spec.py. */

/* Model menus — adapted from research (sources.md / track design docs). */
export const modelChoices = (branch: Branch): string[] =>
  branch === "organic"
    ? ["TRELLIS.2 · local", "Hunyuan3D 2.1 · local · region-gated", "Frontier · Opus 4.8 (judge)"]
    : ["Qwen3.6-27B · local · fine-tuned", "Frontier · Opus 4.8", "gpt-oss-120b · data engine"];

/* ------------------------------------------------------------------ *
 * Store
 * ------------------------------------------------------------------ */
const defaultSpec: Spec = {
  object: "rectangular bracket",
  shape: "box",
  envelope: { length: 80, width: 50, height: 30 },
  features: [
    { id: "f1", type: "fillet", params: { radius: 4 } },
    { id: "f2", type: "through_hole", params: { diameter: 12, from_edge: 18 } },
  ],
  tolerance: 0.1,
};

const seedAssets: Asset[] = [
  { id: "a1", name: "rectangular bracket", cls: "hard", ver: "v3", pass: true },
  { id: "a2", name: "gargoyle bust", cls: "organic", ver: "v2", pass: true },
  { id: "a3", name: "shaft collar", cls: "hard", ver: "v1", pass: false },
  { id: "a4", name: "rock cluster", cls: "organic", ver: "v4", pass: true },
  { id: "a5", name: "vent grille", cls: "hard", ver: "v1", pass: true },
  { id: "a6", name: "dagger hilt", cls: "organic", ver: "v1", pass: true },
];

let timers: any[] = [];
const clearTimers = () => {
  timers.forEach((t) => (typeof t === "number" ? clearTimeout(t) : clearInterval(t)));
  timers = [];
};
const T = (ms: number, fn: () => void) => timers.push(setTimeout(fn, ms));

interface StudioState {
  team: Team; qualityTier: QualityTier;   // team = primary axis; branch mirrors it
  branch: Branch; mode: Mode; fab: Fab; model: string | null; modelOpen: boolean;
  prompt: string; style: number; imageThumb: string | null; scaleAnchor: number; // mm — explicit scale (Track C)
  spec: Spec; organicDetail: number; symmetry: boolean; targetHeight: number;
  view: View; heatmap: boolean; showDims: boolean; highlightId: string | null;
  turntable: boolean; lightMood: string; moodOpen: boolean; scaleFigure: boolean;
  genStatus: "idle" | "running" | "done"; genStep: number; progress: number;
  attempt: number; attempts: number; retry: string | null; retryDiff: string | null;
  inspection: InspectionRow[] | null; organicReport: OrganicCheck[] | null;
  meshStep: string | null;            // base64 STEP (Track A / robotics) — real CAD export
  approved: boolean;                  // organic human art-direction sign-off (Track B / film)
  addMenuOpen: boolean; libOpen: boolean; hollow: boolean; minWall: number; activeVar: number;
  assets: Asset[];
  [k: string]: any;
}

// Map the Track B server's real job stage → the generating-overlay step/progress (replaces fake timers).
// genStep indexes Stage.tsx's organic labels: 1 "Diffusing latents" · 2 "Extracting mesh" · 3 "Synthesizing PBR".
function organicProgress(stage: string, elapsed: number): { genStep: number; progress: number } {
  if (stage === "queued") return { genStep: 0, progress: 8 };
  if (stage === "concept") return { genStep: 1, progress: 24 };          // FLUX concept image (text→mesh)
  if (stage === "generating") {                                          // TRELLIS: latents → mesh → PBR
    const genStep = elapsed < 25 ? 1 : elapsed < 75 ? 2 : 3;
    return { genStep, progress: Math.min(93, 30 + elapsed * 0.7) };      // creep, cap at 93 until done
  }
  return { genStep: 2, progress: 60 };
}

function organicDone(resp: MeshResponse, concept: string | null, get: () => StudioState) {
  const r = resp.report;
  const organicReport: OrganicCheck[] = [
    { label: "Mesh faces", value: String(r.faces), ok: true },
    { label: "PBR maps", value: r.pbr.join(", ") || "none", ok: r.pbr.length > 0 },
    { label: "Watertight", value: r.watertight ? "yes" : "no", ok: true },
    { label: "Generated", value: `${resp.seconds ?? 0}s @ ${resp.pipeline_type || ""}`, ok: true },
  ];
  const nm = (get().prompt.split(/[,.\n]/)[0].trim().slice(0, 22) || "organic asset").toLowerCase();
  const assets = [{ id: "g" + Date.now(), name: nm, cls: "organic" as const, ver: "v1", pass: true }, ...get().assets].slice(0, 10);
  return { genStep: 4, progress: 100, meshGlb: resp.glb_b64 || null, conceptImg: concept, organicReport, approved: false, assets };
}

export const useStudio = create<StudioState>((set, get) => {
  const resetGen = () => ({
    genStatus: "idle" as const, genStep: 0, progress: 0, inspection: null, organicReport: null,
    retry: null, retryDiff: null, approved: false, attempt: 0, attempts: 0,
    meshStl: null, meshStep: null, meshGlb: null, conceptImg: null, code: null, backendError: null,
  });
  const setSpec = (mut: (s: Spec) => void) => { const s = clone(get().spec); mut(s); set({ spec: s }); };

  function finishHard(spec: Spec, attempts: number, cand: any, failMeas: number | null) {
    const inspection = makeInspection(spec);
    let retryDiff: string | null = null;
    if (cand && failMeas != null) {
      const row = inspection.find((r) => r.name.indexOf("Hole") === 0) || inspection[0];
      retryDiff = `${cand.banner} ${failMeas.toFixed(2)} → ${row.meas}`;
    }
    const assets = [{ id: "g" + Date.now(), name: spec.object, cls: "hard" as const, ver: "v1", pass: true }, ...get().assets].slice(0, 10);
    set({ genStatus: "done", genStep: 4, progress: 100, inspection, attempts, retry: null, retryDiff, assets });
  }

  return {
    team: "robotics", qualityTier: "1536_cascade",
    branch: "hard", mode: "text", fab: "render", model: null, modelOpen: false,
    prompt: "", style: 0, imageThumb: null, scaleAnchor: 80, seed: 42,
    spec: defaultSpec, organicDetail: 2, symmetry: false, targetHeight: 120,
    view: "solid", heatmap: false, showDims: false, highlightId: null,
    turntable: false, lightMood: "studio", moodOpen: false, scaleFigure: false,
    genStatus: "idle", genStep: 0, progress: 0, attempt: 0, attempts: 0, retry: null, retryDiff: null,
    inspection: null, organicReport: null, approved: false,
    addMenuOpen: false, libOpen: false, hollow: false, minWall: 1.5, activeVar: 0, assets: seedAssets,
    meshStl: null, meshStep: null, meshGlb: null, conceptImg: null, code: null, backendError: null, useModel: true, // real-backend wiring (live Phase-2 model)
    cancelRequested: false,                                          // film job cancel (polled, single GPU)
    renderPng: null, renderMp4: null, rendering: false, renderStage: "",  // cinematic Cycles render pass
    assemblyMode: false, assembly: null, assemblyObject: null,      // planner / edit-loop

    // planner (multi-part): first prompt PLANS, subsequent prompts EDIT the current design
    toggleAssemblyMode: () => set((s) => ({ assemblyMode: !s.assemblyMode })),
    newDesign: () => { clearTimers(); set({ assembly: null, assemblyObject: null, meshStl: null, meshGlb: null, inspection: null, ...resetGen() }); },

    cancelJob: () => set({ cancelRequested: true }),
    // attach a real rendered thumbnail (viewport snapshot) to the most-recently-generated asset
    thumbLatestAsset: (url: string) => set((s) => ({ assets: s.assets.map((a, i) => (i === 0 ? { ...a, thumb: url } : a)) })),
    // a clean cancel returns to idle without an error banner; a real failure shows the message.
    onOrganicError: (err: any) => { clearTimers(); const m = String(err?.message || err); set({ genStatus: "idle", progress: 0, backendError: m === "cancelled" ? null : m, cancelRequested: false }); },

    // Track B (organic): a reference image → a real TRELLIS.2 mesh via the Track-B service.
    generateMeshFromImage: (imageB64: string, pipelineType = "1536_cascade") => {
      clearTimers();
      set({ branch: "organic", genStatus: "running", genStep: 1, progress: 15, organicReport: null, backendError: null, meshGlb: null, conceptImg: null, cancelRequested: false, renderPng: null, renderMp4: null });
      generateMesh(imageB64, pipelineType, (stage, el) => set(organicProgress(stage, el)), get().seed, () => get().cancelRequested).then((resp) => {
        set({ genStatus: "done", cancelRequested: false, ...organicDone(resp, resp.concept_png_b64 ? "data:image/png;base64," + resp.concept_png_b64 : null, get) });
      }).catch((err) => get().onOrganicError(err));
    },
    generateMeshFromText: (prompt: string, pipelineType = "1536_cascade") => {
      clearTimers();
      set({ branch: "organic", genStatus: "running", genStep: 0, progress: 10, organicReport: null, backendError: null, meshGlb: null, conceptImg: null, cancelRequested: false, renderPng: null, renderMp4: null });
      generateMeshFromText(prompt, pipelineType, (stage, el) => set(organicProgress(stage, el)), get().seed, () => get().cancelRequested).then((resp) => {
        const concept = resp.concept_png_b64 ? "data:image/png;base64," + resp.concept_png_b64 : null;
        set({ genStatus: "done", cancelRequested: false, ...organicDone(resp, concept, get) });
      }).catch((err) => get().onOrganicError(err));
    },
    // Cinematic render pass: send the generated GLB to Blender/Cycles → photoreal beauty still + turntable.
    renderAsset: () => {
      const glb = get().meshGlb;
      if (!glb || get().rendering) return;
      set({ rendering: true, renderPng: null, renderMp4: null, renderStage: "rendering", backendError: null });
      apiRenderAsset(glb, (stage, el) => set({ renderStage: `${stage} · ${el}s` })).then((r) => {
        set({ rendering: false, renderStage: "",
              renderPng: r.beauty_png_b64 ? "data:image/png;base64," + r.beauty_png_b64 : null,
              renderMp4: r.turntable_mp4_b64 || null });
      }).catch((err) => { set({ rendering: false, renderStage: "", backendError: String(err?.message || err) }); });
    },
    // Film iteration: bump the seed and re-run the same prompt/image → a different concept + mesh.
    reseed: () => {
      const seed = (get().seed + 1) % 100000;
      set({ seed });
      const s = get();
      (s.mode === "image" && s.imageThumb)
        ? s.generateMeshFromImage(s.imageThumb.split(",")[1] || s.imageThumb, s.qualityTier)
        : s.generateMeshFromText(s.prompt, s.qualityTier);
    },
    planOrEdit: () => {
      const st = get();
      if (st.genStatus === "running" || !st.prompt.trim()) return;
      const editing = !!st.assembly;
      const instruction = st.prompt;
      clearTimers();
      set({ genStatus: "running", genStep: 0, progress: 6, inspection: null, retry: null, backendError: null });
      T(300, () => set({ genStep: editing ? 2 : 1, progress: 35 }));
      T(1200, () => set({ genStep: 3, progress: 70 }));
      const call = editing ? editAssembly(st.assembly, instruction) : planAssembly(instruction);
      call.then((resp) => {
        clearTimers();
        const inspection = toInspection(resp.inspection, 0.1);
        const assets = [{ id: "g" + Date.now(), name: resp.object || "assembly", cls: "hard" as const, ver: editing ? "edit" : "v1", pass: resp.passed }, ...get().assets].slice(0, 10);
        set({ genStatus: "done", genStep: 4, progress: 100, inspection, assembly: resp.assembly, assemblyObject: resp.object,
              meshStl: resp.mesh_stl_b64 || null, meshStep: resp.step_b64 || null, attempts: resp.components, attempt: resp.components, prompt: "", assets });
      }).catch((err) => { clearTimers(); set({ genStatus: "idle", progress: 0, backendError: String(err?.message || err) }); });
    },

    // nav / mode
    setMode: (mode: Mode) => set({ mode, libOpen: false }),
    toggleLib: () => set((s) => ({ libOpen: !s.libOpen })),
    closeLib: () => set({ libOpen: false }),

    // team = primary axis: robotics→hard/Track A, film→organic/Track B. branch is a derived mirror so
    // every existing s.branch reader (scene.ts, Viewport, warningsFor, EXAMPLES) keeps working untouched.
    setTeam: (team: Team) => {
      if (get().team === team) return;
      clearTimers();
      const branch: Branch = team === "robotics" ? "hard" : "organic";
      set({
        team, branch, style: 0, heatmap: false, libOpen: false, assemblyMode: false,
        fab: team === "robotics" ? "fabricate" : "render",
        ...resetGen(),
      });
    },
    setQualityTier: (qualityTier: QualityTier) => set({ qualityTier }),

    // branch (internal; the UI switches teams, not branches)
    setBranch: (branch: Branch) => {
      if (get().branch === branch) return;
      clearTimers();
      set({ branch, style: 0, model: null, heatmap: false, ...resetGen() });
    },

    // model / style / fab
    toggleModelMenu: () => set((s) => ({ modelOpen: !s.modelOpen })),
    pickModel: (m: string) => set({ model: m, modelOpen: false }),
    setStyle: (style: number) => set({ style }),
    setFab: (fab: Fab) => set({ fab }),

    // input
    onPrompt: (v: string) => set({ prompt: v }),
    onImageFile: (dataUrl: string) => set({ imageThumb: dataUrl }),
    clearImage: () => set({ imageThumb: null }),
    onScaleAnchor: (raw: any) => set({ scaleAnchor: clampNum(raw, 1, 5000, get().scaleAnchor) }),
    useExample: (t: string) => set({ prompt: t }),  // model interprets it on Generate

    // hard spec
    onObjectName: (v: string) => setSpec((s) => { s.object = v; }),
    setEnvelope: (k: string, raw: any, mn: number, mx: number) => setSpec((s) => { s.envelope = { ...s.envelope, [k]: clampNum(raw, mn, mx, s.envelope[k]) }; }),
    setBox: () => setSpec((s) => { if (s.shape === "box") return; const h = s.envelope.height || 30; s.shape = "box"; s.envelope = { length: 80, width: 50, height: h }; }),
    setCylinder: () => setSpec((s) => { if (s.shape === "cylinder") return; const h = s.envelope.height || 30; s.shape = "cylinder"; s.envelope = { diameter: 40, height: h }; }),
    // loft = a tapered bar: base width/height at one end → width_top/height_top at the other (engineered arm/strut).
    setLoft: () => setSpec((s) => { if (s.shape === "loft") return; s.shape = "loft"; s.envelope = { length: 80, width: 50, height: 30, width_top: 25, height_top: 15 }; }),
    updateFeatureParam: (id: string, k: string, raw: any, mn: number, mx: number) => setSpec((s) => { const f = s.features.find((x) => x.id === id); if (f) f.params = { ...f.params, [k]: clampNum(raw, mn, mx, Number(f.params[k]) || 0) }; }),
    setFeatureEnum: (id: string, k: string, val: string) => setSpec((s) => { const f = s.features.find((x) => x.id === id); if (f) f.params = { ...f.params, [k]: val }; }),
    removeFeature: (id: string) => setSpec((s) => { s.features = s.features.filter((x) => x.id !== id); }),
    addFeature: (type: FeatureType, params?: Record<string, number | string | number[]>) =>
      set((st) => { const s = clone(st.spec); s.features.push({ id: "f" + Date.now() + Math.floor(Math.random() * 99), type, params: params || { ...featureDefaults[type] } }); return { spec: s, addMenuOpen: false }; }),
    toggleAddMenu: () => set((s) => ({ addMenuOpen: !s.addMenuOpen })),
    onTolerance: (raw: any) => setSpec((s) => { s.tolerance = clampNum(raw, 0.01, 2, s.tolerance); }),

    // organic
    setDetail: (raw: any) => set({ organicDetail: clampNum(raw, 0, 3, get().organicDetail) }),
    toggleSymmetry: () => set((s) => ({ symmetry: !s.symmetry })),
    onTargetHeight: (raw: any) => set({ targetHeight: clampNum(raw, 10, 400, get().targetHeight) }),

    // viewport
    setView: (view: View) => set({ view }),
    toggleHeatmap: () => set((s) => ({ heatmap: !s.heatmap })),
    toggleDims: () => set((s) => ({ showDims: !s.showDims })),
    toggleTurntable: () => set((s) => ({ turntable: !s.turntable })),
    toggleMood: () => set((s) => ({ moodOpen: !s.moodOpen })),
    pickMood: (m: string) => set({ lightMood: m, moodOpen: false }),
    toggleScaleFigure: () => set((s) => ({ scaleFigure: !s.scaleFigure })),
    setHighlight: (id: string | null) => set({ highlightId: id }),
    pickVariation: (i: number) => set({ activeVar: i }),

    // export / print-prep
    setFabRender: () => set({ fab: "render" }),
    setFabFab: () => set({ fab: "fabricate" }),
    toggleHollow: () => set((s) => ({ hollow: !s.hollow })),
    onMinWall: (raw: any) => set({ minWall: clampNum(raw, 0.4, 10, get().minWall) }),

    // organic human sign-off (Track B bounded best-of-N)
    approveAsset: () => set({ approved: true }),

    // library
    loadAsset: (a: Asset) => { clearTimers(); set({ branch: a.cls, model: null, libOpen: false, style: 0, ...resetGen(), ...(a.cls === "hard" ? { spec: { ...clone(get().spec), object: a.name } } : {}) }); },

    // generation (mock — staged simulation, ported from prototype)
    // Track A (hard-surface / robotics): spec or text prompt → real CadQuery mesh + STEP + verifier report.
    // Organic/film generation does NOT come through here — it routes to generateMeshFromText/Image (Track B).
    generate: () => {
      const st = get();
      if (st.genStatus === "running") return;
      if (warningsFor(st.branch, st.spec).length) return;
      if (st.mode === "image" && !st.imageThumb) return;
      const sp = clone(st.spec);
      sp.fabrication = st.fab;                                  // render | fabricate → backend DFM gates
      if (st.fab === "fabricate") sp.min_wall = st.minWall;     // enforce min manufacturable wall
      clearTimers();
      set({ genStatus: "running", genStep: 0, progress: 4, attempt: 1, retry: null, retryDiff: null, inspection: null, organicReport: null, approved: false, addMenuOpen: false, activeVar: 0 });
      // text prompt → the model interprets it (Track A text→spec); otherwise send the editor spec.
      const usePrompt = st.mode === "text" && !!st.prompt.trim();
      // staged progress for feel; the REAL pipeline call is authoritative for the finish.
      T(300, () => set({ genStep: 1, progress: 25 }));
      T(900, () => set({ genStep: 2, progress: 55 }));
      T(1600, () => set({ genStep: 3, progress: 80 }));
      (usePrompt ? generateFromPrompt(st.prompt, get().useModel) : generateBackend(sp, get().useModel))
        .then((resp) => {
          clearTimers();
          const fspec = resp.spec ? backendToSpec(resp.spec, sp) : sp;  // reflect the interpreted spec
          const inspection = toInspection(resp.inspection, fspec.tolerance);
          const assets = [{ id: "g" + Date.now(), name: fspec.object, cls: "hard" as const, ver: "v1", pass: resp.passed }, ...get().assets].slice(0, 10);
          set({
            spec: fspec, genStatus: "done", genStep: 4, progress: 100, inspection,
            attempt: resp.attempts, attempts: resp.attempts,
            meshStl: resp.mesh_stl_b64 || null, meshStep: resp.step_b64 || null, code: resp.code || null,
            retry: null, retryDiff: null, backendError: null, assets,
          });
        })
        .catch((err) => {
          // backend down → fall back to the offline mock so the UI still demos.
          clearTimers();
          set({ backendError: String(err?.message || err) });
          finishHard(sp, 1, null, null);
        });
    },
  };
});
