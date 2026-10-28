/* Editor — persistent-viewport screen with the left tool rail (Parameters / Suggestions /
 * Component Parts / Measurements / Share / Export / lighting), cut-corner flyout panels, and the
 * collapsible editor prompt bar. EDIT is wired to the real backend: assemblies → POST /api/cad/edit
 * {assembly, instruction}; parts → /generate re-run with the instruction appended (no part-edit
 * route yet). FILE loads a local GLB/STL into the viewport. */
import { useEffect, useRef, useState } from "react";
import { useExit } from "../motion";
import { sx } from "../sx";
import { I } from "../icons";
import { toServer, useStudio } from "../store";
import { VP } from "../viewport";
import { downloadB64, fileToB64 } from "../gltf";
import * as api from "../api";

type ToolKey = "parameters" | "display" | "suggestions" | "parts" | "measurements" | "share" | "export" | "bulb" | "rig" | "animate";

const PANEL = "background:var(--panel-2); border:1px solid var(--border-2); clip-path:polygon(0 0,100% 0,100% calc(100% - 16px),calc(100% - 16px) 100%,0 100%); animation:mlk-cutin .34s cubic-bezier(.25,.7,.25,1) both, mlk-flyout .24s var(--ease-out) both;";
const PANEL_HEAD = "display:flex; align-items:center; justify-content:space-between; padding:14px 14px 12px 16px;";
const PANEL_TITLE = "font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:600; font-size:18px; color:#fff;";
const CLOSE_BTN = "width:28px; height:28px; border:none; border-radius:6px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;";

const tglTrack = (on: boolean) =>
  sx("position:relative;width:42px;height:23px;border-radius:12px;border:none;cursor:pointer;transition:background .2s;flex-shrink:0;background:" +
    (on ? "var(--accent,#4d9eff)" : "rgba(255,255,255,.16)") + ";");
const tglKnob = (on: boolean) =>
  sx("position:absolute;top:2.5px;left:2.5px;width:18px;height:18px;border-radius:50%;background:#fff;transition:transform .2s;transform:translateX(" + (on ? "19px" : "0") + ");");

function PanelClose({ onClose }: { onClose: () => void }) {
  return (
    <button data-press data-iconbtn onClick={onClose} title="Close" style={sx(CLOSE_BTN)}>
      <I k="close" size={18} />
    </button>
  );
}

export function Editor() {
  const st = useStudio();
  const m = st.current;
  const [tool, setTool] = useState<ToolKey | null>(null);
  /* flyouts play an exit before unmounting; while closing we keep rendering the last tool */
  const flyEx = useExit(tool !== null);
  const lastTool = useRef<ToolKey | null>(null);
  if (tool) lastTool.current = tool;
  const shownTool = tool ?? (flyEx.closing ? lastTool.current : null);
  const flyProps = flyEx.closing ? { "data-closing": "", "data-exit": "flyout" } : {};
  const [warm, setWarm] = useState(VP.getWarm());
  const [editorPrompt, setEditorPrompt] = useState("");
  const [editorOpen, setEditorOpen] = useState(true);
  const [params, setParams] = useState([19.7, 95.0, 8.0, 12.0]);
  const [suggest, setSuggest] = useState<Record<string, boolean>>({ Structural: true, Fit: true, Aesthetic: true, Manufacture: true, Functional: true });
  const [showSug, setShowSug] = useState(true);
  const [partsHidden, setPartsHidden] = useState<Record<string, boolean>>({});
  const [partsRemoved, setPartsRemoved] = useState<Record<string, boolean>>({});
  const [partsCollapsed, setPartsCollapsed] = useState(false);
  const [unit, setUnit] = useState<"MM" | "CM" | "M">("MM");
  const [renderMode, setRenderMode] = useState<"solid" | "wire" | "xray">(VP.getRenderMode());
  const [explode, setExplode] = useState(VP.getExplode());
  const [section, setSection] = useState(VP.getSection());
  const [showExtents, setShowExtents] = useState(false);
  const [exportFormat, setExportFormat] = useState("GLB");
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [shareLink, setShareLink] = useState<string | null>(null);
  const [target, setTarget] = useState<string>("Entire Object");
  const fileRef = useRef<HTMLInputElement>(null);
  // mesh pipeline: rig + animate (state survives tool switches; re-syncs when another model opens)
  const [rigging, setRigging] = useState(false);
  const [rigged, setRigged] = useState<boolean>(!!(m as any)?.rigged);
  const [rigReport, setRigReport] = useState<any>((m as any)?.rigReport || null);
  const [animPrompt, setAnimPrompt] = useState("");
  const [animMp4, setAnimMp4] = useState<{ b64: string; name: string } | null>(null);
  const [animBusy, setAnimBusy] = useState(false);
  const [animStage, setAnimStage] = useState<string | null>(null);
  const [skelOn, setSkelOn] = useState(false);
  const mp4Ref = useRef<HTMLInputElement>(null);
  useEffect(() => { setRigged(!!(m as any)?.rigged); setRigReport((m as any)?.rigReport || null); setSkelOn(false); }, [m?.id]);
  useEffect(() => () => { VP.setSkeleton(false); }, []);   // never leave the overlay behind on exit
  const toggleSkeleton = (on: boolean) => {
    if (on && !VP.setSkeleton(true)) { st.showToast("No skeleton in the loaded model — re-open it (the rigged GLB loads on open)"); return; }
    if (!on) VP.setSkeleton(false);
    setSkelOn(on);
  };

  const doRig = async () => {
    if (!m?.glb || rigging || rigged) return;
    setRigging(true);
    st.showToast("Rigging — skeleton + skin weights (~2 min)");
    try {
      const res = await api.rig(m.glb);
      if (res.passed && res.glb_b64) {
        m.glb = res.glb_b64; (m as any).rigged = true; (m as any).rigReport = res.rig_report;
        api.studio.saveModel(toServer(m)).catch(() => { });
        await VP.revealGlb(res.glb_b64);
        setRigged(true); setRigReport(res.rig_report);
        if (VP.setSkeleton(true)) setSkelOn(true);   // show the fresh skeleton immediately — the payoff moment
        st.showToast(`Rigged ✓ ${res.rig_report?.bones ?? "?"} bones — skeleton shown in the viewport`);
      } else {
        const bad = (res.rig_report?.rows || []).filter((r: any) => !r.within_tol).map((r: any) => r.name).join(", ");
        setRigReport(res.rig_report || null);
        st.showToast("Rig gate failed (" + (bad || res.error || "unknown") + ") — original kept");
      }
    } catch (e: any) { st.showToast("Rig failed: " + (e?.message || e)); }
    setRigging(false);
  };

  const doAnimate = async () => {
    if (!m?.glb || animBusy) return;
    if (!rigged) { st.showToast("Rig the model first — Auto-Rig is one tool up"); setTool("rig"); return; }
    if (!animMp4 && !animPrompt.trim()) { st.showToast("Describe the motion or drop a reference MP4"); return; }
    setAnimBusy(true);
    st.showToast(animMp4 ? "Extracting motion from your video… (up to ~1h — keep this tab open)"
                         : "Generating motion video → retargeting onto the rig… (up to ~1h — keep this tab open)");
    try {
      const res = await api.animateClip(m.glb, animMp4 ? { mp4B64: animMp4.b64 } : { prompt: animPrompt.trim() },
        (stage, elapsed) => setAnimStage(`${stage} · ${Math.floor(elapsed / 60)}m${String(elapsed % 60).padStart(2, "0")}s`));
      if (res.glb_b64) {
        m.glb = res.glb_b64; (m as any).animated = true;
        api.studio.saveModel(toServer(m)).catch(() => { });
        await VP.revealGlb(res.glb_b64);
        st.showToast("Animation clip embedded ✓ — plays in any engine");
      } else {
        st.showToast("Animation failed: " + (res.error || "no clip returned"));
      }
    } catch (e: any) {
      const msg = String(e?.message || e);
      st.showToast(msg.includes("not found") ? "Animation engine is in final assembly — your rig is ready for it" : "Animation failed: " + msg);
    }
    setAnimBusy(false);
    setAnimStage(null);
  };

  useEffect(() => {
    VP.onPick = (name) => setTarget(name || "Entire Object");
    return () => { VP.onPick = null; VP.setExtents(false); };
  }, []);
  useEffect(() => { VP.setExtents(showExtents); }, [showExtents]);

  const partNames = VP.partNames().filter((n) => !partsRemoved[n]);
  const measured = VP.extentsMm();
  const unitDiv = unit === "MM" ? 1 : unit === "CM" ? 10 : 1000;
  const fmtExt = (v: number) => (v / unitDiv).toFixed(unit === "MM" ? 1 : 2);

  const isMesh = m?.engine === "mesh";
  // meshes get their OWN rail: no parametric tools (a mesh is final geometry), but first-class
  // RIG + ANIMATE — the game-dev pipeline lives in the editor, same bar language as CAD.
  const toolMeta: { k: ToolKey; icon: string; title: string; divider?: boolean }[] = isMesh ? [
    { k: "display", icon: "eye", title: "Display" },
    { k: "measurements", icon: "ruler", title: "Measurements" },
    { k: "rig", icon: "bone", title: "Auto-Rig", divider: true },
    { k: "animate", icon: "play", title: "Animate" },
    { k: "share", icon: "share", title: "Share", divider: true },
    { k: "export", icon: "pkg", title: "Export" },
    { k: "bulb", icon: "bulb", title: "Controls & lighting", divider: true },
  ] : [
    { k: "parameters", icon: "sliders", title: "Parameters" },
    { k: "display", icon: "eye", title: "Display" },
    { k: "suggestions", icon: "suggest", title: "Suggestions", divider: true },
    { k: "parts", icon: "parts", title: "Component Parts" },
    { k: "measurements", icon: "ruler", title: "Measurements" },
    { k: "share", icon: "share", title: "Share", divider: true },
    { k: "export", icon: "pkg", title: "Export" },
    { k: "bulb", icon: "bulb", title: "Controls & lighting", divider: true },
  ];
  const toolBase = "width:44px;height:44px;border:none;border-radius:8px;display:flex;align-items:center;justify-content:center;cursor:pointer;background:transparent;transition:background .15s,color .15s;";
  const toolClick = (k: ToolKey) => {
    setTool((t) => (t === k ? null : k));
    setExportMenuOpen(false);
  };

  const startParamDrag = (i: number, e: React.PointerEvent) => {
    e.preventDefault();
    const track = e.currentTarget as HTMLElement;
    const rect = track.getBoundingClientRect();
    const ranges: [number, number][] = [[0, 36], [0, 210], [0, 8.7], [0, 60]];
    const set = (cx: number) => {
      let t = (cx - rect.left) / rect.width;
      t = Math.max(0, Math.min(1, t));
      const [mn, mx] = ranges[i];
      const v = mn + t * (mx - mn);
      setParams((p) => { const n = [...p]; n[i] = v; return n; });
      if (i === 0) VP.setParamScale(v / 36);
    };
    set(e.clientX);
    const mv = (ev: PointerEvent) => set(ev.clientX);
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  };

  const doExport = () => {
    const nameBase = (m?.name || "model").toLowerCase().replace(/\s+/g, "-");
    if (exportFormat === "GLB" && m?.glb) downloadB64(m.glb, nameBase + ".glb", "model/gltf-binary");
    else if (exportFormat === "STL" && m?.stl) downloadB64(m.stl, nameBase + ".stl", "model/stl");
    else if (exportFormat === "STEP" && m?.step) downloadB64(m.step, nameBase + ".step", "application/step");
    else if (exportFormat === "CODE" && m?.code) {
      const blob = new Blob([m.code], { type: "text/x-python" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = nameBase + ".py"; a.click();
    } else { st.showToast(`No ${exportFormat} artifact on this model`); return; }
    st.showToast(`Exported ${nameBase}.${exportFormat.toLowerCase()}`);
    setExportMenuOpen(false);
  };

  const onFile = async (f: File | null) => {
    if (!f) return;
    const b64 = await fileToB64(f);
    try {
      if (/\.stl$/i.test(f.name)) VP.loadStl(b64);
      else await VP.loadGlb(b64);
      st.showToast(`Loaded ${f.name} into the viewport`);
    } catch { st.showToast("Could not parse that file (GLB or STL)"); }
  };

  const sMeta: [string, string][] = [["Structural", "#3b9de8"], ["Fit", "#9b7bff"], ["Aesthetic", "#37c26f"], ["Manufacture", "#f0736e"], ["Functional", "#b6e84d"]];
  const chkStyle = (on: boolean) =>
    sx("width:26px;height:26px;border-radius:6px;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:background .15s,border-color .15s;" +
      (on ? "border:none;background:var(--accent,#4d9eff);" : "border:1.5px solid var(--border-2);background:transparent;"));
  const uSeg = (u: string) =>
    sx("padding:6px 15px;border:none;font-family:'Spline Sans Mono',monospace;font-size:12px;font-weight:500;letter-spacing:.05em;cursor:pointer;transition:background .15s,color .15s;" +
      (u === unit ? "background:var(--accent,#4d9eff);color:var(--on-accent,#06111c);" : "background:transparent;color:var(--text-2);"));

  return (
    <div style={sx("position:absolute; inset:0; z-index:3; pointer-events:none; animation:mlk-fade .3s ease;")}>
      <input ref={fileRef} type="file" accept=".glb,.stl" style={{ display: "none" }}
        onChange={(e) => onFile(e.target.files?.[0] || null)} />

      <div style={sx("position:absolute; left:22px; top:18px; pointer-events:auto;")}>
        <span style={sx("display:inline-flex; clip-path:var(--notch); background:var(--border-2);")}>
          <button data-press onClick={() => st.go("dashboard", "dashboard")}
            style={sx("clip-path:var(--notch); margin:1px; display:flex; align-items:center; gap:9px; padding:11px 18px 11px 14px; border:none; background:var(--inset); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.09em; cursor:pointer;")}>
            <I k="chev-left" size={17} /><span data-ulw>BACK</span>
          </button>
        </span>
      </div>

      <div style={sx("position:absolute; left:50%; top:25px; transform:translateX(-50%); font-size:16.5px; color:var(--text);")}>{m?.name || "Viewer"}</div>

      <div style={sx("position:absolute; right:22px; top:18px; display:flex; align-items:center; gap:13px; pointer-events:auto;")}>
        <button data-press className="hv-accentborder" onClick={() => st.go("settings", "settings")}
          style={sx("display:flex; align-items:center; gap:8px; padding:6px 6px 6px 7px; border:1px solid var(--border-2); border-radius:5px; background:rgba(0,0,0,.35); color:var(--text-2); cursor:pointer;")}>
          <span style={sx("width:30px; height:30px; border-radius:5px; background:linear-gradient(140deg,#3a3a40,#1c1c20); display:flex; align-items:center; justify-content:center; font-family:'Spline Sans Mono',monospace; font-size:13px; color:#fff;")}>
            {(st.user?.first?.[0] || "U").toUpperCase()}
          </span>
          <I k="chev-down" size={16} />
        </button>
        <span style={sx("display:inline-flex; clip-path:var(--notch); background:var(--border-2);")}>
          <button data-press onClick={() => st.go("dashboard", "dashboard")}
            style={sx("clip-path:var(--notch); margin:1px; padding:11px 18px; border:none; background:var(--inset); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.09em; cursor:pointer;")}>
            <span data-ulw>NEW GENERATION</span>
          </button>
        </span>
      </div>

      {/* Editor prompt panel — parametric edits only exist for CAD; a mesh is final geometry,
          so the edit box is hidden entirely when a mesh is open (viewer-only). */}
      {m?.engine !== "mesh" && (
      <div style={sx("position:absolute; left:50%; top:70px; transform:translateX(-50%); width:min(864px, calc(100vw - 130px)); pointer-events:auto; background:var(--panel); border:1px solid var(--border-2); border-radius:7px; box-shadow:0 22px 64px rgba(0,0,0,.5);")}>
        <div style={sx("display:flex; align-items:center; gap:12px; padding:15px 18px;")}>
          <I k="editor" size={21} style={{ color: "var(--text)" }} />
          <span style={sx("font-size:17.5px; font-weight:600; color:#fff;")}>Editor</span>
          <span style={sx("padding:5px 11px; clip-path:var(--notch); background:var(--accent,#4d9eff); color:var(--on-accent,#06111c); font-size:13px; font-weight:600;")}>Target: {target}</span>
          <div style={{ flex: 1 }} />
          <button data-press className="hv-panel2" onClick={() => setEditorOpen((o) => !o)}
            style={sx("width:30px; height:30px; border:none; border-radius:5px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
            <svg width="18" height="18" viewBox="0 0 24 24" style={{ transition: "transform .2s", transform: editorOpen ? "rotate(0deg)" : "rotate(180deg)" }}><use href="#i-chev-up" /></svg>
          </button>
        </div>
        {editorOpen && (
          <div style={sx("padding:0 18px 17px;")}>
            <textarea value={editorPrompt} onChange={(e) => setEditorPrompt(e.target.value)}
              placeholder={m?.engine === "assembly" ? 'Edit the assembly, e.g. "make the legs 20 mm longer"' : "Enter a prompt to edit the model"}
              style={sx("width:100%; min-height:92px; padding:15px; border:1px solid var(--border); background:var(--inset); color:var(--text); border-radius:4px; font-size:16px; line-height:1.5;")} />
            <div style={sx("display:grid; grid-template-columns:1fr 1fr 1fr 1.2fr; gap:11px; margin-top:14px;")}>
              <button data-soon title="Coming soon"
                style={sx("display:flex; align-items:center; justify-content:center; gap:10px; padding:13px; border:1px solid var(--border-2); background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:13px; letter-spacing:.08em;")}>
                <span className="soon-normal" style={sx("display:flex; align-items:center; gap:10px;")}><I k="image" size={19} style={{ color: "var(--text-2)" }} />IMAGE</span>
                <span className="soon-hover">COMING SOON</span>
              </button>
              <button data-soon title="Coming soon"
                style={sx("display:flex; align-items:center; justify-content:center; gap:10px; padding:13px; border:1px solid var(--border-2); background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:13px; letter-spacing:.08em;")}>
                <span className="soon-normal" style={sx("display:flex; align-items:center; gap:10px;")}><I k="mesh" size={19} style={{ color: "var(--text-2)" }} />MESH</span>
                <span className="soon-hover">COMING SOON</span>
              </button>
              <button data-press onClick={() => fileRef.current?.click()}
                style={sx("display:flex; align-items:center; justify-content:center; gap:10px; padding:13px; border:1px solid var(--border-2); background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:13px; letter-spacing:.08em; cursor:pointer;")}>
                <I k="clip" size={19} style={{ color: "var(--text-2)" }} /><span data-ulw>FILE</span>
              </button>
              <button data-press data-primary onClick={() => { st.editInstruction(editorPrompt); setEditorPrompt(""); }}
                style={sx("padding:13px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:13px; letter-spacing:.1em; cursor:pointer;")}>
                <span data-ulw>EDIT</span>
              </button>
            </div>
          </div>
        )}
      </div>
      )}

      {/* tool rail */}
      <div style={sx("position:absolute; left:16px; top:50%; transform:translateY(-50%); pointer-events:auto; display:flex; flex-direction:column; align-items:center; gap:6px; padding:10px 7px; background:rgba(15,15,17,.7); border:1px solid var(--border); border-radius:9px; backdrop-filter:blur(8px);")}>
        {toolMeta.map((t) => {
          const active = tool === t.k;
          return (
            <span key={t.k} style={{ display: "contents" }}>
              {t.divider && <div style={sx("height:1px; width:24px; background:var(--border-2); margin:6px 0;")} />}
              <button data-press data-seg {...(active ? { "data-on": "" } : {})} onClick={() => toolClick(t.k)} title={t.title}
                style={sx(toolBase + (active ? "background:var(--accent,#4d9eff);color:var(--on-accent,#06111c);clip-path:var(--notch);" : "color:var(--text-2);"))}>
                <I k={t.icon} size={22} />
              </button>
            </span>
          );
        })}
      </div>

      {/* flyout panels */}
      <div style={sx("position:absolute; left:80px; top:50%; transform:translateY(-50%); pointer-events:auto; z-index:5;")}>

        {shownTool === "parameters" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 266 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Parameters</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 18px;")}>
              {params.map((v, i) => {
                const ranges: [number, number][] = [[0, 36], [0, 210], [0, 8.7], [0, 60]];
                const [mn, mx] = ranges[i];
                const pct = Math.max(0, Math.min(100, ((v - mn) / (mx - mn)) * 100));
                return (
                  <div key={i} style={{ marginBottom: 16 }}>
                    <div style={sx("display:flex; align-items:center; height:34px; border:1px solid var(--border-2); border-radius:5px; background:rgba(0,0,0,.28); overflow:hidden;")}>
                      <span style={sx("display:flex; align-items:center; justify-content:center; width:34px; height:100%; border-right:1px solid var(--border-2); color:var(--text-2); flex-shrink:0;")}><I k="arrows" size={16} /></span>
                      <span style={{ flex: 1 }} />
                      <span style={sx("padding-right:12px; font-family:'Spline Sans Mono',monospace; font-size:14px; color:#fff;")}>{v.toFixed(1)} <span style={sx("color:var(--text-3); font-size:10.5px;")}>MM</span></span>
                    </div>
                    <div onPointerDown={(e) => startParamDrag(i, e)}
                      style={sx("position:relative; height:18px; margin-top:9px; cursor:pointer; display:flex; align-items:center; touch-action:none;")}>
                      <div style={sx("position:absolute; left:0; right:0; height:5px; border-radius:3px; background:rgba(255,255,255,.13);")} />
                      <div style={{ ...sx("position:absolute; left:0; height:5px; border-radius:3px; background:var(--accent,#4d9eff);"), width: pct + "%" }} />
                      <div style={{ ...sx("position:absolute; top:50%; width:13px; height:13px; border-radius:3px; background:var(--accent,#4d9eff); border:2px solid #0d0d0d; transform:translate(-50%,-50%);"), left: pct + "%" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div></div>
        )}

        {shownTool === "display" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 284 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Display</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 18px;")}>
              <div style={sx("display:flex; align-items:center; margin-bottom:16px;")}>
                <span style={sx("flex:1; font-size:14.5px; color:var(--text);")}>Mode</span>
                <div style={sx("display:inline-flex; border:1px solid var(--border-2); border-radius:5px; overflow:hidden;")}>
                  {(["solid", "wire", "xray"] as const).map((md) => (
                    <button key={md} data-press data-seg {...(md === renderMode ? { "data-on": "" } : {})}
                      onClick={() => { setRenderMode(md); VP.setRenderMode(md); }}
                      style={sx("padding:6px 11px;border:none;font-family:'Spline Sans Mono',monospace;font-size:11px;font-weight:500;letter-spacing:.05em;cursor:pointer;transition:background .15s,color .15s;" +
                        (md === renderMode ? "background:var(--accent,#4d9eff);color:var(--on-accent,#06111c);" : "background:transparent;color:var(--text-2);"))}>
                      {md.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
              {[{ label: "EXPLODE", val: explode, set: (v: number) => { setExplode(v); VP.setExplode(v); } },
                { label: "SECTION", val: section, set: (v: number) => { setSection(v); VP.setSection(v); } }].map((sl) => (
                <div key={sl.label} style={{ marginBottom: 14 }}>
                  <div style={sx("display:flex; align-items:center; margin-bottom:7px;")}>
                    <span style={sx("flex:1; font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; color:var(--text-2);")}>{sl.label}</span>
                    <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:11.5px; color:var(--text);")}>{Math.round(sl.val * 100)}%</span>
                  </div>
                  <div onPointerDown={(e) => {
                    e.preventDefault();
                    const track = e.currentTarget as HTMLElement;
                    const rect = track.getBoundingClientRect();
                    const set = (cx: number) => sl.set(Math.max(0, Math.min(1, (cx - rect.left) / rect.width)));
                    set(e.clientX);
                    const mv = (ev: PointerEvent) => set(ev.clientX);
                    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
                    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
                  }} style={sx("position:relative; height:18px; cursor:pointer; display:flex; align-items:center; touch-action:none;")}>
                    <div style={sx("position:absolute; left:0; right:0; height:5px; border-radius:3px; background:rgba(255,255,255,.13);")} />
                    <div style={{ ...sx("position:absolute; left:0; height:5px; border-radius:3px; background:var(--accent,#4d9eff);"), width: (sl.val * 100) + "%" }} />
                    <div style={{ ...sx("position:absolute; top:50%; width:13px; height:13px; border-radius:3px; background:var(--accent,#4d9eff); border:2px solid #0d0d0d; transform:translate(-50%,-50%);"), left: (sl.val * 100) + "%" }} />
                  </div>
                </div>
              ))}
              <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.05em; color:var(--text-3); line-height:1.6;")}>
                SECTION slices from the top — see shell walls and interiors.
              </div>
            </div>
          </div></div>
        )}

        {shownTool === "suggestions" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 296 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Suggestions</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 16px;")}>
              {sMeta.map(([name, color]) => {
                const on = !!suggest[name];
                return (
                  <div key={name} style={sx("display:flex; align-items:center; gap:12px; padding:9px 2px;")}>
                    <span style={{ ...sx("width:15px;height:15px;border-radius:4px;flex-shrink:0;"), background: color }} />
                    <span style={sx("flex:1; font-size:15px; color:var(--text);")}>{name}</span>
                    <button data-press onClick={() => setSuggest((s) => ({ ...s, [name]: !s[name] }))} style={chkStyle(on)}>
                      {on && <svg width="16" height="16" viewBox="0 0 24 24" style={{ color: "var(--on-accent,#06111c)" }}><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                    </button>
                  </div>
                );
              })}
              <div style={sx("height:1px; background:var(--border); margin:10px 0 2px;")} />
              <div style={sx("display:flex; align-items:center; padding:12px 2px 2px;")}>
                <span style={sx("flex:1; font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; color:var(--text-2);")}>SHOW SUGGESTION</span>
                <button data-press onClick={() => setShowSug((s) => !s)} style={tglTrack(showSug)}><span style={tglKnob(showSug)} /></button>
              </div>
            </div>
          </div></div>
        )}

        {shownTool === "parts" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 300 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Component Parts</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 10px 12px; max-height:calc(100vh - 240px); overflow-y:auto;")}>
              <div data-press onClick={() => setPartsCollapsed((c) => !c)}
                style={sx("display:flex; align-items:center; gap:8px; padding:8px 6px; cursor:pointer;")}>
                <I k={partsCollapsed ? "chev-right" : "chev-down"} size={16} style={{ color: "var(--text-2)" }} />
                <I k="folder-open" size={18} style={{ color: "var(--text-2)" }} />
                <span style={sx("font-size:14.5px; font-weight:600; color:#fff;")}>{m?.name || "Model"}</span>
              </div>
              {!partsCollapsed && partNames.map((n) => {
                const hidden = !!partsHidden[n];
                return (
                  <div key={n} style={{ ...sx("display:flex;align-items:center;gap:10px;padding:7px 4px 7px 8px;border-radius:5px;transition:background .12s;"), opacity: hidden ? 0.42 : 1 }}>
                    <span style={{ width: 16, flexShrink: 0 }} />
                    <I k="part" size={17} style={{ color: "var(--text-2)" }} />
                    <span style={sx("flex:1; font-size:14px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{n}</span>
                    <button data-press data-iconbtn title="Toggle visibility"
                      onClick={() => { const h = !hidden; setPartsHidden((p) => ({ ...p, [n]: h })); VP.setPartVisible(n, !h); }}
                      style={sx("width:26px; height:26px; border:none; border-radius:5px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer; flex-shrink:0;")}>
                      <I k={hidden ? "eye-off" : "eye"} size={17} />
                    </button>
                    <button data-press data-iconbtn title="Remove"
                      onClick={() => { setPartsRemoved((p) => ({ ...p, [n]: true })); VP.removePart(n); }}
                      style={sx("width:26px; height:26px; border:none; border-radius:5px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer; flex-shrink:0;")}>
                      <I k="trash" size={16} />
                    </button>
                  </div>
                );
              })}
              {!partsCollapsed && m?.assembly?.components && (
                <div style={sx("margin:8px 6px 2px; padding-top:8px; border-top:1px solid var(--border); font-family:'Spline Sans Mono',monospace; font-size:10.5px; letter-spacing:.06em; color:var(--text-3); line-height:1.7;")}>
                  ASSEMBLY GRAPH · {m.assembly.components.length} PARTS
                  {m.assembly.components.map((c: any) => (
                    <div key={c.name} style={sx("color:var(--text-2); font-size:12px;")}>· {c.name}{c.role ? ` (${c.role})` : ""}</div>
                  ))}
                </div>
              )}
            </div>
          </div></div>
        )}

        {shownTool === "measurements" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 284 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Measurements</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:0 16px 18px;")}>
              <div style={sx("height:1px; background:var(--border); margin:0 -16px 14px;")} />
              <div style={sx("display:flex; align-items:center; gap:9px; color:var(--text-2); margin-bottom:16px;")}>
                <I k="arrows" size={18} />
                <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:13px;")}>
                  {measured[0] ? `${fmtExt(measured[0])} × ${fmtExt(measured[1])} × ${fmtExt(measured[2])} ${unit.toLowerCase()}` : "(0)"}
                </span>
              </div>
              <div style={sx("display:flex; align-items:center; margin-bottom:16px;")}>
                <span style={sx("flex:1; font-size:14.5px; color:var(--text);")}>Unit</span>
                <div style={sx("display:inline-flex; border:1px solid var(--border-2); border-radius:5px; overflow:hidden;")}>
                  {(["MM", "CM", "M"] as const).map((u) => (
                    <button key={u} data-press data-seg {...(u === unit ? { "data-on": "" } : {})} onClick={() => setUnit(u)} style={uSeg(u)}>{u}</button>
                  ))}
                </div>
              </div>
              <div style={sx("display:flex; align-items:center;")}>
                <span style={sx("flex:1; font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; color:var(--text-2);")}>SHOW EXTENTS</span>
                <button data-press onClick={() => setShowExtents((s) => !s)} style={tglTrack(showExtents)}><span style={tglKnob(showExtents)} /></button>
              </div>
            </div>
          </div></div>
        )}

        {shownTool === "share" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 284 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Share</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 16px;")}>
              {!shareLink ? (
                <div style={sx("padding:10px 0 16px; font-size:14px; color:var(--text-3); text-align:center;")}>No active share links.</div>
              ) : (
                <div style={sx("display:flex; align-items:center; gap:8px; padding:10px 12px; margin:2px 0 14px; border:1px solid var(--border-2); border-radius:5px; background:rgba(0,0,0,.28);")}>
                  <I k="share" size={15} style={{ color: "var(--accent,#4d9eff)" }} />
                  <span style={sx("flex:1; font-family:'Spline Sans Mono',monospace; font-size:12px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{shareLink}</span>
                  <button data-press data-iconbtn title="Copy"
                    onClick={() => { navigator.clipboard?.writeText(location.origin + "/#" + shareLink.split("/s/")[1]); st.showToast("Link copied"); }}
                    style={sx("width:24px; height:24px; border:none; border-radius:5px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer; flex-shrink:0;")}>
                    <I k="copy" size={15} />
                  </button>
                </div>
              )}
              <button data-press onClick={() => { setShareLink("motionlab.studio/s/" + Math.random().toString(36).slice(2, 8)); st.showToast("Share link created"); }}
                data-primary style={sx("width:100%; padding:13px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
                <span data-ulw>CREATE SHARE LINK</span>
              </button>
            </div>
          </div></div>
        )}

        {shownTool === "rig" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 300 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Auto-Rig</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 16px;")}>
              {rigReport ? (
                <div style={sx("margin-bottom:12px;")}>
                  {(rigReport.rows || []).map((r: any) => (
                    <div key={r.name} style={sx("display:flex; align-items:center; gap:8px; padding:7px 0; border-bottom:1px solid var(--border); font-size:12.5px;")}>
                      <span style={sx("width:8px; height:8px; border-radius:50%; flex-shrink:0; background:" + (r.within_tol ? "var(--verified)" : "var(--fail)") + ";")} />
                      <span style={sx("flex:1; color:var(--text-2);")}>{r.name.replace("rig · ", "")}</span>
                      <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:11.5px; color:var(--text);")}>{String(r.measured)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={sx("padding:8px 0 14px; font-size:13.5px; line-height:1.55; color:var(--text-2);")}>
                  Generates a skeleton and skin weights for this mesh — verified game-ready
                  (single root, ≤4 weights per vertex). The rigged GLB replaces this asset.
                </div>
              )}
              {rigged ? (
                <>
                  <div style={sx("display:flex; align-items:center; justify-content:center; gap:8px; padding:12px; border:1px solid var(--verified); border-radius:5px; color:var(--verified); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em;")}>
                    <I k="check" size={15} /> RIGGED · GAME-READY
                  </div>
                  <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-top:12px; padding:2px 2px;")}>
                    <span style={sx("display:flex; align-items:center; gap:9px; font-size:13.5px; color:var(--text);")}>
                      <I k="bone" size={16} style={{ color: skelOn ? "var(--accent,#4d9eff)" : "var(--text-2)" }} />
                      View skeleton
                    </span>
                    <button onClick={() => toggleSkeleton(!skelOn)} style={tglTrack(skelOn)} title="Draw the bone chains through the surface">
                      <span style={tglKnob(skelOn)} />
                    </button>
                  </div>
                </>
              ) : (
                <button data-press data-primary onClick={doRig} disabled={rigging}
                  style={sx("width:100%; padding:13px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:500; letter-spacing:.1em; cursor:pointer;" + (rigging ? "opacity:.6;" : ""))}>
                  <span data-ulw>{rigging ? "RIGGING… (~2 MIN)" : "RIG THIS MESH"}</span>
                </button>
              )}
            </div>
          </div></div>
        )}

        {shownTool === "animate" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 312 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Animate</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 16px;")}>
              {!rigged && (
                <div style={sx("display:flex; align-items:center; gap:9px; padding:10px 12px; margin-bottom:12px; border:1px solid var(--warn); border-radius:5px; font-size:12.5px; color:var(--warn);")}>
                  <I k="bone" size={15} /> Needs a rig — run Auto-Rig first (one tool up).
                </div>
              )}
              <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3); margin-bottom:7px;")}>DESCRIBE THE MOTION</div>
              <textarea value={animPrompt} onChange={(e) => setAnimPrompt(e.target.value)}
                placeholder={'e.g. "prowls forward slowly, tail swaying" — or drop a reference video below'}
                style={sx("width:100%; min-height:64px; padding:10px 12px; border:1px solid var(--border-2); background:var(--inset); color:var(--text); border-radius:5px; font-size:13.5px; line-height:1.5;")} />
              <input ref={mp4Ref} type="file" accept="video/mp4,video/*" style={{ display: "none" }}
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (f) setAnimMp4({ b64: await fileToB64(f), name: f.name });
                  e.currentTarget.value = "";
                }} />
              {animMp4 ? (
                <div style={sx("display:flex; align-items:center; gap:9px; padding:8px 10px; margin-top:10px; border:1px solid rgba(var(--accent-rgb),.45); background:rgba(var(--accent-rgb),.07); border-radius:5px;")}>
                  <I k="play" size={15} style={{ color: "var(--accent,#4d9eff)" }} />
                  <span style={sx("flex:1; min-width:0; font-size:12.5px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{animMp4.name}</span>
                  <button data-press data-iconbtn title="Remove video" onClick={() => setAnimMp4(null)}
                    style={sx("width:22px; height:22px; border:none; border-radius:4px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer; flex-shrink:0;")}>
                    <I k="close" size={13} />
                  </button>
                </div>
              ) : (
                <button data-press data-accenthover onClick={() => mp4Ref.current?.click()}
                  style={sx("width:100%; margin-top:10px; padding:10px; border:1px dashed var(--border-2); background:transparent; color:var(--text-2); font-size:12.5px; cursor:pointer; border-radius:5px;")}>
                  Reference MP4 (optional) — motion is extracted and retargeted
                </button>
              )}
              <button data-press data-primary onClick={doAnimate} disabled={animBusy}
                style={sx("width:100%; margin-top:12px; padding:13px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:500; letter-spacing:.1em; cursor:pointer;" + (animBusy || !rigged ? "opacity:.6;" : ""))}>
                <span data-ulw>{animBusy ? "ANIMATING…" : "GENERATE CLIP"}</span>
              </button>
              {animBusy && (
                <div style={sx("margin-top:9px; font-family:'Spline Sans Mono',monospace; font-size:11px; letter-spacing:.05em; color:var(--text-2); text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>
                  {animStage || "queued…"}
                </div>
              )}
            </div>
          </div></div>
        )}

        {shownTool === "export" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 284 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Export</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:2px 16px 16px;")}>
              <div style={sx("display:flex; align-items:center; margin-bottom:14px; position:relative;")}>
                <span style={sx("flex:1; font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; color:var(--text-2);")}>FORMAT</span>
                <button data-press onClick={() => setExportMenuOpen((o) => !o)}
                  style={sx("display:inline-flex; align-items:center; gap:10px; padding:8px 12px; border:1px solid var(--border-2); border-radius:5px; background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12.5px; cursor:pointer;")}>
                  {exportFormat}<I k="chev-down" size={14} style={{ color: "var(--text-2)" }} />
                </button>
                {exportMenuOpen && (
                  <div style={sx("position:absolute; right:0; top:calc(100% + 4px); width:118px; background:var(--panel-2); border:1px solid var(--border-2); border-radius:6px; overflow:hidden; z-index:6; box-shadow:0 10px 26px rgba(0,0,0,.5);")}>
                    {["GLB", "STL", "STEP", "CODE"].map((f) => (
                      <button key={f} data-press data-iconbtn onClick={() => { setExportFormat(f); setExportMenuOpen(false); }}
                        style={sx("display:block;width:100%;text-align:left;padding:9px 13px;border:none;background:transparent;color:" +
                          (f === exportFormat ? "var(--accent,#4d9eff)" : "var(--text)") + ";font-family:'Spline Sans Mono',monospace;font-size:12.5px;cursor:pointer;")}>
                        {f}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button data-press onClick={doExport}
                data-primary style={sx("width:100%; padding:13px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
                <span data-ulw>EXPORT</span>
              </button>
            </div>
          </div></div>
        )}

        {shownTool === "bulb" && (
          <div {...flyProps} style={sx("filter:drop-shadow(0 18px 44px rgba(0,0,0,.5));")}><div style={{ ...sx(PANEL), width: 292 }}>
            <div style={sx(PANEL_HEAD)}>
              <span style={sx(PANEL_TITLE)}>Controls</span>
              <PanelClose onClose={() => setTool(null)} />
            </div>
            <div style={sx("padding:0 16px 16px;")}>
              <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10.5px; letter-spacing:.1em; color:var(--text-3); margin:2px 0 9px;")}>VIEWPORT</div>
              {([["LMB", "Select a part (assemblies)"],
                 ["RMB", "Orbit around the model"],
                 ["MMB", "Pan in any direction"],
                 ["SCROLL", "Zoom — all the way to the surface"],
                 ["CUBE", "Orientation gizmo (bottom right)"]] as [string, string][]).map(([k, v]) => (
                <div key={k} style={sx("display:flex; align-items:center; gap:11px; padding:6.5px 0;")}>
                  <span style={sx("flex-shrink:0; min-width:56px; text-align:center; padding:3px 7px; border:1px solid var(--border-2); border-radius:4px; background:var(--inset); font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.06em; color:var(--text);")}>{k}</span>
                  <span style={sx("font-size:12.5px; color:var(--text-2);")}>{v}</span>
                </div>
              ))}
              <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10.5px; letter-spacing:.1em; color:var(--text-3); margin:14px 0 9px;")}>PANELS</div>
              <div style={sx("font-size:12.5px; line-height:1.6; color:var(--text-2);")}>
                Display — wire / x-ray, explode &amp; section. Parts — per-part visibility. Measurements — live extents.
              </div>
              <div style={sx("display:flex; align-items:center; gap:11px; margin-top:16px; padding-top:14px; border-top:1px solid var(--border);")}>
                <span style={sx("flex:1; font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; color:var(--text-2);")}>WARM LIGHTING</span>
                <button data-press onClick={() => { const w = !warm; setWarm(w); VP.setWarm(w); }} style={tglTrack(warm)} title="Lighting mood">
                  <span style={tglKnob(warm)} />
                </button>
              </div>
            </div>
          </div></div>
        )}
      </div>

      <div style={sx("position:absolute; left:24px; bottom:24px; pointer-events:auto;")}>
        <button data-press className="hv-white-b2" title="Job log"
          onClick={() => st.showToast(m ? `${m.engine.toUpperCase()} · ${m.status} · ${(m.inspection || []).length} checks · ${m.seconds ? Math.round(m.seconds) + "s" : "—"}` : "No job loaded")}
          style={sx("width:50px; height:50px; border:1px solid var(--border); border-radius:9px; background:rgba(15,15,17,.7); color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer; backdrop-filter:blur(8px);")}>
          <I k="log" size={23} />
        </button>
      </div>

    </div>
  );
}
