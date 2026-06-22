import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";

/** Icon — single-path stroke SVG matching the prototype's icon style. */
export function Icon({ d, size = 18, sw = 1.7, fill = "none" }: { d: string; size?: number; sw?: number; fill?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">
      {d.split("||").map((p, i) => (<path key={i} d={p} />))}
    </svg>
  );
}

/** Button that swaps to a hover style — replicates the prototype's style-hover attribute. */
export function HoverButton({ base, hover, children, ...rest }: { base: CSSProperties; hover?: CSSProperties; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const [h, setH] = useState(false);
  return (
    <button {...rest} onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)} style={{ ...base, ...(h && hover ? hover : {}) }}>
      {children}
    </button>
  );
}

export const ICONS = {
  bolt: "M3 16V8l9-5 9 5v8l-9 5z||M3 8l9 5 9-5M12 13v8",
  cube: "M12 2l9 5v10l-9 5-9-5V7z",
  wire: "M12 2l9 5v10l-9 5-9-5V7z||M12 2v20M3 7l9 5 9-5M3 17l9-5 9 5",
  layers: "M12 2L2 7l10 5 10-5z||M2 12l10 5 10-5M2 17l10 5 10-5",
  sparkles: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z",
  image: "M3 5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2z||M8 11a2 2 0 100-4 2 2 0 000 4M21 15l-5-5L5 21",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  organic: "M12 3c4 2 6 5 6 9 0 4-3 6-6 6s-6-2-6-6c0-4 2-7 6-9z",
  dims: "M3 6v12M21 6v12M3 12h18",
  heat: "M3 12h4l3 8 4-16 3 8h4",
  frame: "M4 9V5a1 1 0 011-1h4M20 9V5a1 1 0 00-1-1h-4M4 15v4a1 1 0 001 1h4M20 15v4a1 1 0 01-1 1h-4",
  camera: "M4 8a2 2 0 012-2h1l1.5-2h7L18 6h1a2 2 0 012 2v9a2 2 0 01-2 2H6a2 2 0 01-2-2z||M12 12.5a3.2 3.2 0 100 0.01",
  close: "M6 6l12 12M18 6L6 18",
  check: "M20 6L9 17l-5-5",
  plus: "M12 5v14M5 12h14",
  download: "M12 3v12m-4-4l4 4 4-4M4 21h16",
  retry: "M3 12a9 9 0 109-9||M3 4v5h5",
  warn: "M12 8v5M12 16.5v.5||M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
};
