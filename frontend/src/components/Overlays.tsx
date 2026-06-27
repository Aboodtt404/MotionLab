import { C, fonts, glass, teamAccent } from "../theme";
import { useStudio } from "../store";
import { Bx } from "./ui";

/** Centered generating overlay — real stage + progress, cancellable for long Track-B jobs. */
export function GeneratingOverlay() {
  const s = useStudio();
  if (s.genStatus !== "running") return null;
  const isHard = s.branch === "hard";
  const ac = teamAccent(s.team);
  const stageLabels = isHard
    ? ["", "Generating CadQuery", "Executing in sandbox", "Verifying against spec", ""]
    : ["", "Diffusing latents", "Extracting mesh", "Synthesizing PBR", ""];
  const stage = s.attempt === 2 ? "Regenerating · attempt 2 of 3" : stageLabels[s.genStep] || "Working";
  const sub = isHard ? (s.useModel ? "Qwen3.6-27B · local" : "golden builder · deterministic") : `TRELLIS.2 · ${s.qualityTier}`;

  return (
    <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", zIndex: 17, display: "flex", flexDirection: "column", alignItems: "center", gap: 18, padding: "26px 34px", borderRadius: 18, ...glass(0.5), boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}>
      <div style={{ position: "relative", width: 66, height: 66 }}>
        <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: `3px solid ${C.border2}` }} />
        <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: "3px solid transparent", borderTopColor: ac.a2, animation: "vspin .9s linear infinite" }} />
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: fonts.mono, fontSize: 13.5, color: ac.a3 }}>{s.progress}%</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
        <span style={{ fontFamily: fonts.display, fontSize: 14.5, fontWeight: 600, color: C.text }}>{stage}</span>
        <span style={{ fontSize: 11, color: C.sub, fontFamily: fonts.mono }}>{sub}</span>
      </div>
      {!isHard && !s.cancelRequested && (
        <button onClick={s.cancelJob} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600, padding: "7px 15px", borderRadius: 10, background: "transparent", border: `1px solid ${C.border3}`, color: C.sub, cursor: "pointer", fontFamily: fonts.ui }}>
          <Bx n="x" size={13} />Cancel
        </button>
      )}
      {!isHard && s.cancelRequested && <span style={{ fontSize: 11, color: C.sub2 }}>cancelling…</span>}
    </div>
  );
}
