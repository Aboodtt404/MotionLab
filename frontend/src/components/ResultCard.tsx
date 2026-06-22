import { C, mono } from "../theme";
import { useStudio } from "../store";
import { HoverButton, Icon, ICONS } from "./ui";

const dl = (name: string, content: string, mime: string) => {
  const b = new Blob([content], { type: mime }); const u = URL.createObjectURL(b);
  const a = document.createElement("a"); a.href = u; a.download = name; document.body.appendChild(a); a.click();
  document.body.removeChild(a); setTimeout(() => URL.revokeObjectURL(u), 1000);
};

export function ResultCard() {
  const s = useStudio();
  if (s.genStatus !== "done") return null;
  const isHard = s.branch === "hard";
  const base = (s.spec.object || "asset").replace(/\s+/g, "_");
  const fab = s.fab === "fabricate";

  const exportButtons = fab
    ? isHard
      ? [{ label: "STEP", fn: () => dl(base + ".step", "ISO-10303-21;\nHEADER;\nFILE_NAME('" + base + "');\nENDSEC;\nEND-ISO-10303-21;\n", "application/step") }, { label: "STL", fn: () => dl(base + ".stl", "solid " + base + "\nendsolid\n", "model/stl") }]
      : [{ label: "STL", fn: () => dl(base + ".stl", "solid " + base + "\nendsolid\n", "model/stl") }, { label: "GLB", fn: () => dl(base + ".glb", "glb placeholder", "model/gltf-binary") }]
    : [{ label: "glTF", fn: () => dl(base + ".glb", "glb placeholder", "model/gltf-binary") }, { label: "USD", fn: () => dl(base + ".usd", "#usda 1.0\n( generator = \"MotionLab\" )\n", "model/vnd.usd") }];

  const ring = `conic-gradient(${C.accent2} ${s.fidelity * 3.6}deg, ${C.border2} 0)`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, border: `1px solid ${C.border2}`, borderRadius: 16, background: C.card, padding: 15, animation: "fadeUp .3s ease both" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ width: 26, height: 26, borderRadius: 8, background: "rgba(52,211,153,.14)", display: "flex", alignItems: "center", justifyContent: "center", color: C.good }}><Icon d={ICONS.check} size={15} sw={2.2} /></span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{isHard ? "Verified" : "Printable"}</span>
        </div>
        <span style={{ fontSize: 10.5, color: C.sub, fontFamily: mono }}>{s.attempts > 1 ? `${s.attempts} attempts` : "1 attempt"}</span>
      </div>

      {/* HARD — dimensional inspection */}
      {isHard && s.inspection && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 44px 48px 78px", gap: 6, padding: "0 4px 6px" }}>
            {["Feature", "Exp", "Meas", "±tol"].map((h, i) => (
              <span key={h} style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".08em", color: C.sub2, fontWeight: 600, textAlign: i === 0 ? "left" : i === 3 ? "center" : "right" }}>{h}</span>
            ))}
          </div>
          {s.inspection.map((r, i) => {
            const col = r.pass ? C.good : C.bad;
            return (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 44px 48px 78px", gap: 6, padding: "5px 4px", alignItems: "center" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}><span style={{ width: 6, height: 6, borderRadius: "50%", flex: "0 0 6px", background: col }} /><span style={{ fontSize: 11, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span></span>
                <span style={{ fontSize: 11.5, fontFamily: mono, color: C.sub, textAlign: "right" }}>{r.req}</span>
                <span style={{ fontSize: 11.5, fontFamily: mono, color: col, textAlign: "right", fontWeight: 500 }}>{r.meas}</span>
                <span style={{ position: "relative", height: 16, display: "flex", alignItems: "center" }}>
                  <span style={{ position: "absolute", left: 0, right: 0, height: 3, background: C.border2, borderRadius: 2 }} />
                  <span style={{ position: "absolute", left: "25%", right: "25%", height: 6, background: col, borderRadius: 2, opacity: 0.4 }} />
                  <span style={{ position: "absolute", left: "50%", top: 1, bottom: 1, width: 1, background: C.faint }} />
                  <span style={{ position: "absolute", left: r.gaugeLeft, top: "50%", transform: "translate(-50%,-50%)", width: 9, height: 9, borderRadius: "50%", background: col, border: `2px solid ${C.card}` }} />
                </span>
              </div>
            );
          })}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "9px 4px 0", marginTop: 6, borderTop: `1px solid ${C.border2}` }}>
            <span style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.good }}><Icon d={ICONS.check} size={13} sw={2} />Watertight · manifold</span>
            {/* Track A core IP: resolve-twice selector binding */}
            <span style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.good }}><Icon d={ICONS.check} size={13} sw={2} />Selectors resolved · {s.spec.features.length} / {s.spec.features.length}</span>
          </div>
          {s.retryDiff && (
            <div style={{ marginTop: 8, padding: "8px 10px", borderRadius: 9, background: "rgba(52,211,153,.06)", fontSize: 10.5, fontFamily: mono, color: C.sub, lineHeight: 1.5 }}><span style={{ color: C.faint }}>corrected · </span>{s.retryDiff}</div>
          )}
        </div>
      )}

      {/* ORGANIC — fidelity + printability + human sign-off */}
      {!isHard && s.organicReport && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ position: "relative", width: 56, height: 56, flex: "0 0 56px" }}>
              <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: ring }} />
              <div style={{ position: "absolute", inset: 5, borderRadius: "50%", background: C.card }} />
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}><span style={{ fontSize: 18, fontWeight: 700, fontFamily: mono, color: C.text }}>{s.fidelity}</span></div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: ".08em", color: C.sub, fontWeight: 600 }}>Visual fidelity · VLM judge</span>
              <span style={{ fontSize: 11.5, color: C.text, lineHeight: 1.45 }}>Best of {s.bestOfN} candidates · 9-view + normals</span>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {s.organicReport.map((c) => (
              <div key={c.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 4px", borderBottom: `1px solid rgba(38,38,47,.5)` }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: C.text }}><span style={{ color: c.ok ? C.good : C.bad }}><Icon d={c.ok ? ICONS.check : ICONS.warn} size={13} sw={2} /></span>{c.label}</span>
                <span style={{ fontSize: 11.5, fontFamily: mono, color: c.ok ? C.sub : C.bad }}>{c.value}</span>
              </div>
            ))}
          </div>
          {/* Track B: aesthetics have no objective fixpoint → human art-direction sign-off */}
          {!s.approved ? (
            <div style={{ display: "flex", gap: 9 }}>
              <button onClick={s.approveAsset} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, border: "none", background: `linear-gradient(135deg,${C.accent},${C.accent2})`, color: C.bg, cursor: "pointer" }}><Icon d={ICONS.check} size={13} sw={2.2} />Approve</button>
              <HoverButton onClick={() => s.generate()} base={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, background: C.raised2, border: `1px solid ${C.border3}`, color: C.text, cursor: "pointer" }} hover={{ borderColor: C.accent2 }}><Icon d={ICONS.retry} size={13} sw={1.8} />Regenerate</HoverButton>
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.good, padding: "2px 2px" }}><Icon d={ICONS.check} size={13} sw={2} />Approved by art direction</div>
          )}
        </>
      )}

      {/* export */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 9, padding: 3, gap: 2 }}>
          {(["render", "fabricate"] as const).map((f) => (
            <button key={f} onClick={() => s.setFab(f)} style={{ flex: 1, fontSize: 12, fontWeight: 600, padding: "7px 0", borderRadius: 7, border: "none", cursor: "pointer", textTransform: "capitalize", fontFamily: "inherit", background: s.fab === f ? "rgba(167,139,250,.16)" : "transparent", color: s.fab === f ? C.accent2 : C.sub }}>{f}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 9 }}>
          {exportButtons.map((x) => (
            <HoverButton key={x.label} onClick={x.fn} base={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, background: C.raised2, border: `1px solid ${C.border3}`, color: C.text, cursor: "pointer" }} hover={{ borderColor: C.accent2 }}><Icon d={ICONS.download} size={13} sw={1.8} />{x.label}</HoverButton>
          ))}
        </div>
        {fab && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9, borderTop: `1px solid ${C.border2}`, paddingTop: 11 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 11.5, color: C.text }}>Hollow body</span>
              <button onClick={s.toggleHollow} style={{ width: 38, height: 22, borderRadius: 11, border: "none", cursor: "pointer", background: s.hollow ? C.accent2 : C.border3, position: "relative", transition: "background .15s" }}><span style={{ position: "absolute", top: 2, left: s.hollow ? 18 : 2, width: 18, height: 18, borderRadius: "50%", background: "#fff", transition: "left .15s" }} /></button>
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 11.5, color: C.text }}>Min wall · mm</span>
              <input type="number" value={s.minWall} min={0.4} max={10} step={0.1} onChange={(ev) => s.onMinWall(ev.target.value)} style={{ width: 72, background: C.inputBg, border: `1px solid ${C.border2}`, borderRadius: 7, color: C.text, fontSize: 13, fontFamily: mono, padding: "6px 8px", textAlign: "right" }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
