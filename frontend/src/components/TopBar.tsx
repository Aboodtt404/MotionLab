import { C, fonts, glass, teamAccent } from "../theme";
import { useStudio } from "../store";
import { Bx, BX, HoverButton } from "./ui";
import type { Team } from "../types";

export const MOODS = [
  { key: "studio", label: "Studio" },
  { key: "dramatic", label: "Dramatic" },
  { key: "soft", label: "Soft box" },
  { key: "rim", label: "Rim" },
];

const iconBtn = (active = false): React.CSSProperties => ({
  width: 32, height: 30, display: "flex", alignItems: "center", justifyContent: "center",
  background: active ? "rgba(255,255,255,.08)" : "transparent", border: "none", borderRadius: 8,
  color: active ? C.text : C.sub, cursor: "pointer",
});
const seg: React.CSSProperties = { display: "flex", alignItems: "center", gap: 2, background: "rgba(255,255,255,.03)", border: `1px solid ${C.border2}`, borderRadius: 10, padding: 3 };

export function TopBar() {
  const s = useStudio();
  const isHard = s.branch === "hard";
  const teams: { key: Team; label: string; icon: string }[] = [
    { key: "robotics", label: "Robotics", icon: BX.robotics },
    { key: "film", label: "Film", icon: BX.film },
  ];

  return (
    <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 56, zIndex: 20, display: "flex", alignItems: "center", gap: 16, padding: "0 16px", ...glass(0.55), borderLeft: "none", borderRight: "none", borderTop: "none" }}>
      {/* brand — solid purple wordmark (black + purple palette) */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, paddingLeft: 2 }}>
        <span style={{ fontFamily: fonts.display, fontSize: 18, fontWeight: 600, letterSpacing: "-0.02em", color: "#A855F7" }}>MotionLab</span>
        <span style={{ fontSize: 10, letterSpacing: ".24em", textTransform: "uppercase", color: C.sub2, fontWeight: 500 }}>Studio</span>
      </div>

      {/* team switch — the primary axis */}
      <div style={seg}>
        {teams.map((t) => {
          const ac = teamAccent(t.key); const active = s.team === t.key;
          return (
            <HoverButton key={t.key} onClick={() => s.setTeam(t.key)}
              base={{ display: "flex", alignItems: "center", gap: 7, height: 30, padding: "0 13px", borderRadius: 8, border: "none", cursor: "pointer", fontFamily: fonts.ui, fontSize: 12.5, fontWeight: 600, background: active ? ac.soft : "transparent", color: active ? ac.a2 : C.sub, boxShadow: active ? `inset 0 0 0 1px ${ac.line}` : "none" }}
              hover={{ color: active ? ac.a2 : C.text }}>
              <Bx n={t.icon} size={15} />{t.label}
            </HoverButton>
          );
        })}
      </div>

      <div style={{ flex: 1 }} />

      {/* look-dev + view tools (shared) */}
      <div style={seg}>
        <button title="Solid" style={iconBtn(s.view === "solid")} onClick={() => s.setView("solid")}><Bx n={BX.solid} size={16} /></button>
        <button title="Wireframe" style={iconBtn(s.view === "wire")} onClick={() => s.setView("wire")}><Bx n={BX.wire} size={16} /></button>
        <button title="X-ray" style={iconBtn(s.view === "xray")} onClick={() => s.setView("xray")}><Bx n={BX.xray} size={16} /></button>
      </div>
      <div style={seg}>
        <button title={s.turntable ? "Pause turntable" : "Play turntable"} style={iconBtn(s.turntable)} onClick={s.toggleTurntable}><Bx n={s.turntable ? BX.pause : BX.play} size={16} /></button>
        {isHard
          ? <button title="Dimensions" style={iconBtn(s.showDims)} onClick={s.toggleDims}><Bx n={BX.dims} size={16} /></button>
          : <button title="Wall thickness" style={iconBtn(s.heatmap)} onClick={s.toggleHeatmap}><Bx n={BX.heat} size={16} /></button>}
        {!isHard && <button title="Scale figure (1.7 m)" style={iconBtn(s.scaleFigure)} onClick={s.toggleScaleFigure}><Bx n={BX.scale} size={16} /></button>}
        <div style={{ position: "relative" }}>
          <button title="Lighting" style={iconBtn(s.moodOpen)} onClick={s.toggleMood}><Bx n={BX.light} size={16} /></button>
          {s.moodOpen && (
            <div style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", ...glass(0.9), borderRadius: 12, padding: 6, zIndex: 30, boxShadow: "0 16px 36px rgba(0,0,0,.55)", display: "flex", flexDirection: "column", gap: 1, minWidth: 150 }}>
              <span style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".09em", color: C.sub2, fontWeight: 700, padding: "4px 9px 5px" }}>Lighting</span>
              {MOODS.map((m) => (
                <button key={m.key} onClick={() => s.pickMood(m.key)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "transparent", border: "none", color: s.lightMood === m.key ? C.text : C.sub, fontSize: 12, padding: "7px 9px", borderRadius: 8, cursor: "pointer", fontFamily: fonts.ui }}>
                  {m.label}{s.lightMood === m.key && <Bx n="check" size={14} style={{ color: C.accent2 }} />}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div style={seg}>
        <button title="Frame" style={iconBtn()} onClick={() => s.frameView?.()}><Bx n={BX.frame} size={16} /></button>
        <button title="Snapshot" style={iconBtn()} onClick={() => s.shotView?.()}><Bx n={BX.camera} size={16} /></button>
      </div>
    </div>
  );
}
