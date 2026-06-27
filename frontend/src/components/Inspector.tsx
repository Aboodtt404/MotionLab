import { C, fonts, glass, mono, teamAccent } from "../theme";
import { useStudio } from "../store";
import { Bx, BX } from "./ui";
import { ResultCard } from "./ResultCard";
import { Settings } from "./Settings";

/** Floating right panel — the contextual workspace: live editor/settings, plus the result when done. */
export function Inspector() {
  const s = useStudio();
  const ac = teamAccent(s.team);
  const robotics = s.team === "robotics";
  return (
    <div style={{ position: "absolute", right: 14, top: 72, bottom: 18, width: 374, zIndex: 16, display: "flex", flexDirection: "column", borderRadius: 18, ...glass(0.74), boxShadow: "0 20px 60px -12px rgba(0,0,0,.7)", overflow: "hidden", animation: "slideInRight .25s ease both" }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "14px 16px", borderBottom: `1px solid ${C.border}` }}>
        <span style={{ width: 28, height: 28, borderRadius: 9, background: ac.soft, border: `1px solid ${ac.line}`, display: "flex", alignItems: "center", justifyContent: "center", color: ac.a2 }}>
          <Bx n={robotics ? BX.robotics : BX.film} size={16} />
        </span>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
          <span style={{ fontFamily: fonts.display, fontSize: 13.5, fontWeight: 600, color: C.text }}>{robotics ? "Robotics" : "Film"}</span>
          <span style={{ fontSize: 9.5, color: C.sub2, fontFamily: mono, letterSpacing: ".03em" }}>{robotics ? "parametric · verified CAD" : "generative · organic mesh"}</span>
        </div>
      </div>

      {/* body */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: 16 }}>
        {s.genStatus === "done" && <ResultCard />}
        {s.retry && s.genStatus === "running" && (
          <div style={{ background: "rgba(251,191,36,.08)", border: "1px solid rgba(251,191,36,.4)", borderRadius: 12, padding: "11px 12px", display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ color: C.warn, marginTop: 1 }}><Bx n="refresh" size={15} /></span>
            <div style={{ fontSize: 11, lineHeight: 1.55, color: C.warn, fontFamily: mono }}>{s.retry}</div>
          </div>
        )}
        <Settings />
      </div>
    </div>
  );
}
