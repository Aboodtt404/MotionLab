import { C, glass, teamAccent } from "../theme";
import { useStudio } from "../store";
import { Bx, BX, HoverButton } from "./ui";

/** Slim floating dock (left) — input mode + library + help. The viewport shows through behind it. */
export function ToolDock() {
  const s = useStudio();
  const ac = teamAccent(s.team);
  const robotics = s.team === "robotics";
  const items = [
    { key: "text", label: robotics ? "Spec / prompt" : "Prompt", icon: BX.text, active: s.mode === "text" && !s.libOpen, onClick: () => s.setMode("text") },
    { key: "image", label: robotics ? "Image + scale" : "Reference image", icon: BX.image, active: s.mode === "image" && !s.libOpen, onClick: () => s.setMode("image") },
    { key: "lib", label: "Asset library", icon: BX.library, active: s.libOpen, onClick: s.toggleLib },
  ];
  const btn = (active: boolean): React.CSSProperties => ({
    width: 44, height: 44, borderRadius: 12, border: `1px solid ${active ? ac.line : "transparent"}`, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    background: active ? ac.soft : "transparent", color: active ? ac.a2 : C.sub2,
  });
  return (
    <div style={{ position: "absolute", left: 14, top: 72, zIndex: 16, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: 7, borderRadius: 16, ...glass(0.6), boxShadow: "0 14px 40px rgba(0,0,0,.5)" }}>
      {items.map((it) => (
        <HoverButton key={it.key} title={it.label} onClick={it.onClick} base={btn(it.active)} hover={{ color: it.active ? ac.a2 : C.text, borderColor: ac.line }}>
          <Bx n={it.icon} size={21} />
        </HoverButton>
      ))}
      <div style={{ width: 24, height: 1, background: C.border2, margin: "2px 0" }} />
      <HoverButton title="Help" base={{ width: 44, height: 44, borderRadius: 12, border: "1px solid transparent", background: "transparent", color: C.sub2, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }} hover={{ color: C.text }}>
        <Bx n={BX.help} size={20} />
      </HoverButton>
    </div>
  );
}
