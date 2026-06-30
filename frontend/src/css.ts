/* Parse a CSS-text string ("display:flex;gap:7px;…") into a React style object.
 * The design (ported from a Claude Design dc.html prototype) computes inline styles as CSS strings —
 * both static template styles and dynamic ones (e.g. row/badge/gauge styles). React's `style` prop
 * needs an object, so every element renders `style={css("…")}` and copies the design's strings verbatim. */

import type { CSSProperties } from "react";

const cache = new Map<string, CSSProperties>();

function toCamel(prop: string): string {
  // custom properties (--accent, --accent-rgb) must stay literal; vendor prefixes (-webkit-…) camelize to WebkitX
  if (prop.startsWith("--")) return prop;
  return prop.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
}

export function css(text?: string | null): CSSProperties {
  if (!text) return {};
  const hit = cache.get(text);
  if (hit) return hit;
  const out: Record<string, string> = {};
  for (const decl of text.split(";")) {
    const i = decl.indexOf(":");
    if (i < 0) continue;
    const prop = decl.slice(0, i).trim();
    const val = decl.slice(i + 1).trim();
    if (!prop || !val) continue;
    out[toCamel(prop)] = val;
  }
  cache.set(text, out as CSSProperties);
  return out as CSSProperties;
}
