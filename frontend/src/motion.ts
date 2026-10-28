/* Shared motion utilities. Rules of the house (theme.css tokens): micro 120ms / standard 200ms /
 * overlay 300ms, strong ease-out, transform+opacity only, nothing on high-frequency paths. */
import React, { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

const REDUCED = typeof matchMedia !== "undefined" &&
  matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Deferred unmount for exit animations: render while `mounted`, add data-closing (+ optional
 * data-exit="fade"|"flyout") while `closing` — theme.css plays the exit, then we unmount. */
export function useExit(open: boolean, ms = 130): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    if (open) { setMounted(true); setClosing(false); return; }
    if (!mounted) return;
    if (REDUCED) { setMounted(false); return; }
    setClosing(true);
    const t = setTimeout(() => { setMounted(false); setClosing(false); }, ms);
    return () => clearTimeout(t);
  }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps
  return { mounted, closing };
}

/** Count-up number: eases to `value` over ~0.5s on change (rAF, ease-out cubic), renders with
 * tabular figures so digits don't jitter. Formats with `fmt` (default: locale grouping). */
export function Tick({ value, fmt, style }: {
  value: number; fmt?: (n: number) => string; style?: React.CSSProperties;
}) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  const raf = useRef(0);
  useEffect(() => {
    if (REDUCED || !isFinite(value)) { setShown(value); return; }
    const start = performance.now(), a = from.current, dur = 500;
    cancelAnimationFrame(raf.current);
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - k, 3);
      setShown(a + (value - a) * e);
      if (k < 1) raf.current = requestAnimationFrame(step);
      else from.current = value;
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [value]);  // eslint-disable-line react-hooks/exhaustive-deps
  const f = fmt || ((n: number) => Math.round(n).toLocaleString());
  return React.createElement("span",
    { style: { fontVariantNumeric: "tabular-nums", ...style } }, f(shown));
}

/** Wrap a state change that swaps screens in a View Transition (crossfade via theme.css).
 * Degrades to a plain call where unsupported or under reduced motion. */
export function viewSwap(apply: () => void) {
  const d = document as any;
  if (REDUCED || typeof d.startViewTransition !== "function") { apply(); return; }
  d.startViewTransition(() => flushSync(apply));  // flushSync: commit the swap inside the capture
}
