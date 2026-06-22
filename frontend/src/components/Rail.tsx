import { C } from "../theme";
import { useStudio } from "../store";
import { HoverButton, Icon, ICONS } from "./ui";

const railBtn = (active: boolean): React.CSSProperties => ({
  width: 42, height: 42, borderRadius: 11, border: "none", cursor: "pointer",
  display: "flex", alignItems: "center", justifyContent: "center",
  background: active ? "rgba(167,139,250,.14)" : "transparent",
  color: active ? C.accent2 : C.sub2,
});

export function Rail() {
  const { mode, libOpen, setMode, toggleLib } = useStudio();
  const items = [
    { key: "text", label: "Text + metrics", icon: ICONS.sparkles, active: mode === "text" && !libOpen, onClick: () => setMode("text") },
    { key: "image", label: "Image", icon: ICONS.image, active: mode === "image" && !libOpen, onClick: () => setMode("image") },
    { key: "lib", label: "Asset library", icon: ICONS.grid, active: libOpen, onClick: toggleLib },
  ];
  return (
    <div style={{ width: 66, flex: "0 0 66px", borderRight: `1px solid ${C.border}`, background: C.panel, display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 6, zIndex: 30 }}>
      <div style={{ width: 36, height: 36, borderRadius: 10, background: `linear-gradient(135deg,${C.accent},${C.accent2})`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 10, boxShadow: "0 4px 14px rgba(124,92,252,.45)", color: C.bg }}>
        <Icon d={ICONS.bolt} size={20} sw={1.8} />
      </div>
      {items.map((r) => (
        <HoverButton key={r.key} title={r.label} onClick={r.onClick} base={railBtn(r.active)} hover={{ color: C.text }}>
          <Icon d={r.icon} size={20} sw={1.7} />
        </HoverButton>
      ))}
      <div style={{ flex: 1 }} />
      <HoverButton title="Help" base={{ width: 42, height: 42, borderRadius: 11, border: "none", background: "transparent", color: C.sub2, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }} hover={{ color: C.text }}>
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 015 .2c0 1.8-2.5 2-2.5 3.8M12 17v.01" /></svg>
      </HoverButton>
      <div style={{ width: 32, height: 32, borderRadius: "50%", background: `linear-gradient(135deg,#3a3a48,${C.raised})`, border: `1px solid ${C.border3}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 600, color: C.muted }}>SK</div>
    </div>
  );
}
