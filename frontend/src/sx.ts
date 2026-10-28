/* sx("css: string") → React.CSSProperties, memoized.
 *
 * The design handoff is an HTML prototype styled entirely with inline `style="…"` strings. Rather
 * than hand-transcribe thousands of declarations into camelCase objects (and introduce pixel drift),
 * we copy the prototype's style strings verbatim and parse them once at runtime. Values containing
 * var()/calc()/clip-path polygons pass straight through. */
import type { CSSProperties } from "react";

const cache = new Map<string, CSSProperties>();

export function sx(css: string): CSSProperties {
  let o = cache.get(css);
  if (o) return o;
  o = {};
  // split on ';' not inside parens (clip-path polygons, gradients contain ';'-free commas but be safe)
  let depth = 0, start = 0;
  const parts: string[] = [];
  for (let i = 0; i < css.length; i++) {
    const c = css[i];
    if (c === "(") depth++;
    else if (c === ")") depth--;
    else if (c === ";" && depth === 0) { parts.push(css.slice(start, i)); start = i + 1; }
  }
  parts.push(css.slice(start));
  for (const p of parts) {
    const idx = p.indexOf(":");
    if (idx < 0) continue;
    const rawKey = p.slice(0, idx).trim();
    const val = p.slice(idx + 1).trim();
    if (!rawKey || !val) continue;
    const key = rawKey.startsWith("--")
      ? rawKey
      : rawKey.replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    (o as any)[key] = val;
  }
  cache.set(css, o);
  return o;
}
