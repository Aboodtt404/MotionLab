import { C, fonts, mono, teamAccent } from "../theme";
import { useStudio, warningsFor, paramDefs, typeLabel } from "../store";
import type { FeatureType } from "../types";
import { Bx, BX, HoverButton } from "./ui";
import { ART_STYLES } from "../constants";

const featureIcon: Record<string, string> = {
  through_hole: BX.hole, hole_pattern: BX.pattern, counterbore: BX.counterbore,
  countersink: BX.countersink, fillet: BX.fillet, chamfer: BX.chamfer, pocket: BX.pocket, shell: BX.shell,
};

const label = (t: string) => (<div style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: ".1em", color: C.sub2, fontWeight: 700 }}>{t}</div>);
const numInput: React.CSSProperties = { width: 72, background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 8, color: C.text, fontSize: 13, fontFamily: mono, padding: "6px 9px", textAlign: "right" };

export function Settings() {
  const s = useStudio();
  const ac = teamAccent(s.team);
  const isHard = s.branch === "hard";
  const e = s.spec.envelope;
  const warns = warningsFor(s.branch, s.spec);
  const seg = (active: boolean): React.CSSProperties => ({ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "8px 0", borderRadius: 8, border: "none", cursor: "pointer", fontFamily: fonts.ui, background: active ? ac.soft : "transparent", color: active ? ac.a2 : C.sub, boxShadow: active ? `inset 0 0 0 1px ${ac.line}` : "none" });
  const envFields = s.spec.shape === "box"
    ? [{ k: "length", label: "Length" }, { k: "width", label: "Width" }, { k: "height", label: "Height" }]
    : s.spec.shape === "loft"
    ? [{ k: "length", label: "Length" }, { k: "width", label: "Base W" }, { k: "height", label: "Base H" }, { k: "width_top", label: "Tip W" }, { k: "height_top", label: "Tip H" }]
    : s.spec.shape === "cylinder"
    ? [{ k: "diameter", label: "Diameter" }, { k: "height", label: "Height" }]
    : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, color: ac.a2 }}>
      {/* film look */}
      {!isHard && (
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {label("Look")}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
            {ART_STYLES.map((a, i) => (
              <button key={a.label} onClick={() => s.setStyle(i)} style={{ display: "flex", flexDirection: "column", gap: 5, background: "transparent", border: "none", cursor: "pointer", padding: 0, fontFamily: fonts.ui }}>
                <span style={{ height: 38, borderRadius: 9, background: a.swatch, border: `2px solid ${s.style === i ? ac.a2 : "transparent"}` }} />
                <span style={{ fontSize: 9.5, color: s.style === i ? C.text : C.sub2, textAlign: "center" }}>{a.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* HARD — parametric spec editor */}
      {isHard && (
        <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            {label("Specification")}
            <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".08em", color: ac.a2, fontWeight: 700, display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: ac.a2, boxShadow: `0 0 6px ${ac.a}` }} />live</span>
          </div>
          <input value={s.spec.object} onChange={(ev) => s.onObjectName(ev.target.value)} style={{ width: "100%", background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 9, color: C.text, fontSize: 13.5, padding: "10px 12px", fontFamily: fonts.ui }} />
          <div style={{ display: "flex", background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 9, padding: 3, gap: 2 }}>
            <button style={seg(s.spec.shape === "box")} onClick={s.setBox}>Box</button>
            <button style={seg(s.spec.shape === "cylinder")} onClick={s.setCylinder}>Cylinder</button>
            <button style={seg(s.spec.shape === "loft")} onClick={s.setLoft}>Loft</button>
          </div>
          {(s.spec.shape === "revolve" || s.spec.shape === "sweep") && (
            <div style={{ fontSize: 10.5, color: C.sub2, lineHeight: 1.5, background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 9, padding: "9px 11px" }}>
              {s.spec.shape === "revolve" ? "Revolved" : "Swept"} body — its profile is defined via the prompt. Switch to Box/Cylinder/Loft to edit here.
            </div>
          )}
          {envFields.map((f) => (
            <div key={f.k} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <span style={{ fontSize: 11.5, color: C.sub }}>{f.label}</span>
                <input type="number" value={e[f.k]} min={1} max={400} step={1} onChange={(ev) => s.setEnvelope(f.k, ev.target.value, 1, 400)} style={numInput} />
              </div>
              <input type="range" value={e[f.k]} min={1} max={400} step={1} onChange={(ev) => s.setEnvelope(f.k, ev.target.value, 1, 400)} style={{ color: ac.a2 }} />
            </div>
          ))}

          {/* features */}
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {label("Features")}
            {s.spec.features.map((feature) => (
              <div key={feature.id} style={{ background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 11, padding: 11 }} onMouseEnter={() => s.setHighlight(feature.id)} onMouseLeave={() => s.setHighlight(null)}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 9 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 8, color: ac.a2 }}><Bx n={featureIcon[feature.type] || "shape-square"} size={15} /><span style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{typeLabel(feature.type)}</span></span>
                  <HoverButton onClick={() => s.removeFeature(feature.id)} base={{ background: "transparent", border: "none", color: C.faint, cursor: "pointer", padding: 2, display: "flex" }} hover={{ color: C.bad }}><Bx n="x" size={15} /></HoverButton>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {paramDefs(feature.type).map((p) => (
                    <div key={p.key} style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 70 }}>
                      <span style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".06em", color: C.sub2 }}>{p.label}</span>
                      {p.kind === "enum" ? (
                        <select value={String(feature.params[p.key])} onChange={(ev) => s.setFeatureEnum(feature.id, p.key, ev.target.value)} style={{ width: "100%", background: C.bg2, border: `1px solid ${C.border2}`, borderRadius: 7, color: C.text, fontSize: 12, fontFamily: mono, padding: "6px 8px" }}>
                          {p.options!.map((o) => (<option key={o} value={o}>{o}</option>))}
                        </select>
                      ) : (
                        <input type="number" value={Number(feature.params[p.key]) || 0} min={p.min} max={p.max} step={p.step} onChange={(ev) => s.updateFeatureParam(feature.id, p.key, ev.target.value, p.min!, p.max!)} style={{ width: "100%", background: C.bg2, border: `1px solid ${C.border2}`, borderRadius: 7, color: C.text, fontSize: 13, fontFamily: mono, padding: "6px 8px", textAlign: "right" }} />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div style={{ position: "relative" }}>
              <HoverButton onClick={s.toggleAddMenu} base={{ width: "100%", background: "transparent", border: `1px dashed ${C.border3}`, color: C.sub, fontSize: 12, fontWeight: 500, padding: 10, borderRadius: 10, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontFamily: fonts.ui }} hover={{ borderColor: ac.line, color: C.text }}><Bx n="plus" size={15} />Add feature</HoverButton>
              {s.addMenuOpen && (
                <div style={{ position: "absolute", left: 0, right: 0, bottom: "calc(100% + 6px)", background: C.raised2, border: `1px solid ${C.border3}`, borderRadius: 11, padding: 6, zIndex: 16, boxShadow: "0 14px 30px rgba(0,0,0,.55)", display: "flex", flexDirection: "column", gap: 2 }}>
                  <div style={{ display: "flex", gap: 5, padding: "2px 2px 5px" }}>
                    {[{ l: "M3", d: 3.4 }, { l: "M4", d: 4.5 }, { l: "M6", d: 6.6 }].map((m) => (
                      <HoverButton key={m.l} onClick={() => s.addFeature("through_hole", { diameter: m.d, pos_x: 0, pos_y: 0, axis: "z" })} base={{ flex: 1, background: C.inputBg, border: `1px solid ${C.border2}`, color: C.text, fontSize: 11, padding: 6, borderRadius: 7, cursor: "pointer", fontFamily: mono }} hover={{ borderColor: ac.line }}>{m.l}</HoverButton>
                    ))}
                  </div>
                  {(["through_hole", "hole_pattern", "counterbore", "countersink", "fillet", "chamfer", "pocket", "shell"] as FeatureType[]).map((t) => (
                    <HoverButton key={t} onClick={() => s.addFeature(t)} base={{ display: "flex", alignItems: "center", gap: 9, textAlign: "left", background: "transparent", border: "none", color: C.text, fontSize: 12, padding: "8px 9px", borderRadius: 7, cursor: "pointer", fontFamily: fonts.ui }} hover={{ background: C.border2 }}><Bx n={featureIcon[t]} size={14} style={{ color: ac.a2 }} />{typeLabel(t)}</HoverButton>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            {label("Tolerance · ± mm")}
            <input type="number" value={s.spec.tolerance} min={0.01} max={2} step={0.01} onChange={(ev) => s.onTolerance(ev.target.value)} style={{ ...numInput, width: 80 }} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {label("Fabrication")}
            <div style={{ display: "flex", background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 9, padding: 3, gap: 2 }}>
              <button style={seg(s.fab === "render")} onClick={() => s.setFab("render")}>Render</button>
              <button style={seg(s.fab === "fabricate")} onClick={() => s.setFab("fabricate")}>Fabricate</button>
            </div>
            {s.fab === "fabricate" && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <span style={{ fontSize: 11.5, color: C.sub }}>Min wall · mm</span>
                <input type="number" value={s.minWall} min={0.4} max={10} step={0.1} onChange={(ev) => s.onMinWall(ev.target.value)} style={{ ...numInput, width: 80 }} />
              </div>
            )}
          </div>

          {warns.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {warns.map((w, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", background: "rgba(248,113,113,.08)", border: "1px solid rgba(248,113,113,.35)", borderRadius: 9, padding: "8px 10px" }}>
                  <span style={{ color: C.bad, marginTop: 1 }}><Bx n="error" size={14} /></span>
                  <span style={{ fontSize: 11, color: C.badSoft, lineHeight: 1.5 }}>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* FILM — quality tier */}
      {!isHard && (
        <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {label("Quality")}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {([
                { t: "512", name: "Preview", time: "~30 s" },
                { t: "1024", name: "Standard", time: "~1 min" },
                { t: "1024_cascade", name: "High", time: "~1.5 min" },
                { t: "1536_cascade", name: "Max detail", time: "~2–2.5 min" },
              ] as const).map((q) => {
                const active = s.qualityTier === q.t;
                return (
                  <button key={q.t} onClick={() => s.setQualityTier(q.t)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", borderRadius: 10, cursor: "pointer", fontFamily: fonts.ui, textAlign: "left", border: `1px solid ${active ? ac.line : C.border2}`, background: active ? ac.soft : C.inputBg, color: active ? C.text : C.sub }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: active ? ac.a2 : C.border3, boxShadow: active ? `0 0 8px ${ac.a}` : "none" }} />
                      <span style={{ fontSize: 12.5, fontWeight: active ? 600 : 500 }}>{q.name}</span>
                    </span>
                    <span style={{ fontSize: 10.5, fontFamily: mono, color: active ? ac.a3 : C.sub2 }}>{q.time}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <div style={{ fontSize: 10.5, color: C.sub2, lineHeight: 1.55 }}>
            Iterate with <b style={{ color: C.sub }}>Preview</b>, then run <b style={{ color: C.sub }}>Max detail</b> for the hero asset.
          </div>
        </div>
      )}
    </div>
  );
}
