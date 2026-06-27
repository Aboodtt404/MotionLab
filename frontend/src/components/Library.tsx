import { C, fonts, glass, mono } from "../theme";
import { useStudio } from "../store";
import { Bx, BX, HoverButton } from "./ui";

export function Library() {
  const { libOpen, assets, closeLib, loadAsset } = useStudio();
  if (!libOpen) return null;
  return (
    <>
      <div onClick={closeLib} style={{ position: "absolute", inset: 0, zIndex: 24, background: "rgba(6,7,12,.55)", backdropFilter: "blur(3px)" }} />
      <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: 396, zIndex: 25, padding: 20, display: "flex", flexDirection: "column", gap: 16, ...glass(0.86), borderTop: "none", borderBottom: "none", borderLeft: "none", boxShadow: "26px 0 70px rgba(0,0,0,.55)", animation: "slideInRight .25s ease both" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontFamily: fonts.display, fontSize: 16, fontWeight: 600 }}>Asset library</span>
          <button onClick={closeLib} style={{ background: "transparent", border: "none", color: C.sub, cursor: "pointer", padding: 4, display: "flex" }}><Bx n="x" size={19} /></button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, overflowY: "auto", paddingRight: 4 }}>
          {assets.map((a) => (
            <HoverButton key={a.id} onClick={() => loadAsset(a)} base={{ background: C.card2, border: `1px solid ${C.border2}`, borderRadius: 12, padding: 0, overflow: "hidden", cursor: "pointer", textAlign: "left" }} hover={{ borderColor: a.cls === "hard" ? "#7C5CFC" : "#A855F7" }}>
              <div style={{ height: 100, background: a.thumb ? `center/cover no-repeat url(${a.thumb})` : a.cls === "hard" ? "linear-gradient(135deg,#1B1438,#0E0A1C)" : "linear-gradient(135deg,#231435,#140C22)", position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {!a.thumb && <Bx n={a.cls === "hard" ? BX.robotics : BX.film} size={40} style={{ color: C.sub2 }} />}
                <span style={{ position: "absolute", top: 8, left: 8, fontSize: 8, textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 700, color: "#06070C", background: a.cls === "hard" ? "#7C5CFC" : "#A855F7", borderRadius: 4, padding: "2px 6px" }}>{a.cls === "hard" ? "robotics" : "film"}</span>
                <span style={{ position: "absolute", top: 8, right: 8, width: 8, height: 8, borderRadius: "50%", background: a.pass ? C.good : C.bad, boxShadow: "0 0 0 2px rgba(0,0,0,.45)" }} />
              </div>
              <div style={{ padding: "9px 11px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                <span style={{ fontSize: 12, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                <span style={{ fontSize: 9.5, color: C.faint, fontFamily: mono }}>{a.ver}</span>
              </div>
            </HoverButton>
          ))}
        </div>
      </div>
    </>
  );
}
