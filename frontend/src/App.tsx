/* MotionLab Studio — root component. Owns all app state (the Studio contract in store.tsx),
 * the persistent WebGL viewport, and the REAL generation task engine:
 *   CAD part      → POST /api/cad/generate  → poll → STL/STEP/code/inspection
 *   CAD assembly  → POST /api/cad/plan      → poll → assembly JSON + fused STL + kinematic rows
 *   Mesh          → POST /api/trackb/text2mesh|image2mesh → poll → GLB + report
 * Screens are pixel transcriptions of the Claude-Design handoff (docs/design/). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "./api";
import { IconDefs } from "./icons";
import { useExit, viewSwap } from "./motion";
import { sx } from "./sx";
import {
  Attempt, CadKind, EngineStatus, MeshTier, Model, Screen, Studio, StudioCtx, Task, Theater, Track,
  User, TIER_LABEL, attemptsFromHistory, fromServer, migrateLocalLibrary, pollHealth, toServer,
  titleFromPrompt,
} from "./store";
import { VP } from "./viewport";
import { Login } from "./screens/Login";
import { Shell } from "./screens/Shell";
import { Editor } from "./screens/Editor";
import { Result, ResultPhase } from "./screens/Result";
import { GenerateModal } from "./screens/GenerateModal";
import { BugFab } from "./screens/BugFab";
import { BugReport } from "./screens/BugReport";

let idSeq = 0;
const uid = () => Date.now().toString(36) + "-" + (idSeq++).toString(36) + Math.random().toString(36).slice(2, 6);

export function App() {
  /* ---------- routing + auth (real: studio_api bearer session) ---------- */
  const [user, setUser] = useState<User | null>(null);
  const [authBusy, setAuthBusy] = useState(!!api.getToken());   // token present → validating
  const [screen, setScreen] = useState<Screen>(api.getToken() ? "dashboard" : "login");
  const [nav, setNav] = useState("dashboard");
  const go = useCallback((s: Screen, n?: string) => {
    viewSwap(() => {  // native View Transition crossfade between screens (instant where unsupported)
      setScreen(s);
      if (n) setNav(n);
      else if (s === "projects" || s === "project") setNav("projects");
      else if (s === "dashboard" || s === "settings") setNav(s === "settings" ? "settings" : "dashboard");
    });
  }, []);

  /* ---------- generation inputs ---------- */
  const [track, setTrack] = useState<Track>("cad");
  const [cadKind, setCadKind] = useState<CadKind>("part");
  const [meshTier, setMeshTier] = useState<MeshTier>("quality");
  const [prompt, setPrompt] = useState("");

  /* ---------- engines / tasks / library ---------- */
  const [engines, setEngines] = useState<EngineStatus>({ cad: "unknown", assembly: "unknown", mesh: "unknown" });
  const [tasks, setTasks] = useState<Task[]>([]);
  const [library, setLibrary] = useState<Model[]>([]);
  const [activeProject, setActiveProject] = useState("My Project");
  const [projectNames, setProjectNames] = useState<string[]>(["My Project"]);

  /* ---------- result focus ---------- */
  const [current, setCurrent] = useState<Model | null>(null);
  const [liveTask, setLiveTask] = useState<Task | null>(null);
  const [phase, setPhase] = useState<ResultPhase>("running");
  const [resultError, setResultError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const lastRun = useRef<{ prompt: string; track: Track; cadKind: CadKind; meshTier: MeshTier; imageB64?: string; multiview?: boolean } | null>(null);

  /* ---------- generation theater (live mid-job artifacts) ---------- */
  const [theater, setTheater] = useState<Theater>({ views: [], partNames: [] });
  const livePartsRef = useRef<api.CadPart[]>([]);
  const resetTheater = useCallback((concept?: string | null) => {
    livePartsRef.current = [];
    setTheater({ concept: concept ?? null, views: [], partNames: [] });
  }, []);

  /* ---------- toast + modal ---------- */
  const [toast, setToast] = useState<string | null>(null);
  const toastT = useRef<any>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    clearTimeout(toastT.current);
    toastT.current = setTimeout(() => setToast(null), 2600);
  }, []);
  const [genModalOpen, setGenModalOpen] = useState(false);

  /* deferred unmounts so overlays play their exit (theme.css [data-closing]) */
  const toastEx = useExit(!!toast, 150);
  const lastToast = useRef("");
  if (toast) lastToast.current = toast;
  const genModalEx = useExit(genModalOpen, 140);
  const [bugOpen, setBugOpen] = useState(false);
  const bugEx = useExit(bugOpen, 140);

  /* ---------- server library / projects ---------- */
  const loadUserData = useCallback(async () => {
    const [ms, ps] = await Promise.all([api.studio.models(), api.studio.projects()]);
    setLibrary(ms.models.map(fromServer));
    setProjectNames([...new Set(["My Project", ...ps.projects.map((p) => p.name)])]);
  }, []);

  /** One-time migration of the pre-auth IndexedDB library into this account — runs in the
   * BACKGROUND after sign-in (the payloads are tens of MB over the tunnel; it must never block
   * the auth flow). Resumable: skips models the server already has, flags completion. */
  const migrateInBackground = useCallback(async () => {
    if (localStorage.getItem("mlk-migrated")) return;
    try {
      const local = await migrateLocalLibrary();
      if (!local.length) { localStorage.setItem("mlk-migrated", "1"); return; }
      const have = new Set((await api.studio.models()).models.map((m: any) => m.id));
      const todo = local.filter((m) => m.id && !have.has(m.id));
      if (!todo.length) { localStorage.setItem("mlk-migrated", "1"); return; }
      showToast(`Syncing ${todo.length} local model${todo.length === 1 ? "" : "s"} to your account…`);
      let ok = 0;
      for (const m of todo) {
        try { await api.studio.saveModel(toServer(m)); ok++; } catch { /* keep going; retried next boot */ }
      }
      if (ok === todo.length) localStorage.setItem("mlk-migrated", "1");
      const ms = await api.studio.models();
      setLibrary(ms.models.map(fromServer));
      showToast(`Synced ${ok} of ${todo.length} local models into your account`);
    } catch { /* never disturb the session over a migration */ }
  }, [showToast]);

  /* ---------- boot: validate session, load per-user data, poll health ---------- */
  useEffect(() => {
    if (!api.getToken()) return;
    (async () => {
      try {
        const me = await api.studio.me();
        setUser(me.user);
        await loadUserData();
        migrateInBackground();   // fire-and-forget — never blocks auth
      } catch (e: any) {
        api.setToken(null);            // expired/invalid session → clean login
        setUser(null);
        setScreen("login");
      } finally {
        setAuthBusy(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    let alive = true;
    const tick = () => pollHealth().then((h) => { if (alive) setEngines(h); });
    tick();
    const t = setInterval(tick, 20000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  /* ---------- viewport lifecycle ---------- */
  const vpRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (vpRef.current) VP.mount(vpRef.current); return () => VP.unmount(); }, []);
  useEffect(() => { VP.setActive(screen === "editor" || screen === "result"); }, [screen]);

  /* ---------- the task engine ---------- */
  const updateTask = useCallback((id: string, patch: Partial<Task>) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch } : t)));
    setLiveTask((lt) => (lt && lt.id === id ? { ...lt, ...patch } : lt));
  }, []);

  const finishModel = useCallback((m: Model) => {
    setLibrary((lib) => [m, ...lib].slice(0, 500));
    setCurrent(m);
    setPhase("done");
    // thumbnail once the mesh is actually in the viewport, then persist to the user's account
    setTimeout(() => {
      const thumb = VP.captureThumb();
      const full = thumb ? { ...m, thumb } : m;
      if (thumb) setLibrary((lib) => lib.map((x) => (x.id === m.id ? { ...x, thumb } : x)));
      api.studio.saveModel(toServer(full)).catch((e) =>
        showToast("Saved locally only — sync failed: " + (e?.message || e)));
    }, 350);
  }, [showToast]);

  const startGenerate = useCallback((opts?: { prompt?: string; imageB64?: string; multiview?: boolean }) => {
    const p = (opts?.prompt ?? prompt).trim();
    const imageB64 = opts?.imageB64;
    // image input ⇒ multi-view by default (MV-Adapter 6 views → multi-view TRELLIS): single-view
    // guesses every unseen side. An explicit value (the concept modal's toggle) still wins.
    const multiview = opts?.multiview ?? true;   // MV-Adapter default-on for ALL mesh gens (text + image)
    if (!p && !imageB64) { showToast("Describe what to generate first"); return; }
    const tk = track, kind = cadKind, tier = meshTier;
    lastRun.current = { prompt: p, track: tk, cadKind: kind, meshTier: tier, imageB64, multiview };
    const engine = tk === "mesh" ? "mesh" : kind === "assembly" ? "assembly" : "cad";
    const name = titleFromPrompt(p || "Image to 3D");
    const estSec = (engine === "mesh" ? (tier === "fast" ? 45 : tier === "quality" ? 130 : 300) : engine === "assembly" ? 150 : 35)
      + (engine === "mesh" && multiview ? 30 : 0);   // MV-Adapter view synthesis rides ahead of TRELLIS
    const task: Task = { id: uid(), name, engine, stage: "queued", elapsed: 0, estSec, running: true, done: false };
    setTasks((ts) => [task, ...ts].slice(0, 8));
    setLiveTask(task);
    setCurrent(null);
    setAttempts([]);
    setResultError(null);
    setPhase("running");
    resetTheater(imageB64 ? "data:image/png;base64," + imageB64 : null);
    go("result");
    VP.beginConstruction();          // empty stage — the theater fills it

    // Track B publishes the FLUX concept + MV views mid-job; surface them the moment they exist.
    const onProgress: api.Progress = (stage, elapsed, conceptB64, mvViews) => {
      updateTask(task.id, { stage: stage || "running", elapsed });
      if (conceptB64 || (mvViews && mvViews.length)) {
        setTheater((t) => ({
          ...t,
          concept: conceptB64 ? "data:image/png;base64," + conceptB64 : t.concept,
          views: mvViews && mvViews.length ? mvViews.map((v) => "data:image/png;base64," + v) : t.views,
        }));
      }
    };
    // Track A publishes stage/attempt, the parsed spec or the token-streamed assembly JSON, and
    // per-part STLs — each part drops into the viewport as the backend places it.
    const onCadLive: api.CadLiveFn = (live) => {
      updateTask(task.id, { stage: live.stage, elapsed: live.elapsed });
      if (live.newParts) {
        for (const pt of live.newParts) {
          if (pt.revised) livePartsRef.current = livePartsRef.current.map((x) => (x.name === pt.name ? pt : x));
          else livePartsRef.current = [...livePartsRef.current.filter((x) => x.name !== pt.name), pt];
          try { VP.addConstructionPart(pt.name, pt.stl_b64, !!pt.revised); } catch { /* bad STL chunk — skip */ }
        }
      }
      setTheater((t) => ({
        ...t,
        specStream: live.specStream ?? t.specStream,
        specObj: live.spec ?? t.specObj,
        assembly: live.assembly ?? t.assembly,
        attempt: live.attempt ?? t.attempt,
        partNames: live.newParts ? livePartsRef.current.map((x) => x.name) : t.partNames,
      }));
    };

    const done = (m: Model) => {
      VP.flash(m.status === "verified" ? 0x37d67a : 0xe0a63a, 620);
      updateTask(task.id, { running: false, done: true, stage: m.status === "verified" ? "verified" : "finished with fails", modelId: m.id });
      finishModel(m);
    };
    const fail = (err: any) => {
      const msg = String(err?.message || err);
      updateTask(task.id, { running: false, done: false, error: msg, stage: "error" });
      setResultError(msg);
      setPhase("error");
    };

    if (engine === "mesh") {
      const namePromise = api.cadName(p || "concept image asset");   // parallel, best-effort
      const run = imageB64
        ? api.image2mesh(imageB64, TIER_LABEL[tier], multiview, onProgress, undefined, p)
        : api.text2mesh(p, TIER_LABEL[tier], multiview, onProgress);
      run.then(async (res) => {
        const nice = (await namePromise) || name;
        if (nice !== name) updateTask(task.id, { name: nice });
        await VP.revealGlb(res.glb_b64);   // the reconstruction moment: un-clip bottom → top
        const rep: any = res.report;
        // The Track B gate returns REAL verifier rows (M1..M10 mesh checks, W* texture checks) —
        // that's the verification card's evidence. Fall back to a report summary if absent.
        const gateRows: any[] = rep?.gate?.rows || [];
        const inspection: api.CadRow[] = gateRows.length
          ? gateRows.map((r: any) => ({
              name: r.name, expected: r.expected, measured: r.measured, delta: null,
              within_tol: !!r.within_tol,
              category: /^W|texture|POT/i.test(r.name) ? "uv" : "structural",
            }))
          : [
              { name: "Watertight", expected: "true", measured: String(rep.watertight), delta: null, within_tol: !!rep.watertight, category: "structural" },
              { name: "Triangle count", expected: "—", measured: String(rep.faces), delta: null, within_tol: true, category: "budget" },
              { name: "PBR channels", expected: "textured", measured: (rep.pbr || []).join(", ") || "none", delta: null, within_tol: (rep.pbr || []).length > 0, category: "render" },
            ];
        inspection.push(
          { name: "Triangle count", expected: "—", measured: rep.faces?.toLocaleString?.() || String(rep.faces), delta: null, within_tol: true, category: "budget" },
          { name: "PBR channels", expected: "textured", measured: (rep.pbr || []).join(", ").replace(/Texture/g, "") || "none", delta: null, within_tol: (rep.pbr || []).length > 0, category: "render" },
          { name: "File size", expected: "—", measured: (rep.size_mb ?? 0).toFixed(1) + " MB", delta: null, within_tol: true, category: "budget" },
        );
        const passed = rep?.gate ? !!rep.gate.passed : !!rep.watertight;
        setAttempts([{ n: 1, fails: inspection.filter((r) => !r.within_tol).length, status: passed ? "passed" : "failed" }]);
        done({
          id: uid(), name: nice, prompt: p || "Image to 3D", project: activeProject, engine: "mesh",
          status: passed ? "verified" : "failed", ts: Date.now(),
          glbId: uid(), glb: res.glb_b64, report: rep, inspection, tier, seconds: res.seconds,
        });
      }).catch(fail);
    } else {
      const route = engine === "assembly" ? "/plan" : "/generate";
      api.cadRun(route, { prompt: p }, onCadLive).then((j) => {
        const nice = j.display_name || name;
        if (nice !== name) updateTask(task.id, { name: nice });
        const atts = attemptsFromHistory(j.history, j.passed, j.attempts);
        setAttempts(atts);
        // Assemblies constructed live keep their per-part meshes (real per-part visibility) and
        // get the slow showpiece replay; otherwise fall back to the fused STL the verifier measured.
        if (engine === "assembly" && VP.constructionCount() > 0) VP.replayConstruction();
        else if (j.mesh_stl_b64) VP.loadStl(j.mesh_stl_b64);
        done({
          id: uid(), name: nice, prompt: p, project: activeProject, engine,
          status: j.passed ? "verified" : "failed", ts: Date.now(),
          stl: j.mesh_stl_b64, step: j.step_b64, code: j.code, spec: j.spec,
          assembly: (j as any).assembly, inspection: j.inspection || [],
          attempts: j.attempts, history: j.history, seconds: j.seconds,
          parts: livePartsRef.current.length ? livePartsRef.current : undefined,
        });
      }).catch(fail);
    }
  }, [prompt, track, cadKind, meshTier, activeProject, go, showToast, updateTask, finishModel, resetTheater]);

  const reGenerate = useCallback(() => {
    const lr = lastRun.current;
    if (!lr && current) {
      setTrack(current.engine === "mesh" ? "mesh" : "cad");
      setCadKind(current.engine === "assembly" ? "assembly" : "part");
      startGenerate({ prompt: current.prompt });
      return;
    }
    if (!lr) { showToast("Nothing to regenerate yet"); return; }
    setTrack(lr.track); setCadKind(lr.cadKind); setMeshTier(lr.meshTier);
    startGenerate({ prompt: lr.prompt, imageB64: lr.imageB64, multiview: lr.multiview });
  }, [current, startGenerate, showToast]);

  /** Parametric edit from the editor bar. Assemblies use the real /edit route; parts re-run
   * /generate with the instruction appended to the original prompt (no part-edit route yet). */
  const editInstruction = useCallback((instruction: string) => {
    const m = current;
    if (!m) { showToast("Open a model first"); return; }
    if (!instruction.trim()) return;
    if (m.engine === "assembly" && m.assembly) {
      const task: Task = { id: uid(), name: titleFromPrompt(instruction), engine: "assembly", stage: "applying edit", elapsed: 0, estSec: 90, running: true, done: false };
      setTasks((ts) => [task, ...ts].slice(0, 8));
      setLiveTask(task);
      setAttempts([]); setResultError(null); setPhase("running");
      resetTheater();
      VP.beginConstruction();
      go("result");
      const onLive: api.CadLiveFn = (live) => {
        updateTask(task.id, { stage: live.stage, elapsed: live.elapsed });
        if (live.newParts) {
          for (const pt of live.newParts) {
            if (pt.revised) livePartsRef.current = livePartsRef.current.map((x) => (x.name === pt.name ? pt : x));
            else livePartsRef.current = [...livePartsRef.current.filter((x) => x.name !== pt.name), pt];
            try { VP.addConstructionPart(pt.name, pt.stl_b64, !!pt.revised); } catch { /* skip bad chunk */ }
          }
        }
        setTheater((t) => ({
          ...t, specStream: live.specStream ?? t.specStream, assembly: live.assembly ?? t.assembly,
          attempt: live.attempt ?? t.attempt,
          partNames: live.newParts ? livePartsRef.current.map((x) => x.name) : t.partNames,
        }));
      };
      api.cadRun("/edit", { assembly: m.assembly, instruction }, onLive)
        .then((j) => {
          setAttempts(attemptsFromHistory(j.history, j.passed, j.attempts));
          if (VP.constructionCount() > 0) VP.replayConstruction();
          else if (j.mesh_stl_b64) VP.loadStl(j.mesh_stl_b64);
          const nm: Model = {
            ...m, id: uid(), name: m.name, prompt: m.prompt + " · " + instruction, ts: Date.now(),
            status: j.passed ? "verified" : "failed", stl: j.mesh_stl_b64, step: j.step_b64,
            assembly: (j as any).assembly, inspection: j.inspection || [], history: j.history,
            parts: livePartsRef.current.length ? livePartsRef.current : m.parts,
          };
          updateTask(task.id, { running: false, done: true, stage: j.passed ? "verified" : "finished with fails", modelId: nm.id });
          finishModel(nm);
        })
        .catch((e) => { updateTask(task.id, { running: false, error: String(e?.message || e), stage: "error" }); setResultError(String(e?.message || e)); setPhase("error"); });
    } else {
      setTrack(m.engine === "mesh" ? "mesh" : "cad");
      setCadKind("part");
      startGenerate({ prompt: (m.prompt ? m.prompt + "; " : "") + instruction });
    }
  }, [current, go, showToast, startGenerate, updateTask, finishModel, resetTheater]);

  /* ---------- library actions ---------- */
  const showModel = useCallback((m: Model, where: "result" | "editor") => {
    setCurrent(m);
    setResultError(null);
    setAttempts(attemptsFromHistory(m.history, m.status === "verified", m.attempts));
    setPhase("done");
    if (m.parts && m.parts.length) {
      // saved per-part assembly — the slow construction replay, same as fresh generations
      VP.beginConstruction();
      m.parts.forEach((pt) => { try { VP.addConstructionPart(pt.name, pt.stl_b64); } catch { /* skip */ } });
      VP.replayConstruction();
    } else if (m.glb) VP.loadGlb(m.glb);
    else if (m.stl) VP.loadStl(m.stl);
    else VP.loadPlaceholder();
    if (m.engine === "assembly" && !(m.parts && m.parts.length)) VP.playAssembleEntrance();
    go(where);
  }, [go]);

  /** List responses are light (no meshes) — hydrate the artifacts from the server on first open.
   * Hydration over the tunnel takes seconds for hero meshes, so a themed loading overlay covers it. */
  const [modelLoading, setModelLoading] = useState<Model | null>(null);
  const loadEx = useExit(!!modelLoading, 150);
  const lastLoad = useRef<Model | null>(null);
  if (modelLoading) lastLoad.current = modelLoading;
  const openModel = useCallback((m: Model, where: "result" | "editor") => {
    const hydrated = !!(m.stl || m.glb || (m.parts && m.parts.length));
    if (hydrated) { showModel(m, where); return; }
    setModelLoading(m);
    api.studio.model(m.id)
      .then((full) => {
        const fm = { ...m, ...fromServer(full) };
        setLibrary((lib) => lib.map((x) => (x.id === m.id ? fm : x)));
        showModel(fm, where);
      })
      .catch(() => showModel(m, where))   // metadata-only view is still useful
      .finally(() => setModelLoading(null));
  }, [showModel]);

  const deleteModel = useCallback((id: string) => {
    setLibrary((lib) => lib.filter((m) => m.id !== id));
    api.studio.deleteModel(id).catch(() => {});
    showToast("Model removed");
  }, [showToast]);

  const deleteProject = useCallback((name: string) => {
    if (name === "My Project") { showToast("The default project can't be deleted"); return; }
    setLibrary((lib) => lib.filter((m) => m.project !== name));
    setProjectNames((ns) => ns.filter((n) => n !== name));
    setActiveProject((cur) => (cur === name ? "My Project" : cur));
    api.studio.deleteProject(name).catch(() => {});
    showToast(`Project "${name}" deleted`);
  }, [showToast]);

  const newProject = useCallback((name?: string) => {
    setProjectNames((ns) => {
      const nm = (name || "").trim() || "Project " + (ns.length + 1);
      if (ns.includes(nm)) { setActiveProject(nm); return ns; }
      api.studio.createProject(nm).catch(() => {});
      setActiveProject(nm);
      showToast(`${nm} created — new generations land here`);
      return [...ns, nm];
    });
  }, [showToast]);

  const openProject = useCallback((name: string) => { setActiveProject(name); go("project", "projects"); }, [go]);
  const selectProject = useCallback((name: string) => { setActiveProject(name); }, []);

  /** Move a model between projects — optimistic local move + light server PATCH. */
  const assignProject = useCallback((modelId: string, project: string) => {
    setLibrary((lib) => lib.map((m) => (m.id === modelId ? { ...m, project } : m)));
    setCurrent((c) => (c && c.id === modelId ? { ...c, project } : c));
    setProjectNames((ns) => (ns.includes(project) ? ns : [...ns, project]));
    api.studio.updateModel(modelId, { project }).catch((e) =>
      showToast("Move failed to sync: " + (e?.message || e)));
    showToast(`Moved to ${project}`);
  }, [showToast]);

  /* ---------- auth ---------- */
  const signIn = useCallback(async (email: string, password: string): Promise<string | null> => {
    setAuthBusy(true);
    try {
      const r = await api.studio.login(email, password);
      api.setToken(r.token);
      setUser(r.user);
      await loadUserData();
        migrateInBackground();   // fire-and-forget — never blocks auth
      go("dashboard", "dashboard");
      return null;
    } catch (e: any) {
      return String(e?.message || "sign-in failed");
    } finally { setAuthBusy(false); }
  }, [go, loadUserData]);

  const signUp = useCallback(async (d: { email: string; password: string; first: string; last: string }): Promise<string | null> => {
    setAuthBusy(true);
    try {
      const r = await api.studio.signup(d.email, d.password, d.first, d.last);
      api.setToken(r.token);
      setUser(r.user);
      await loadUserData();
        migrateInBackground();   // fire-and-forget — never blocks auth
      go("dashboard", "dashboard");
      return null;
    } catch (e: any) {
      return String(e?.message || "sign-up failed");
    } finally { setAuthBusy(false); }
  }, [go, loadUserData]);

  const signOut = useCallback(() => {
    api.studio.logout();
    api.setToken(null);
    setUser(null);
    setLibrary([]);
    setProjectNames(["My Project"]);
    setActiveProject("My Project");
    setCurrent(null);
    go("login");
  }, [go]);

  const updateUser = useCallback(async (patch: Partial<User> & { password?: string }) => {
    const r = await api.studio.updateMe(patch);
    setUser(r.user);
  }, []);

  const studio: Studio = useMemo(() => ({
    screen, nav, go,
    user, authBusy, signIn, signUp, signOut, updateUser,
    track, setTrack, cadKind, setCadKind, meshTier, setMeshTier, prompt, setPrompt,
    engines, tasks, startGenerate,
    library, projects: projectNames, activeProject, openProject, selectProject, newProject, assignProject, deleteModel, deleteProject,
    current, liveTask, openModel, reGenerate, editInstruction,
    toast, showToast, genModalOpen, setGenModalOpen,
  }), [screen, nav, go, user, authBusy, signIn, signUp, signOut, updateUser, track, cadKind, meshTier, prompt, engines,
       tasks, startGenerate, library, projectNames, activeProject, openProject, selectProject, newProject, assignProject, deleteModel, deleteProject,
       current, liveTask, openModel, reGenerate, editInstruction, toast, showToast, genModalOpen]);

  const isShell = screen === "dashboard" || screen === "projects" || screen === "project" || screen === "settings" || screen === "docs";

  return (
    <StudioCtx.Provider value={studio}>
      <div id="mlk">
        <IconDefs />

        {/* Persistent 3D viewport */}
        <div id="mlk-vp" ref={vpRef} style={sx("position:absolute; inset:0; z-index:0; background:radial-gradient(120% 120% at 50% 42%, #141416 0%, #0b0b0c 78%);")} />

        {isShell && <Shell />}
        {screen === "editor" && <Editor />}
        {screen === "result" && <Result phase={phase} attempts={attempts} error={resultError} theater={theater} />}
        {screen === "login" && <Login />}
        {genModalEx.mounted && <GenerateModal closing={genModalEx.closing} />}

        {/* Model hydration overlay — content-shaped skeleton while artifacts stream in */}
        {loadEx.mounted && (
          <div {...(loadEx.closing ? { "data-closing": "", "data-exit": "fade" } : {})}
            style={sx("position:absolute; inset:0; z-index:60; background:rgba(6,6,7,.62); backdrop-filter:blur(4px); display:flex; align-items:center; justify-content:center; animation:mlk-backdrop .18s ease;")}>
            <div style={sx("position:relative; width:380px; max-width:90vw; background:var(--panel); border:1px solid var(--border-2); clip-path:polygon(0 0,100% 0,100% calc(100% - 16px),calc(100% - 16px) 100%,0 100%); padding:24px 26px 26px; box-shadow:0 30px 80px rgba(0,0,0,.5); animation:mlk-cutin .34s cubic-bezier(.25,.7,.25,1) both, mlk-rise .25s var(--ease-out) both;")}>
              <div style={sx("display:flex; align-items:center; gap:12px;")}>
                <span style={sx("width:20px; height:20px; flex-shrink:0; border:2px solid rgba(255,255,255,.16); border-top-color:var(--accent,#4d9eff); border-radius:50%; animation:mlk-spin .8s linear infinite;")} />
                <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:13px; letter-spacing:.09em; color:#fff;")}>LOADING MODEL</span>
                <span style={sx("margin-left:auto; padding:3px 9px; border:1px solid var(--border-2); border-radius:4px; font-family:'Spline Sans Mono',monospace; font-size:9.5px; letter-spacing:.07em; color:var(--text-2); text-transform:uppercase;")}>{lastLoad.current?.engine}</span>
              </div>
              <div style={sx("margin-top:12px; font-size:15.5px; font-weight:600; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{lastLoad.current?.name}</div>
              {/* skeleton: viewport block + inspection lines, shaped like the editor it becomes */}
              <div className="sk" style={sx("margin-top:14px; height:72px; border-radius:6px;")} />
              <div style={sx("display:flex; flex-direction:column; gap:7px; margin-top:12px;")}>
                <div className="sk" style={sx("height:9px; width:82%;")} />
                <div className="sk" style={sx("height:9px; width:64%;")} />
                <div className="sk" style={sx("height:9px; width:43%;")} />
              </div>
            </div>
          </div>
        )}

        {/* Report a bug — the corner critter: a bug crawls the bottom-right corner and constructs
            into the button when the cursor comes near (BugFab; never blocks clicks while roaming) */}
        <BugFab onReport={() => setBugOpen(true)} />
        {bugEx.mounted && (
          <BugReport closing={bugEx.closing} onClose={() => setBugOpen(false)}
            onDone={() => { setBugOpen(false); showToast("Got it \u2014 I\u2019ll take a look. \u2014 Tete"); }}
            context={{ screen, model: current?.name, engine: current?.engine, modelId: current?.id }} />
        )}

        {/* Toast (global) — positioning lives on the wrapper so enter/exit transforms can't
            fight the translateX(-50%) centering */}
        {toastEx.mounted && (
          <div style={sx("position:absolute; left:50%; bottom:92px; transform:translateX(-50%); z-index:70; pointer-events:none;")}>
            <div {...(toastEx.closing ? { "data-closing": "" } : {})}
              style={sx("padding:11px 20px; background:var(--panel-2); border:1px solid var(--border-2); border-left:2px solid var(--accent,#4d9eff); color:var(--text); clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:500; letter-spacing:.06em; box-shadow:0 10px 30px rgba(0,0,0,.4); animation:mlk-pop var(--dur-2) var(--ease-out);")}>
              {toast || lastToast.current}
            </div>
          </div>
        )}
      </div>
    </StudioCtx.Provider>
  );
}
