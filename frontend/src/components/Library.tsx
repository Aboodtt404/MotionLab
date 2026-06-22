import { C, mono } from "../theme";
import { useStudio } from "../store";
import { HoverButton, Icon, ICONS } from "./ui";

export function Library() {
  const { libOpen, assets, closeLib, loadAsset } = useStudio();
  if (!libOpen) return null;
  return (
    <>
      <div onClick={closeLib} style={{ position: "absolute", inset: 0, zIndex: 20, background: "rgba(8,8,12,.55)", backdropFilter: "blur(3px)" }} />
      <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: 380, zIndex: 21, background: C.panel, borderRight: `1px solid ${C.border}`, padding: 20, display: "flex", flexDirection: "column", gap: 16, boxShadow: "24px 0 60px rgba(0,0,0,.5)", animation: "fadeUp .25s ease both" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 15, fontWeight: 600 }}>Asset library</span>
          <button onClick={closeLib} style={{ background: "transparent", border: "none", color: C.sub, cursor: "pointer", padding: 4 }}><Icon d={ICONS.close} size={18} sw={1.8} /></button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, overflowY: "auto", paddingRight: 4 }}>
          {assets.map((a) => (
            <HoverButton key={a.id} onClick={() => loadAsset(a)} base={{ background: C.card2, border: `1px solid ${C.border2}`, borderRadius: 12, padding: 0, overflow: "hidden", cursor: "pointer", textAlign: "left" }} hover={{ borderColor: C.accent2 }}>
              <div style={{ height: 96, background: a.cls === "hard" ? "linear-gradient(135deg,#23232e,#15151c)" : "linear-gradient(135deg,#2a2140,#181226)", position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Icon d={a.cls === "hard" ? ICONS.cube : ICONS.organic} size={44} sw={1} />
                <span style={{ position: "absolute", top: 7, left: 7, fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 700, color: C.bg, background: C.accent3, borderRadius: 4, padding: "1px 5px" }}>{a.cls}</span>
                <span style={{ position: "absolute", top: 7, right: 7, width: 8, height: 8, borderRadius: "50%", background: a.pass ? C.good : C.bad }} />
              </div>
              <div style={{ padding: "9px 10px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
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
