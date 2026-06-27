import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";

/** Boxicons glyph. `n` is the icon name without the `bx-`/`bxs-` prefix; pass `solid` for the filled set. */
export function Bx({ n, size = 18, solid = false, style, className = "" }: { n: string; size?: number; solid?: boolean; style?: CSSProperties; className?: string }) {
  return <i className={`bx ${solid ? "bxs" : "bx"}-${n} ${className}`} style={{ fontSize: size, ...style }} />;
}

/** Semantic icon names → Boxicons. One place to retarget glyphs. */
export const BX = {
  // teams / brand
  robotics: "wrench",
  film: "movie-play",
  // input modes / nav
  text: "text",
  image: "image-alt",
  library: "grid-alt",
  help: "help-circle",
  settings: "slider-alt",
  // view tools
  solid: "cube-alt",
  wire: "grid-alt",
  xray: "layer",
  dims: "ruler",
  heat: "bar-chart-alt-2",
  frame: "fullscreen",
  camera: "camera",
  play: "play",
  pause: "pause",
  light: "bulb",
  scale: "male",
  // actions
  close: "x",
  check: "check",
  checkCircle: "check-circle",
  plus: "plus",
  download: "download",
  retry: "refresh",
  warn: "error",
  bolt: "bolt-circle",
  cube: "cube",
  // robotics features
  hole: "circle",
  pattern: "grid",
  counterbore: "target-lock",
  countersink: "down-arrow-circle",
  fillet: "shape-circle",
  chamfer: "shape-triangle",
  pocket: "square-rounded",
  shell: "box",
} as const;

/** Button that swaps to a hover style. */
export function HoverButton({ base, hover, children, ...rest }: { base: CSSProperties; hover?: CSSProperties; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const [h, setH] = useState(false);
  return (
    <button {...rest} onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)} style={{ ...base, ...(h && hover ? hover : {}) }}>
      {children}
    </button>
  );
}
