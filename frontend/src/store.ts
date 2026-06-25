import { create } from "zustand";
import { backendToSpec, editAssembly, generateBackend, generateFromPrompt, planAssembly, toInspection } from "./api";
import type { Asset, Branch, Fab, FeatureType, InspectionRow, Mode, OrganicCheck, Spec, View } from "./types";

/* ------------------------------------------------------------------ *
 * Pure spec helpers (ported from the prototype's DCLogic methods).
 * ------------------------------------------------------------------ */
export const typeLabel = (t: FeatureType): string =>
  ({ through_hole: "Through-hole", fillet: "Fillet", chamfer: "Chamfer", pocket: "Pocket" }[t] || t);

export const iconPath = (t: FeatureType): string =>
  ({
    through_hole: "M12 4a8 8 0 100 16 8 8 0 000-16zM12 9a3 3 0 100 6 3 3 0 000-6z",
    fillet: "M5 19V11a6 6 0 016-6h8",
    chamfer: "M5 19v-7l7-7h8",
    pocket: "M4 5h16v14H4zM9 9h6v6H9z",
  }[t] || "M4 4h16v16H4z");

export const paramDefs = (t: FeatureType) => {
  if (t === "through_hole")
    return [
      { key: "diameter", label: "Diameter", min: 0.5, max: 200, step: 0.5 },
      { key: "from_edge", label: "From edge", min: 0, max: 400, step: 1 },
    ];
  if (t === "fillet") return [{ key: "radius", label: "Radius", min: 0, max: 60, step: 0.5 }];
  if (t === "chamfer") return [{ key: "distance", label: "Distance", min: 0, max: 60, step: 0.5 }];
  if (t === "pocket")
    return [
      { key: "length", label: "Length", min: 1, max: 400, step: 1 },
      { key: "width", label: "Width", min: 1, max: 400, step: 1 },
      { key: "depth", label: "Depth", min: 0.5, max: 200, step: 0.5 },
    ];
  return [];
};

const featureDefaults: Record<FeatureType, Record<string, number>> = {
  through_hole: { diameter: 10, from_edge: 15 },
  fillet: { radius: 3 },
  chamfer: { distance: 2 },
  pocket: { length: 24, width: 16, depth: 6 },
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
  const minFace = spec.shape === "box" ? Math.min(e.length, e.width) : e.diameter;
  spec.features.forEach((f) => {
    if (f.type === "through_hole" && f.params.diameter >= minFace)
      w.push(`Hole ⌀${f.params.diameter} exceeds the ${minFace} mm face — it won't fit.`);
    if (f.type === "through_hole" && f.params.from_edge != null && spec.shape === "box" && f.params.from_edge > e.length)
      w.push(`Hole sits ${f.params.from_edge} mm in, past the ${e.length} mm length.`);
    if (f.type === "fillet" && f.params.radius > minFace / 2) w.push(`Fillet r${f.params.radius} exceeds half the thinnest wall.`);
  });
  return w;
}

function descriptors(spec: Spec) {
  const d: { name: string; banner: string; requested: number; cand: boolean }[] = [];
  const e = spec.envelope;
  const D = (n: string, b: string, r: number, c = false) => d.push({ name: n, banner: b, requested: Number(r) || 0, cand: c });
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
  const f = (n: number) => (Number(n) || 0).toFixed(1);
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
  branch: Branch; mode: Mode; fab: Fab; model: string | null; modelOpen: boolean;
  prompt: string; style: number; imageThumb: string | null; scaleAnchor: number; // mm — explicit scale (Track C)
  spec: Spec; organicDetail: number; symmetry: boolean; targetHeight: number;
  view: View; heatmap: boolean; showDims: boolean; highlightId: string | null;
  turntable: boolean; lightMood: string; moodOpen: boolean; scaleFigure: boolean;
  genStatus: "idle" | "running" | "done"; genStep: number; progress: number;
  attempt: number; attempts: number; retry: string | null; retryDiff: string | null;
  inspection: InspectionRow[] | null; organicReport: OrganicCheck[] | null; fidelity: number;
  bestOfN: number; approved: boolean; // organic human sign-off (Track B)
  addMenuOpen: boolean; libOpen: boolean; hollow: boolean; minWall: number; activeVar: number;
  assets: Asset[];
  [k: string]: any;
}

export const useStudio = create<StudioState>((set, get) => {
  const resetGen = () => ({
    genStatus: "idle" as const, genStep: 0, progress: 0, inspection: null, organicReport: null,
    retry: null, retryDiff: null, fidelity: 0, bestOfN: 0, approved: false, attempt: 0, attempts: 0,
    meshStl: null, code: null, backendError: null,
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

  function finishOrganic() {
    const st = get();
    const fab = st.fab === "fabricate", minWall = 1.8, wallOk = minWall >= st.minWall;
    const report: OrganicCheck[] = [
      { label: "Manifold", value: "pass", ok: true },
      { label: "Watertight", value: "pass", ok: true },
      { label: "Min wall", value: `${minWall.toFixed(1)} / ${st.minWall.toFixed(1)} mm`, ok: !fab || wallOk },
      { label: "Self-intersections", value: "0", ok: true },
      { label: "Degenerate faces", value: "0", ok: true },
    ];
    const nm = (st.prompt.split(/[,.\n]/)[0].trim().slice(0, 22) || "organic asset").toLowerCase();
    const assets = [{ id: "g" + Date.now(), name: nm, cls: "organic" as const, ver: "v1", pass: true }, ...st.assets].slice(0, 10);
    set({ genStatus: "done", genStep: 4, progress: 100, organicReport: report, bestOfN: 4, approved: false, assets });
    let f = 0;
    const fi = setInterval(() => { f += 4; if (f >= 86) { f = 86; clearInterval(fi); } set({ fidelity: f }); }, 26);
    timers.push(fi);
  }

  return {
    branch: "hard", mode: "text", fab: "render", model: null, modelOpen: false,
    prompt: "", style: 0, imageThumb: null, scaleAnchor: 80,
    spec: defaultSpec, organicDetail: 2, symmetry: false, targetHeight: 120,
    view: "solid", heatmap: false, showDims: false, highlightId: null,
    turntable: true, lightMood: "studio", moodOpen: false, scaleFigure: false,
    genStatus: "idle", genStep: 0, progress: 0, attempt: 0, attempts: 0, retry: null, retryDiff: null,
    inspection: null, organicReport: null, fidelity: 0, bestOfN: 0, approved: false,
    addMenuOpen: false, libOpen: false, hollow: false, minWall: 1.5, activeVar: 0, assets: seedAssets,
    meshStl: null, code: null, backendError: null, useModel: true, // real-backend wiring (live Phase-2 model)
    assemblyMode: false, assembly: null, assemblyObject: null,      // planner / edit-loop

    // planner (multi-part): first prompt PLANS, subsequent prompts EDIT the current design
    toggleAssemblyMode: () => set((s) => ({ assemblyMode: !s.assemblyMode })),
    newDesign: () => { clearTimers(); set({ assembly: null, assemblyObject: null, meshStl: null, inspection: null, ...resetGen() }); },
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
              meshStl: resp.mesh_stl_b64 || null, attempts: resp.components, attempt: resp.components, prompt: "", assets });
      }).catch((err) => { clearTimers(); set({ genStatus: "idle", progress: 0, backendError: String(err?.message || err) }); });
    },

    // nav / mode
    setMode: (mode: Mode) => set({ mode, libOpen: false }),
    toggleLib: () => set((s) => ({ libOpen: !s.libOpen })),
    closeLib: () => set({ libOpen: false }),

    // branch
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
    updateFeatureParam: (id: string, k: string, raw: any, mn: number, mx: number) => setSpec((s) => { const f = s.features.find((x) => x.id === id); if (f) f.params = { ...f.params, [k]: clampNum(raw, mn, mx, f.params[k]) }; }),
    removeFeature: (id: string) => setSpec((s) => { s.features = s.features.filter((x) => x.id !== id); }),
    addFeature: (type: FeatureType, params?: Record<string, number>) =>
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
    generate: () => {
      const st = get();
      if (st.genStatus === "running") return;
      if (warningsFor(st.branch, st.spec).length) return;
      if (st.mode === "image" && !st.imageThumb) return;
      const spec = st.spec;
      clearTimers();
      set({ genStatus: "running", genStep: 0, progress: 4, attempt: 1, retry: null, retryDiff: null, inspection: null, organicReport: null, fidelity: 0, bestOfN: 0, approved: false, addMenuOpen: false, activeVar: 0 });

      if (st.branch === "organic") {
        T(450, () => set({ genStep: 1, progress: 12 }));
        const di = setInterval(() => set((s) => ({ progress: Math.min(68, s.progress + 4) })), 190);
        timers.push(di);
        T(3300, () => { clearInterval(di); set({ genStep: 2, progress: 74 }); });
        T(4300, () => set({ genStep: 3, progress: 88 }));
        T(5200, () => finishOrganic());
      } else {
        const sp = clone(spec);
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
              meshStl: resp.mesh_stl_b64 || null, code: resp.code || null,
              retry: null, retryDiff: null, backendError: null, assets,
            });
          })
          .catch((err) => {
            // backend down → fall back to the offline mock so the UI still demos.
            clearTimers();
            set({ backendError: String(err?.message || err) });
            finishHard(sp, 1, null, null);
          });
      }
    },
  };
});
