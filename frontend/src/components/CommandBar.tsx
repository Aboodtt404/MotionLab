import { C, fonts, glass, teamAccent } from "../theme";
import { useStudio, warningsFor } from "../store";
import { Bx, HoverButton } from "./ui";
import { EXAMPLES, placeholder } from "../constants";

/** Bottom-center command bar — the primary input. Routes to Track A (robotics) / Track B (film) /
 * assembly planner depending on team + mode + assembly toggle. Logic mirrors the old PromptDock. */
export function CommandBar() {
  const s = useStudio();
  const ac = teamAccent(s.team);
  const asm = s.assemblyMode;
  const editing = asm && !!s.assembly;
  const organicText = s.branch === "organic" && s.mode === "text";
  const blocked = asm || organicText
    ? (s.genStatus === "running" || !s.prompt.trim())
    : warningsFor(s.branch, s.spec).length > 0 || (s.mode === "image" && !s.imageThumb) || s.genStatus === "running";
  const examples = EXAMPLES[s.branch];
  const btnLabel = asm ? (editing ? "Edit" : "Plan") : "Generate";
  const onGo = () => {
    if (blocked) return;
    if (asm) return s.planOrEdit();
    if (organicText) return s.generateMeshFromText(s.prompt, s.qualityTier);
    if (s.branch === "organic" && s.mode === "image" && s.imageThumb)
      return s.generateMeshFromImage(s.imageThumb.split(",")[1] || s.imageThumb, s.qualityTier);
    s.generate();
  };

  return (
    <div style={{ position: "absolute", bottom: 22, left: "50%", transform: "translateX(-50%)", zIndex: 18, width: "min(820px, calc(100% - 420px))" }}>
      {s.backendError && (
        <div style={{ marginBottom: 9, padding: "8px 13px", borderRadius: 11, background: "rgba(248,113,113,.12)", border: "1px solid rgba(248,113,113,.4)", color: C.badSoft, fontSize: 11.5, display: "flex", gap: 8, alignItems: "center" }}>
          <Bx n="error-circle" size={15} />generation failed: {String(s.backendError).slice(0, 150)}
        </div>
      )}

      {/* context row: assembly toggle + examples */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 7, marginBottom: 10, paddingLeft: 4 }}>
        {s.branch === "hard" && (
          <HoverButton onClick={s.toggleAssemblyMode}
            base={{ display: "flex", alignItems: "center", gap: 6, background: asm ? ac.soft : "rgba(13,15,23,.7)", backdropFilter: "blur(8px)", border: `1px solid ${asm ? ac.line : C.border2}`, color: asm ? ac.a2 : C.sub, fontSize: 11, fontWeight: 600, padding: "5px 11px", borderRadius: 999, cursor: "pointer", fontFamily: fonts.ui }}
            hover={{ borderColor: ac.line, color: asm ? ac.a2 : C.text }}><Bx n="been-here" size={13} />Assembly</HoverButton>
        )}
        {editing && (
          <span style={{ fontSize: 11, color: C.sub }}>editing <b style={{ color: C.text }}>{s.assemblyObject}</b> ·{" "}
            <button onClick={s.newDesign} style={{ background: "none", border: "none", color: ac.a2, fontSize: 11, cursor: "pointer", padding: 0, textDecoration: "underline" }}>new</button>
          </span>
        )}
        {!asm && examples.map((ex) => (
          <HoverButton key={ex} onClick={() => s.useExample(ex)} base={{ background: "rgba(13,15,23,.7)", backdropFilter: "blur(8px)", border: `1px solid ${C.border2}`, color: C.sub, fontSize: 11, padding: "5px 11px", borderRadius: 999, cursor: "pointer", fontFamily: fonts.ui }} hover={{ borderColor: ac.line, color: C.text }}>{ex}</HoverButton>
        ))}
      </div>

      {/* the bar */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 11, padding: "11px 11px 11px 14px", borderRadius: 18, ...glass(0.82), boxShadow: "0 22px 60px rgba(0,0,0,.6)" }}>
        <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 8, paddingBottom: 4 }}>
          {s.mode === "image" && !s.imageThumb && (
            <label title="Upload reference image" style={{ width: 36, height: 36, borderRadius: 10, border: `1px dashed ${C.border3}`, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: C.sub }}>
              <Bx n="image-add" size={18} />
              <input type="file" accept="image/*" onChange={(ev) => { const f = ev.target.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => s.onImageFile(r.result as string); r.readAsDataURL(f); }} style={{ display: "none" }} />
            </label>
          )}
          {s.mode === "image" && s.imageThumb && (
            <button onClick={s.clearImage} title="Remove image" style={{ width: 36, height: 36, borderRadius: 10, border: `1px solid ${C.border3}`, position: "relative", overflow: "hidden", cursor: "pointer", background: `center/cover url(${s.imageThumb})`, padding: 0 }}>
              <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(7,8,13,.5)", color: "#fff" }}><Bx n="x" size={14} /></span>
            </button>
          )}
          {s.mode === "image" && s.branch === "hard" && (
            <div title="Real-world size anchor — vision can't recover absolute scale" style={{ display: "flex", alignItems: "center", gap: 5, background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 10, padding: "5px 9px" }}>
              <span style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".06em", color: C.sub2, fontWeight: 700 }}>scale</span>
              <input type="number" value={s.scaleAnchor} min={1} max={5000} step={1} onChange={(ev) => s.onScaleAnchor(ev.target.value)} style={{ width: 48, background: "transparent", border: "none", color: C.text, fontSize: 12.5, fontFamily: fonts.mono, textAlign: "right", outline: "none" }} />
              <span style={{ fontSize: 10, color: C.sub2, fontFamily: fonts.mono }}>mm</span>
            </div>
          )}
        </div>
        <textarea value={s.prompt} onChange={(ev) => s.onPrompt(ev.target.value)}
          placeholder={asm ? (editing ? `edit ${s.assemblyObject} — e.g. "make the legs 20mm longer"` : "describe a multi-part object — e.g. \"a 4-legged stool ~80mm, 45 tall\"") : placeholder(s.branch, s.mode)}
          rows={1} style={{ flex: 1, resize: "none", background: "transparent", border: "none", color: C.text, fontSize: 14.5, lineHeight: 1.5, padding: "8px 0", minHeight: 30, maxHeight: 100, outline: "none", fontFamily: fonts.ui }} />
        <button onClick={onGo} disabled={blocked} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13.5, fontWeight: 600, fontFamily: fonts.ui, padding: "11px 22px", borderRadius: 12, border: "none", whiteSpace: "nowrap", cursor: blocked ? "not-allowed" : "pointer", opacity: blocked ? 0.45 : 1, background: ac.grad, color: "#06070C", boxShadow: `0 5px 20px ${ac.glow}`, letterSpacing: ".01em" }}>
          {s.genStatus === "running" && <span style={{ width: 15, height: 15, border: "2px solid rgba(6,7,12,.35)", borderTopColor: "#06070C", borderRadius: "50%", display: "inline-block", animation: "vspin .7s linear infinite" }} />}
          {btnLabel}
        </button>
      </div>
    </div>
  );
}
