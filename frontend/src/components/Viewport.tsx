import { useEffect, useRef } from "react";
import { useStudio } from "../store";
import { StudioScene } from "../viewport/scene";

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
      turntable: s.turntable, lightMood: s.lightMood, meshStl: s.meshStl,
    });
  }, [s.branch, s.spec, s.style, s.organicDetail, s.symmetry, s.targetHeight, s.view, s.heatmap, s.turntable, s.lightMood, s.meshStl]);

  return <div ref={host} style={{ position: "absolute", inset: 0, cursor: "grab" }} />;
}
