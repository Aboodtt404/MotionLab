import { C, mono } from "../theme";
import { useStudio, warningsFor, modelChoices, paramDefs, typeLabel, iconPath } from "../store";
import type { FeatureType } from "../types";
import { HoverButton, Icon, ICONS } from "./ui";
import { ART_STYLES } from "../constants";

const label = (t: string) => (<div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".08em", color: C.sub, fontWeight: 600 }}>{t}</div>);
const segStyle = (active: boolean): React.CSSProperties => ({ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "8px 0", borderRadius: 8, border: "none", cursor: "pointer", fontFamily: "inherit", background: active ? "rgba(167,139,250,.16)" : "transparent", color: active ? C.accent2 : C.sub });
const numInput: React.CSSProperties = { width: 72, background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 7, color: C.text, fontSize: 13, fontFamily: mono, padding: "5px 8px", textAlign: "right" };

export function Settings() {
  const s = useStudio();
  const isHard = s.branch === "hard";
  const e = s.spec.envelope;
  const warns = warningsFor(s.branch, s.spec);
  const envFields = s.spec.shape === "box"
    ? [{ k: "length", label: "Length" }, { k: "width", label: "Width" }, { k: "height", label: "Height" }]
    : [{ k: "diameter", label: "Diameter" }, { k: "height", label: "Height" }];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>Settings</div>

      {/* class */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {label("Class")}
        <div style={{ display: "flex", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10, padding: 3, gap: 2 }}>
          <button style={segStyle(isHard)} onClick={() => s.setBranch("hard")}><Icon d={ICONS.cube} size={13} />Hard-surface</button>
          <button style={segStyle(!isHard)} onClick={() => s.setBranch("organic")}><Icon d={ICONS.organic} size={13} />Organic</button>
        </div>
      </div>

      {/* art style */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {label("Art style")}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
          {ART_STYLES.map((a, i) => (
            <button key={a.label} onClick={() => s.setStyle(i)} style={{ display: "flex", flexDirection: "column", gap: 5, background: "transparent", border: "none", cursor: "pointer", padding: 0, fontFamily: "inherit" }}>
              <span style={{ height: 38, borderRadius: 9, background: a.swatch, border: `2px solid ${s.style === i ? C.accent2 : "transparent"}` }} />
              <span style={{ fontSize: 9.5, color: s.style === i ? C.text : C.sub, textAlign: "center" }}>{a.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* model */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {label("Model")}
        <div style={{ position: "relative" }}>
          <button onClick={s.toggleModelMenu} style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 9, padding: "9px 11px", color: C.text, fontSize: 12.5, fontFamily: "inherit", cursor: "pointer" }}>
            {s.model || modelChoices(s.branch)[0]}
            <Icon d="M6 9l6 6 6-6" size={12} sw={2} />
          </button>
          {s.modelOpen && (
            <div style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)", background: C.raised2, border: `1px solid ${C.border3}`, borderRadius: 10, padding: 5, zIndex: 15, boxShadow: "0 14px 30px rgba(0,0,0,.5)", display: "flex", flexDirection: "column", gap: 1 }}>
              {modelChoices(s.branch).map((m) => (
                <HoverButton key={m} onClick={() => s.pickModel(m)} base={{ display: "flex", alignItems: "center", width: "100%", textAlign: "left", background: "transparent", border: "none", color: C.text, fontSize: 12, padding: "8px 10px", borderRadius: 6, cursor: "pointer", fontFamily: "inherit" }} hover={{ background: C.border2 }}>{m}{(s.model || modelChoices(s.branch)[0]) === m && <span style={{ marginLeft: "auto", color: C.accent2 }}>✓</span>}</HoverButton>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ height: 1, background: C.border }} />

      {/* HARD params */}
      {isHard && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            {label("Specification")}
            <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".07em", color: C.accent2, fontWeight: 700, display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 6, height: 6, borderRadius: "50%", background: C.accent2 }} />live</div>
          </div>
          <input value={s.spec.object} onChange={(ev) => s.onObjectName(ev.target.value)} style={{ width: "100%", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 9, color: C.text, fontSize: 13, padding: "9px 11px", fontFamily: "inherit" }} />
          <div style={{ display: "flex", background: C.card, border: `1px solid ${C.border2}`, borderRadius: 9, padding: 3, gap: 2 }}>
            <button style={segStyle(s.spec.shape === "box")} onClick={s.setBox}>Box</button>
            <button style={segStyle(s.spec.shape === "cylinder")} onClick={s.setCylinder}>Cylinder</button>
          </div>
          {envFields.map((f) => (
            <div key={f.k} style={{ display: "flex", flexDirection: "column", gap: 7 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <span style={{ fontSize: 11, color: C.sub }}>{f.label}</span>
                <input type="number" value={e[f.k]} min={1} max={400} step={1} onChange={(ev) => s.setEnvelope(f.k, ev.target.value, 1, 400)} style={numInput} />
              </div>
              <input type="range" value={e[f.k]} min={1} max={400} step={1} onChange={(ev) => s.setEnvelope(f.k, ev.target.value, 1, 400)} />
            </div>
          ))}

          {/* features */}
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {label("Features")}
            {s.spec.features.map((feature) => (
              <div key={feature.id} style={{ background: C.card, border: `1px solid ${C.border2}`, borderRadius: 10, padding: 10 }} onMouseEnter={() => s.setHighlight(feature.id)} onMouseLeave={() => s.setHighlight(null)}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, color: C.accent2 }}><Icon d={iconPath(feature.type)} size={14} sw={1.6} /><span style={{ fontSize: 11.5, fontWeight: 600, color: C.text }}>{typeLabel(feature.type)}</span></div>
                  <HoverButton onClick={() => s.removeFeature(feature.id)} base={{ background: "transparent", border: "none", color: C.faint, cursor: "pointer", padding: 2, display: "flex" }} hover={{ color: C.bad }}><Icon d={ICONS.close} size={13} sw={1.8} /></HoverButton>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {paramDefs(feature.type).map((p) => (
                    <div key={p.key} style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 72 }}>
                      <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".06em", color: C.sub }}>{p.label}</span>
                      <input type="number" value={feature.params[p.key]} min={p.min} max={p.max} step={p.step} onChange={(ev) => s.updateFeatureParam(feature.id, p.key, ev.target.value, p.min, p.max)} style={{ width: "100%", background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 7, color: C.text, fontSize: 13, fontFamily: mono, padding: "5px 8px", textAlign: "right" }} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div style={{ position: "relative" }}>
              <HoverButton onClick={s.toggleAddMenu} base={{ width: "100%", background: "transparent", border: `1px dashed ${C.border3}`, color: C.sub, fontSize: 12, fontWeight: 500, padding: 9, borderRadius: 9, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontFamily: "inherit" }} hover={{ borderColor: C.accent2, color: C.text }}><Icon d={ICONS.plus} size={13} sw={2} />Add feature</HoverButton>
              {s.addMenuOpen && (
                <div style={{ position: "absolute", left: 0, right: 0, bottom: "calc(100% + 6px)", background: C.raised2, border: `1px solid ${C.border3}`, borderRadius: 10, padding: 6, zIndex: 16, boxShadow: "0 12px 28px rgba(0,0,0,.5)", display: "flex", flexDirection: "column", gap: 3 }}>
                  <div style={{ display: "flex", gap: 5, padding: "2px 2px 5px" }}>
                    {[{ l: "M3", d: 3.4, fe: 10 }, { l: "M4", d: 4.5, fe: 12 }, { l: "M6", d: 6.6, fe: 14 }].map((m) => (
                      <HoverButton key={m.l} onClick={() => s.addFeature("through_hole", { diameter: m.d, from_edge: m.fe })} base={{ flex: 1, background: C.inputBg, border: `1px solid ${C.border2}`, color: C.text, fontSize: 11, padding: 6, borderRadius: 7, cursor: "pointer", fontFamily: mono }} hover={{ borderColor: C.accent2 }}>{m.l}</HoverButton>
                    ))}
                  </div>
                  {(["through_hole", "fillet", "chamfer", "pocket"] as FeatureType[]).map((t) => (
                    <HoverButton key={t} onClick={() => s.addFeature(t)} base={{ textAlign: "left", background: "transparent", border: "none", color: C.text, fontSize: 12, padding: "7px 9px", borderRadius: 6, cursor: "pointer", fontFamily: "inherit" }} hover={{ background: C.border2 }}>{typeLabel(t)}</HoverButton>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            {label("Tolerance · ± mm")}
            <input type="number" value={s.spec.tolerance} min={0.01} max={2} step={0.01} onChange={(ev) => s.onTolerance(ev.target.value)} style={{ ...numInput, width: 80 }} />
          </div>

          {warns.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {warns.map((w, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", background: "rgba(248,113,113,.07)", border: "1px solid rgba(248,113,113,.35)", borderRadius: 9, padding: "8px 10px" }}>
                  <span style={{ color: C.bad, flex: "0 0 14px", marginTop: 1 }}><Icon d={ICONS.warn} size={14} sw={1.8} /></span>
                  <span style={{ fontSize: 11, color: C.badSoft, lineHeight: 1.5 }}>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ORGANIC params */}
      {!isHard && (
        <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}><span style={{ fontSize: 11, color: C.sub }}>Detail</span><span style={{ fontSize: 12, color: C.text, fontFamily: mono }}>{["draft", "low", "medium", "high"][s.organicDetail]}</span></div>
            <input type="range" value={s.organicDetail} min={0} max={3} step={1} onChange={(ev) => s.setDetail(ev.target.value)} />
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 11, color: C.sub }}>Symmetry</span>
            <button onClick={s.toggleSymmetry} style={{ width: 38, height: 22, borderRadius: 11, border: "none", cursor: "pointer", background: s.symmetry ? C.accent2 : C.border3, position: "relative" }}><span style={{ position: "absolute", top: 2, left: s.symmetry ? 18 : 2, width: 18, height: 18, borderRadius: "50%", background: "#fff", transition: "left .15s" }} /></button>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            {label("Target height · mm")}
            <input type="number" value={s.targetHeight} min={10} max={400} step={5} onChange={(ev) => s.onTargetHeight(ev.target.value)} style={{ ...numInput, width: 80 }} />
          </div>
        </div>
      )}
    </div>
  );
}
