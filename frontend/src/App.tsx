/* MotionLab Studio — faithful React port of the Claude Design prototype (MotionLab Studio.dc.html).
 * The design was authored as a DCLogic class; it ports 1:1 to a React class component. The Three.js
 * viewport uses the npm `three` package instead of the prototype's CDN r128 global (window.THREE). */
import React from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { css } from "./css";
import { IconDefs } from "./icons";
import * as api from "./api";
import { parseGlbScene, glbToUsdz, exportGlb, exportUsdz, downloadB64, downloadBytes, bytesToB64, fileToB64, renderThumbnail, fetchPresetGlb } from "./gltf";

// Pre-baked Infinigen terrain tiles served statically at /presets/<biome>.{glb,png} — instant, no generation.
const TERRAIN_PRESETS: [string, string][] = [["plain", "Plain"], ["desert", "Desert"], ["forest", "Forest"]];
import { loadState, saveState } from "./persist";

const Icon = ({ k, size = 17 }: { k: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: "block" }}>
    <use href={"#" + k} />
  </svg>
);

export class Studio extends React.Component<{}, any> {
  state: any = {
    workspace: "robotics",
    viewMode: "solid",
    turntable: false,
    lighting: 1, // index into moods
    simFail: false,
    leftOpen: true,
    rightOpen: true,
    featMenuOpen: false,
    shortcutsOpen: false,
    dragLabel: null,
    hoverRow: null,
    toast: null,
    job: null, // {key,title,hint,stages,idx,status,elapsed,concept,errorStage}
    command: "",
    // ROBOTICS
    rob: {
      leftMode: "spec", // spec | image
      assembly: false,
      scaleAnchor: 50,
      spec: {
        name: "Mounting Bracket", shape: "Box",
        L: 80, W: 60, H: 12, dia: 40,
        tol: 0.1, fabrication: "Fabricate", minWall: 1.5,
        features: [
          { id: "f1", kind: "through-hole", dia: 8, x: 20, y: 0 },
          { id: "f2", kind: "hole-pattern", count: 4, pcd: 50, holeDia: 5 },
          { id: "f3", kind: "fillet", r: 3 },
        ],
      },
      result: null,
    },
    // CREATE
    cre: {
      inputMode: "text", tier: "Standard", multiview: true,   // default ON — real geometry on unseen sides (the quality lever)
      panel: "generate", // generate | terrain | render | library
      result: null, lowpolyTarget: 24000,
      renderTab: "still", motionVariant: 0, motionPlaying: false,
      renderTarget: "Hero Boulder",
      imageB64: null as string | null, imageName: "",   // image-mode upload (→ /image2mesh)
      renderBeauty: null as string | null, motionMp4: null as string | null,   // real Cycles/LTX outputs
    },
    librarySearch: "",
    library: [] as any[],   // starts empty; populated by real generations + restored from IndexedDB on mount
    // ASSEMBLE
    asm: {
      leftTab: "library", gizmoMode: "move", selectedId: null,
      selectedIds: [] as string[],               // multi-select (selectedId = the primary, drives gizmo/inspector)
      snap: false,                               // persistent snap toggle (Shift also forces snap)
      ground: "forest",                          // biome key (colored base) OR "tile" when a real terrain GLB is the ground
      groundGlbId: null as string | null, groundGlb: null as string | null,
      objects: [] as any[],
    },
  };

  ACCENTS: any = { robotics: "124,139,255", create: "124,139,255", assemble: "124,139,255" };
  GEOCOLOR: any = { rock: "#8a8f9c", tree: "#5a8f5e", arch: "#b59a78", box: "#b88a52", mushroom: "#d98a8a", terrain: "#6f7a55" };
  MOODS = ["Studio", "Sunset", "Night"];

  _timers: any = {};
  _uid = 100;
  _undo: any[] = [];
  _redo: any[] = [];
  _onKey: any = null;
  _toastT: any = null;
  _threeT: any = null;
  _raf: any = null;
  _ro: any = null;
  _three: any = null;
  _cam: any = null;
  _rim: any = null;
  _grid: any = null;
  _gizmoGroup: any = null;
  _raycaster: any = null;
  _mouse: any = null;
  _sig = "";
  _dragging = false;
  _dragItem: any = null;
  _dragRow: any = null;
  _glbCache: any = {};               // glbId -> normalized template Object3D (parsed once, cloned per use)
  _cancelFlag = false;               // cooperative cancel for the in-flight real job
  _renderTurntable: string | null = null;   // last Cycles turntable mp4 (feeds LTX animate)
  _renderBeauty: string | null = null;       // last Cycles beauty still (animate first frame)
  _fileInput: HTMLInputElement | null = null;
  _saveT: any = null;                        // debounce timer for persistence
  _hoverOid: any = null;                     // object currently under the cursor (hover highlight)

  componentDidMount() {
    this._waitThree();
    this._onKey = (e: KeyboardEvent) => this._handleKey(e);
    window.addEventListener("keydown", this._onKey);
    // restore the persisted library + assembly scene (IndexedDB)
    loadState().then((st) => {
      if (!st) return;
      this.setState((s: any) => ({
        library: st.library,
        asm: { ...s.asm, objects: st.scene.objects, ground: st.scene.ground || s.asm.ground, groundGlbId: st.scene.groundGlbId || null, groundGlb: st.scene.groundGlb || null },
      }));
    });
  }
  componentWillUnmount() {
    Object.values(this._timers).flat().forEach((t: any) => { clearTimeout(t); clearInterval(t); });
    clearTimeout(this._saveT);
    window.removeEventListener("keydown", this._onKey);
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this._ro) this._ro.disconnect();
    if (this._threeT) clearTimeout(this._threeT);
    if (this._three) {
      try {
        this._three.renderer.dispose();
        this._three.renderer.forceContextLoss && this._three.renderer.forceContextLoss();
        const cv = this._three.renderer.domElement;
        if (cv && cv.parentNode) cv.parentNode.removeChild(cv);
      } catch (e) {}
      this._three = null;
    }
  }
  componentDidUpdate(_prevProps: any, prevState: any) {
    this._syncViewport();
    // persist when the library or the scene changed (debounced — these arrays are replaced immutably,
    // so a cheap ref check suffices; coalesces rapid gizmo-drag updates into one write).
    if (prevState.library !== this.state.library
      || prevState.asm.objects !== this.state.asm.objects
      || prevState.asm.ground !== this.state.asm.ground
      || prevState.asm.groundGlbId !== this.state.asm.groundGlbId) {
      clearTimeout(this._saveT);
      const a = this.state.asm;
      this._saveT = setTimeout(() => saveState(this.state.library, { objects: a.objects, ground: a.ground, groundGlbId: a.groundGlbId, groundGlb: a.groundGlb }), 500);
    }
  }

  // ---------- toast ----------
  toast(msg: string) {
    clearTimeout(this._toastT);
    this.setState({ toast: msg });
    this._toastT = setTimeout(() => this.setState({ toast: null }), 2200);
  }

  // ---------- keyboard ----------
  _handleKey(e: any) {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea";
    if (e.key === "?" && !typing) { this.setState((s: any) => ({ shortcutsOpen: !s.shortcutsOpen })); return; }
    if (e.key === "Escape") { this.setState({ shortcutsOpen: false, featMenuOpen: false }); return; }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); return; }
    if (this.state.workspace !== "assemble" || typing) return;
    const k = e.key.toLowerCase();
    if (k === "w") this._setGizmo("move");
    else if (k === "e") this._setGizmo("rotate");
    else if (k === "r") this._setGizmo("scale");
    else if (k === "f") { const sel = this.state.asm.objects.find((o: any) => o.id === this.state.asm.selectedId); this.frameObject(sel || null); }
    else if (k === "delete" || k === "backspace") { if (this._selIds().length) this.deleteSel(); }
    else if (k === "d" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (this._selIds().length) this.dupSel(); }
    else if (k === "arrowup" || k === "arrowdown" || k === "arrowleft" || k === "arrowright") {
      const ids = this._selIds(); if (!ids.length) return; e.preventDefault();
      const step = e.shiftKey ? 1 : 0.25;
      const dx = k === "arrowright" ? step : k === "arrowleft" ? -step : 0;
      const dz = k === "arrowdown" ? step : k === "arrowup" ? -step : 0;
      this._pushUndo();
      this.setState((s: any) => ({ asm: { ...s.asm, objects: s.asm.objects.map((o: any) => ids.includes(o.id) ? { ...o, pos: [+(o.pos[0] + dx).toFixed(2), +this._groundHeightAt(o.pos[0] + dx, o.pos[2] + dz).toFixed(2), +(o.pos[2] + dz).toFixed(2)] } : o) } }));
    }
  }

  // ================= JOB ENGINE =================
  startJob(key: string, title: string, hint: string, stages: any[], concept: any, onDone: any) {
    this._clearTimers(key);
    const t0 = Date.now();
    const tick = setInterval(() => this.setState((s: any) => s.job && s.job.key === key ? ({ job: { ...s.job, elapsed: ((Date.now() - t0) / 1000) } }) : {}), 100);
    this._timers[key] = [tick];
    const fail = this.state.simFail;
    const job = { key, title, hint, stages, idx: 0, status: "running", elapsed: 0, concept: concept || null, conceptShown: false, onDone };
    this.setState({ job });
    const failAt = fail ? Math.min(2, stages.length - 1) : -1;
    const step = (i: number) => {
      if (i === failAt) {
        this._clearTimers(key);
        this.setState((s: any) => ({ job: { ...s.job, status: "error", errorStage: stages[i - 1] ? stages[i - 1].label : stages[0].label } }));
        return;
      }
      if (i >= stages.length) {
        this._clearTimers(key);
        const done = this.state.job && this.state.job.onDone;
        this.setState({ job: null });
        if (done) done();
        return;
      }
      this.setState((s: any) => ({ job: { ...s.job, idx: i, conceptShown: s.job.conceptShown || (concept && i >= 1) } }));
      const to = setTimeout(() => step(i + 1), stages[i].ms || 1400);
      this._timers[key].push(to);
    };
    const to = setTimeout(() => step(1), stages[0].ms || 1400);
    this._timers[key].push(to);
  }
  _clearTimers(key: string) { (this._timers[key] || []).forEach((t: any) => { clearTimeout(t); clearInterval(t); }); this._timers[key] = []; }
  cancelJob() { if (this.state.job) this._clearTimers(this.state.job.key); this._cancelFlag = true; this.setState({ job: null }); }
  retryJob() {
    const j = this.state.job; if (!j) return;
    this.setState({ simFail: false }, () => { if (j.retry) j.retry(); else this.startJob(j.key, j.title, j.hint, j.stages, j.concept, j.onDone); });
  }

  // Real backend job: keeps the design's staged-progress / concept / cancel UI, but driven by the async
  // Track B endpoints (submit → poll). `runner(onProgress, shouldCancel)` resolves to the job result; the
  // backend's free-text `stage` is mapped onto the predefined `stages` checklist by keyword.
  _startAsyncJob(key: string, title: string, hint: string, stages: any[], concept: boolean,
    runner: (onP: api.Progress, sc: api.ShouldCancel) => Promise<any>, onDone: (r: any) => void, retry: () => void) {
    this._clearTimers(key);
    this._cancelFlag = false;
    const labels = stages.map((s) => s.label);
    const t0 = Date.now();
    const tick = setInterval(() => this.setState((s: any) => (s.job && s.job.key === key) ? ({ job: { ...s.job, elapsed: (Date.now() - t0) / 1000 } }) : {}), 100);
    // stall guard: nothing should run past 10 min (terrain ~6 min is the longest legit job). If it does,
    // the backend likely hung — abandon + signal cancel + surface a clear error instead of spinning forever.
    const stall = setTimeout(() => {
      if (this.state.job && this.state.job.key === key && this.state.job.status === "running") {
        this._cancelFlag = true; this._clearTimers(key);
        this.setState((s: any) => (s.job && s.job.key === key) ? ({ job: { ...s.job, status: "error", errorStage: (s.job.stages[s.job.idx] && s.job.stages[s.job.idx].label) || "", errorMsg: "Generation stalled — no result after 10 min. The job was signalled to cancel; if this recurs, the Track B service may need a restart." } }) : {});
      }
    }, 600000);
    this._timers[key] = [tick, stall];
    this.setState({ job: { key, title, hint, stages, idx: 0, status: "running", elapsed: 0, concept: !!concept, conceptShown: false, retry } });
    const onProgress: api.Progress = (stage, _elapsed, conceptB64, mvViews) => {
      this.setState((s: any) => {
        if (!(s.job && s.job.key === key)) return {};
        const idx = Math.max(s.job.idx, this._resolveStage(stage, labels));
        return { job: { ...s.job, idx, conceptImg: conceptB64 || s.job.conceptImg, mvViews: (mvViews && mvViews.length ? mvViews : s.job.mvViews), conceptShown: s.job.conceptShown || (s.job.concept && idx >= 1) } };
      });
    };
    runner(onProgress, () => this._cancelFlag)
      .then((result) => {
        if (!(this.state.job && this.state.job.key === key)) return;   // cancelled / superseded
        this._clearTimers(key); this.setState({ job: null }); onDone(result);
      })
      .catch((err) => {
        const msg = String((err && err.message) || err);
        if (msg === "cancelled") return;   // cancelJob already cleared the UI
        if (!(this.state.job && this.state.job.key === key)) return;
        this._clearTimers(key);
        this.setState((s: any) => ({ job: { ...s.job, status: "error", errorStage: (s.job.stages[s.job.idx] && s.job.stages[s.job.idx].label) || "", errorMsg: msg } }));
      });
  }
  _resolveStage(stage: string, labels: string[]): number {
    const m = (stage || "").toLowerCase();
    const find = (re: RegExp) => labels.findIndex((l) => re.test(l));
    if (m.includes("queue")) return 0;
    if (m.includes("concept")) return find(/concept/i);
    if (m.includes("multi") || m.includes("view") || m.includes("lock")) return find(/multi|view|lock/i);
    if (m.includes("decim")) return find(/decim/i);
    if (m.includes("terrain")) return find(/terrain/i);
    if (m.includes("bak") || m.includes("tile")) return find(/bak|tile/i);
    if (m.includes("denois")) return find(/denois/i);
    if (m.includes("render") || m.includes("path") || m.includes("cycles")) return find(/render|path|cycles|turntable/i);
    if (m.includes("anim") || m.includes("ltx") || m.includes("motion")) return find(/ltx|motion|anim/i);
    if (m.includes("generat") || m.includes("mesh") || m.includes("sampl")) return find(/generat|mesh/i);
    return -1;   // unknown → keep current idx
  }
  _fmtFaces(n: number) { return n >= 1000 ? Math.round(n / 1000) + "k" : String(n || 0); }
  _cap(b: string) { return b.charAt(0).toUpperCase() + b.slice(1); }
  // Apply a pre-baked terrain tile as the scene ground (fetched static, instant). goAssemble jumps to view it.
  _useTerrainPreset(biome: string, label: string, goAssemble: boolean) {
    this.toast("Loading " + label + " tile…");
    fetchPresetGlb(biome)
      .then((b64) => { this.setState((p: any) => ({ asm: { ...p.asm, ground: "tile", groundGlbId: "preset-" + biome, groundGlb: b64 }, ...(goAssemble ? { workspace: "assemble" } : {}) })); this.toast(label + " terrain set as ground"); })
      .catch(() => this.toast(label + " preset unavailable"));
  }

  // ================= ROBOTICS =================
  generateRobotics() {
    const stages = [
      { label: "Queued", ms: 700 },
      { label: "Interpreting spec (local LLM)", ms: 2400 },
      { label: "Generating CadQuery geometry", ms: 1800 },
      { label: "Verifying against spec", ms: 1600 },
    ];
    this.startJob("cad", "Generating part", "Interpreter is a fine-tuned local model — this can take a moment.", stages, null, () => {
      this.setState((s: any) => ({ rob: { ...s.rob, result: this._buildVerification(s.rob.spec) } }));
      this.toast("Part verified · STEP + STL ready");
    });
  }
  _buildVerification(spec: any) {
    const tol = spec.tol;
    const mk = (name: string, exp: number) => { const d = (Math.random() * 1.4 - 0.7) * tol; return { name, exp: exp.toFixed(2), meas: (exp + d).toFixed(2), delta: d, tol, pass: Math.abs(d) <= tol }; };
    const rows: any[] = [];
    if (spec.shape === "Cylinder") { rows.push(mk("Diameter ⌀", spec.dia), mk("Height", spec.H)); }
    else { rows.push(mk("Length", spec.L), mk("Width", spec.W), mk("Height", spec.H)); }
    spec.features.forEach((f: any) => {
      if (f.kind === "through-hole") rows.push(mk("Hole ⌀", f.dia));
      else if (f.kind === "hole-pattern") rows.push(mk("Bolt-circle PCD", f.pcd));
      else if (f.kind === "fillet") rows.push(mk("Fillet r", f.r));
      else if (f.kind === "chamfer") rows.push(mk("Chamfer d", f.d || 2));
      else if (f.kind === "pocket") rows.push(mk("Pocket depth", f.depth || 5));
    });
    rows.forEach((r) => { r.pass = true; r.meas = (parseFloat(r.exp) + (Math.random() * 1.2 - 0.6) * tol).toFixed(2); });
    return { rows, attempts: 1 + Math.round(Math.random()), timeStr: (8 + Math.random() * 30).toFixed(1) + "s", watertight: true, manifold: true, selectors: rows.length, corrected: Math.random() > 0.5 ? "fillet order to satisfy adjacent face" : null };
  }

  // ================= CREATE (Track B: text/image → 3D) =================
  generateCreate() {
    const { tier, multiview: mv, inputMode } = this.state.cre;
    const isImg = inputMode === "image";
    if (isImg && !this.state.cre.imageB64) { this.toast("Drop a reference image on the left first"); return; }
    const name = this.state.command.trim() || (isImg ? (this.state.cre.imageName || "Image asset") : "Untitled asset");
    const stages: any[] = [{ label: "Queued" }];
    if (!isImg) stages.push({ label: "Concept image (FLUX)" });
    if (mv) stages.push({ label: "Locking geometry (multi-view)" });
    stages.push({ label: "Generating mesh" });
    const run = (onP: api.Progress, sc: api.ShouldCancel) => isImg
      ? api.image2mesh(this.state.cre.imageB64 as string, tier, mv, onP, sc)
      : api.text2mesh(name, tier, mv, onP, sc);
    this._startAsyncJob("trackb", isImg ? "Image → 3D asset" : "Text → 3D asset", tier + " tier · honest progress, cancellable.",
      stages, !isImg, run, (res) => this._onMeshResult(name, "rock", res), () => this.generateCreate());
  }
  _onMeshResult(name: string, geo: string, res: any) {
    const glbId = "g" + (this._uid++);
    const rep = res.report || {};
    this._renderTurntable = null; this._renderBeauty = null;   // new asset → previous render outputs are stale
    this.setState((s: any) => ({
      cre: {
        ...s.cre,
        result: { name, geo, glb: res.glb_b64, glbId, thumb: null, faces: this._fmtFaces(rep.faces), verts: this._fmtFaces(rep.verts),
                  watertight: rep.watertight !== false, pbr: rep.pbr || [], size: (rep.size_mb || 0) + " MB", time: (res.seconds || 0) + "s", concept: res.concept_png_b64 || null },
        lowpolyTarget: 24000, renderTarget: name, renderBeauty: null, motionMp4: null,
      },
      command: "",
    }));
    this.toast("Asset generated · " + this._fmtFaces(rep.faces) + " faces");
    renderThumbnail(res.glb_b64).then((thumb) => this.setState((s: any) => (s.cre.result && s.cre.result.glbId === glbId) ? { cre: { ...s.cre, result: { ...s.cre.result, thumb } } } : {})).catch(() => {});
  }
  runLowpoly() {
    const t = this.state.cre.lowpolyTarget;
    const glb = this.state.cre.result && this.state.cre.result.glb;
    if (!glb) { this.toast("No mesh to decimate"); return; }
    this._startAsyncJob("lowpoly", "Low-Poly decimation", "Welding, then collapsing to a face budget.",
      [{ label: "Queued" }, { label: "Decimating mesh" }], false,
      (onP, sc) => api.lowpoly(glb, t, onP, sc),
      (res) => {
        const glbId = "g" + (this._uid++);
        const faces = this._fmtFaces(res.report ? res.report.faces : t);
        this.setState((s: any) => ({ cre: { ...s.cre, result: { ...s.cre.result, glb: res.glb_b64, glbId, faces } } }));
        this.toast("Decimated to " + faces + " faces");
      }, () => this.runLowpoly());
  }
  generateTerrain(biome: string) {
    const beBiome = biome === "snowy" ? "snowy_mountain" : biome;   // design label → backend biome key
    this._startAsyncJob("terrain", this._cap(biome) + " terrain", "Infinigen terrain tile — true time ~5–6 min. You can keep working.",
      [{ label: "Queued" }, { label: "Generating terrain" }, { label: "Baking tile" }], false,
      (onP, sc) => api.terrain(beBiome, 40000, onP, sc),
      (res) => {
        const glbId = "g" + (this._uid++);
        const id = "t" + (this._uid++);
        const name = this._cap(biome) + " Tile";
        const rep = res.report || {};
        this.setState((s: any) => ({
          library: [{ id, name, geo: "terrain", glb: res.glb_b64, glbId, thumb: null, faces: this._fmtFaces(rep.faces), size: (rep.size_mb || 0) + " MB", status: "ready" }, ...s.library],
          asm: { ...s.asm, ground: "tile", groundGlbId: glbId, groundGlb: res.glb_b64 },   // auto-apply as the scene ground
        }));
        this.toast(name + " added to Library");
        renderThumbnail(res.glb_b64).then((thumb) => this.setState((s: any) => ({ library: s.library.map((x: any) => x.id === id ? { ...x, thumb } : x) }))).catch(() => {});
      }, () => this.generateTerrain(biome));
  }
  doRender(kind: string) {
    const glb = this.state.cre.result && this.state.cre.result.glb;
    const name = this.state.cre.renderTarget || "asset";
    if (!glb) { this.toast("Generate an asset first"); return; }
    if (kind === "still") {
      this._startAsyncJob("render", "Photoreal render", "Path-traced Cycles beauty still + turntable.",
        [{ label: "Queued" }, { label: "Rendering (Cycles)" }], false,
        (onP, sc) => api.render(glb, onP, sc),
        (res) => {
          this._renderBeauty = res.beauty_png_b64 || null; this._renderTurntable = res.turntable_mp4_b64 || null;
          this.setState((s: any) => ({ cre: { ...s.cre, renderTab: "still", renderBeauty: res.beauty_png_b64 || null } }));
          this.toast("Beauty render complete");
        }, () => this.doRender("still"));
    } else {
      const variant = this.state.cre.motionVariant === 0 ? "strong" : "subtle";
      this._startAsyncJob("animate", "Motion clip", "Render turntable → LTX render-to-real motion.",
        [{ label: "Queued" }, { label: "Render turntable" }, { label: "LTX motion synthesis" }], false,
        async (onP, sc) => {
          let tt = this._renderTurntable, ff = this._renderBeauty;
          if (!tt || !ff) { onP("rendering", 0); const r = await api.render(glb, onP, sc); tt = r.turntable_mp4_b64 || null; ff = r.beauty_png_b64 || null; this._renderTurntable = tt; this._renderBeauty = ff; }
          if (!tt || !ff) throw new Error("render produced no turntable to animate");
          return api.animate(tt, ff, name, variant, onP, sc);
        },
        (res) => { this.setState((s: any) => ({ cre: { ...s.cre, renderTab: "motion", motionMp4: res.animated_mp4_b64 || null } })); this.toast("Motion clip ready"); },
        () => this.doRender("motion"));
    }
  }

  // ================= ASSEMBLE =================
  addObject(libItem: any, atRandom: boolean, at?: number[] | null) {
    this._pushUndo();
    const id = "o" + (this._uid++);
    const pos = at
      ? [+at[0].toFixed(2), +at[1].toFixed(2), +at[2].toFixed(2)]                       // dropped at a specific ground point
      : [atRandom ? (Math.random() * 4 - 2) : 0, 0, atRandom ? (Math.random() * 4 - 2) : 0];
    const obj = {
      id, name: libItem.name, geo: libItem.geo, faces: libItem.faces,
      glb: libItem.glb || null, glbId: libItem.glbId || null,   // real mesh, if this asset has one
      pos, rot: [0, Math.random() * 360, 0], scale: [1, 1, 1], hidden: false,
    };
    this.setState((s: any) => ({ asm: { ...s.asm, objects: [...s.asm.objects, obj], selectedId: id } }));
    this.toast(libItem.name + " dropped to ground");
  }
  // Drop a Library asset onto the canvas at the cursor's ground/terrain point.
  _dropAsset(e: any) {
    e.preventDefault();
    if (this.state.workspace !== "assemble" || !this._dragItem) return;
    const it = this._dragItem; this._dragItem = null;
    const cv = this._three && this._three.renderer.domElement;
    let at: number[] | null = null;
    if (cv) {
      const r = cv.getBoundingClientRect();
      this._mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      this._mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      const g = this._groundPoint();
      if (g) at = [g.x, g.y, g.z];
    }
    this.addObject(it, !at, at);
  }
  // Assemble "Finish": export / render / animate the composed scene (the live modelGroup).
  async _sceneAction(kind: string) {
    if (!this._three) return;
    const group = this._three.modelGroup;
    if (kind === "GLB") { try { downloadBytes(await exportGlb(group), "scene.glb", "model/gltf-binary"); this.toast("Scene exported · GLB"); } catch (e) { this.toast("Export failed"); } return; }
    if (kind === "USDZ") { try { downloadBytes(await exportUsdz(group), "scene.usdz", "model/vnd.usdz+zip"); this.toast("Scene exported · USDZ"); } catch (e) { this.toast("USDZ failed"); } return; }
    let glbB64: string;
    try { glbB64 = bytesToB64(await exportGlb(group)); } catch (e) { this.toast("Scene export failed"); return; }
    if (kind === "Render") {
      this._startAsyncJob("scrender", "Render scene", "Path-traced Cycles of the composed scene.",
        [{ label: "Queued" }, { label: "Rendering (Cycles)" }], false,
        (onP, sc) => api.render(glbB64, onP, sc),
        (res) => { if (res.beauty_png_b64) downloadB64(res.beauty_png_b64, "scene-beauty.png", "image/png"); this.toast("Scene render complete · PNG downloaded"); },
        () => this._sceneAction("Render"));
    } else {
      this._startAsyncJob("scanim", "Animate scene", "Render turntable → LTX motion.",
        [{ label: "Queued" }, { label: "Render turntable" }, { label: "LTX motion synthesis" }], false,
        async (onP, sc) => { onP("rendering", 0); const r = await api.render(glbB64, onP, sc); const tt = r.turntable_mp4_b64, ff = r.beauty_png_b64; if (!tt || !ff) throw new Error("render produced no turntable"); return api.animate(tt, ff, "composed scene", this.state.cre.motionVariant === 0 ? "strong" : "subtle", onP, sc); },
        (res) => { if (res.animated_mp4_b64) downloadB64(res.animated_mp4_b64, "scene-motion.mp4", "video/mp4"); this.toast("Scene motion ready · MP4 downloaded"); },
        () => this._sceneAction("Animate"));
    }
  }
  selectObj(id: any) { this.setState((s: any) => ({ asm: { ...s.asm, selectedId: id, selectedIds: id ? [id] : [] } })); }
  toggleSelect(id: any) {
    this.setState((s: any) => {
      const cur: string[] = s.asm.selectedIds && s.asm.selectedIds.length ? s.asm.selectedIds : (s.asm.selectedId ? [s.asm.selectedId] : []);
      const has = cur.includes(id);
      const ids = has ? cur.filter((x) => x !== id) : [...cur, id];
      return { asm: { ...s.asm, selectedIds: ids, selectedId: has ? (ids[ids.length - 1] || null) : id } };
    });
  }
  _selIds(): string[] { const a = this.state.asm; return a.selectedIds && a.selectedIds.length ? a.selectedIds : (a.selectedId ? [a.selectedId] : []); }
  _isSelected(id: any) { const a = this.state.asm; return (a.selectedIds && a.selectedIds.includes(id)) || a.selectedId === id; }
  // hover highlight (assemble): tint the object under the cursor, imperatively (no React re-render per move)
  _updateHover(cv: any) {
    if (!this._three || this.state.workspace !== "assemble") { if (this._hoverOid) { this._applyHover(this._hoverOid, false); this._hoverOid = null; } return; }
    this._raycaster.setFromCamera(this._mouse, this._three.camera);
    const hits = this._raycaster.intersectObjects(this._three.modelGroup.children, true);
    const hit = hits.find((h: any) => h.object.userData.oid || (h.object.parent && h.object.parent.userData.oid));
    const oid = hit ? (hit.object.userData.oid || hit.object.parent.userData.oid) : null;
    if (oid !== this._hoverOid) {
      if (this._hoverOid) this._applyHover(this._hoverOid, false);
      this._hoverOid = oid;
      if (oid) this._applyHover(oid, true);
      if (cv) cv.style.cursor = oid ? "pointer" : "grab";
    }
  }
  _applyHover(oid: any, on: boolean) {
    const node = this._objNode(oid); if (!node) return;
    const sel = this._isSelected(oid);
    const hex = on ? (sel ? 0x2a3050 : 0x1a1d2e) : (sel ? 0x222a44 : 0x000000);
    node.traverse((c: any) => { const ms = c.material ? (Array.isArray(c.material) ? c.material : [c.material]) : []; ms.forEach((m: any) => { if (m && m.emissive) m.emissive.setHex(hex); }); });
  }
  _setGizmo(m: string) { this.setState((s: any) => ({ asm: { ...s.asm, gizmoMode: m } })); }
  deleteSel() { const ids = this._selIds(); if (!ids.length) return; this._pushUndo(); this.setState((s: any) => ({ asm: { ...s.asm, objects: s.asm.objects.filter((o: any) => !ids.includes(o.id)), selectedId: null, selectedIds: [] } })); this.toast(ids.length > 1 ? ids.length + " deleted" : "Deleted"); }
  dupSel() {
    const ids = this._selIds(); if (!ids.length) return;
    this._pushUndo();
    const sel = this.state.asm.objects.filter((o: any) => ids.includes(o.id));
    const copies = sel.map((o: any) => ({ ...JSON.parse(JSON.stringify(o)), id: "o" + (this._uid++), name: o.name + " copy", pos: [o.pos[0] + 1.2, o.pos[1], o.pos[2] + 1.2] }));
    const newIds = copies.map((c: any) => c.id);
    this.setState((s: any) => ({ asm: { ...s.asm, objects: [...s.asm.objects, ...copies], selectedId: newIds[newIds.length - 1], selectedIds: newIds } }));
    this.toast(copies.length > 1 ? copies.length + " duplicated" : "Duplicated");
  }
  updateObj(id: any, patch: any) { this.setState((s: any) => ({ asm: { ...s.asm, objects: s.asm.objects.map((o: any) => o.id === id ? { ...o, ...patch } : o) } })); }
  toggleHide(id: any) { this._pushUndo(); this.setState((s: any) => ({ asm: { ...s.asm, objects: s.asm.objects.map((o: any) => o.id === id ? { ...o, hidden: !o.hidden } : o) } })); }
  _snapAsm() { return JSON.parse(JSON.stringify({ objects: this.state.asm.objects, selectedId: this.state.asm.selectedId, ground: this.state.asm.ground })); }
  _pushUndo() { this._undo.push(this._snapAsm()); if (this._undo.length > 60) this._undo.shift(); this._redo = []; }
  undo() { if (!this._undo.length) { return; } this._redo.push(this._snapAsm()); const snap = this._undo.pop(); this.setState((p: any) => ({ asm: { ...p.asm, objects: snap.objects, selectedId: snap.selectedId, ground: snap.ground } })); this.toast("Undo"); }
  redo() { if (!this._redo.length) { return; } this._undo.push(this._snapAsm()); const snap = this._redo.pop(); this.setState((p: any) => ({ asm: { ...p.asm, objects: snap.objects, selectedId: snap.selectedId, ground: snap.ground } })); this.toast("Redo"); }
  reorderObjects(fromId: any, toId: any) { if (fromId === toId) return; this._pushUndo(); this.setState((p: any) => { const arr = [...p.asm.objects]; const fi = arr.findIndex((o: any) => o.id === fromId); const ti = arr.findIndex((o: any) => o.id === toId); if (fi < 0 || ti < 0) return {}; const [m] = arr.splice(fi, 1); arr.splice(ti, 0, m); return { asm: { ...p.asm, objects: arr } }; }); }
  setGround(g: string) { this._pushUndo(); this.setState((p: any) => ({ asm: { ...p.asm, ground: g } })); }
  editObj(id: any, patch: any) { this._pushUndo(); this.updateObj(id, patch); }
  frameObject(o: any) { if (!this._cam) return; if (o) { this._cam.target.set(o.pos[0], Math.max(0.8, o.pos[1] + 0.8), o.pos[2]); this._cam.r = 8; } else { this._cam.target.set(0, this.state.workspace === "assemble" ? 1.2 : 1.5, 0); this._cam.r = 16; this._cam.theta = 0.7; this._cam.phi = 1.05; } }

  // ================= THREE VIEWPORT =================
  _waitThree() {
    // three is bundled (npm), so it's always present — just (re)try until the viewport div exists.
    this._initViewport();
  }
  _initViewport() {
    const el = document.getElementById("ml-viewport");
    if (!el) { this._threeT = setTimeout(() => this._waitThree(), 120); return; }
    if (this._three) return;
    while (el.firstChild) el.removeChild(el.firstChild);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;   // contact shadows
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x06070a, 0.018);
    const camera = new THREE.PerspectiveCamera(42, el.clientWidth / el.clientHeight, 0.1, 1000);
    this._cam = { theta: 0.7, phi: 1.05, r: 16, target: new THREE.Vector3(0, 1.5, 0) };
    scene.add(new THREE.HemisphereLight(0x9fb4ff, 0x0a0a12, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.1); key.position.set(6, 12, 8); scene.add(key);
    key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -0.0005;
    key.shadow.camera.near = 1; key.shadow.camera.far = 60;
    key.shadow.camera.left = -25; key.shadow.camera.right = 25; key.shadow.camera.top = 25; key.shadow.camera.bottom = -25;
    const rim = new THREE.PointLight(0xffffff, 0.8, 60); rim.position.set(-8, 6, -6); scene.add(rim);
    this._rim = rim;
    // image-based lighting (procedural studio env, no external HDR) → PBR/metallic surfaces (car paint,
    // metals) get real reflections instead of rendering flat/blotchy. ACES tone-mapping for HDR→display.
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();
    const grid = new THREE.GridHelper(40, 40, 0x2a2f44, 0x161a28);
    (grid.material as any).transparent = true; (grid.material as any).opacity = 0.5; scene.add(grid);
    this._grid = grid;
    const modelGroup = new THREE.Group(); scene.add(modelGroup);
    this._gizmoGroup = new THREE.Group(); scene.add(this._gizmoGroup);
    this._three = { renderer, scene, camera, modelGroup, el };
    this._raycaster = new THREE.Raycaster();
    this._mouse = new THREE.Vector2();
    this._bindPointer(el);
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(el);
    this._sig = "";
    this._syncViewport();
    const loop = () => {
      this._raf = requestAnimationFrame(loop);
      if (this.state.turntable && !this._dragging && this.state.workspace !== "assemble") this._cam.theta += 0.0032;
      this._updateCamera();
      // gizmo: constant on-screen size — scale by distance to camera so it's grabbable at any zoom
      if (this._gizmoGroup && this._gizmoGroup.children.length) {
        const d = camera.position.distanceTo(this._gizmoGroup.position);
        this._gizmoGroup.scale.setScalar(Math.max(0.05, d * 0.062));
      }
      const moodCols = [[0x9fb4ff, 0.8], [0xffb070, 0.9], [0x5060a0, 0.6]];
      const mc = moodCols[this.state.lighting] || moodCols[0];
      this._rim.color.setHex(mc[0]); this._rim.intensity = mc[1];
      renderer.render(scene, camera);
    };
    loop();
  }
  _updateCamera() {
    const c = this._cam, cam = this._three.camera;
    c.phi = Math.max(0.25, Math.min(1.45, c.phi));
    cam.position.set(
      c.target.x + c.r * Math.sin(c.phi) * Math.cos(c.theta),
      c.target.y + c.r * Math.cos(c.phi),
      c.target.z + c.r * Math.sin(c.phi) * Math.sin(c.theta),
    );
    cam.lookAt(c.target);
  }
  _resize() {
    if (!this._three) return;
    const { renderer, camera, el } = this._three;
    if (!el.clientWidth) return;
    renderer.setSize(el.clientWidth, el.clientHeight);
    camera.aspect = el.clientWidth / el.clientHeight; camera.updateProjectionMatrix();
  }
  _axisOf(obj: any) { let o = obj; while (o) { if (o.userData && o.userData.gizmoAxis) return o.userData.gizmoAxis; o = o.parent; } return null; }
  _closestAxisParam(anchor: any, d: any) {
    const ray = this._raycaster.ray;
    const w0 = new THREE.Vector3().subVectors(anchor, ray.origin);
    const b = d.dot(ray.direction), dd = d.dot(w0), ee = ray.direction.dot(w0);
    const denom = 1 - b * b; if (Math.abs(denom) < 1e-6) return 0;
    return (b * ee - dd) / denom;
  }
  _bindPointer(el: any) {
    const cv = this._three.renderer.domElement;
    let last: any = null, dragObj: any = null, dragStart: any = null, orbiting = false, panning = false, gizmoDrag: any = null;
    const setMouse = (e: any) => { const r = cv.getBoundingClientRect(); this._mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1; this._mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1; };
    cv.style.cursor = "grab";
    cv.addEventListener("mousedown", (e: any) => { if (e.button === 1) e.preventDefault(); });
    cv.addEventListener("auxclick", (e: any) => { if (e.button === 1) e.preventDefault(); });
    cv.addEventListener("pointerdown", (e: any) => {
      setMouse(e); try { cv.setPointerCapture(e.pointerId); } catch (_) {}
      const isAssemble = this.state.workspace === "assemble";
      const isMiddle = e.button === 1;
      if (isMiddle) e.preventDefault();
      if (isAssemble && e.button === 0) {
        this._raycaster.setFromCamera(this._mouse, this._three.camera);
        const sel = this.state.asm.objects.find((o: any) => o.id === this.state.asm.selectedId);
        if (sel && this._gizmoGroup && this._gizmoGroup.children.length) {
          const gHits = this._raycaster.intersectObjects(this._gizmoGroup.children, true);
          const gHit = gHits.find((h: any) => this._axisOf(h.object));
          if (gHit) {
            this._pushUndo();
            const axisName = this._axisOf(gHit.object);
            const ai = ({ x: 0, y: 1, z: 2 } as any)[axisName];
            const axisVec = new THREE.Vector3(ai === 0 ? 1 : 0, ai === 1 ? 1 : 0, ai === 2 ? 1 : 0);
            const anchor = new THREE.Vector3(sel.pos[0], Math.max(0.8, sel.pos[1] + 0.8), sel.pos[2]);
            const byId0: any = {}; this.state.asm.objects.forEach((o: any) => { byId0[o.id] = o; });
            const gGroup = this._selIds().map((id) => ({ id, pos: [...byId0[id].pos] }));   // translate all selected
            gizmoDrag = { mode: this.state.asm.gizmoMode, ai, axisVec, anchor, id: sel.id, startObj: JSON.parse(JSON.stringify(sel)), group: gGroup, downX: e.clientX, downY: e.clientY, scStart: this._closestAxisParam(anchor, axisVec) };
            this._dragging = true; cv.style.cursor = "grabbing";
            return;
          }
        }
        const hits = this._raycaster.intersectObjects(this._three.modelGroup.children, true);
        const hit = hits.find((h: any) => h.object.userData.oid || (h.object.parent && h.object.parent.userData.oid));
        if (hit) {
          const oid = hit.object.userData.oid || hit.object.parent.userData.oid;
          if (e.shiftKey) { this.toggleSelect(oid); return; }   // shift-click toggles selection (no drag)
          let group: any[];
          if (e.altKey) {
            this._pushUndo();
            const src = this.state.asm.objects.find((o: any) => o.id === oid);
            const nid = "o" + (this._uid++);
            const dup = { ...JSON.parse(JSON.stringify(src)), id: nid, name: src.name + " copy" };
            this.setState((p: any) => ({ asm: { ...p.asm, objects: [...p.asm.objects, dup], selectedId: nid, selectedIds: [nid] } }));
            this.toast("Alt-duplicated");
            group = [{ id: nid, pos: [...src.pos] }]; dragObj = dup;
          } else {
            const inMulti = this._isSelected(oid) && this._selIds().length > 1;   // click inside a multi-selection → drag the group
            if (!inMulti) this.selectObj(oid);
            this._pushUndo();
            const ids = inMulti ? this._selIds() : [oid];
            const byId: any = {}; this.state.asm.objects.forEach((o: any) => { byId[o.id] = o; });
            group = ids.map((id) => ({ id, pos: [...byId[id].pos] })); dragObj = byId[oid];
          }
          dragStart = { mode: this.state.asm.gizmoMode, obj: JSON.parse(JSON.stringify(dragObj)), x: e.clientX, y: e.clientY, ground: this._groundPoint(), group };
          this._dragging = true; cv.style.cursor = "grabbing";
        } else { this.selectObj(null); }
        return;
      }
      const wantPan = (isMiddle && e.shiftKey) || e.button === 2;   // ⇧+middle-drag OR right-drag = pan
      if (wantPan) {
        panning = true; this._dragging = true; last = { x: e.clientX, y: e.clientY };
        cv.style.cursor = "move"; e.preventDefault();
      } else if (isMiddle || (!isAssemble && e.button === 0)) {
        orbiting = true; this._dragging = true; last = { x: e.clientX, y: e.clientY };
        cv.style.cursor = "grabbing";
      }
    });
    cv.addEventListener("pointermove", (e: any) => {
      setMouse(e);
      if (!this._dragging) { this._updateHover(cv); return; }
      if (gizmoDrag) {
        this._raycaster.setFromCamera(this._mouse, this._three.camera);
        const g = gizmoDrag; const snap = e.shiftKey || this.state.asm.snap; const AX = ["X", "Y", "Z"][g.ai];
        if (g.mode === "move") {
          let d = this._closestAxisParam(g.anchor, g.axisVec) - g.scStart;
          if (snap) d = Math.round(d / 0.5) * 0.5;
          for (const gs of (g.group && g.group.length ? g.group : [{ id: g.id, pos: g.startObj.pos }])) {   // translate the whole selection
            const np = [...gs.pos]; np[g.ai] = +(gs.pos[g.ai] + d).toFixed(2);
            if (g.ai === 1) np[1] = Math.max(0, np[1]);
            this.updateObj(gs.id, { pos: np });
          }
          this._dragReadout(e, AX + " Δ" + d.toFixed(2));
        } else if (g.mode === "rotate") {
          let ang = g.startObj.rot[g.ai] + ((e.clientX - g.downX) + (g.downY - e.clientY)) * 0.6;
          if (snap) ang = Math.round(ang / 15) * 15;
          const rot = [...g.startObj.rot]; rot[g.ai] = +(((ang % 360) + 360) % 360).toFixed(0);
          this.updateObj(g.id, { rot });
          this._dragReadout(e, AX + " " + rot[g.ai] + "°");
        } else {
          let f = Math.max(0.1, g.startObj.scale[g.ai] + (e.clientX - g.downX) * 0.01);
          if (snap) f = Math.max(0.1, Math.round(f / 0.1) * 0.1);
          const sc = [...g.startObj.scale]; sc[g.ai] = +f.toFixed(2);
          this.updateObj(g.id, { scale: sc });
          this._dragReadout(e, AX + " ×" + sc[g.ai].toFixed(2));
        }
        return;
      }
      if (dragObj && dragStart) {
        const snap = e.shiftKey || this.state.asm.snap;
        if (dragStart.mode === "move") {
          const g = this._groundPoint();
          if (g && dragStart.ground) {
            let dx = g.x - dragStart.ground.x, dz = g.z - dragStart.ground.z;
            if (snap) { dx = Math.round(dx / 0.5) * 0.5; dz = Math.round(dz / 0.5) * 0.5; }   // snap the delta → preserves group spacing
            for (const gs of (dragStart.group && dragStart.group.length ? dragStart.group : [{ id: dragObj.id, pos: dragStart.obj.pos }])) {
              const nx = gs.pos[0] + dx, nz = gs.pos[2] + dz;
              this.updateObj(gs.id, { pos: [+nx.toFixed(2), +this._groundHeightAt(nx, nz).toFixed(2), +nz.toFixed(2)] });
            }
            this._dragReadout(e, "Δ " + dx.toFixed(1) + ", " + dz.toFixed(1));
          }
        } else if (dragStart.mode === "rotate") {
          let ry = dragStart.obj.rot[1] + (e.clientX - dragStart.x) * 0.7;
          if (snap) ry = Math.round(ry / 15) * 15;
          ry = +(((ry % 360) + 360) % 360).toFixed(0);
          this.updateObj(dragObj.id, { rot: [dragStart.obj.rot[0], ry, dragStart.obj.rot[2]] });
          this._dragReadout(e, "Y " + ry + "°");
        } else if (dragStart.mode === "scale") {
          let f = Math.max(0.2, dragStart.obj.scale[0] + (e.clientX - dragStart.x) * 0.01);
          if (snap) f = Math.max(0.2, Math.round(f / 0.1) * 0.1);
          this.updateObj(dragObj.id, { scale: [+f.toFixed(2), +f.toFixed(2), +f.toFixed(2)] });
          this._dragReadout(e, "× " + f.toFixed(2));
        }
        return;
      }
      if (panning && last) {
        // pan = slide the camera target across its own screen plane (right/up basis), scaled by distance
        const cam = this._three.camera;
        const fwd = new THREE.Vector3(); cam.getWorldDirection(fwd);
        const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
        const up = new THREE.Vector3().crossVectors(right, fwd).normalize();
        const k = this._cam.r * 0.0016;
        this._cam.target.addScaledVector(right, -(e.clientX - last.x) * k).addScaledVector(up, (e.clientY - last.y) * k);
        last = { x: e.clientX, y: e.clientY };
        return;
      }
      if (orbiting && last) {
        this._cam.theta += (e.clientX - last.x) * 0.006;
        this._cam.phi -= (e.clientY - last.y) * 0.006;
        last = { x: e.clientX, y: e.clientY };
      }
    });
    const end = (_e: any) => { this._dragging = false; dragObj = null; dragStart = null; last = null; orbiting = false; panning = false; gizmoDrag = null; cv.style.cursor = "grab"; if (this.state.dragLabel) this.setState({ dragLabel: null }); };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("contextmenu", (e: any) => e.preventDefault());   // allow right-drag to pan without the menu
    cv.addEventListener("wheel", (e: any) => { e.preventDefault(); this._cam.r = Math.max(5, Math.min(40, this._cam.r + e.deltaY * 0.01)); }, { passive: false });
    cv.addEventListener("dblclick", (e: any) => {
      setMouse(e);
      if (this.state.workspace === "assemble") {
        this._raycaster.setFromCamera(this._mouse, this._three.camera);
        const hits = this._raycaster.intersectObjects(this._three.modelGroup.children, true);
        const hit = hits.find((h: any) => h.object.userData.oid || (h.object.parent && h.object.parent.userData.oid));
        if (hit) { const oid = hit.object.userData.oid || hit.object.parent.userData.oid; const o = this.state.asm.objects.find((x: any) => x.id === oid); this.selectObj(oid); this.frameObject(o); return; }
      }
      this.frameObject(null);
    });
  }
  _dragReadout(e: any, text: string) { this.setState({ dragLabel: { text, x: e.clientX + 14, y: e.clientY + 14 } }); }
  _groundPoint() {
    this._raycaster.setFromCamera(this._mouse, this._three.camera);
    // prefer the real ground mesh (terrain tile / base) so drops land on the surface; else the y=0 plane
    const ground = this._three.modelGroup.children.find((c: any) => c.userData.isGround);
    if (ground) { const hits = this._raycaster.intersectObject(ground, true); if (hits.length) return hits[0].point; }
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const pt = new THREE.Vector3();
    return this._raycaster.ray.intersectPlane(plane, pt) ? pt : null;
  }
  // Surface height at an XZ position (raycast straight down onto the ground mesh) — keeps objects on the terrain.
  _groundHeightAt(x: number, z: number) {
    const ground = this._three && this._three.modelGroup.children.find((c: any) => c.userData.isGround);
    if (!ground) return 0;
    this._raycaster.set(new THREE.Vector3(x, 100, z), new THREE.Vector3(0, -1, 0));
    const hits = this._raycaster.intersectObject(ground, true);
    return hits.length ? hits[0].point.y : 0;
  }
  _disposeChildren(group: any) {
    while (group.children.length) {
      const c = group.children[0];
      if (c.traverse) c.traverse((n: any) => { if (n.geometry) n.geometry.dispose(); if (n.material) { (Array.isArray(n.material) ? n.material : [n.material]).forEach((m: any) => m && m.dispose && m.dispose()); } });
      group.remove(c);
    }
  }
  _makeGeo(geo: string) {
    const g = new THREE.Group();
    if (geo === "rock") { g.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.4, 1), this._mat(geo))); }
    else if (geo === "tree") {
      const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.24, 1.2, 8), this._mat("box")); trunk.position.y = 0.6;
      const top = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2, 9), this._mat("tree")); top.position.y = 2;
      g.add(trunk, top);
    } else if (geo === "arch") {
      const t = new THREE.Mesh(new THREE.TorusGeometry(1.1, 0.32, 12, 24, Math.PI), this._mat(geo)); t.position.y = 1.1; g.add(t);
    } else if (geo === "box") { const m = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.4, 1.6), this._mat(geo)); m.position.y = 0.7; g.add(m); }
    else if (geo === "mushroom") {
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 1, 10), this._mat("box")); stem.position.y = 0.5;
      const cap = new THREE.Mesh(new THREE.SphereGeometry(0.8, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2), this._mat(geo)); cap.position.y = 1; cap.scale.y = 0.7;
      g.add(stem, cap);
    } else if (geo === "terrain") {
      const m = new THREE.Mesh(new THREE.BoxGeometry(6, 0.4, 6), this._mat(geo)); m.position.y = 0.2; g.add(m);
    } else { g.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.4, 1), this._mat("rock"))); }
    g.traverse((c: any) => { if (c.isMesh) c.castShadow = true; });
    return g;
  }
  _mat(geo: string) {
    const col = this.GEOCOLOR[geo] || "#9aa0ac";
    const mode = this.state.viewMode;
    if (mode === "wireframe") return new THREE.MeshBasicMaterial({ color: col, wireframe: true });
    if (mode === "xray") return new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.3, depthWrite: false });
    return new THREE.MeshStandardMaterial({ color: col, metalness: 0.2, roughness: 0.65 });
  }
  // ---- real GLB into the viewport (TRELLIS.2 meshes + terrain tiles) ----
  _glbModel(scene: any) {
    // normalize to ~2.4 world units, center in XZ, sit on the ground; wrap so callers transform the wrapper.
    const obj = scene;
    const size = new THREE.Box3().setFromObject(obj).getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    obj.scale.setScalar(2.4 / maxDim);
    const bb = new THREE.Box3().setFromObject(obj);
    const ctr = bb.getCenter(new THREE.Vector3());
    obj.position.set(-ctr.x, -bb.min.y, -ctr.z);
    const wrap = new THREE.Group(); wrap.add(obj); return wrap;
  }
  _applyViewToGlb(node: any) {
    const mode = this.state.viewMode;
    if (mode === "solid") return;   // keep the real PBR materials
    node.traverse((c: any) => {
      if (c.isMesh) {
        const col = (c.material && c.material.color) ? c.material.color.getHex() : 0x9aa6d6;
        c.material = mode === "wireframe"
          ? new THREE.MeshBasicMaterial({ color: col, wireframe: true })
          : new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.3, depthWrite: false });
      }
    });
  }
  _addGlbToGroup(group: any, b64: string, id: string, oid: any) {
    const place = (tmpl: any) => {
      const node = tmpl.clone(true);
      if (this.state.viewMode === "solid") node.traverse((c: any) => {
        if (!(c.isMesh && c.material)) return;
        // TRELLIS meshes have a sliver-heavy surface; mirror-sharp reflections craze on it. Soften them:
        // raise a roughness floor, cap metalness, dial env reflections — keeps PBR, kills the crazing.
        const tame = (m: any) => { const x = m.clone(); if (x.roughness !== undefined) x.roughness = Math.max(x.roughness, 0.55); if (x.metalness !== undefined) x.metalness = Math.min(x.metalness, 0.5); x.envMapIntensity = 0.6; return x; };
        c.material = Array.isArray(c.material) ? c.material.map(tame) : tame(c.material);
      });
      else this._applyViewToGlb(node);
      node.traverse((c: any) => { if (c.isMesh) c.castShadow = true; });
      if (oid) { node.userData.oid = oid; node.traverse((c: any) => { c.userData.oid = oid; }); }
      group.add(node);
    };
    if (this._glbCache[id]) { place(this._glbCache[id]); return; }
    const sigAt = this._sig;
    parseGlbScene(b64).then((scene) => {
      const tmpl = this._glbModel(scene);
      this._glbCache[id] = tmpl;
      if (this._three && this._sig === sigAt) place(tmpl);   // group still current → drop it in; else next rebuild clones from cache
    }).catch((e) => console.error("GLB load failed", e));
  }
  _objNode(id: any) { return this._three ? this._three.modelGroup.children.find((n: any) => n.userData.oid === id) : null; }
  // terrain tile used as the scene ground: normalize to a large footprint, base at y=0.
  _groundModel(scene: any) {
    const obj = scene;
    const size = new THREE.Box3().setFromObject(obj).getSize(new THREE.Vector3());
    const footprint = Math.max(size.x, size.z) || 1;
    obj.scale.setScalar(24 / footprint);
    const bb = new THREE.Box3().setFromObject(obj);
    const ctr = bb.getCenter(new THREE.Vector3());
    obj.position.set(-ctr.x, -bb.min.y, -ctr.z);   // center XZ, sit base on y=0
    const wrap = new THREE.Group(); wrap.add(obj); return wrap;
  }
  _addGroundGlb(group: any, b64: string, id: string) {
    const key = "ground:" + id;
    const place = (tmpl: any) => { const node = tmpl.clone(true); node.userData.isGround = true; node.traverse((c: any) => { c.userData.isGround = true; if (c.isMesh) c.receiveShadow = true; }); group.add(node); };
    if (this._glbCache[key]) { place(this._glbCache[key]); return; }
    const sigAt = this._sig;
    parseGlbScene(b64).then((scene) => { const tmpl = this._groundModel(scene); this._glbCache[key] = tmpl; if (this._three && this._sig === sigAt) place(tmpl); }).catch((e) => console.error("ground GLB load failed", e));
  }

  _buildRoboticsModel() {
    const g = new THREE.Group();
    const acc = "#7c8bff";
    const matMetal = this.state.viewMode === "wireframe" ? new THREE.MeshBasicMaterial({ color: acc, wireframe: true })
      : this.state.viewMode === "xray" ? new THREE.MeshBasicMaterial({ color: acc, transparent: true, opacity: 0.3, depthWrite: false })
      : new THREE.MeshStandardMaterial({ color: 0x9aa6d6, metalness: 0.7, roughness: 0.34 });
    const sp = this.state.rob.spec;
    const L = sp.L / 20, W = sp.W / 20, H = Math.max(0.3, sp.H / 20);
    const base = new THREE.Mesh(new THREE.BoxGeometry(L, H, W), matMetal); base.position.y = H / 2 + 0.4; g.add(base);
    const boss = new THREE.Mesh(new THREE.CylinderGeometry(W * 0.28, W * 0.32, H * 1.6, 24), matMetal); boss.position.set(L * 0.22, H + 0.4, 0); g.add(boss);
    const hole = new THREE.Mesh(new THREE.CylinderGeometry(W * 0.13, W * 0.13, H * 2, 20), new THREE.MeshBasicMaterial({ color: 0x05060a }));
    hole.position.set(L * 0.22, H + 0.4, 0); g.add(hole);
    return g;
  }
  _syncViewport() {
    if (!this._three) return;
    const s = this.state;
    const sig = [s.workspace, s.viewMode, JSON.stringify(s.rob.spec.L), s.rob.spec.shape, s.rob.spec.W, s.rob.spec.H, s.cre.result ? (s.cre.result.glbId || s.cre.result.faces) : "n", s.asm.objects.map((o: any) => o.id + o.geo + (o.glbId || "") + o.hidden).join(","), s.asm.ground, s.asm.groundGlbId || ""].join("|");
    if (sig === this._sig) { this._syncTransforms(); this._syncGizmo(); return; }
    this._sig = sig;
    const mg = this._three.modelGroup;
    this._disposeChildren(mg);
    if (this._gizmoGroup) this._disposeChildren(this._gizmoGroup);
    this._grid.visible = (s.workspace === "assemble");

    if (s.workspace === "robotics") {
      this._cam.target.set(0, 1.6, 0); mg.add(this._buildRoboticsModel());
    } else if (s.workspace === "create") {
      this._cam.target.set(0, 1.5, 0);
      if (s.cre.result && s.cre.result.glb) {
        this._addGlbToGroup(mg, s.cre.result.glb, s.cre.result.glbId, null);   // the real generated mesh
      } else {
        const m = this._makeGeo("rock"); m.position.y = 0.2; m.scale.set(0.9, 0.9, 0.9);   // idle placeholder
        m.traverse((c: any) => { if (c.material) { c.material.transparent = true; c.material.opacity = 0.35; } });
        mg.add(m);
      }
    } else {
      this._cam.target.set(0, 1.2, 0);
      if (s.asm.groundGlb) {
        this._addGroundGlb(mg, s.asm.groundGlb, s.asm.groundGlbId);   // real terrain tile as the ground
      } else {
        const tileCol = ({ forest: 0x4a5c3a, desert: 0xb89a5e, snowy: 0xcfd8e8, arctic: 0xbcd0d8, plain: 0x6f7a55, none: 0x1a1d28 } as any)[s.asm.ground] || 0x4a5c3a;
        const tile = new THREE.Mesh(new THREE.BoxGeometry(20, 0.3, 20), new THREE.MeshStandardMaterial({ color: tileCol, roughness: 0.95, metalness: 0 }));
        tile.position.y = -0.15; tile.userData.isGround = true; tile.receiveShadow = true; mg.add(tile);
      }
      s.asm.objects.forEach((o: any) => {
        if (o.hidden) return;
        if (o.glb) { this._addGlbToGroup(mg, o.glb, o.glbId || o.id, o.id); return; }   // real asset
        const node = this._makeGeo(o.geo); node.userData.oid = o.id; node.traverse((c: any) => { c.userData.oid = o.id; });
        mg.add(node);
      });
    }
    this._syncTransforms();
    this._syncGizmo();
  }
  _syncTransforms() {
    if (!this._three || this.state.workspace !== "assemble") return;
    const mg = this._three.modelGroup;
    const map: any = {};
    this.state.asm.objects.forEach((o: any) => { map[o.id] = o; });
    mg.children.forEach((node: any) => {
      const o = node.userData.oid && map[node.userData.oid];
      if (o) {
        node.position.set(o.pos[0], o.pos[1], o.pos[2]);
        node.rotation.set(o.rot[0] * Math.PI / 180, o.rot[1] * Math.PI / 180, o.rot[2] * Math.PI / 180);
        node.scale.set(o.scale[0], o.scale[1], o.scale[2]);
        node.visible = !o.hidden;
        const sel = this._isSelected(o.id);
        node.traverse((c: any) => { const ms = c.material ? (Array.isArray(c.material) ? c.material : [c.material]) : []; ms.forEach((m: any) => { if (m && m.emissive) m.emissive.setHex(sel ? 0x222a44 : 0x000000); }); });
      }
    });
  }
  _syncGizmo() {
    if (!this._gizmoGroup) return;
    this._disposeChildren(this._gizmoGroup);
    if (this.state.workspace !== "assemble") return;
    const o = this.state.asm.objects.find((x: any) => x.id === this.state.asm.selectedId);
    if (!o || o.hidden) return;
    const mode = this.state.asm.gizmoMode;
    const yUp = new THREE.Vector3(0, 1, 0), zFwd = new THREE.Vector3(0, 0, 1);
    const axes: any[] = [["x", new THREE.Vector3(1, 0, 0), 0xff5a6e], ["y", new THREE.Vector3(0, 1, 0), 0x5fe39a], ["z", new THREE.Vector3(0, 0, 1), 0x6e8bff]];
    const tag = (m: any, name: string) => { m.userData.gizmoAxis = name; m.renderOrder = 999; if (m.material) m.material.depthTest = false; return m; };
    const invis = () => new THREE.MeshBasicMaterial({ visible: false });
    axes.forEach(([name, dir, col]: any) => {
      const mat = new THREE.MeshBasicMaterial({ color: col, depthTest: false, transparent: true });
      if (mode === "move") {
        const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 2.0, 10), mat);
        shaft.quaternion.setFromUnitVectors(yUp, dir); shaft.position.copy(dir.clone().multiplyScalar(1.0));
        const tip = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.5, 14), mat);
        tip.quaternion.setFromUnitVectors(yUp, dir); tip.position.copy(dir.clone().multiplyScalar(2.2));
        const hit = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.32, 2.8, 8), invis());
        hit.quaternion.setFromUnitVectors(yUp, dir); hit.position.copy(dir.clone().multiplyScalar(1.25));
        this._gizmoGroup.add(tag(shaft, name), tag(tip, name), tag(hit, name));
      } else if (mode === "rotate") {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(2, 0.05, 10, 48), mat);
        ring.quaternion.setFromUnitVectors(zFwd, dir);
        const hit = new THREE.Mesh(new THREE.TorusGeometry(2, 0.26, 6, 40), invis());
        hit.quaternion.setFromUnitVectors(zFwd, dir);
        this._gizmoGroup.add(tag(ring, name), tag(hit, name));
      } else {
        const line = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 2.0, 8), mat);
        line.quaternion.setFromUnitVectors(yUp, dir); line.position.copy(dir.clone().multiplyScalar(1.0));
        const box = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.34, 0.34), mat);
        box.position.copy(dir.clone().multiplyScalar(2.05));
        const hit = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.7, 0.7), invis());
        hit.position.copy(dir.clone().multiplyScalar(2.05));
        this._gizmoGroup.add(tag(line, name), tag(box, name), tag(hit, name));
      }
    });
    const hub = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
    hub.renderOrder = 999; this._gizmoGroup.add(hub);
    this._gizmoGroup.position.set(o.pos[0], Math.max(0.8, o.pos[1] + 0.8), o.pos[2]);
  }

  // ================= RENDER VALS =================
  renderVals(): any {
    const s = this.state;
    const ws = s.workspace;
    const accentRgb = this.ACCENTS[ws];
    const accent = "rgb(" + accentRgb + ")";
    const isRob = ws === "robotics", isCre = ws === "create", isAsm = ws === "assemble";
    const job = s.job;

    const segBase = "display:flex;align-items:center;gap:7px;padding:7px 13px;border:none;border-radius:8px;font-size:12.5px;font-weight:600;font-family:Hanken Grotesk,sans-serif;cursor:pointer;transition:all .15s;";
    const seg = (active: boolean) => segBase + (active ? "background:transparent;color:" + accent + ";box-shadow:inset 0 0 0 1px rgba(" + accentRgb + ",.4);" : "background:transparent;color:var(--txt2);");
    const iconBtn = (active: boolean) => "width:30px;height:30px;display:flex;align-items:center;justify-content:center;border:none;border-radius:7px;font-size:14px;cursor:pointer;background:" + (active ? "transparent;color:" + accent : "transparent;color:var(--txt2)") + ";";
    const pill = (active: boolean) => "flex:1;padding:7px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid " + (active ? "rgba(" + accentRgb + ",.45)" : "var(--bd)") + ";background:" + (active ? "transparent;color:" + accent : "rgba(255,255,255,.02);color:var(--txt2)") + ";font-family:Hanken Grotesk,sans-serif;";
    const tab = (active: boolean) => "flex:1;padding:8px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;border:none;background:" + (active ? "transparent;color:" + accent : "transparent;color:var(--txt2)") + ";font-family:Hanken Grotesk,sans-serif;";

    // ---- workspace switch ----
    const wsDefs = [["robotics", "Robotics"], ["create", "Create"], ["assemble", "Assemble"]];
    const workspaces = wsDefs.map(([k, label]) => ({
      key: k, label, onSelect: () => this.setState({ workspace: k }),
      btnStyle: seg(ws === k),
      dotStyle: "width:7px;height:7px;border-radius:50%;background:rgb(" + this.ACCENTS[k] + ");box-shadow:0 0 6px rgb(" + this.ACCENTS[k] + ");",
    }));

    // ---- view tools ----
    const vmDef = [["solid", "i-solid", "Solid"], ["wireframe", "i-wire", "Wireframe"], ["xray", "i-xray", "X-ray"]];
    const viewTools: any[] = vmDef.map(([m, iconKey, title]) => ({ iconKey, title, style: iconBtn(s.viewMode === m), onClick: () => this.setState({ viewMode: m }) }));
    viewTools.push({ iconKey: "i-turntable", title: "Turntable", style: iconBtn(s.turntable), onClick: () => this.setState((p: any) => ({ turntable: !p.turntable })) });
    viewTools.push({ iconKey: "i-light", title: "Lighting: " + this.MOODS[s.lighting], style: iconBtn(false), onClick: () => this.setState((p: any) => ({ lighting: (p.lighting + 1) % 3 })) });

    const actionTools = [
      { iconKey: "i-frame", title: "Frame selection", style: iconBtn(false), onClick: () => { const sel = this.state.asm.objects.find((o: any) => o.id === this.state.asm.selectedId); this.frameObject(this.state.workspace === "assemble" && sel ? sel : null); } },
      { iconKey: "i-snap", title: "Snapshot", style: iconBtn(false), onClick: () => this.toast("Snapshot saved") },
    ];
    const onToggleSimFail = () => { this.setState((p: any) => ({ simFail: !p.simFail })); this.toast(this.state.simFail ? "Next job will fail" : "Failure sim off"); };
    const simFailStyle = "width:32px;height:32px;display:flex;align-items:center;justify-content:center;border-radius:8px;font-size:14px;cursor:pointer;border:1px solid " + (s.simFail ? "rgba(255,180,60,.5)" : "var(--bd)") + ";background:" + (s.simFail ? "rgba(255,180,60,.16);color:#FFC25A" : "rgba(0,0,0,.28);color:var(--txt3)") + ";";
    const onToggleLeft = () => this.setState((p: any) => ({ leftOpen: !p.leftOpen }));
    const onToggleRight = () => this.setState((p: any) => ({ rightOpen: !p.rightOpen }));
    const leftMax = s.leftOpen ? "calc(100vh - 220px)" : "0px";
    const rightMax = s.rightOpen ? "calc(100vh - 220px)" : "0px";
    const leftOpacityV = s.leftOpen ? "1" : "0";
    const rightOpacityV = s.rightOpen ? "1" : "0";
    const leftCaret = s.leftOpen ? "rotate(0deg)" : "rotate(-90deg)";
    const rightCaret = s.rightOpen ? "rotate(0deg)" : "rotate(-90deg)";

    // ---- LEFT TABS ----
    let leftTabs: any[] = [];
    if (isRob) leftTabs = [{ label: "Input", style: tab(true), onClick: () => {} }];
    else if (isCre) {
      const cd = [["generate", "Generate"], ["terrain", "Terrain"], ["library", "Library"]];
      leftTabs = cd.map(([k, l]) => ({ label: l, style: tab(s.cre.panel === k || (k === "generate" && s.cre.panel === "render")), onClick: () => this.setState((p: any) => ({ cre: { ...p.cre, panel: k } })) }));
    } else {
      const ad = [["library", "Library"], ["outliner", "Outliner"]];
      leftTabs = ad.map(([k, l]) => ({ label: l, style: tab(s.asm.leftTab === k), onClick: () => this.setState((p: any) => ({ asm: { ...p.asm, leftTab: k } })) }));
    }

    // ---- ROBOTICS left ----
    const robInputs = [
      { key: "spec", label: "Spec / Prompt", sub: "Describe the part in text", style: pill(s.rob.leftMode === "spec").replace("flex:1;", "") + "text-align:left;padding:10px 12px;", onClick: () => this.setState((p: any) => ({ rob: { ...p.rob, leftMode: "spec" } })) },
      { key: "image", label: "Image + scale", sub: "Upload a reference photo", style: pill(s.rob.leftMode === "image").replace("flex:1;", "") + "text-align:left;padding:10px 12px;", onClick: () => this.setState((p: any) => ({ rob: { ...p.rob, leftMode: "image" } })) },
    ];
    const robImageMode = isRob && s.rob.leftMode === "image";
    const onScaleAnchor = (e: any) => this.setState((p: any) => ({ rob: { ...p.rob, scaleAnchor: +e.target.value } }));
    const assemblyToggleStyle = "margin-top:14px;display:flex;align-items:center;justify-content:space-between;padding:11px 12px;border-radius:10px;border:1px solid " + (s.rob.assembly ? "rgba(" + accentRgb + ",.4)" : "var(--bd)") + ";background:" + (s.rob.assembly ? "transparent" : "rgba(255,255,255,.02)") + ";cursor:pointer;";
    const onToggleAssembly = () => this.setState((p: any) => ({ rob: { ...p.rob, assembly: !p.rob.assembly } }));
    const knobTrack = (on: boolean) => "width:36px;height:20px;border-radius:20px;background:" + (on ? accent : "rgba(255,255,255,.14)") + ";position:relative;transition:all .15s;";
    const knob = (on: boolean) => "position:absolute;top:2px;left:" + (on ? "18px" : "2px") + ";width:16px;height:16px;border-radius:50%;background:#fff;transition:all .15s;";
    const robLibrary = s.library.slice(0, 4).map((it: any) => ({ name: it.name, meta: it.faces, bg: "linear-gradient(135deg," + this.GEOCOLOR[it.geo] + "55,#0d0f16)" }));

    // ---- CREATE left ----
    const creLeftInput = isCre && s.cre.panel === "generate";
    const creTerrainMode = isCre && s.cre.panel === "terrain";
    const creInputs = [["text", "Text"], ["image", "Image"]].map(([k, l]) => ({ label: l, style: pill(s.cre.inputMode === k), onClick: () => this.setState((p: any) => ({ cre: { ...p.cre, inputMode: k } })) }));
    const creImageMode = isCre && s.cre.inputMode === "image";
    const tierDefs = [["Preview", "~30s"], ["Standard", "~1 min"], ["High", "~1.5 min"], ["Max detail", "~2–2.5 min"]];
    const creTiers = tierDefs.map(([k, t]) => ({ label: k, time: t, style: "display:flex;align-items:center;justify-content:space-between;padding:9px 12px;border-radius:9px;cursor:pointer;border:1px solid " + (s.cre.tier === k ? "rgba(" + accentRgb + ",.45)" : "var(--bd)") + ";background:" + (s.cre.tier === k ? "transparent" : "rgba(255,255,255,.02)") + ";color:var(--txt);", onClick: () => this.setState((p: any) => ({ cre: { ...p.cre, tier: k } })) }));
    // multi-view is always on (the quality lever) — no toggle; image-mode upload → base64 for /image2mesh (click-to-pick or drag onto the drop zone)
    const setFileInput = (el: any) => { this._fileInput = el; };
    const onPickImage = () => { if (this._fileInput) this._fileInput.click(); };
    const takeImage = async (f: File) => { if (!f) return; const b64 = await fileToB64(f); this.setState((p: any) => ({ cre: { ...p.cre, imageB64: b64, imageName: f.name } })); this.toast("Image ready: " + f.name); };
    const onImageChosen = (e: any) => { const f = e.target.files && e.target.files[0]; if (f) takeImage(f); };
    const onImageDrop = (e: any) => { e.preventDefault(); const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) takeImage(f); };

    // ---- library (create library tab + assemble library tab) ----
    const showLibrary = (isCre && s.cre.panel === "library") || (isAsm && s.asm.leftTab === "library");
    const q = s.librarySearch.toLowerCase();
    const libraryItems = s.library.filter((it: any) => !q || it.name.toLowerCase().includes(q)).map((it: any) => ({
      name: it.name, meta: it.faces + " · " + it.size, bg: "linear-gradient(135deg," + this.GEOCOLOR[it.geo] + "66,#0d0f16)", thumbKey: "thumb-" + it.geo, geoColor: this.GEOCOLOR[it.geo] || "#9aa0ac",
      thumb: it.thumb || null,
      busy: it.status === "busy", canAdd: isAsm,
      onAdd: () => this.addObject(it, true),
      onDragStart: (e: any) => { this._dragItem = it; try { e.dataTransfer.setData("text/plain", it.id); } catch (x) {} },
    }));

    // ---- outliner ----
    const showOutliner = isAsm && s.asm.leftTab === "outliner";
    const asmEmpty = s.asm.objects.length === 0;
    const outlinerRows = s.asm.objects.map((o: any) => ({
      name: o.name, dot: this.GEOCOLOR[o.geo] || "#888",
      draggable: true,
      onDragStart: (e: any) => { this._dragRow = o.id; try { e.dataTransfer.effectAllowed = "move"; } catch (x) {} },
      onDragOver: (e: any) => { e.preventDefault(); },
      onDrop: (e: any) => { e.preventDefault(); if (this._dragRow) this.reorderObjects(this._dragRow, o.id); this._dragRow = null; },
      rowStyle: "display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:8px;cursor:pointer;border:1px solid " + (this._isSelected(o.id) ? "rgba(" + accentRgb + ",.45)" : "transparent") + ";background:" + (this._isSelected(o.id) ? "rgba(" + accentRgb + ",.08)" : "transparent") + ";",
      eyeKey: o.hidden ? "i-eye-off" : "i-eye",
      onSelect: (e: any) => { if (e && e.shiftKey) this.toggleSelect(o.id); else this.selectObj(o.id); }, onHide: (e: any) => { e.stopPropagation(); this.toggleHide(o.id); }, onDelete: (e: any) => { e.stopPropagation(); this.setState((p: any) => ({ asm: { ...p.asm, objects: p.asm.objects.filter((x: any) => x.id !== o.id), selectedId: p.asm.selectedId === o.id ? null : p.asm.selectedId, selectedIds: (p.asm.selectedIds || []).filter((id: string) => id !== o.id) } })); },
    }));

    // ---- canvas hint ----
    let showCanvasHint = false, canvasHintTitle = "", canvasHintBody = "";
    if (isAsm && asmEmpty && !job) { showCanvasHint = true; canvasHintTitle = "Empty scene"; canvasHintBody = "Drag an asset from the Library onto the ground, or use ＋ Generate below to make a new one."; }

    // ================= JOB view =================
    const jobRunning = !!(job && job.status === "running");
    const jobError = !!(job && job.status === "error");
    const jobStages = job ? job.stages.map((st: any, i: number) => ({
      label: st.label,
      mark: i < job.idx ? "✓" : (i === job.idx ? "" : ""),
      color: i <= job.idx ? "var(--txt)" : "var(--txt3)",
      dot: "width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0;" + (i < job.idx ? "background:rgba(80,220,140,.2);color:#5fe39a;" : i === job.idx ? "background:rgba(" + accentRgb + ",.2);color:" + accent + ";animation:ml-pulse 1.2s infinite;border:1px solid " + accent + ";" : "background:rgba(255,255,255,.06);color:var(--txt3);"),
    })) : [];
    const jobConcept = !!(job && job.concept && job.conceptShown && job.status === "running");
    const jobMvViews = (job && job.mvViews && job.mvViews.length) ? job.mvViews : null;   // 6 MV-Adapter views (collage)
    const jobConceptBg = (job && job.conceptImg)
      ? ("center/cover no-repeat url(data:image/png;base64," + job.conceptImg + ")")   // the real FLUX concept
      : ("linear-gradient(135deg,rgba(" + accentRgb + ",.5),#1a1020 60%,#0d0a12)");      // placeholder while it's still rendering
    const jobConceptReady = !!(job && job.conceptImg);
    const jobConceptLabel = jobMvViews ? ("Multi-view · " + jobMvViews.length + " angles") : (jobConceptReady ? "Concept image · FLUX" : "Rendering concept…");

    // ================= ROBOTICS inspector =================
    const showRobInspector = isRob && !job;
    const robSpecMode = showRobInspector && !s.rob.result;
    const robResult = showRobInspector && !!s.rob.result;
    const sp = s.rob.spec;
    const robShapes = ["Box", "Cylinder", "Loft"].map((sh) => ({ label: sh, style: pill(sp.shape === sh), onClick: () => this.setState((p: any) => ({ rob: { ...p.rob, spec: { ...p.rob.spec, shape: sh } } })) }));
    const setSpec = (k: string, v: any) => this.setState((p: any) => ({ rob: { ...p.rob, spec: { ...p.rob.spec, [k]: v } } }));
    let robDims: any[];
    if (sp.shape === "Cylinder") robDims = [{ label: "Diameter ⌀", value: sp.dia, min: 5, max: 200, onInput: (e: any) => setSpec("dia", +e.target.value) }, { label: "Height", value: sp.H, min: 2, max: 200, onInput: (e: any) => setSpec("H", +e.target.value) }];
    else robDims = [{ label: "Length", value: sp.L, min: 10, max: 200, onInput: (e: any) => setSpec("L", +e.target.value) }, { label: "Width", value: sp.W, min: 10, max: 200, onInput: (e: any) => setSpec("W", +e.target.value) }, { label: "Height", value: sp.H, min: 2, max: 120, onInput: (e: any) => setSpec("H", +e.target.value) }];
    const featTitle: any = { "through-hole": "Through-hole", "hole-pattern": "Hole pattern · bolt-circle", fillet: "Fillet", chamfer: "Chamfer", counterbore: "Counterbore", pocket: "Pocket", shell: "Shell" };
    const updFeat = (id: any, k: string, v: any) => this.setState((p: any) => ({ rob: { ...p.rob, spec: { ...p.rob.spec, features: p.rob.spec.features.map((f: any) => f.id === id ? { ...f, [k]: v } : f) } } }));
    const robFeatures = sp.features.map((f: any) => {
      let params: any[] = [];
      if (f.kind === "through-hole") params = [{ label: "⌀", value: f.dia, onInput: (e: any) => updFeat(f.id, "dia", +e.target.value) }, { label: "x", value: f.x, onInput: (e: any) => updFeat(f.id, "x", +e.target.value) }];
      else if (f.kind === "hole-pattern") params = [{ label: "n", value: f.count, onInput: (e: any) => updFeat(f.id, "count", +e.target.value) }, { label: "PCD", value: f.pcd, onInput: (e: any) => updFeat(f.id, "pcd", +e.target.value) }, { label: "⌀", value: f.holeDia, onInput: (e: any) => updFeat(f.id, "holeDia", +e.target.value) }];
      else if (f.kind === "fillet") params = [{ label: "r", value: f.r, onInput: (e: any) => updFeat(f.id, "r", +e.target.value) }];
      else if (f.kind === "chamfer") params = [{ label: "d", value: f.d, onInput: (e: any) => updFeat(f.id, "d", +e.target.value) }];
      else if (f.kind === "pocket") params = [{ label: "D", value: f.depth, onInput: (e: any) => updFeat(f.id, "depth", +e.target.value) }];
      return { title: featTitle[f.kind] || f.kind, params, onRemove: () => this.setState((p: any) => ({ rob: { ...p.rob, spec: { ...p.rob.spec, features: p.rob.spec.features.filter((x: any) => x.id !== f.id) } } })) };
    });
    const onAddFeature = () => this.setState((p: any) => ({ featMenuOpen: !p.featMenuOpen }));
    const addFeatureType = (k: string) => { const nf = { id: "f" + (this._uid++), kind: k, dia: 6, x: 10, y: 0, d: 2, depth: 5, r: 2, count: 4, pcd: 40, holeDia: 5, wall: 2 }; this.setState((p: any) => ({ featMenuOpen: false, rob: { ...p.rob, spec: { ...p.rob.spec, features: [...p.rob.spec.features, nf] } } })); };
    const featMenuOpen = s.featMenuOpen && isRob && !s.rob.result;
    const featureTypes = [["through-hole", "Through-hole"], ["hole-pattern", "Hole pattern"], ["counterbore", "Counterbore"], ["countersink", "Countersink"], ["fillet", "Fillet"], ["chamfer", "Chamfer"], ["pocket", "Pocket"], ["shell", "Shell"]].map(([k, l]) => ({ label: l, onClick: () => addFeatureType(k) }));
    const minFace = Math.min(sp.L, sp.W);
    const bigHole = sp.features.find((f: any) => f.kind === "through-hole" && f.dia * 1.2 > minFace);
    const robWarning = bigHole ? ("Hole ⌀" + bigHole.dia + " is close to the " + minFace + " mm face — interpreter may flag a thin wall.") : null;
    const onSpecName = (e: any) => setSpec("name", e.target.value);
    const onSpecTol = (e: any) => setSpec("tol", +e.target.value);
    const onSpecMinWall = (e: any) => setSpec("minWall", +e.target.value);
    const robFab = ["Render", "Fabricate"].map((fb) => ({ label: fb, style: pill(sp.fabrication === fb).replace("flex:1;", "flex:1;") + "padding:6px;font-size:11px;", onClick: () => setSpec("fabrication", fb) }));
    const robFabricate = robResult ? false : (isRob && sp.fabrication === "Fabricate");

    const rr = s.rob.result;
    let verifyRows: any[] = [], verifyBadges: any[] = [];
    if (rr) {
      verifyRows = rr.rows.map((r: any, ri: number) => {
        const frac = Math.max(-1, Math.min(1, r.delta / r.tol));
        return {
          name: r.name, exp: r.exp, meas: r.meas, mark: "✓",
          gaugeDot: "position:absolute;top:50%;left:" + (50 + frac * 42) + "%;width:7px;height:7px;border-radius:50%;background:#5fe39a;transform:translate(-50%,-50%);box-shadow:0 0 5px #5fe39a;",
          badge: "text-align:center;color:#5fe39a;font-size:13px;",
          rowStyle: "display:grid;grid-template-columns:1fr 52px 52px 60px 28px;gap:6px;padding:9px 10px;border-top:1px solid var(--bd);align-items:center;font-family:JetBrains Mono,monospace;font-size:11px;transition:background .15s;background:" + (s.hoverRow === ri ? "rgba(255,255,255,.06)" : "transparent") + ";",
          onEnter: () => this.setState({ hoverRow: ri }),
          onLeave: () => this.setState((p: any) => (p.hoverRow === ri ? { hoverRow: null } : {})),
        };
      });
      verifyBadges = ["watertight", "manifold", "selectors " + rr.selectors + "/" + rr.selectors];
    }

    // ================= CREATE inspector =================
    const showCreInspector = isCre && !job && (s.cre.panel === "generate");
    const creIdle = showCreInspector && !s.cre.result;
    const creResult = showCreInspector && !!s.cre.result;
    const cr = s.cre.result;
    const creReport = cr ? [
      { label: "Faces", value: cr.faces }, { label: "Verts", value: cr.verts },
      { label: "Watertight", value: cr.watertight ? "Yes" : "No" }, { label: "Time", value: cr.time },
    ] : [];
    const creMaps = ["Base color", "Metal-Rough", "Normal"];
    const creLowpolyLabel = (s.cre.lowpolyTarget / 1000) + "k";
    const onLowpoly = (e: any) => this.setState((p: any) => ({ cre: { ...p.cre, lowpolyTarget: +e.target.value } }));

    const showTerrain = isCre && !job && s.cre.panel === "terrain";
    const biomeDefs = [["plain", "Plain", "#6f7a55"], ["desert", "Desert", "#c9a96a"], ["forest", "Forest", "#4a6b3a"], ["snowy", "Snowy Mtn", "#cdd8ea"], ["arctic", "Arctic", "#b6cdd6"], ["canyon", "Canyon", "#b5704a"], ["coast", "Coast", "#5b8fa8"], ["river", "River", "#4a7d6b"]];
    const biomes = biomeDefs.map(([k, l, c]) => ({ label: l, swatch: "linear-gradient(135deg," + c + ",#0d0f16)", style: "padding:9px;border-radius:10px;cursor:pointer;text-align:center;border:1px solid var(--bd);background:rgba(255,255,255,.02);color:var(--txt);", onClick: () => { this.setState((p: any) => ({ cre: { ...p.cre, panel: "generate" } })); this.generateTerrain(k); } }));

    const showRenderGallery = isCre && !job && s.cre.panel === "render";
    const renderTarget = s.cre.renderTarget;
    const renderTabs = [["still", "Photoreal still"], ["motion", "Motion clip"]].map(([k, l]) => ({ label: l, style: tab(s.cre.renderTab === k), onClick: () => this.setState((p: any) => ({ cre: { ...p.cre, renderTab: k } })) }));
    const renderStill = showRenderGallery && s.cre.renderTab === "still";
    const renderMotion = showRenderGallery && s.cre.renderTab === "motion";
    const renderStillBg = s.cre.renderBeauty
      ? ("center/cover no-repeat url(data:image/png;base64," + s.cre.renderBeauty + ")")
      : ("radial-gradient(80% 80% at 60% 35%,rgba(" + accentRgb + ",.45),#160c1c 55%,#08060b)");
    const motionVariants = [0, 1].map((i) => ({ label: "Variant " + (i + 1), style: pill(s.cre.motionVariant === i).replace("flex:1;", "flex:1;") + "padding:7px;font-size:11.5px;", onClick: () => this.setState((p: any) => ({ cre: { ...p.cre, motionVariant: i } })) }));

    // ================= ASSEMBLE inspector =================
    const showAsmInspector = isAsm && !job;
    const asmSel = s.asm.objects.find((o: any) => o.id === s.asm.selectedId);
    const asmSelected = showAsmInspector && !!asmSel;
    const asmSceneSettings = showAsmInspector && !asmSel;
    const axCols = ["#ff5a6e", "#5fe39a", "#6e8bff"];
    let asmTransforms: any[] = [];
    if (asmSel) {
      const mk = (label: string, key: string, step: number) => ({ label, axes: ["X", "Y", "Z"].map((axis, i) => ({ axis, color: axCols[i], step, value: asmSel[key][i], onInput: (e: any) => { const arr = [...asmSel[key]]; arr[i] = +e.target.value; this.updateObj(asmSel.id, { [key]: arr }); } })) });
      asmTransforms = [mk("Position", "pos", 0.1), mk("Rotation", "rot", 1), mk("Scale", "scale", 0.05)];
    }
    const onRenameSel = (e: any) => this.updateObj(asmSel.id, { name: e.target.value });
    const onResetTransform = () => this.updateObj(asmSel.id, { pos: [0, 0, 0], rot: [0, 0, 0], scale: [1, 1, 1] });
    const groundStyle = (active: boolean) => "padding:8px;border-radius:9px;cursor:pointer;text-align:center;border:1px solid " + (active ? "rgba(" + accentRgb + ",.45)" : "var(--bd)") + ";background:" + (active ? "transparent" : "rgba(255,255,255,.02)") + ";color:var(--txt);";
    const groundDefs = [["forest", "Forest", "#4a6b3a"], ["desert", "Desert", "#c9a96a"], ["snowy", "Snowy", "#cdd8ea"], ["none", "None", "#1a1d28"]];
    // biome bases (colored ground) — selecting one clears any terrain-tile ground
    const biomeGrounds = groundDefs.map(([k, l, c]) => ({ label: l, swatch: "linear-gradient(135deg," + c + ",#0d0f16)", style: groundStyle(s.asm.ground === k && !s.asm.groundGlb), onClick: () => this.setState((p: any) => ({ asm: { ...p.asm, ground: k, groundGlb: null, groundGlbId: null } })) }));
    // generated terrain tiles — render the real GLB as the ground
    const tileGrounds = s.library.filter((it: any) => it.geo === "terrain").map((it: any) => ({
      label: it.name.replace(/ Tile$/, ""),
      swatch: it.thumb ? ("center/cover no-repeat url(data:image/png;base64," + it.thumb + ")") : "linear-gradient(135deg,#6f7a55,#0d0f16)",
      style: groundStyle(s.asm.groundGlbId === it.glbId),
      onClick: () => this.setState((p: any) => ({ asm: { ...p.asm, ground: "tile", groundGlbId: it.glbId, groundGlb: it.glb } })),
    }));
    // pre-baked terrain presets (instant, static) — shown first, with photo thumbnails
    const presetGrounds = TERRAIN_PRESETS.map(([b, l]) => ({ label: l, swatch: "center/cover no-repeat url(/presets/" + b + ".png)", style: groundStyle(s.asm.groundGlbId === "preset-" + b), onClick: () => this._useTerrainPreset(b, l, false) }));
    const asmGrounds = [...presetGrounds, ...biomeGrounds, ...tileGrounds];
    const terrainPresets = TERRAIN_PRESETS.map(([b, l]) => ({ label: l, thumb: "/presets/" + b + ".png", onClick: () => this._useTerrainPreset(b, l, true) }));
    const lightingMoods = this.MOODS.map((m, i) => ({ label: m, style: pill(s.lighting === i).replace("flex:1;", "flex:1;") + "padding:7px;font-size:11.5px;", onClick: () => this.setState({ lighting: i }) }));

    // ---- gizmo bar ----
    const showGizmoBar = isAsm && !job;
    const gizmoDefs = [["move", "i-move", "Move", "W"], ["rotate", "i-rotate", "Rotate", "E"], ["scale", "i-scale", "Scale", "R"]];
    const gizmoModes = gizmoDefs.map(([k, iconKey, title, key]) => ({ iconKey, title, key, style: "display:flex;flex-direction:column;align-items:center;gap:1px;width:38px;height:42px;justify-content:center;border:none;border-radius:9px;cursor:pointer;background:" + (s.asm.gizmoMode === k ? "transparent;color:" + accent : "transparent;color:var(--txt2)") + ";", onClick: () => this._setGizmo(k) }));
    const onToggleSnap = () => this.setState((p: any) => ({ asm: { ...p.asm, snap: !p.asm.snap } }));
    const snapStyle = "display:flex;flex-direction:column;align-items:center;gap:1px;width:38px;height:42px;justify-content:center;border:none;border-radius:9px;cursor:pointer;background:" + (s.asm.snap ? "transparent;color:" + accent : "transparent;color:var(--txt2)") + ";";

    // ================= INSPECTOR title =================
    let inspectorTitle = "Inspector", inspectorMeta = "";
    if (job) { inspectorTitle = "Job"; inspectorMeta = job.key; }
    else if (isRob) { inspectorTitle = rr ? "Verification" : "Spec editor"; inspectorMeta = sp.shape; }
    else if (isCre) { inspectorTitle = s.cre.panel === "terrain" ? "Terrain" : s.cre.panel === "render" ? "Finish" : (cr ? "Asset" : "Generate"); }
    else { const nsel = this._selIds().length; inspectorTitle = asmSel ? (nsel > 1 ? nsel + " objects" : "Object") : "Scene"; inspectorMeta = nsel > 1 ? nsel + " selected" : s.asm.objects.length + " objs"; }

    // ================= COMMAND BAR =================
    let commandIcon = "✦", commandPlaceholder = "", primaryActionLabel = "Generate", primaryAction = () => {};
    let showFinishMenu = false, finishActions: any[] = [];
    if (isRob) { commandPlaceholder = s.rob.assembly ? "Plan a multi-part assembly, or edit it…" : 'Describe a part, e.g. "80×60 bracket, 4× M5 bolt circle"'; primaryActionLabel = rr ? "Regenerate" : "Generate"; primaryAction = () => this.generateRobotics(); }
    else if (isCre) {
      if (s.cre.panel === "terrain") { commandPlaceholder = "Pick a biome on the right →"; primaryActionLabel = "Terrain"; primaryAction = () => {}; }
      else if (s.cre.panel === "render") { commandPlaceholder = "Finish " + renderTarget; primaryActionLabel = s.cre.renderTab === "motion" ? "Animate" : "Render"; primaryAction = () => this.doRender(s.cre.renderTab); }
      else { commandPlaceholder = s.cre.inputMode === "image" ? "Drop image on the left, add a prompt…" : 'Describe a 3D asset, e.g. "mossy granite boulder"'; primaryActionLabel = "Generate"; primaryAction = () => this.generateCreate(); }
      commandIcon = "✦";
    } else {
      commandPlaceholder = "Generate a new asset without leaving the scene…";
      primaryActionLabel = "＋ Generate";
      primaryAction = () => {
        const name = s.command.trim() || "New asset";
        this._startAsyncJob("inline", "Generating in scene", "Standard tier · the scene stays interactive.",
          [{ label: "Queued" }, { label: "Concept image (FLUX)" }, { label: "Generating mesh" }], true,
          (onP, sc) => api.text2mesh(name, "Standard", false, onP, sc),
          (res) => { const glbId = "g" + (this._uid++); this.addObject({ name, geo: "rock", faces: this._fmtFaces(res.report ? res.report.faces : 0), glb: res.glb_b64, glbId }, true); this.setState({ command: "" }); },
          () => this.setState({ workspace: "assemble" }, () => primaryAction()));
      };
      showFinishMenu = !job && s.asm.objects.length > 0;
      const faDef = [["GLB", "Export GLB (whole scene · instant)"], ["USDZ", "Export USDZ"], ["Render", "Photoreal render of scene"], ["Animate", "LTX motion"]];
      finishActions = faDef.map(([l, title]) => ({ label: l, title, style: "padding:8px 12px;border-radius:9px;border:1px solid var(--bd);background:rgba(255,255,255,.03);color:var(--txt);font-size:12px;font-weight:600;cursor:pointer;", onClick: () => this._sceneAction(l) }));
    }
    const primaryActionStyle = "padding:10px 20px;border:none;border-radius:11px;background:linear-gradient(95deg, rgb(" + accentRgb + "), color-mix(in oklab, rgb(" + accentRgb + ") 58%, #ffffff));color:#0c0a12;font-weight:700;font-size:13px;font-family:Hanken Grotesk,sans-serif;cursor:pointer;white-space:nowrap;box-shadow:0 4px 20px rgba(" + accentRgb + ",.5);flex-shrink:0;";

    // ---- time hint chip (honest durations) ----
    let timeHint = "", showTimeHint = false;
    if (isRob) { timeHint = "secs–min"; showTimeHint = !rr; }
    else if (isCre) {
      if (s.cre.panel === "terrain") { timeHint = "~5–6 min"; showTimeHint = false; }
      else if (s.cre.panel === "render") { timeHint = s.cre.renderTab === "motion" ? "~40s" : "~1–2 min"; showTimeHint = true; }
      else { timeHint = (({ Preview: "~1 min", Standard: "~1.5 min", High: "~2 min", "Max detail": "~2.5–3 min" } as any)[s.cre.tier] || "~1.5 min"); showTimeHint = !cr; }
    } else { timeHint = "~1 min"; showTimeHint = true; }

    // ---- floating mesh-stats card (Meshy-style) ----
    let showStats = false, statsRows: any[] = [], statsCheckLabel = "";
    if (!job && isCre && cr) {
      showStats = true;
      statsRows = [{ label: "Topology", value: "Triangle" }, { label: "Faces", value: cr.faces }, { label: "Vertices", value: cr.verts }];
      statsCheckLabel = "Watertight";
    } else if (!job && isRob && rr) {
      showStats = true;
      statsRows = [{ label: "Topology", value: "BREP" }, { label: "Tolerance", value: "±" + sp.tol + " mm" }, { label: "Selectors", value: rr.selectors + "/" + rr.selectors }];
      statsCheckLabel = "Verified";
    } else if (!job && isAsm && asmSel) {
      showStats = true;
      statsRows = [{ label: "Object", value: asmSel.name.length > 12 ? asmSel.name.slice(0, 12) + "…" : asmSel.name }, { label: "Faces", value: asmSel.faces || "—" }, { label: "Objects", value: String(s.asm.objects.length) }];
      statsCheckLabel = "Ground-snapped";
    }

    const jobPillShow = !!job;
    const jobPillLabel = job ? job.title : "";
    const jobPillElapsed = job ? job.elapsed.toFixed(0) + "s" : "";
    const jobPillError = !!(job && job.status === "error");
    const onOpenJob = () => this.setState({ rightOpen: true });
    const shortcutsOpen = s.shortcutsOpen;
    const onToggleShortcuts = () => this.setState((p: any) => ({ shortcutsOpen: !p.shortcutsOpen }));
    const onCloseShortcuts = () => this.setState({ shortcutsOpen: false });
    const shortcutList = [["W / E / R", "Move · Rotate · Scale"], ["Middle-drag", "Orbit camera"], ["⇧ Middle / Right-drag", "Pan camera"], ["Scroll", "Zoom"], ["F", "Frame selection"], ["Shift + drag", "Snap (grid / 15°)"], ["Alt + drag", "Duplicate & move"], ["Double-click", "Focus object"], ["Ctrl/⌘ + D", "Duplicate"], ["Del", "Delete"], ["Ctrl/⌘ + Z", "Undo"], ["Ctrl/⌘ + Shift + Z", "Redo"], ["?", "Toggle this panel"]].map(([k, v]) => ({ k, v }));
    const facesNum = cr ? (parseFloat(cr.faces) * (String(cr.faces).includes("k") ? 1000 : 1)) : 1;
    const lowpolyPct = cr ? (Math.max(4, Math.min(100, Math.round(s.cre.lowpolyTarget / facesNum * 100))) + "%") : "0%";
    const lowpolyAfter = (s.cre.lowpolyTarget / 1000) + "k";
    return {
      accent, accentRgb, workspaces, viewTools, actionTools, leftTabs,
      onToggleSimFail, simFailStyle, onToggleLeft, onToggleRight, leftMax, rightMax, leftOpacityV, rightOpacityV, leftCaret, rightCaret,
      showStats, statsRows, statsCheckLabel,
      isRob, isCre, isAsm,
      robInputs, robImageMode, onScaleAnchor, rob: s.rob, assemblyToggleStyle, onToggleAssembly,
      assemblyKnobTrack: knobTrack(s.rob.assembly), assemblyKnob: knob(s.rob.assembly), robLibrary,
      creLeftInput, creTerrainMode, creInputs, creImageMode, creTiers,
      showLibrary, libraryItems, libraryEmpty: showLibrary && libraryItems.length === 0, librarySearch: s.librarySearch, onLibrarySearch: (e: any) => this.setState({ librarySearch: e.target.value }),
      showOutliner, asmEmpty, outlinerRows,
      showCanvasHint, canvasHintTitle, canvasHintBody,
      onCanvasDragOver: (e: any) => { if (isAsm) e.preventDefault(); },
      onCanvasDrop: (e: any) => this._dropAsset(e),
      job, jobRunning, jobError, jobTitle: job ? job.title : "", jobHint: job ? job.hint : "",
      jobElapsed: job ? job.elapsed.toFixed(1) : "0", jobStageCount: job ? ("stage " + Math.min(job.idx + 1, job.stages.length) + "/" + job.stages.length) : "",
      jobStages, jobConcept, jobConceptBg, jobConceptReady, jobMvViews, jobConceptLabel, jobErrorMsg: (job && job.errorMsg) || "The generator returned an error. The interpreter or mesher failed on this attempt.", jobErrorStage: job ? (job.errorStage || "") : "",
      onCancelJob: () => this.cancelJob(), onRetryJob: () => this.retryJob(),
      showRobInspector, robSpecMode, robResult, robShapes, robDims, robFeatures, onAddFeature, robWarning,
      onSpecName, onSpecTol, onSpecMinWall, robFab, robFabricate,
      verifyRows, verifyBadges, onExportStep: () => this.toast("STEP exported"), onExportStl: () => this.toast("STL exported"),
      onRobReset: () => this.setState((p: any) => ({ rob: { ...p.rob, result: null } })),
      showCreInspector, creIdle, creResult, cre: s.cre, creReport, creMaps, creLowpolyLabel, onLowpoly,
      onRunLowpoly: () => this.runLowpoly(),
      onAddToLibrary: () => { const r = this.state.cre.result; if (!r) return; this.setState((p: any) => ({ library: [{ id: "a" + (this._uid++), name: r.name, geo: r.geo, glb: r.glb, glbId: r.glbId, thumb: r.thumb || null, faces: r.faces, size: r.size || "—", status: "ready" }, ...p.library] })); this.toast("Added to Library"); },
      onExportGlb: () => { const r = s.cre.result; if (r && r.glb) { downloadB64(r.glb, (r.name || "asset") + ".glb", "model/gltf-binary"); this.toast("GLB downloaded"); } else this.toast("Nothing to export"); },
      onExportUsdz: async () => { const r = s.cre.result; if (!(r && r.glb)) { this.toast("Nothing to export"); return; } this.toast("Building USDZ…"); try { const u = await glbToUsdz(r.glb); downloadBytes(u, (r.name || "asset") + ".usdz", "model/vnd.usdz+zip"); this.toast("USDZ downloaded"); } catch (e) { this.toast("USDZ failed"); } },
      onOpenRender: () => this.setState((p: any) => ({ cre: { ...p.cre, panel: "render" } })),
      showTerrain, biomes, terrainPresets, showRenderGallery, renderTarget, renderTabs, renderStill, renderMotion, renderStillBg,
      renderBeauty: s.cre.renderBeauty, motionMp4: s.cre.motionMp4,
      creImageB64: s.cre.imageB64, creImageName: s.cre.imageName, onPickImage, onImageChosen, onImageDrop, setFileInput,
      onDownloadStill: () => { if (s.cre.renderBeauty) { downloadB64(s.cre.renderBeauty, (renderTarget || "beauty") + ".png", "image/png"); this.toast("PNG downloaded"); } else this.toast("Render a still first"); },
      onDownloadMotion: () => { if (s.cre.motionMp4) { downloadB64(s.cre.motionMp4, (renderTarget || "motion") + ".mp4", "video/mp4"); this.toast("MP4 downloaded"); } else this.toast("Animate first"); },
      motionVariants, motionPlayKey: s.cre.motionPlaying ? "i-pause" : "i-play", motionProgress: s.cre.motionPlaying ? "64%" : "0%",
      onPlayMotion: () => this.setState((p: any) => ({ cre: { ...p.cre, motionPlaying: !p.cre.motionPlaying } })),
      showAsmInspector, asmSelected, asmSceneSettings, asmSel: asmSel || {}, asmTransforms, onRenameSel, onResetTransform,
      onDupSel: () => this.dupSel(), onDeleteSel: () => this.deleteSel(),
      onLowpolySel: () => { const o = asmSel; if (!o || !o.glb) { this.toast("This object has no mesh to decimate"); return; } this._startAsyncJob("asmlowpoly", "Low-Poly object", "Decimating the selected object to ~8k faces.", [{ label: "Queued" }, { label: "Decimating mesh" }], false, (onP, sc) => api.lowpoly(o.glb, 8000, onP, sc), (res) => { const glbId = "g" + (this._uid++); this.updateObj(o.id, { glb: res.glb_b64, glbId, faces: this._fmtFaces(res.report ? res.report.faces : 8000) }); this.toast("Object decimated"); }, () => {}); },
      onExportSel: async () => { const o = asmSel; if (o && o.glb) { downloadB64(o.glb, (o.name || "object") + ".glb", "model/gltf-binary"); this.toast("Object exported"); return; } const node = this._objNode(o && o.id); if (node) { try { const b = await exportGlb(node); downloadBytes(b, (o.name || "object") + ".glb", "model/gltf-binary"); this.toast("Object exported"); } catch (e) { this.toast("Export failed"); } } else this.toast("Nothing to export"); },
      asmGrounds, lightingMoods, showGizmoBar, gizmoModes, onToggleSnap, snapStyle, snapActive: s.asm.snap,
      inspectorTitle, inspectorMeta,
      commandIcon, commandPlaceholder, commandValue: s.command, onCommandInput: (e: any) => this.setState({ command: e.target.value }),
      onCommandKey: (e: any) => { if (e.key === "Enter") primaryAction(); },
      onPrimaryAction: primaryAction, primaryActionLabel, primaryActionStyle, showFinishMenu, finishActions,
      timeHint, showTimeHint,
      featMenuOpen, featureTypes,
      jobPillShow, jobPillLabel, jobPillElapsed, jobPillError, onOpenJob,
      shortcutsOpen, onToggleShortcuts, onCloseShortcuts, shortcutList,
      dragLabel: s.dragLabel, lowpolyPct, lowpolyAfter,
      toast: s.toast,
    };
  }

  render() {
    const v = this.renderVals();
    return (
      <div id="ml-root" style={css(`--accent: ${v.accent}; --accent-rgb: ${v.accentRgb}; --panel: rgba(17,19,26,.72); --panel-solid: #12141B; --bd: rgba(255,255,255,.09); --txt: #EAECEF; --txt2: rgba(234,236,239,.56); --txt3: rgba(234,236,239,.34); position: fixed; inset: 0; overflow: hidden; font-family: Hanken Grotesk, system-ui, sans-serif; color: var(--txt); background: radial-gradient(120% 90% at 50% 0%, #0E1018 0%, #06070A 70%); -webkit-font-smoothing: antialiased;`)}>
        <IconDefs />
        <div id="ml-viewport" onDragOver={v.onCanvasDragOver} onDrop={v.onCanvasDrop} style={css("position: absolute; inset: 0; z-index: 0;")} />
        <div style={css("position: absolute; inset: 0; z-index: 1; pointer-events: none; background: radial-gradient(130% 120% at 50% 38%, transparent 52%, rgba(0,0,0,.55) 100%);")} />

        {/* empty / hint overlay */}
        {v.showCanvasHint && (
          <div style={css("position: absolute; inset: 0; z-index: 2; display: flex; align-items: center; justify-content: center; pointer-events: none;")}>
            <div style={css("text-align: center; max-width: 360px; animation: ml-rise .4s ease;")}>
              <div style={css("width: 54px; height: 54px; margin: 0 auto 18px; border-radius: 14px; border: 1px dashed rgba(var(--accent-rgb),.5); display: flex; align-items: center; justify-content: center; color: var(--accent); font-size: 22px;")}>＋</div>
              <div style={css("font-family: Sora, sans-serif; font-size: 17px; font-weight: 600; letter-spacing: -.01em;")}>{v.canvasHintTitle}</div>
              <div style={css("margin-top: 7px; font-size: 13px; line-height: 1.5; color: var(--txt2);")}>{v.canvasHintBody}</div>
            </div>
          </div>
        )}

        {/* ===== TOP BAR ===== */}
        <div style={css("position: absolute; top: 14px; left: 16px; right: 16px; z-index: 30; display: flex; align-items: center; gap: 14px; height: 50px; padding: 0 8px 0 16px; background: var(--panel); backdrop-filter: blur(20px) saturate(1.3); -webkit-backdrop-filter: blur(20px) saturate(1.3); border: 1px solid var(--bd); border-radius: 13px; box-shadow: 0 12px 40px rgba(0,0,0,.4);")}>
          <div style={css("display: flex; align-items: center; gap: 9px;")}>
            <div style={css("position: relative; width: 24px; height: 24px; border-radius: 7px; background: linear-gradient(140deg, rgb(var(--accent-rgb)), rgba(var(--accent-rgb),.5)); box-shadow: 0 0 13px rgba(var(--accent-rgb),.5); display: flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
              <svg width="17" height="17" viewBox="0 0 24 24" style={{ display: "block" }}><path d="M12 4 19 8 12 12 5 8Z" fill="#fff" fillOpacity=".95" /><path d="M5 8 12 12 12 20 5 16Z" fill="#0c0a12" fillOpacity=".3" /><path d="M19 8 12 12 12 20 19 16Z" fill="#0c0a12" fillOpacity=".16" /><g fill="none" stroke="#0c0a12" strokeOpacity=".5" strokeWidth="1.1" strokeLinejoin="round" strokeLinecap="round"><path d="M12 4 19 8 19 16 12 20 5 16 5 8Z" /><path d="M5 8 12 12 19 8M12 12 12 20" /></g></svg>
            </div>
            <span style={css("font-family: Sora, sans-serif; font-weight: 600; font-size: 15px; letter-spacing: -.01em;")}>MotionLab</span>
          </div>
          <div style={css("width: 1px; height: 22px; background: var(--bd);")} />
          <div style={css("display: flex; gap: 3px; padding: 3px; background: rgba(0,0,0,.28); border-radius: 10px;")}>
            {v.workspaces.map((ws: any) => (
              <button key={ws.key} onClick={ws.onSelect} style={css(ws.btnStyle)}>{ws.label}</button>
            ))}
          </div>
          <div style={css("flex: 1;")} />
          <div style={css("display: flex; align-items: center; gap: 7px;")}>
            <span style={css("display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 20px; background: rgba(80,220,140,.1); border: 1px solid rgba(80,220,140,.28); font-size: 11px; color: #9FF0C5;")}><span style={css("width: 6px; height: 6px; border-radius: 50%; background: #5FE39A; box-shadow: 0 0 6px #5FE39A;")} />Self-hosted · online</span>
            {v.jobPillShow && (
              <button onClick={v.onOpenJob} title="Open job" style={css("display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px 5px 9px; border-radius: 20px; border: 1px solid var(--bd); background: rgba(255,255,255,.04); color: var(--txt); font-size: 11.5px; cursor: pointer; max-width: 230px;")}><span style={css("width: 13px; height: 13px; border: 2px solid rgba(255,255,255,.22); border-top-color: var(--accent); border-radius: 50%; animation: ml-spin .8s linear infinite; flex-shrink: 0;")} /><span style={css("white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500;")}>{v.jobPillLabel}</span><span style={css("color: var(--txt3); font-family: 'JetBrains Mono', monospace; flex-shrink: 0;")}>{v.jobPillElapsed}</span></button>
            )}
            <button onClick={v.onToggleSimFail} title="Simulate next job failure" style={css(v.simFailStyle)}><Icon k="i-fault" size={15} /></button>
            <button onClick={v.onToggleShortcuts} title="Keyboard shortcuts (?)" style={css("width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; border: 1px solid var(--bd); background: rgba(0,0,0,.28); color: var(--txt2); font-family: 'JetBrains Mono', monospace;")}>?</button>
          </div>
        </div>

        {/* ===== LEFT PANEL ===== */}
        <div id="ml-left" style={css("position: absolute; left: 16px; top: 78px; max-height: calc(100vh - 168px); width: 280px; z-index: 25; display: flex; flex-direction: column; background: var(--panel); backdrop-filter: blur(20px) saturate(1.3); -webkit-backdrop-filter: blur(20px) saturate(1.3); border: 1px solid var(--bd); border-radius: 13px; box-shadow: 0 12px 40px rgba(0,0,0,.4); overflow: hidden;")}>
          <div style={css("display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--bd);")}>
            <div style={css("display: flex; gap: 3px; flex: 1; min-width: 0;")}>
              {v.leftTabs.map((lt: any, i: number) => (
                <button key={i} onClick={lt.onClick} style={css(lt.style)}>{lt.label}</button>
              ))}
            </div>
            <button onClick={v.onToggleLeft} title="Collapse panel" style={css("width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; border: none; border-radius: 7px; background: rgba(0,0,0,.25); color: var(--txt2); cursor: pointer; flex-shrink: 0;")}><svg width="14" height="14" viewBox="0 0 24 24" style={css("display:block; transition: transform .2s; transform: " + v.leftCaret + ";")}><use href="#i-chevron" /></svg></button>
          </div>

          <div style={css("flex: 1; min-height: 0; overflow-y: auto; transition: max-height .26s ease, opacity .2s ease; max-height: " + v.leftMax + "; opacity: " + v.leftOpacityV + "; padding: 13px;")}>
            {/* ROBOTICS left */}
            {v.isRob && (
              <>
                <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Input mode</div>
                <div style={css("display: grid; gap: 7px;")}>
                  {v.robInputs.map((ri: any) => (
                    <button key={ri.key} onClick={ri.onClick} style={css(ri.style)}>
                      <div style={css("font-size: 13px; font-weight: 600;")}>{ri.label}</div>
                      <div style={css("font-size: 11px; color: var(--txt2); margin-top: 2px;")}>{ri.sub}</div>
                    </button>
                  ))}
                </div>
                {v.robImageMode && (
                  <div style={css("margin-top: 11px; padding: 12px; border: 1px dashed var(--bd); border-radius: 10px; text-align: center;")}>
                    <div style={css("color: var(--txt3); display: flex; justify-content: center;")}><Icon k="i-upload" size={26} /></div>
                    <div style={css("font-size: 12px; color: var(--txt2); margin-top: 4px;")}>Drop reference image</div>
                    <div style={css("margin-top: 10px; display: flex; align-items: center; gap: 7px; text-align: left;")}>
                      <div style={css("font-size: 11px; color: var(--txt2); flex: 1;")}>Scale anchor</div>
                      <input type="number" value={v.rob.scaleAnchor} onChange={v.onScaleAnchor} style={css("width: 62px; padding: 5px 7px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 7px; color: var(--txt); font-size: 12px;")} />
                      <span style={css("font-size: 11px; color: var(--txt3);")}>mm</span>
                    </div>
                    <div style={css("font-size: 10px; color: var(--txt3); margin-top: 6px; line-height: 1.4;")}>Vision can't recover absolute size — give one real dimension.</div>
                  </div>
                )}
                <div onClick={v.onToggleAssembly} style={css(v.assemblyToggleStyle)}>
                  <div>
                    <div style={css("font-size: 13px; font-weight: 600;")}>Assembly</div>
                    <div style={css("font-size: 11px; color: var(--txt2);")}>Multi-part object</div>
                  </div>
                  <div style={css(v.assemblyKnobTrack)}><div style={css(v.assemblyKnob)} /></div>
                </div>
                <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Library</div>
                <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 7px;")}>
                  {v.robLibrary.map((it: any, i: number) => (
                    <div key={i} style={css("aspect-ratio: 1; border-radius: 9px; border: 1px solid var(--bd); background: " + it.bg + "; padding: 8px; display: flex; flex-direction: column; justify-content: flex-end; cursor: pointer;")}>
                      <div style={css("font-size: 11px; font-weight: 600;")}>{it.name}</div>
                      <div style={css("font-size: 10px; color: var(--txt2); font-family: 'JetBrains Mono', monospace;")}>{it.meta}</div>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* CREATE left: input options */}
            {v.creLeftInput && (
              <>
                <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Source</div>
                <div style={css("display: flex; gap: 7px; margin-bottom: 14px;")}>
                  {v.creInputs.map((ci: any, i: number) => (
                    <button key={i} onClick={ci.onClick} style={css(ci.style)}>{ci.label}</button>
                  ))}
                </div>
                {v.creImageMode && (
                  <div onClick={v.onPickImage} onDrop={v.onImageDrop} onDragOver={(e) => e.preventDefault()} style={css("margin-bottom: 14px; padding: 18px 12px; border: 1px dashed var(--bd); border-radius: 10px; text-align: center; cursor: pointer;")}>
                    <input ref={v.setFileInput} type="file" accept="image/*" onChange={v.onImageChosen} style={{ display: "none" }} />
                    {v.creImageB64 ? (
                      <>
                        <img src={"data:image/*;base64," + v.creImageB64} alt="reference" style={css("max-width: 100%; max-height: 120px; border-radius: 8px; display: block; margin: 0 auto;")} />
                        <div style={css("font-size: 11px; color: var(--txt2); margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;")}>{v.creImageName}</div>
                      </>
                    ) : (
                      <>
                        <div style={css("color: var(--txt3); display: flex; justify-content: center;")}><Icon k="i-upload" size={26} /></div>
                        <div style={css("font-size: 12px; color: var(--txt2); margin-top: 4px;")}>Drop an image, or click to choose</div>
                      </>
                    )}
                  </div>
                )}
                <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Quality tier</div>
                <div style={css("display: grid; gap: 6px;")}>
                  {v.creTiers.map((ct: any, i: number) => (
                    <button key={i} onClick={ct.onClick} style={css(ct.style)}>
                      <span style={css("font-size: 12.5px; font-weight: 600;")}>{ct.label}</span>
                      <span style={css("font-size: 11px; color: var(--txt2); font-family: 'JetBrains Mono', monospace;")}>{ct.time}</span>
                    </button>
                  ))}
                </div>
              </>
            )}

            {/* CREATE terrain mode — biome picker is in the right Inspector */}
            {v.creTerrainMode && (
              <>
                <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Terrain tile</div>
                <div style={css("font-size: 12px; color: var(--txt2); line-height: 1.55;")}>Generate a placeable, vertex-colored ground tile with <strong style={css("color:var(--txt);")}>Infinigen</strong> — real heightfield + erosion. Pick a biome on the right →</div>
                <div style={css("margin-top: 10px; padding: 9px 11px; border-radius: 9px; background: rgba(255,180,60,.08); border: 1px solid rgba(255,180,60,.25); font-size: 11px; color: #FFD79A; line-height: 1.45;")}>Heavier job · ~5–6 min. It lands in your Library and is set as the scene ground.</div>
              </>
            )}

            {/* CREATE/ASSEMBLE library */}
            {v.showLibrary && (
              <>
                <div style={css("display: flex; align-items: center; gap: 8px; margin-bottom: 11px;")}>
                  <input type="text" placeholder="Search library…" value={v.librarySearch} onChange={v.onLibrarySearch} style={css("flex: 1; padding: 7px 10px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 8px; color: var(--txt); font-size: 12px; font-family: Hanken Grotesk,sans-serif;")} />
                </div>
                {v.libraryEmpty && (
                  <div style={css("padding: 22px 8px; text-align: center; color: var(--txt3); font-size: 12px; line-height: 1.5;")}>No assets yet.<br />Generate one in Create — it lands here.</div>
                )}
                <div style={css("display: grid; gap: 9px;")}>
                  {v.libraryItems.map((it: any, i: number) => (
                    <div key={i} draggable onDragStart={it.onDragStart} title={it.name} style={css("display: flex; gap: 11px; padding: 9px; border-radius: 11px; border: 1px solid var(--bd); background: rgba(255,255,255,.02); cursor: grab; align-items: center;")}>
                      <div style={css("width: 48px; height: 48px; border-radius: 8px; background: " + it.bg + "; flex-shrink: 0; position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; color: " + it.geoColor + ";")}>
                        {it.thumb
                          ? <img src={it.thumb} alt={it.name} style={css("width: 100%; height: 100%; object-fit: cover; display: block;")} />
                          : <svg width="30" height="30" viewBox="0 0 24 24" style={css("display:block; opacity:.92;")}><use href={"#" + it.thumbKey} /></svg>}
                        {it.busy && (
                          <div style={css("position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;")}><div style={css("width: 16px; height: 16px; border: 2px solid rgba(255,255,255,.25); border-top-color: var(--accent); border-radius: 50%; animation: ml-spin .8s linear infinite;")} /></div>
                        )}
                      </div>
                      <div style={css("flex: 1; min-width: 0;")}>
                        <div style={css("font-size: 11px; color: var(--txt2); font-family: 'JetBrains Mono', monospace;")}>{it.meta}</div>
                      </div>
                      {it.canAdd && (
                        <button onClick={it.onAdd} title="Add to scene" style={css("width: 28px; height: 28px; border-radius: 8px; border: 1px solid var(--bd); background: transparent; color: var(--accent); font-size: 16px; cursor: pointer; flex-shrink: 0;")}>＋</button>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* ASSEMBLE outliner */}
            {v.showOutliner && (
              <>
                {v.asmEmpty && (
                  <div style={css("padding: 24px 8px; text-align: center; color: var(--txt3); font-size: 12px; line-height: 1.5;")}>No objects yet.<br />Drop assets from the Library onto the canvas.</div>
                )}
                <div style={css("display: grid; gap: 4px;")}>
                  {v.outlinerRows.map((ob: any, i: number) => (
                    <div key={i} draggable={ob.draggable} onDragStart={ob.onDragStart} onDragOver={ob.onDragOver} onDrop={ob.onDrop} onClick={ob.onSelect} style={css(ob.rowStyle)}>
                      <span style={css("width: 7px; height: 7px; border-radius: 50%; background: " + ob.dot + "; flex-shrink: 0;")} />
                      <span style={css("flex: 1; font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;")}>{ob.name}</span>
                      <button onClick={ob.onHide} title="Hide" style={css("background: none; border: none; color: var(--txt3); cursor: pointer; padding: 2px; display: flex;")}><svg width="15" height="15" viewBox="0 0 24 24" style={{ display: "block" }}><use href={"#" + ob.eyeKey} /></svg></button>
                      <button onClick={ob.onDelete} title="Delete" style={css("background: none; border: none; color: var(--txt3); cursor: pointer; font-size: 13px; padding: 2px;")}>✕</button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {/* ===== RIGHT INSPECTOR ===== */}
        <div id="ml-right" style={css("position: absolute; right: 16px; top: 78px; max-height: calc(100vh - 168px); width: 320px; z-index: 25; display: flex; flex-direction: column; background: var(--panel); backdrop-filter: blur(20px) saturate(1.3); -webkit-backdrop-filter: blur(20px) saturate(1.3); border: 1px solid var(--bd); border-radius: 13px; box-shadow: 0 12px 40px rgba(0,0,0,.4); overflow: hidden;")}>
          <div style={css("padding: 13px 15px; border-bottom: 1px solid var(--bd); display: flex; align-items: center; gap: 9px;")}>
            <span style={css("width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent);")} />
            <span style={css("font-family: Sora, sans-serif; font-weight: 600; font-size: 13.5px;")}>{v.inspectorTitle}</span>
            <span style={css("flex: 1;")} />
            <span style={css("font-size: 10.5px; color: var(--txt3); font-family: 'JetBrains Mono', monospace;")}>{v.inspectorMeta}</span>
            <button onClick={v.onToggleRight} title="Collapse panel" style={css("width: 26px; height: 26px; display: flex; align-items: center; justify-content: center; border: none; border-radius: 7px; background: rgba(0,0,0,.25); color: var(--txt2); cursor: pointer; flex-shrink: 0; margin-left: 2px;")}><svg width="14" height="14" viewBox="0 0 24 24" style={css("display:block; transition: transform .2s; transform: " + v.rightCaret + ";")}><use href="#i-chevron" /></svg></button>
          </div>
          <div style={css("flex: 1; min-height: 0; overflow-y: auto; transition: max-height .26s ease, opacity .2s ease; max-height: " + v.rightMax + "; opacity: " + v.rightOpacityV + ";")}>

            {/* JOB PROGRESS */}
            {v.job && (
              <div style={css("padding: 18px 15px;")}>
                {v.jobRunning && (
                  <>
                    <div style={css("font-family: Sora, sans-serif; font-size: 15px; font-weight: 600;")}>{v.jobTitle}</div>
                    <div style={css("font-size: 12px; color: var(--txt2); margin-top: 3px;")}>{v.jobHint}</div>
                    <div style={css("margin: 16px 0 6px; height: 4px; border-radius: 4px; background: rgba(255,255,255,.08); overflow: hidden; position: relative;")}>
                      <div style={css("position: absolute; inset: 0; width: 40%; background: linear-gradient(90deg, transparent, var(--accent), transparent); animation: ml-shimmer 1.4s ease-in-out infinite;")} />
                    </div>
                    <div style={css("display: flex; justify-content: space-between; font-size: 11px; color: var(--txt3); font-family: 'JetBrains Mono', monospace;")}>
                      <span>elapsed {v.jobElapsed}s</span><span>{v.jobStageCount}</span>
                    </div>
                    {v.jobConcept && (
                      <div style={css("margin-top: 14px; border-radius: 11px; overflow: hidden; border: 1px solid var(--bd); position: relative; animation: ml-rise .4s ease;")}>
                        {v.jobMvViews ? (
                          <div style={css("aspect-ratio: 16/10; display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; background: #0d0a12;")}>
                            {v.jobMvViews.map((mv: string, i: number) => (
                              <img key={i} src={"data:image/png;base64," + mv} alt={"view " + (i + 1)} style={css("width: 100%; height: 100%; object-fit: cover; display: block; animation: ml-rise .3s ease;")} />
                            ))}
                          </div>
                        ) : (
                          <div style={css("aspect-ratio: 16/10; background: " + v.jobConceptBg + ";" + (v.jobConceptReady ? "" : "animation: ml-pulse 1.4s infinite;"))} />
                        )}
                        <div style={css("position: absolute; bottom: 0; left: 0; right: 0; padding: 7px 10px; background: linear-gradient(transparent, rgba(0,0,0,.7)); font-size: 10.5px; color: rgba(255,255,255,.85);")}>{v.jobConceptLabel}</div>
                      </div>
                    )}
                    <div style={css("margin-top: 16px; display: grid; gap: 9px;")}>
                      {v.jobStages.map((js: any, i: number) => (
                        <div key={i} style={css("display: flex; align-items: center; gap: 10px;")}>
                          <span style={css(js.dot)}>{js.mark}</span>
                          <span style={css("font-size: 12.5px; color: " + js.color + ";")}>{js.label}</span>
                        </div>
                      ))}
                    </div>
                    <button onClick={v.onCancelJob} style={css("margin-top: 18px; width: 100%; padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.04); color: var(--txt2); font-size: 12.5px; font-weight: 500; cursor: pointer;")}>Cancel</button>
                  </>
                )}
                {v.jobError && (
                  <div style={css("text-align: center; padding: 12px 0;")}>
                    <div style={css("width: 46px; height: 46px; margin: 0 auto 14px; border-radius: 12px; background: rgba(255,90,90,.12); border: 1px solid rgba(255,90,90,.4); color: #FF7A7A; display: flex; align-items: center; justify-content: center; font-size: 22px;")}>!</div>
                    <div style={css("font-family: Sora, sans-serif; font-size: 15px; font-weight: 600;")}>Job failed</div>
                    <div style={css("font-size: 12px; color: var(--txt2); margin-top: 5px; line-height: 1.5;")}>{v.jobErrorMsg}</div>
                    <div style={css("margin-top: 8px; font-size: 10.5px; color: var(--txt3); font-family: 'JetBrains Mono', monospace;")}>stage: {v.jobErrorStage} · {v.jobElapsed}s</div>
                    <div style={css("display: flex; gap: 8px; margin-top: 16px;")}>
                      <button onClick={v.onCancelJob} style={css("flex: 1; padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.04); color: var(--txt2); font-size: 12.5px; cursor: pointer;")}>Dismiss</button>
                      <button onClick={v.onRetryJob} style={css("flex: 1; padding: 9px; border-radius: 9px; border: none; background: var(--accent); color: #0A0A0F; font-weight: 600; font-size: 12.5px; cursor: pointer;")}>Retry</button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ROBOTICS INSPECTOR */}
            {v.showRobInspector && (
              <>
                {v.robSpecMode && (
                  <div style={css("padding: 14px 15px;")}>
                    <label style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3);")}>Object name</label>
                    <input type="text" value={v.rob.spec.name} onChange={v.onSpecName} style={css("width: 100%; margin-top: 6px; padding: 8px 10px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 8px; color: var(--txt); font-size: 13px; font-family: Hanken Grotesk,sans-serif;")} />

                    <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3);")}>Shape</div>
                    <div style={css("display: flex; gap: 6px; margin-top: 7px;")}>
                      {v.robShapes.map((sh: any, i: number) => (
                        <button key={i} onClick={sh.onClick} style={css(sh.style)}>{sh.label}</button>
                      ))}
                    </div>

                    <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Envelope</div>
                    <div style={css("display: grid; gap: 11px;")}>
                      {v.robDims.map((d: any, i: number) => (
                        <div key={i}>
                          <div style={css("display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;")}>
                            <span style={css("font-size: 12px; color: var(--txt2);")}>{d.label}</span>
                            <div style={css("display: flex; align-items: center; gap: 4px;")}>
                              <input type="number" value={d.value} onChange={d.onInput} style={css("width: 56px; padding: 4px 7px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 6px; color: var(--txt); font-size: 12px; text-align: right;")} />
                              <span style={css("font-size: 11px; color: var(--txt3);")}>mm</span>
                            </div>
                          </div>
                          <input type="range" min={d.min} max={d.max} value={d.value} onChange={d.onInput} style={css("width: 100%;")} />
                        </div>
                      ))}
                    </div>

                    <div style={css("margin-top: 18px; display: flex; align-items: center; justify-content: space-between; position: relative;")}>
                      <span style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3);")}>Features</span>
                      <button onClick={v.onAddFeature} style={css("font-size: 11px; color: var(--accent); background: transparent; border: 1px solid rgba(var(--accent-rgb),.3); border-radius: 7px; padding: 4px 9px; cursor: pointer; font-weight: 600;")}>＋ Add</button>
                      {v.featMenuOpen && (
                        <div style={css("position: absolute; top: 30px; right: 0; z-index: 50; width: 184px; background: var(--panel-solid); border: 1px solid var(--bd); border-radius: 10px; box-shadow: 0 16px 44px rgba(0,0,0,.55); padding: 5px; animation: ml-rise .15s ease;")}>
                          {v.featureTypes.map((ft: any, i: number) => (
                            <button key={i} className="ml-menu-item" onClick={ft.onClick} style={css("display: block; width: 100%; text-align: left; padding: 8px 10px; border: none; background: transparent; color: var(--txt); font-size: 12.5px; border-radius: 7px; cursor: pointer; font-family: Hanken Grotesk, sans-serif;")}>{ft.label}</button>
                          ))}
                        </div>
                      )}
                    </div>
                    <div style={css("margin-top: 9px; display: grid; gap: 8px;")}>
                      {v.robFeatures.map((f: any, i: number) => (
                        <div key={i} style={css("padding: 10px; border-radius: 10px; border: 1px solid var(--bd); background: rgba(255,255,255,.02);")}>
                          <div style={css("display: flex; align-items: center; gap: 8px;")}>
                            <span style={css("font-size: 12.5px; font-weight: 600; flex: 1;")}>{f.title}</span>
                            <button onClick={f.onRemove} style={css("background: none; border: none; color: var(--txt3); cursor: pointer; font-size: 13px;")}>✕</button>
                          </div>
                          <div style={css("display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 8px;")}>
                            {f.params.map((p: any, j: number) => (
                              <div key={j} style={css("display: flex; align-items: center; gap: 5px;")}>
                                <span style={css("font-size: 11px; color: var(--txt2);")}>{p.label}</span>
                                <input type="number" value={p.value} onChange={p.onInput} style={css("width: 48px; padding: 3px 6px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 6px; color: var(--txt); font-size: 11.5px; text-align: right;")} />
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>

                    {v.robWarning && (
                      <div style={css("margin-top: 11px; padding: 9px 11px; border-radius: 9px; background: rgba(255,180,60,.1); border: 1px solid rgba(255,180,60,.35); display: flex; gap: 8px;")}>
                        <span style={css("color: #FFC25A; display: flex; flex-shrink: 0;")}><Icon k="i-fault" size={15} /></span>
                        <span style={css("font-size: 11.5px; color: #FFD79A; line-height: 1.45;")}>{v.robWarning}</span>
                      </div>
                    )}

                    <div style={css("margin-top: 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;")}>
                      <div>
                        <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 6px;")}>Tolerance</div>
                        <div style={css("display: flex; align-items: center; gap: 5px;")}><span style={css("font-size: 12px; color: var(--txt2);")}>±</span><input type="number" step="0.01" value={v.rob.spec.tol} onChange={v.onSpecTol} style={css("width: 56px; padding: 5px 7px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 6px; color: var(--txt); font-size: 12px; text-align: right;")} /><span style={css("font-size: 11px; color: var(--txt3);")}>mm</span></div>
                      </div>
                      <div>
                        <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 6px;")}>Fabrication</div>
                        <div style={css("display: flex; gap: 4px;")}>
                          {v.robFab.map((fb: any, i: number) => (
                            <button key={i} onClick={fb.onClick} style={css(fb.style)}>{fb.label}</button>
                          ))}
                        </div>
                      </div>
                    </div>
                    {v.robFabricate && (
                      <div style={css("margin-top: 11px; display: flex; align-items: center; justify-content: space-between; padding: 9px 11px; border-radius: 9px; background: rgba(255,255,255,.02); border: 1px solid var(--bd);")}>
                        <span style={css("font-size: 12px; color: var(--txt2);")}>Min-wall (DFM)</span>
                        <div style={css("display: flex; align-items: center; gap: 5px;")}><input type="number" step="0.1" value={v.rob.spec.minWall} onChange={v.onSpecMinWall} style={css("width: 52px; padding: 4px 7px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 6px; color: var(--txt); font-size: 12px; text-align: right;")} /><span style={css("font-size: 11px; color: var(--txt3);")}>mm</span></div>
                      </div>
                    )}
                  </div>
                )}

                {v.robResult && (
                  <div style={css("padding: 14px 15px; animation: ml-rise .4s ease;")}>
                    <div style={css("display: flex; align-items: center; gap: 9px; padding: 11px 13px; border-radius: 11px; background: rgba(80,220,140,.1); border: 1px solid rgba(80,220,140,.38);")}>
                      <span style={css("width: 26px; height: 26px; border-radius: 50%; background: rgba(80,220,140,.2); color: #5FE3A1; display: flex; align-items: center; justify-content: center; font-size: 15px;")}>✓</span>
                      <div style={css("flex: 1;")}>
                        <div style={css("font-size: 13px; font-weight: 600; color: #8FF0C0;")}>Verified against spec</div>
                        <div style={css("font-size: 11px; color: var(--txt2); font-family: 'JetBrains Mono', monospace;")}>{v.rob.result.attempts} attempts · {v.rob.result.timeStr}</div>
                      </div>
                    </div>
                    {v.rob.result.corrected && (
                      <div style={css("margin-top: 9px; font-size: 11px; color: var(--txt2); padding: 7px 11px; border-radius: 8px; background: rgba(255,255,255,.03); border: 1px solid var(--bd);")}>↻ Auto-corrected: {v.rob.result.corrected}</div>
                    )}

                    <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 8px;")}>Verification table</div>
                    <div style={css("border: 1px solid var(--bd); border-radius: 11px; overflow: hidden;")}>
                      <div style={css("display: grid; grid-template-columns: 1fr 52px 52px 60px 28px; gap: 6px; padding: 8px 10px; background: rgba(0,0,0,.25); font-size: 9.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--txt3);")}>
                        <span>Feature</span><span style={css("text-align: right;")}>Exp</span><span style={css("text-align: right;")}>Meas</span><span style={css("text-align: center;")}>±tol</span><span />
                      </div>
                      {v.verifyRows.map((vr: any, i: number) => (
                        <div key={i} onMouseEnter={vr.onEnter} onMouseLeave={vr.onLeave} style={css(vr.rowStyle)}>
                          <span style={css("font-family: Hanken Grotesk,sans-serif; color: var(--txt);")}>{vr.name}</span>
                          <span style={css("text-align: right; color: var(--txt2);")}>{vr.exp}</span>
                          <span style={css("text-align: right;")}>{vr.meas}</span>
                          <span style={css("position: relative; height: 6px; border-radius: 4px; background: rgba(255,255,255,.1); align-self: center;")}><span style={css("position: absolute; top: 50%; left: 50%; width: 1px; height: 8px; background: var(--txt3); transform: translate(-50%,-50%);")} /><span style={css(vr.gaugeDot)} /></span>
                          <span style={css(vr.badge)}>{vr.mark}</span>
                        </div>
                      ))}
                    </div>

                    <div style={css("margin-top: 12px; display: flex; flex-wrap: wrap; gap: 7px;")}>
                      {v.verifyBadges.map((b: any, i: number) => (
                        <span key={i} style={css("display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border-radius: 20px; background: rgba(80,220,140,.1); border: 1px solid rgba(80,220,140,.3); font-size: 11px; color: #9FF0C5;")}>✓ {b}</span>
                      ))}
                    </div>

                    <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 8px;")}>Export</div>
                    <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 9px;")}>
                      <button onClick={v.onExportStep} style={css("padding: 11px; border-radius: 10px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); cursor: pointer; text-align: left;")}>
                        <div style={css("font-size: 13px; font-weight: 600; color: var(--txt);")}>STEP</div>
                        <div style={css("font-size: 10px; color: var(--txt2); margin-top: 1px;")}>Parametric · CAD/CAM</div>
                      </button>
                      <button onClick={v.onExportStl} style={css("padding: 11px; border-radius: 10px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); cursor: pointer; text-align: left;")}>
                        <div style={css("font-size: 13px; font-weight: 600; color: var(--txt);")}>STL</div>
                        <div style={css("font-size: 10px; color: var(--txt2); margin-top: 1px;")}>Mesh · 3D printing</div>
                      </button>
                    </div>
                    <button onClick={v.onRobReset} style={css("margin-top: 10px; width: 100%; padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: transparent; color: var(--txt2); font-size: 12px; cursor: pointer;")}>← Back to spec</button>
                  </div>
                )}
              </>
            )}

            {/* CREATE INSPECTOR */}
            {v.showCreInspector && (
              <>
                {v.creIdle && (
                  <div style={css("padding: 22px 16px; color: var(--txt2); font-size: 12.5px; line-height: 1.6;")}>Describe an asset below, choose a quality tier on the left, then <strong style={css("color:var(--txt);")}>Generate</strong>. The textured result and its report appear here.</div>
                )}
                {v.creResult && (
                  <div style={css("padding: 14px 15px; animation: ml-rise .4s ease;")}>
                    <div style={css("font-family: Sora, sans-serif; font-size: 15px; font-weight: 600;")}>{v.cre.result.name}</div>
                    <div style={css("margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px;")}>
                      {v.creReport.map((rp: any, i: number) => (
                        <div key={i} style={css("padding: 9px 11px; border-radius: 9px; background: rgba(255,255,255,.03); border: 1px solid var(--bd);")}>
                          <div style={css("font-size: 10px; color: var(--txt3); letter-spacing: .04em; text-transform: uppercase;")}>{rp.label}</div>
                          <div style={css("font-size: 13px; font-weight: 600; font-family: 'JetBrains Mono', monospace; margin-top: 3px;")}>{rp.value}</div>
                        </div>
                      ))}
                    </div>
                    <div style={css("margin-top: 10px; padding: 10px 12px; border-radius: 9px; background: rgba(255,255,255,.02); border: 1px solid var(--bd);")}>
                      <div style={css("font-size: 10.5px; color: var(--txt3); letter-spacing: .04em; text-transform: uppercase; margin-bottom: 7px;")}>PBR maps</div>
                      <div style={css("display: flex; gap: 7px;")}>
                        {v.creMaps.map((m: any, i: number) => (
                          <span key={i} style={css("flex: 1; text-align: center; padding: 6px 4px; border-radius: 7px; background: rgba(80,220,140,.1); border: 1px solid rgba(80,220,140,.28); font-size: 10.5px; color: #9FF0C5;")}>{m}</span>
                        ))}
                      </div>
                    </div>

                    <div style={css("margin-top: 16px; padding: 12px; border-radius: 11px; border: 1px solid rgba(var(--accent-rgb),.3); background: transparent;")}>
                      <div style={css("display: flex; align-items: center; justify-content: space-between;")}>
                        <span style={css("font-size: 12.5px; font-weight: 600;")}>Low-Poly · game-ready</span>
                        <span style={css("font-size: 11.5px; color: var(--accent); font-family: 'JetBrains Mono', monospace;")}>{v.creLowpolyLabel}</span>
                      </div>
                      <input type="range" min="1000" max="100000" step="1000" value={v.cre.lowpolyTarget} onChange={v.onLowpoly} style={css("width: 100%; margin-top: 10px;")} />
                      <div style={css("display: flex; justify-content: space-between; font-size: 10px; color: var(--txt3); font-family: 'JetBrains Mono', monospace; margin-top: 4px;")}><span>1k</span><span>{v.cre.result.faces} now</span><span>100k</span></div>
                      <div style={css("margin-top: 11px; display: flex; align-items: center; gap: 8px; font-size: 10.5px; font-family: 'JetBrains Mono', monospace;")}>
                        <span style={css("color: var(--txt2); white-space: nowrap;")}>now {v.cre.result.faces}</span>
                        <div style={css("flex: 1; height: 6px; border-radius: 4px; background: rgba(255,255,255,.08); position: relative; overflow: hidden;")}><div style={css("position: absolute; left: 0; top: 0; bottom: 0; width: " + v.lowpolyPct + "; background: var(--accent); border-radius: 4px; transition: width .15s ease;")} /></div>
                        <span style={css("color: var(--accent); white-space: nowrap;")}>{v.lowpolyAfter}</span>
                      </div>
                      <button onClick={v.onRunLowpoly} style={css("margin-top: 10px; width: 100%; padding: 8px; border-radius: 8px; border: 1px solid rgba(var(--accent-rgb),.4); background: transparent; color: var(--accent); font-size: 12px; font-weight: 600; cursor: pointer;")}>Decimate to {v.creLowpolyLabel}</button>
                    </div>

                    <div style={css("margin-top: 14px; display: grid; gap: 8px;")}>
                      <button onClick={v.onAddToLibrary} style={css("width: 100%; padding: 10px; border-radius: 9px; border: none; background: var(--accent); color: #100A14; font-weight: 600; font-size: 12.5px; cursor: pointer;")}>＋ Add to Library &amp; Assemble</button>
                      <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 8px;")}>
                        <button onClick={v.onExportGlb} style={css("padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>Export GLB</button>
                        <button onClick={v.onExportUsdz} style={css("padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>Export USDZ</button>
                      </div>
                      <button onClick={v.onOpenRender} style={css("width: 100%; padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt2); font-size: 12px; cursor: pointer;")}>Finish → Photoreal render / Motion clip</button>
                    </div>
                  </div>
                )}
              </>
            )}

            {/* CREATE terrain panel */}
            {v.showTerrain && (
              <div style={css("padding: 14px 15px;")}>
                <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 8px;")}>Instant presets · pre-baked</div>
                <div style={css("display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 16px;")}>
                  {v.terrainPresets.map((p: any, i: number) => (
                    <button key={i} onClick={p.onClick} title={"Use " + p.label + " as the scene ground"} style={css("padding: 0; border-radius: 10px; overflow: hidden; cursor: pointer; border: 1px solid var(--bd); background: #0d0f16; color: var(--txt);")}>
                      <div style={css("aspect-ratio: 1; background: center/cover no-repeat url(" + p.thumb + ");")} />
                      <div style={css("padding: 5px 0; font-size: 11px; font-weight: 600;")}>{p.label}</div>
                    </button>
                  ))}
                </div>
                <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 8px;")}>Generate new · ~5–6 min</div>
                <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 8px;")}>
                  {v.biomes.map((bm: any, i: number) => (
                    <button key={i} onClick={bm.onClick} style={css(bm.style)}>
                      <div style={css("height: 34px; border-radius: 7px; background: " + bm.swatch + "; margin-bottom: 7px;")} />
                      <span style={css("font-size: 12px; font-weight: 600;")}>{bm.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* CREATE render/motion gallery */}
            {v.showRenderGallery && (
              <div style={css("padding: 14px 15px;")}>
                <div style={css("font-family: Sora, sans-serif; font-size: 15px; font-weight: 600;")}>Finish</div>
                <div style={css("font-size: 12px; color: var(--txt2); margin-top: 3px;")}>Path-traced Cycles output for {v.renderTarget}.</div>
                <div style={css("display: flex; gap: 6px; margin-top: 14px;")}>
                  {v.renderTabs.map((rt: any, i: number) => (
                    <button key={i} onClick={rt.onClick} style={css(rt.style)}>{rt.label}</button>
                  ))}
                </div>

                {v.renderStill && (
                  <div style={css("margin-top: 14px;")}>
                    <div style={css("border-radius: 12px; overflow: hidden; border: 1px solid var(--bd); aspect-ratio: 16/10; background: " + v.renderStillBg + "; position: relative;")}>
                      <div style={css("position: absolute; bottom: 8px; left: 10px; font-size: 10.5px; color: rgba(255,255,255,.8); font-family: 'JetBrains Mono', monospace;")}>beauty.png · 2048² · 512 spp</div>
                    </div>
                    <button onClick={v.onDownloadStill} style={css("margin-top: 9px; width: 100%; padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>↓ Download PNG</button>
                  </div>
                )}
                {v.renderMotion && (
                  <div style={css("margin-top: 14px;")}>
                    {v.motionMp4 ? (
                      <video src={"data:video/mp4;base64," + v.motionMp4} controls autoPlay loop muted playsInline style={css("width: 100%; border-radius: 12px; border: 1px solid var(--bd); display: block; aspect-ratio: 16/10; object-fit: cover; background: #08060b;")} />
                    ) : (
                      <div style={css("border-radius: 12px; overflow: hidden; border: 1px solid var(--bd); aspect-ratio: 16/10; background: " + v.renderStillBg + "; position: relative; display: flex; align-items: center; justify-content: center;")}>
                        <button onClick={v.onPlayMotion} style={css("width: 52px; height: 52px; border-radius: 50%; border: none; background: rgba(255,255,255,.92); color: #111; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center;")}><svg width="20" height="20" viewBox="0 0 24 24" style={{ display: "block" }}><use href={"#" + v.motionPlayKey} /></svg></button>
                        <div style={css("position: absolute; bottom: 0; left: 0; right: 0; padding: 8px 10px; background: linear-gradient(transparent, rgba(0,0,0,.6));")}>
                          <div style={css("height: 3px; border-radius: 3px; background: rgba(255,255,255,.25);")}><div style={css("height: 100%; width: " + v.motionProgress + "; background: var(--accent); border-radius: 3px;")} /></div>
                        </div>
                      </div>
                    )}
                    <div style={css("margin-top: 9px; display: flex; gap: 7px;")}>
                      {v.motionVariants.map((mv: any, i: number) => (
                        <button key={i} onClick={mv.onClick} style={css(mv.style)}>{mv.label}</button>
                      ))}
                    </div>
                    <button onClick={v.onDownloadMotion} style={css("margin-top: 9px; width: 100%; padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>↓ Download MP4</button>
                  </div>
                )}
              </div>
            )}

            {/* ASSEMBLE INSPECTOR */}
            {v.showAsmInspector && (
              <>
                {v.asmSelected && (
                  <div style={css("padding: 14px 15px; animation: ml-rise .25s ease;")}>
                    <input type="text" value={v.asmSel.name} onChange={v.onRenameSel} style={css("width: 100%; padding: 8px 10px; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 8px; color: var(--txt); font-size: 13px; font-weight: 600; font-family: Hanken Grotesk,sans-serif;")} />
                    <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 10px;")}>Transform</div>
                    {v.asmTransforms.map((tr: any, i: number) => (
                      <div key={i} style={css("margin-bottom: 12px;")}>
                        <div style={css("font-size: 11px; color: var(--txt2); margin-bottom: 5px;")}>{tr.label}</div>
                        <div style={css("display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px;")}>
                          {tr.axes.map((ax: any, j: number) => (
                            <div key={j} style={css("display: flex; align-items: center; background: rgba(0,0,0,.3); border: 1px solid var(--bd); border-radius: 7px; padding: 0 4px 0 7px;")}>
                              <span style={css("font-size: 10px; color: " + ax.color + "; font-weight: 700; font-family: 'JetBrains Mono', monospace;")}>{ax.axis}</span>
                              <input type="number" step={ax.step} value={ax.value} onChange={ax.onInput} style={css("width: 100%; padding: 6px 4px; background: transparent; border: none; color: var(--txt); font-size: 11.5px; text-align: right;")} />
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                    <button onClick={v.onResetTransform} style={css("width: 100%; padding: 8px; border-radius: 8px; border: 1px solid var(--bd); background: transparent; color: var(--txt2); font-size: 12px; cursor: pointer;")}>↺ Reset transform</button>

                    <div style={css("margin-top: 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px;")}>
                      <button onClick={v.onDupSel} style={css("padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>Duplicate</button>
                      <button onClick={v.onLowpolySel} style={css("padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>Low-Poly</button>
                      <button onClick={v.onDeleteSel} style={css("padding: 9px; border-radius: 9px; border: 1px solid rgba(255,90,90,.3); background: rgba(255,90,90,.08); color: #FF9A9A; font-size: 12px; cursor: pointer;")}>Delete</button>
                      <button onClick={v.onExportSel} style={css("padding: 9px; border-radius: 9px; border: 1px solid var(--bd); background: rgba(255,255,255,.03); color: var(--txt); font-size: 12px; cursor: pointer;")}>Export</button>
                    </div>
                  </div>
                )}
                {v.asmSceneSettings && (
                  <div style={css("padding: 14px 15px;")}>
                    <div style={css("font-size: 12.5px; color: var(--txt2); line-height: 1.5; margin-bottom: 14px;")}>Nothing selected — scene settings.</div>
                    <div style={css("font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Ground / terrain tile</div>
                    <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 8px;")}>
                      {v.asmGrounds.map((g: any, i: number) => (
                        <button key={i} onClick={g.onClick} style={css(g.style)}>
                          <div style={css("height: 30px; border-radius: 6px; background: " + g.swatch + "; margin-bottom: 6px;")} />
                          <span style={css("font-size: 11.5px;")}>{g.label}</span>
                        </button>
                      ))}
                    </div>
                    <div style={css("margin-top: 16px; font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--txt3); margin-bottom: 9px;")}>Lighting mood</div>
                    <div style={css("display: flex; gap: 6px;")}>
                      {v.lightingMoods.map((lm: any, i: number) => (
                        <button key={i} onClick={lm.onClick} style={css(lm.style)}>{lm.label}</button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* ===== FLOATING MESH-STATS CARD ===== */}
        {v.showStats && (
          <div style={css("position: absolute; top: 78px; left: 312px; z-index: 22; width: 196px; background: rgba(10,11,16,.72); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid var(--bd); border-radius: 12px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,.4); animation: ml-rise .3s ease;")}>
            <div style={css("padding: 9px 13px;")}>
              {v.statsRows.map((sr: any, i: number) => (
                <div key={i} style={css("display: flex; justify-content: space-between; align-items: center; padding: 4px 0; font-size: 12px;")}>
                  <span style={css("color: var(--txt2);")}>{sr.label}</span>
                  <span style={css("font-family: 'JetBrains Mono', monospace; color: var(--txt); font-weight: 500;")}>{sr.value}</span>
                </div>
              ))}
            </div>
            <div style={css("padding: 9px 13px; border-top: 1px solid var(--bd); display: flex; align-items: center; justify-content: space-between; background: rgba(80,220,140,.06);")}>
              <span style={css("font-size: 12px; color: var(--txt2);")}>{v.statsCheckLabel}</span>
              <span style={css("width: 18px; height: 18px; border-radius: 50%; background: rgba(80,220,140,.2); color: #5FE39A; display: flex; align-items: center; justify-content: center; font-size: 11px;")}>✓</span>
            </div>
          </div>
        )}

        {/* ===== BOTTOM VIEWPORT TOOLBAR ===== */}
        <div style={css("position: absolute; left: 50%; transform: translateX(-50%); bottom: 86px; z-index: 27; display: flex; align-items: center; gap: 3px; padding: 5px 7px; background: var(--panel); backdrop-filter: blur(20px) saturate(1.3); -webkit-backdrop-filter: blur(20px) saturate(1.3); border: 1px solid var(--bd); border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.45);")}>
          {v.viewTools.map((vt: any, i: number) => (
            <button key={i} onClick={vt.onClick} title={vt.title} style={css(vt.style)}><Icon k={vt.iconKey} /></button>
          ))}
          <span style={css("width: 1px; height: 18px; background: var(--bd); margin: 0 3px;")} />
          {v.actionTools.map((at: any, i: number) => (
            <button key={i} onClick={at.onClick} title={at.title} style={css(at.style)}><Icon k={at.iconKey} /></button>
          ))}
        </div>

        {/* ASSEMBLE gizmo mode toolbar */}
        {v.showGizmoBar && (
          <div style={css("position: absolute; left: 50%; top: 90px; transform: translateX(-50%); z-index: 26; display: flex; flex-direction: row; align-items: center; gap: 4px; padding: 5px 6px; background: var(--panel); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid var(--bd); border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.4);")}>
            {v.gizmoModes.map((gm: any, i: number) => (
              <button key={i} onClick={gm.onClick} title={gm.title} style={css(gm.style)}><Icon k={gm.iconKey} size={18} /><span style={css("font-size: 9px; opacity: .6; font-family: 'JetBrains Mono', monospace;")}>{gm.key}</span></button>
            ))}
            <span style={css("width: 1px; height: 24px; background: var(--bd); margin: 0 2px;")} />
            <button onClick={v.onToggleSnap} title="Snap to grid / 15° (Shift also forces snap)" style={css(v.snapStyle)}><Icon k="i-snap" size={18} /><span style={css("font-size: 9px; opacity: .6; font-family: 'JetBrains Mono', monospace;")}>{v.snapActive ? "snap" : "free"}</span></button>
            <div style={css("margin-left: 3px; padding-left: 8px; border-left: 1px solid var(--bd); font-size: 9px; line-height: 1.2; color: var(--txt3); font-family: 'JetBrains Mono', monospace; white-space: nowrap;")}>MMB orbit<br />⇧·RMB pan</div>
          </div>
        )}

        {/* ===== BOTTOM COMMAND BAR ===== */}
        <div style={css("position: absolute; left: 50%; transform: translateX(-50%); bottom: 16px; z-index: 28; width: min(860px, calc(100% - 56px)); display: flex; align-items: center; gap: 10px; padding: 9px 9px 9px 16px; background: var(--panel); backdrop-filter: blur(20px) saturate(1.3); -webkit-backdrop-filter: blur(20px) saturate(1.3); border: 1px solid var(--bd); border-radius: 14px; box-shadow: 0 16px 50px rgba(0,0,0,.5);")}>
          <span style={css("color: var(--accent); flex-shrink: 0; display: flex;")}><Icon k="i-generate" size={19} /></span>
          <input type="text" placeholder={v.commandPlaceholder} value={v.commandValue} onChange={v.onCommandInput} onKeyDown={v.onCommandKey} style={css("flex: 1; min-width: 0; background: transparent; border: none; outline: none; color: var(--txt); font-size: 14px; font-family: Hanken Grotesk,sans-serif;")} />
          {v.showFinishMenu && (
            <div style={css("display: flex; gap: 6px; flex-shrink: 0;")}>
              {v.finishActions.map((fa: any, i: number) => (
                <button key={i} onClick={fa.onClick} title={fa.title} style={css(fa.style)}>{fa.label}</button>
              ))}
            </div>
          )}
          {v.showTimeHint && (
            <span style={css("display: inline-flex; align-items: center; gap: 5px; padding: 6px 11px; border-radius: 9px; background: rgba(255,255,255,.05); border: 1px solid var(--bd); font-size: 11.5px; color: var(--txt2); font-family: 'JetBrains Mono', monospace; flex-shrink: 0;")}><Icon k="i-clock" size={13} />{v.timeHint}</span>
          )}
          <button onClick={v.onPrimaryAction} style={css(v.primaryActionStyle)}>{v.primaryActionLabel}</button>
        </div>

        {v.dragLabel && (
          <div style={css("position: fixed; left: " + v.dragLabel.x + "px; top: " + v.dragLabel.y + "px; z-index: 60; pointer-events: none; padding: 4px 9px; border-radius: 7px; background: var(--panel-solid); border: 1px solid var(--bd); font-size: 11.5px; font-family: 'JetBrains Mono', monospace; color: var(--txt); box-shadow: 0 6px 20px rgba(0,0,0,.5); white-space: nowrap;")}>{v.dragLabel.text}</div>
        )}

        {v.shortcutsOpen && (
          <div onClick={v.onCloseShortcuts} style={css("position: absolute; inset: 0; z-index: 70; background: rgba(4,5,8,.62); backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center;")}>
            <div style={css("width: 372px; max-width: calc(100% - 40px); background: var(--panel-solid); border: 1px solid var(--bd); border-radius: 16px; box-shadow: 0 24px 70px rgba(0,0,0,.6); overflow: hidden; animation: ml-rise .2s ease;")}>
              <div style={css("padding: 15px 18px; border-bottom: 1px solid var(--bd); display: flex; align-items: center; gap: 9px;")}>
                <span style={css("font-family: Sora, sans-serif; font-weight: 600; font-size: 15px; flex: 1;")}>Keyboard &amp; mouse</span>
                <button onClick={v.onCloseShortcuts} style={css("width: 26px; height: 26px; border: none; border-radius: 7px; background: rgba(255,255,255,.06); color: var(--txt2); cursor: pointer; font-size: 13px;")}>✕</button>
              </div>
              <div style={css("padding: 8px 12px 14px;")}>
                {v.shortcutList.map((sc: any, i: number) => (
                  <div key={i} style={css("display: flex; align-items: center; gap: 12px; padding: 6px 6px;")}>
                    <span style={css("font-family: 'JetBrains Mono', monospace; font-size: 11.5px; color: var(--accent); min-width: 138px;")}>{sc.k}</span>
                    <span style={css("font-size: 12.5px; color: var(--txt2);")}>{sc.v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* toast */}
        {v.toast && (
          <div style={css("position: absolute; bottom: 148px; left: 50%; transform: translateX(-50%); z-index: 40; padding: 10px 18px; background: var(--panel-solid); border: 1px solid var(--bd); border-radius: 10px; font-size: 12.5px; box-shadow: 0 12px 40px rgba(0,0,0,.5); animation: ml-rise .25s ease; display: flex; align-items: center; gap: 9px;")}>
            <span style={css("color: var(--accent);")}>●</span>{v.toast}
          </div>
        )}
      </div>
    );
  }
}
