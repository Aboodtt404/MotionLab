import { useState } from "react";
import { C, fonts, mono, teamAccent } from "../theme";
import { useStudio } from "../store";
import { Bx, HoverButton } from "./ui";
import { glbToUsdz } from "../viewport/exportUsdz";

/** base64 payload → real file download (inverse of scene.ts decode). The actual asset, not a placeholder. */
function dlB64(name: string, b64: string, mime: string) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const a = document.createElement("a"); a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const cardStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 14, border: `1px solid ${C.border2}`, borderRadius: 14, background: C.card, padding: 15, animation: "fadeUp .3s ease both" };
const exportLabel: React.CSSProperties = { fontSize: 9, textTransform: "uppercase", letterSpacing: ".1em", color: C.sub2, fontWeight: 700 };

function ExportBtn({ b64, label, ext, mime, reason }: { b64: string | null | undefined; label: string; ext: string; mime: string; reason?: string }) {
  const s = useStudio();
  const base = (s.spec.object || s.assemblyObject || "asset").replace(/\s+/g, "_");
  if (!b64) return (
    <div title={reason || "not available"} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, border: `1px dashed ${C.border3}`, color: C.faint, cursor: "not-allowed", fontFamily: fonts.ui }}><Bx n="download" size={14} />{label}</div>
  );
  return (
    <HoverButton onClick={() => dlB64(`${base}.${ext}`, b64, mime)} base={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, background: C.raised2, border: `1px solid ${C.border3}`, color: C.text, cursor: "pointer", fontFamily: fonts.ui }} hover={{ borderColor: C.accent2 }}><Bx n="download" size={14} />{label}</HoverButton>
  );
}

function UsdzBtn({ b64 }: { b64: string | null | undefined }) {
  const s = useStudio();
  const [busy, setBusy] = useState(false);
  const base = (s.spec.object || "asset").replace(/\s+/g, "_");
  const run = async () => {
    if (!b64 || busy) return;
    setBusy(true);
    try {
      const bytes = await glbToUsdz(b64);
      const url = URL.createObjectURL(new Blob([bytes as unknown as BlobPart], { type: "model/vnd.usdz+zip" }));
      const a = document.createElement("a"); a.href = url; a.download = `${base}.usdz`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { console.error("USDZ export failed", err); }
    setBusy(false);
  };
  if (!b64) return (<div title="no mesh yet" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, border: `1px dashed ${C.border3}`, color: C.faint, cursor: "not-allowed", fontFamily: fonts.ui }}><Bx n="download" size={14} />USDZ</div>);
  return (
    <HoverButton onClick={run} disabled={busy} base={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, background: C.raised2, border: `1px solid ${C.border3}`, color: busy ? C.sub : C.text, cursor: busy ? "wait" : "pointer", fontFamily: fonts.ui }} hover={{ borderColor: C.accent2 }}>
      {busy ? <span style={{ width: 13, height: 13, border: `2px solid ${C.border3}`, borderTopColor: C.accent2, borderRadius: "50%", display: "inline-block", animation: "vspin .7s linear infinite" }} /> : <Bx n="download" size={14} />}USDZ
    </HoverButton>
  );
}

function RoboticsResultCard() {
  const s = useStudio();
  const offline = !!s.backendError && !s.meshStl;
  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ width: 27, height: 27, borderRadius: 8, background: offline ? "rgba(248,113,113,.14)" : "rgba(61,214,140,.14)", display: "flex", alignItems: "center", justifyContent: "center", color: offline ? C.bad : C.good }}><Bx n={offline ? "error" : "check"} size={16} /></span>
          <span style={{ fontFamily: fonts.display, fontSize: 14.5, fontWeight: 600 }}>{offline ? "Offline preview" : "Verified"}</span>
        </span>
        <span style={{ fontSize: 10.5, color: C.sub, fontFamily: mono }}>{s.attempts > 1 ? `${s.attempts} attempts` : "1 attempt"}</span>
      </div>

      {s.inspection && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 44px 48px 76px", gap: 6, padding: "0 4px 6px" }}>
            {["Feature", "Exp", "Meas", "±tol"].map((h, i) => (<span key={h} style={{ fontSize: 8.5, textTransform: "uppercase", letterSpacing: ".08em", color: C.sub2, fontWeight: 700, textAlign: i === 0 ? "left" : i === 3 ? "center" : "right" }}>{h}</span>))}
          </div>
          {s.inspection.map((r, i) => {
            const col = r.pass ? C.good : C.bad;
            return (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 44px 48px 76px", gap: 6, padding: "5px 4px", alignItems: "center" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}><span style={{ width: 6, height: 6, borderRadius: "50%", flex: "0 0 6px", background: col }} /><span style={{ fontSize: 11, color: C.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span></span>
                <span style={{ fontSize: 11.5, fontFamily: mono, color: C.sub, textAlign: "right" }}>{r.req}</span>
                <span style={{ fontSize: 11.5, fontFamily: mono, color: col, textAlign: "right", fontWeight: 500 }}>{r.meas}</span>
                <span style={{ position: "relative", height: 16, display: "flex", alignItems: "center" }}>
                  <span style={{ position: "absolute", left: 0, right: 0, height: 3, background: C.border2, borderRadius: 2 }} />
                  <span style={{ position: "absolute", left: "25%", right: "25%", height: 6, background: col, borderRadius: 2, opacity: 0.35 }} />
                  <span style={{ position: "absolute", left: "50%", top: 1, bottom: 1, width: 1, background: C.faint }} />
                  <span style={{ position: "absolute", left: r.gaugeLeft, top: "50%", transform: "translate(-50%,-50%)", width: 9, height: 9, borderRadius: "50%", background: col, border: `2px solid ${C.card}` }} />
                </span>
              </div>
            );
          })}
          {!offline && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "9px 4px 0", marginTop: 6, borderTop: `1px solid ${C.border2}` }}>
              <span style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.good }}><Bx n="check" size={13} />Watertight · manifold</span>
              <span style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.good }}><Bx n="check" size={13} />Selectors resolved · {s.spec.features.length} / {s.spec.features.length}</span>
            </div>
          )}
          {s.retryDiff && (<div style={{ marginTop: 8, padding: "8px 10px", borderRadius: 9, background: "rgba(61,214,140,.06)", fontSize: 10.5, fontFamily: mono, color: C.sub, lineHeight: 1.5 }}><span style={{ color: C.faint }}>corrected · </span>{s.retryDiff}</div>)}
        </div>
      )}

      {offline && <div style={{ fontSize: 10.5, color: C.badSoft, lineHeight: 1.5 }}>Backend unreachable — synthetic preview. Export is disabled until a real result is generated.</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        <span style={exportLabel}>Export</span>
        <div style={{ display: "flex", gap: 9 }}>
          <ExportBtn b64={s.meshStep} label="STEP" ext="step" mime="application/step" reason="regenerate to include STEP" />
          <ExportBtn b64={s.meshStl} label="STL" ext="stl" mime="model/stl" reason="no mesh yet" />
        </div>
        <span style={{ fontSize: 10, color: C.faint, lineHeight: 1.5 }}>STEP = parametric BREP for CAD/CAM · STL = mesh for 3D printing</span>
      </div>
    </div>
  );
}

function FilmResultCard() {
  const s = useStudio();
  const ac = teamAccent("film");
  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ width: 27, height: 27, borderRadius: 8, background: "rgba(61,214,140,.14)", display: "flex", alignItems: "center", justifyContent: "center", color: C.good }}><Bx n="check" size={16} /></span>
        <span style={{ fontFamily: fonts.display, fontSize: 14.5, fontWeight: 600 }}>Generated</span>
      </div>

      {s.organicReport && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {s.organicReport.map((c) => (
            <div key={c.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 4px", borderBottom: `1px solid rgba(38,41,55,.6)` }}>
              <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, color: C.text }}><span style={{ color: c.ok ? C.good : C.bad }}><Bx n={c.ok ? "check" : "error"} size={13} /></span>{c.label}</span>
              <span style={{ fontSize: 11.5, fontFamily: mono, color: c.ok ? C.sub : C.bad }}>{c.value}</span>
            </div>
          ))}
        </div>
      )}

      {!s.approved ? (
        <div style={{ display: "flex", gap: 9 }}>
          <button onClick={s.approveAsset} style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, border: "none", background: ac.grad, color: "#06070C", cursor: "pointer", fontFamily: fonts.ui }}><Bx n="check" size={14} />Approve</button>
          <HoverButton onClick={s.reseed} title="New variation (new seed)" base={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, background: C.raised2, border: `1px solid ${C.border3}`, color: C.text, cursor: "pointer", fontFamily: fonts.ui }} hover={{ borderColor: ac.line }}><Bx n="refresh" size={14} />Regenerate</HoverButton>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.good }}><Bx n="check" size={13} />Approved by art direction</div>
      )}

      {/* cinematic render pass — path-traced beauty still + turntable (photoreal, vs the raster viewport) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        <span style={exportLabel}>Cinematic render</span>
        {!s.renderPng ? (
          <HoverButton onClick={s.renderAsset} disabled={s.rendering || !s.meshGlb}
            base={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 10, borderRadius: 9, border: `1px solid ${ac.line}`, background: ac.soft, color: ac.a2, cursor: s.rendering ? "wait" : "pointer", fontFamily: fonts.ui }}
            hover={{ borderColor: ac.a2 }}>
            {s.rendering
              ? <><span style={{ width: 13, height: 13, border: `2px solid ${C.border3}`, borderTopColor: ac.a2, borderRadius: "50%", display: "inline-block", animation: "vspin .7s linear infinite" }} />{s.renderStage || "Path-tracing…"}</>
              : <><Bx n="movie-play" size={15} />Render — Cinematic (Cycles)</>}
          </HoverButton>
        ) : (
          <>
            <a href={s.renderPng} download="beauty.png" title="Open / save the beauty render">
              <img src={s.renderPng} alt="cinematic render" style={{ width: "100%", display: "block", borderRadius: 10, border: `1px solid ${C.border3}`, cursor: "zoom-in" }} />
            </a>
            <div style={{ display: "flex", gap: 9 }}>
              <a href={s.renderPng} download="beauty.png" style={{ flex: 1, textDecoration: "none" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 9, borderRadius: 9, background: C.raised2, border: `1px solid ${C.border3}`, color: C.text }}><Bx n="download" size={14} />Still (PNG)</div>
              </a>
              <ExportBtn b64={s.renderMp4} label="Turntable (MP4)" ext="mp4" mime="video/mp4" reason="no turntable" />
            </div>
            <HoverButton onClick={s.renderAsset} disabled={s.rendering} base={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 11, fontWeight: 500, padding: 7, borderRadius: 8, background: "transparent", border: "none", color: C.sub, cursor: "pointer", fontFamily: fonts.ui }} hover={{ color: C.text }}><Bx n="refresh" size={13} />Re-render</HoverButton>
          </>
        )}
        <span style={{ fontSize: 10, color: C.faint, lineHeight: 1.5 }}>Path-traced in Blender/Cycles — photoreal lighting + materials (~1–2 min)</span>
      </div>

      {/* cinematic MOTION pass — LTX-2.3 + 3DREAL turns the rendered turntable into a photoreal moving clip.
          Offered only after a render exists (it consumes the turntable MP4 + beauty still as first frame). */}
      {s.renderPng && s.renderMp4 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={exportLabel}>Cinematic motion · 3DREAL</span>
            <div style={{ display: "flex", gap: 4 }}>
              {(["light", "strong"] as const).map((v) => (
                <button key={v} onClick={() => s.setAnimVariant(v)} disabled={s.animating} title={v === "light" ? "Faithful — stays close to the input" : "Aggressive — more photoreal detail"}
                  style={{ fontSize: 9.5, textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 700, padding: "3px 8px", borderRadius: 6, cursor: s.animating ? "default" : "pointer", fontFamily: mono, border: `1px solid ${s.animVariant === v ? ac.line : C.border3}`, background: s.animVariant === v ? ac.soft : "transparent", color: s.animVariant === v ? ac.a2 : C.sub }}>{v}</button>
              ))}
            </div>
          </div>
          {!s.animMp4 ? (
            <HoverButton onClick={s.animateAsset} disabled={s.animating}
              base={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, fontSize: 12, fontWeight: 600, padding: 10, borderRadius: 9, border: `1px solid ${ac.line}`, background: ac.soft, color: ac.a2, cursor: s.animating ? "wait" : "pointer", fontFamily: fonts.ui }}
              hover={{ borderColor: ac.a2 }}>
              {s.animating
                ? <><span style={{ width: 13, height: 13, border: `2px solid ${C.border3}`, borderTopColor: ac.a2, borderRadius: "50%", display: "inline-block", animation: "vspin .7s linear infinite" }} />{s.animStage || "Animating…"}</>
                : <><Bx n="film" size={15} />Animate — Render-to-Real (LTX-2.3)</>}
            </HoverButton>
          ) : (
            <>
              <video src={"data:video/mp4;base64," + s.animMp4} autoPlay loop muted playsInline style={{ width: "100%", display: "block", borderRadius: 10, border: `1px solid ${ac.line}` }} />
              <ExportBtn b64={s.animMp4} label="Motion (MP4)" ext="mp4" mime="video/mp4" reason="no clip yet" />
              <HoverButton onClick={s.animateAsset} disabled={s.animating} base={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 11, fontWeight: 500, padding: 7, borderRadius: 8, background: "transparent", border: "none", color: C.sub, cursor: "pointer", fontFamily: fonts.ui }} hover={{ color: C.text }}><Bx n="refresh" size={13} />Re-animate</HoverButton>
            </>
          )}
          <span style={{ fontSize: 10, color: C.faint, lineHeight: 1.5 }}>Photoreal motion via LTX-2.3 + 3DREAL — keeps the turntable, makes materials real (~40s)</span>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        <span style={exportLabel}>Export mesh</span>
        <div style={{ display: "flex", gap: 9 }}>
          <ExportBtn b64={s.meshGlb} label="GLB" ext="glb" mime="model/gltf-binary" reason="no mesh yet" />
          <UsdzBtn b64={s.meshGlb} />
        </div>
        <span style={{ fontSize: 10, color: C.faint, lineHeight: 1.5 }}>GLB / USDZ with PBR — import into Blender / Houdini / Unreal</span>
      </div>
    </div>
  );
}

export function ResultCard() {
  const s = useStudio();
  if (s.genStatus !== "done") return null;
  return s.branch === "hard" ? <RoboticsResultCard /> : <FilmResultCard />;
}
