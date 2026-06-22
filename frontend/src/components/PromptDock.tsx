import { C, mono } from "../theme";
import { useStudio, warningsFor } from "../store";
import { HoverButton, Icon, ICONS } from "./ui";
import { ART_STYLES, EXAMPLES, placeholder } from "../constants";

export function PromptDock() {
  const s = useStudio();
  const asm = s.assemblyMode;
  const editing = asm && !!s.assembly;
  const blocked = asm
    ? (s.genStatus === "running" || !s.prompt.trim())
    : warningsFor(s.branch, s.spec).length > 0 || (s.mode === "image" && !s.imageThumb) || s.genStatus === "running";
  const examples = EXAMPLES[s.branch];
  const btnLabel = asm ? (editing ? "Edit" : "Plan") : "Generate";
  const onGo = () => { if (blocked) return; asm ? s.planOrEdit() : s.generate(); };

  const generateStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 7, fontSize: 13.5, fontWeight: 600, fontFamily: "inherit",
    padding: "9px 16px", borderRadius: 11, border: "none", whiteSpace: "nowrap",
    cursor: blocked ? "not-allowed" : "pointer", opacity: blocked ? 0.5 : 1,
    background: `linear-gradient(135deg,${C.accent},${C.accent2})`, color: C.bg,
    boxShadow: "0 4px 16px rgba(124,92,252,.4)",
  };

  return (
    <div style={{ position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)", zIndex: 14, width: "min(760px,calc(100% - 40px))" }}>
      {s.backendError && (
        <div style={{ marginBottom: 8, padding: "7px 12px", borderRadius: 10, background: "rgba(220,80,80,.14)", border: "1px solid rgba(220,80,80,.4)", color: "#ffb4b4", fontSize: 11.5 }}>
          ⚠ generation failed: {String(s.backendError).slice(0, 160)} — try rephrasing or hit {btnLabel} again.
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, marginBottom: 9, paddingLeft: 4 }}>
        {/* planner mode: one prompt PLANS a multi-part assembly, then each prompt EDITS it */}
        <HoverButton onClick={s.toggleAssemblyMode}
          base={{ background: asm ? C.accent : "rgba(21,21,28,.7)", backdropFilter: "blur(8px)", border: `1px solid ${asm ? C.accent : C.border2}`, color: asm ? C.bg : C.muted, fontSize: 11, fontWeight: 600, padding: "5px 11px", borderRadius: 999, cursor: "pointer" }}
          hover={{ borderColor: C.accent2, color: asm ? C.bg : C.text }}>⊞ Assembly</HoverButton>
        {editing && (
          <span style={{ fontSize: 11, color: C.muted }}>
            editing <b style={{ color: C.text }}>{s.assemblyObject}</b> ·{" "}
            <button onClick={s.newDesign} style={{ background: "none", border: "none", color: C.accent2, fontSize: 11, cursor: "pointer", padding: 0, textDecoration: "underline" }}>new</button>
          </span>
        )}
        {!asm && examples.map((ex) => (
          <HoverButton key={ex} onClick={() => s.useExample(ex)} base={{ background: "rgba(21,21,28,.7)", backdropFilter: "blur(8px)", border: `1px solid ${C.border2}`, color: C.muted, fontSize: 11, padding: "5px 11px", borderRadius: 999, cursor: "pointer" }} hover={{ borderColor: C.accent2, color: C.text }}>{ex}</HoverButton>
        ))}
      </div>
      <div style={{ background: "rgba(20,20,27,.92)", backdropFilter: "blur(16px)", border: `1px solid ${C.border3}`, borderRadius: 18, padding: "11px 11px 11px 15px", display: "flex", alignItems: "flex-end", gap: 11, boxShadow: "0 18px 48px rgba(0,0,0,.55)" }}>
        <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 8, paddingBottom: 5 }}>
          {s.mode === "text" && <span style={{ width: 26, height: 26, borderRadius: 8, background: ART_STYLES[s.style].swatch }} />}
          {s.mode === "image" && !s.imageThumb && (
            <label title="Upload concept image" style={{ width: 34, height: 34, borderRadius: 9, border: `1px dashed ${C.border3}`, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: C.sub }}>
              <Icon d="M12 16V4m0 0L8 8m4-4l4 4||M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" size={16} sw={1.8} />
              <input type="file" accept="image/*" onChange={(ev) => { const f = ev.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => s.onImageFile(r.result as string); r.readAsDataURL(f); }} style={{ display: "none" }} />
            </label>
          )}
          {s.mode === "image" && s.imageThumb && (
            <button onClick={s.clearImage} title="Remove image" style={{ width: 34, height: 34, borderRadius: 9, border: `1px solid ${C.border3}`, position: "relative", overflow: "hidden", cursor: "pointer", background: `center/cover url(${s.imageThumb})`, padding: 0 }}>
              <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(12,12,17,.55)" }}><Icon d={ICONS.close} size={13} sw={2.2} /></span>
            </button>
          )}
          {/* Track C: absolute scale must be an explicit input for the hard-surface/fabrication path */}
          {s.mode === "image" && s.branch === "hard" && (
            <div title="Real-world size anchor — vision can't recover absolute scale; you provide one true dimension" style={{ display: "flex", alignItems: "center", gap: 5, background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 9, padding: "4px 8px" }}>
              <span style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".06em", color: C.sub2, fontWeight: 700 }}>scale</span>
              <input type="number" value={s.scaleAnchor} min={1} max={5000} step={1} onChange={(ev) => s.onScaleAnchor(ev.target.value)} style={{ width: 52, background: "transparent", border: "none", color: C.text, fontSize: 12.5, fontFamily: mono, textAlign: "right", outline: "none" }} />
              <span style={{ fontSize: 10, color: C.sub2, fontFamily: mono }}>mm</span>
            </div>
          )}
        </div>
        <textarea value={s.prompt} onChange={(ev) => s.onPrompt(ev.target.value)}
          placeholder={asm ? (editing ? `edit ${s.assemblyObject} — e.g. "make the legs 20mm longer", "add a shelf"` : "describe a multi-part object — e.g. \"a 4-legged stool ~80mm, 45 tall\"") : placeholder(s.branch, s.mode)}
          rows={1} style={{ flex: 1, resize: "none", background: "transparent", border: "none", color: C.text, fontSize: 14, lineHeight: 1.5, padding: "7px 0", minHeight: 30, maxHeight: 90, outline: "none" }} />
        <button onClick={onGo} style={generateStyle} disabled={blocked}>
          {s.genStatus === "running"
            ? <span style={{ width: 14, height: 14, border: "2px solid rgba(12,12,17,.35)", borderTopColor: C.bg, borderRadius: "50%", display: "inline-block", animation: "vspin .7s linear infinite" }} />
            : <Icon d={ICONS.sparkles} size={15} sw={1.8} />}
          {btnLabel}
        </button>
      </div>
    </div>
  );
}
