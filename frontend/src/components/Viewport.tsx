import { useEffect, useRef, useState } from "react";
import { useStudio } from "../store";
import { StudioScene } from "../viewport/scene";
import { C, fonts, teamAccent } from "../theme";
import { Bx, BX } from "./ui";

export function Viewport() {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<StudioScene | null>(null);

  const s = useStudio();

  useEffect(() => {
    if (!host.current) return;
    const sc = new StudioScene(host.current);
    scene.current = sc;
    // expose imperative viewport actions to the store for the stage toolbar
    useStudio.setState({
      frameView: () => sc.frame(),
      shotView: () => {
        const url = sc.snapshot();
        const a = document.createElement("a");
        a.href = url;
        a.download = (useStudio.getState().spec.object || "asset").replace(/\s+/g, "_") + ".png";
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
      },
    });
    return () => { sc.dispose(); scene.current = null; };
  }, []);

  useEffect(() => {
    scene.current?.update({
      branch: s.branch, spec: s.spec, style: s.style, organicDetail: s.organicDetail,
      symmetry: s.symmetry, targetHeight: s.targetHeight, view: s.view, heatmap: s.heatmap,
      turntable: s.turntable, lightMood: s.lightMood, meshStl: s.meshStl, meshGlb: s.meshGlb,
    });
  }, [s.branch, s.spec, s.style, s.organicDetail, s.symmetry, s.targetHeight, s.view, s.heatmap, s.turntable, s.lightMood, s.meshStl, s.meshGlb]);

  // when a generation finishes, snapshot the viewport into the new asset's library thumbnail.
  // a short delay lets the real mesh load (GLTFLoader.parse is async) and render at least one frame.
  useEffect(() => {
    if (s.genStatus !== "done") return;
    const id = setTimeout(() => {
      const url = scene.current?.snapshot();
      if (url) useStudio.getState().thumbLatestAsset(url);
    }, 1300);
    return () => clearTimeout(id);
  }, [s.genStatus, s.meshStl, s.meshGlb]);

  const ac = teamAccent(s.team);
  const [zoom, setZoom] = useState(false);
  // Esc closes the concept lightbox
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setZoom(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);

  return (
    <div ref={host} style={{ position: "absolute", inset: 0, cursor: "grab" }}>
      {/* film idle: no procedural preview for organic output — guide the first generation instead */}
      {s.team === "film" && !s.meshGlb && s.genStatus !== "running" && (
        <div style={{ position: "absolute", top: "46%", left: "calc(50% - 30px)", transform: "translate(-50%,-50%)", zIndex: 6, pointerEvents: "none", display: "flex", flexDirection: "column", alignItems: "center", gap: 13, textAlign: "center" }}>
          <span style={{ width: 60, height: 60, borderRadius: 18, background: ac.soft, border: `1px solid ${ac.line}`, display: "flex", alignItems: "center", justifyContent: "center", color: ac.a2, boxShadow: `0 0 40px ${ac.glow}` }}><Bx n={BX.film} size={28} /></span>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={{ fontFamily: fonts.display, fontSize: 16, fontWeight: 600, color: C.text }}>Describe an asset to begin</span>
            <span style={{ fontSize: 12, color: C.sub, maxWidth: 330, lineHeight: 1.55 }}>A text prompt or a reference image becomes a textured 3D mesh. Pick a quality tier on the right.</span>
          </div>
        </div>
      )}

      {/* text→mesh: the FLUX concept image TRELLIS reconstructed from (clear of the left dock) — click to zoom */}
      {s.branch === "organic" && s.conceptImg && (
        <button onClick={() => setZoom(true)} title="View concept image" className="concept-thumb"
          style={{ position: "absolute", bottom: 26, left: 86, zIndex: 6, padding: 0, borderRadius: 12, overflow: "hidden", border: `1px solid ${C.border3}`, boxShadow: "0 10px 30px rgba(0,0,0,.55)", background: C.card, cursor: "zoom-in" }}>
          <img src={s.conceptImg} alt="concept" style={{ display: "block", width: 124, height: 124, objectFit: "cover" }} />
          <span style={{ position: "absolute", top: 6, right: 6, width: 22, height: 22, borderRadius: 7, background: "rgba(7,8,13,.6)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff" }}><Bx n="zoom-in" size={13} /></span>
          <span style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: "4px 6px", fontSize: 8.5, letterSpacing: ".08em", textTransform: "uppercase", color: C.sub, background: "linear-gradient(transparent,rgba(0,0,0,.8))", textAlign: "center", fontFamily: fonts.mono }}>concept · FLUX</span>
        </button>
      )}

      {/* concept lightbox */}
      {zoom && s.conceptImg && (
        <div onClick={() => setZoom(false)} style={{ position: "fixed", inset: 0, zIndex: 40, display: "flex", alignItems: "center", justifyContent: "center", padding: 40, background: "rgba(5,6,11,.82)", backdropFilter: "blur(10px)", cursor: "zoom-out", animation: "fadeIn .15s ease both" }}>
          <div onClick={(ev) => ev.stopPropagation()} style={{ position: "relative", display: "flex", flexDirection: "column", gap: 12, alignItems: "center", animation: "fadeUp .2s ease both", cursor: "default" }}>
            <img src={s.conceptImg} alt="concept" style={{ maxWidth: "min(86vw, 900px)", maxHeight: "82vh", objectFit: "contain", borderRadius: 14, border: `1px solid ${C.border3}`, boxShadow: "0 30px 90px rgba(0,0,0,.7)" }} />
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: C.sub, fontFamily: fonts.mono, letterSpacing: ".04em" }}>
              <Bx n={BX.film} size={14} style={{ color: ac.a2 }} />FLUX concept · the image TRELLIS reconstructed
              <span style={{ color: C.faint }}>· click anywhere or Esc to close</span>
            </div>
            <button onClick={() => setZoom(false)} title="Close" style={{ position: "absolute", top: -12, right: -12, width: 32, height: 32, borderRadius: "50%", background: C.raised2, border: `1px solid ${C.border3}`, color: C.text, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}><Bx n="x" size={17} /></button>
          </div>
        </div>
      )}
    </div>
  );
}
