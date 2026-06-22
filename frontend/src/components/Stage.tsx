import { C, mono } from "../theme";
import { useStudio } from "../store";
import { HoverButton, Icon, ICONS } from "./ui";
import { Viewport } from "./Viewport";
import { PromptDock } from "./PromptDock";
import { Library } from "./Library";

const MOODS = [
  { key: "studio", label: "Studio", swatch: "linear-gradient(135deg,#d8d8e0,#9a9ab0)" },
  { key: "dramatic", label: "Dramatic", swatch: "linear-gradient(135deg,#8a6bff,#241a3a)" },
  { key: "soft", label: "Soft box", swatch: "linear-gradient(135deg,#fff,#cfcfe0)" },
  { key: "rim", label: "Rim", swatch: "linear-gradient(135deg,#1a1430,#a78bfa)" },
];

const glassBtn = (active = false): React.CSSProperties => ({
  width: 34, height: 34, display: "flex", alignItems: "center", justifyContent: "center",
  background: active ? "rgba(167,139,250,.16)" : "rgba(21,21,28,.8)", backdropFilter: "blur(10px)",
  border: `1px solid ${active ? "rgba(167,139,250,.4)" : C.border2}`, borderRadius: 10,
  color: active ? C.accent2 : C.sub, cursor: "pointer",
});
const segBtn = (active: boolean): React.CSSProperties => ({
  width: 32, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
  background: active ? "rgba(167,139,250,.16)" : "transparent", border: "none", borderRadius: 8,
  color: active ? C.accent2 : C.sub, cursor: "pointer",
});

export function Stage() {
  const s = useStudio();
  const isHard = s.branch === "hard";
  const e = s.spec.envelope;
  const envelopeBadge = isHard
    ? s.spec.shape === "box" ? `${e.length} × ${e.width} × ${e.height} mm` : `⌀${e.diameter} × ${e.height} mm`
    : `${s.targetHeight} mm tall`;
  const assetName = s.spec.object || "untitled";
  const stageLabels = isHard
    ? ["", "Generating CadQuery", "Executing in sandbox", "Verifying against spec", ""]
    : ["", "Diffusing latents", "Extracting mesh", "Synthesizing PBR", ""];
  const runningStage = s.attempt === 2 ? "Regenerating · attempt 2 of 3" : stageLabels[s.genStep] || "Working";
  const runningSub = `${s.model || (isHard ? "Qwen3.6-27B · local" : "TRELLIS.2 · local")}`;

  return (
    <div style={{ flex: 1, minWidth: 0, position: "relative", background: C.bg, overflow: "hidden" }}>
      <Viewport />
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "radial-gradient(120% 85% at 50% 32%, transparent 50%, rgba(0,0,0,.6) 100%)" }} />

      {/* top-left: asset id + envelope */}
      <div style={{ position: "absolute", top: 18, left: 20, zIndex: 9, display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: C.text, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{assetName}</span>
          <span style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700, color: C.accent3, background: "rgba(167,139,250,.13)", border: "1px solid rgba(167,139,250,.3)", borderRadius: 5, padding: "2px 7px" }}>{isHard ? "Hard-surface" : "Organic"}</span>
        </div>
        <div style={{ background: "rgba(12,12,17,.55)", backdropFilter: "blur(8px)", border: `1px solid ${C.border2}`, borderRadius: 9, padding: "6px 11px", display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".09em", color: C.sub, fontWeight: 600 }}>{isHard ? "envelope" : "target"}</span>
          <span style={{ fontFamily: mono, fontSize: 13, fontWeight: 500, color: C.text, letterSpacing: ".3px" }}>{envelopeBadge}</span>
        </div>
      </div>

      {/* top-right: view tools */}
      <div style={{ position: "absolute", top: 16, right: 20, zIndex: 9, display: "flex", gap: 8, alignItems: "center" }}>
        <div style={{ display: "flex", background: "rgba(21,21,28,.8)", backdropFilter: "blur(10px)", border: `1px solid ${C.border2}`, borderRadius: 10, padding: 3, gap: 2 }}>
          <button title="Solid" style={segBtn(s.view === "solid")} onClick={() => s.setView("solid")}><Icon d={ICONS.cube} size={16} /></button>
          <button title="Wireframe" style={segBtn(s.view === "wire")} onClick={() => s.setView("wire")}><Icon d={ICONS.wire} size={16} sw={1.5} /></button>
          <button title="X-ray" style={segBtn(s.view === "xray")} onClick={() => s.setView("xray")}><Icon d={ICONS.layers} size={16} sw={1.5} /></button>
        </div>
        {isHard
          ? <button title="Dimensions" style={glassBtn(s.showDims)} onClick={s.toggleDims}><Icon d={ICONS.dims} size={16} /></button>
          : <button title="Wall thickness" style={glassBtn(s.heatmap)} onClick={s.toggleHeatmap}><Icon d={ICONS.heat} size={16} /></button>}
        <button title="Frame" style={glassBtn()} onClick={() => s.frameView?.()}><Icon d={ICONS.frame} size={16} /></button>
        <button title="Snapshot" style={glassBtn()} onClick={() => s.shotView?.()}><Icon d={ICONS.camera} size={16} /></button>
      </div>
      <div style={{ position: "absolute", top: 62, right: 22, zIndex: 9, fontSize: 10, color: C.faint }}>drag · scroll to zoom</div>

      {/* stage pill */}
      <div style={{ position: "absolute", top: 102, left: 20, zIndex: 11, display: "flex", alignItems: "center", gap: 4, background: "rgba(20,20,27,.82)", backdropFilter: "blur(12px)", border: `1px solid ${C.border2}`, borderRadius: 13, padding: 5, boxShadow: "0 12px 32px rgba(0,0,0,.45)" }}>
        <button onClick={s.toggleTurntable} title={s.turntable ? "Pause turntable" : "Play turntable"} style={{ width: 34, height: 34, borderRadius: 9, border: "none", background: "transparent", color: C.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {s.turntable
            ? <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
            : <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M7 5l12 7-12 7z" /></svg>}
        </button>
        <div style={{ width: 1, height: 20, background: C.border3, margin: "0 2px" }} />
        <div style={{ position: "relative" }}>
          <button onClick={s.toggleMood} title="Lighting" style={{ display: "flex", alignItems: "center", gap: 7, height: 34, padding: "0 11px 0 7px", border: "none", borderRadius: 9, background: "transparent", cursor: "pointer", color: C.text }}>
            <span style={{ width: 18, height: 18, borderRadius: 6, background: (MOODS.find((m) => m.key === s.lightMood) || MOODS[0]).swatch, boxShadow: "inset 0 0 0 1px rgba(255,255,255,.12)" }} />
            <span style={{ fontSize: 11.5, fontWeight: 500 }}>{(MOODS.find((m) => m.key === s.lightMood) || MOODS[0]).label}</span>
            <Icon d="M6 9l6 6 6-6" size={11} sw={2} />
          </button>
          {s.moodOpen && (
            <div style={{ position: "absolute", left: 0, top: "calc(100% + 8px)", background: C.raised, border: `1px solid ${C.border3}`, borderRadius: 12, padding: 6, zIndex: 20, boxShadow: "0 16px 36px rgba(0,0,0,.55)", display: "flex", flexDirection: "column", gap: 2, minWidth: 168, animation: "fadeUp .18s ease both" }}>
              <span style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".08em", color: C.sub2, fontWeight: 700, padding: "4px 8px 5px" }}>Lighting mood</span>
              {MOODS.map((m) => (
                <button key={m.key} onClick={() => s.pickMood(m.key)} style={{ display: "flex", alignItems: "center", gap: 9, background: "transparent", border: "none", color: C.text, fontSize: 12, padding: "7px 8px", borderRadius: 8, cursor: "pointer" }}>
                  <span style={{ width: 20, height: 20, borderRadius: 6, background: m.swatch, boxShadow: "inset 0 0 0 1px rgba(255,255,255,.12)" }} />{m.label}
                  {s.lightMood === m.key && <span style={{ marginLeft: "auto", color: C.accent2 }}>✓</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        {!isHard && (
          <>
            <div style={{ width: 1, height: 20, background: C.border3, margin: "0 2px" }} />
            <button onClick={s.toggleScaleFigure} title="Toggle 1.7 m scale reference" style={glassBtn(s.scaleFigure)}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="5" r="2.4" /><path d="M12 8v8M12 16l-3 5M12 16l3 5M7 11h10" /></svg>
            </button>
          </>
        )}
      </div>

      {/* generating overlay */}
      {s.genStatus === "running" && (
        <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", zIndex: 12, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          <div style={{ position: "relative", width: 64, height: 64 }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `3px solid ${C.border2}` }} />
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: "3px solid transparent", borderTopColor: C.accent2, animation: "vspin .9s linear infinite" }} />
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 13, color: C.accent3 }}>{s.progress}%</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{runningStage}</span>
            <span style={{ fontSize: 11, color: C.sub, fontFamily: mono }}>{runningSub}</span>
          </div>
        </div>
      )}

      <PromptDock />
      <Library />
    </div>
  );
}
