// MotionLab "Command Deck" design system.
// Viewport-first dark studio: deep blue-black canvas, floating glass panels, per-team accent.
// Type: Space Grotesk (display) · Inter (UI) · JetBrains Mono (data/measurements).
import type { CSSProperties } from "react";
import type { Team } from "./types";

export const C = {
  // base canvas — near-black with a cool blue undertone
  bg: "#07080D",
  bg2: "#0A0C13",
  panel: "#0D0F17",
  card: "#12141E",
  card2: "#161927",
  raised: "#1A1D2B",
  raised2: "#1F2333",
  inputBg: "#0B0D14",
  // borders / hairlines
  border: "#1B1E2B",
  border2: "#252937",
  border3: "#2F3445",
  // text ramp
  text: "#EEF0F6",
  sub: "#969BAE",
  sub2: "#6C7282",
  faint: "#565C6E",
  muted: "#A2A8BA",
  // accent (violet base — the Film accent; Robotics overrides via teamAccent)
  accent: "#8B5CF6",
  accent2: "#A78BFA",
  accent3: "#C9BCFB",
  // semantic
  good: "#3DD68C",
  goodSoft: "#86EFAC",
  warn: "#FBBF24",
  bad: "#F87171",
  badSoft: "#FCA5A5",
} as const;

export const fonts = {
  display: "'Space Grotesk', 'Inter', system-ui, sans-serif",   // headings / brand / numbers-as-titles
  ui: "'Inter', system-ui, -apple-system, sans-serif",          // body / labels / controls
  mono: "'JetBrains Mono', ui-monospace, monospace",            // measurements / data / code
} as const;

export const mono = fonts.mono;   // back-compat (widely imported)

// Glass surface for floating panels over the viewport.
export const glass = (opacity = 0.72): CSSProperties => ({
  background: `rgba(13, 15, 23, ${opacity})`,
  backdropFilter: "blur(20px) saturate(140%)",
  WebkitBackdropFilter: "blur(20px) saturate(140%)",
  border: `1px solid ${C.border2}`,
});

export const shadow = {
  panel: "0 20px 60px -12px rgba(0,0,0,.7), 0 0 0 1px rgba(255,255,255,.02)",
  pop: "0 14px 40px rgba(0,0,0,.6)",
  glow: (c: string) => `0 6px 28px ${c}`,
} as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 22, pill: 999 } as const;

// Per-team accent — black + purple palette. Robotics = cooler indigo-violet (technical),
// Film = warmer magenta-violet (cinematic). Two shades of purple, no off-palette hues.
export const teamAccent = (team: Team) =>
  team === "robotics"
    ? { a: "#7C5CFC", a2: "#9F86FF", a3: "#CBBEFB", glow: "rgba(124,92,252,.40)", soft: "rgba(124,92,252,.12)", line: "rgba(124,92,252,.32)", grad: "linear-gradient(135deg,#6D49F0,#9F86FF)" }
    : { a: "#A855F7", a2: "#C084FC", a3: "#E2CFFD", glow: "rgba(168,85,247,.42)", soft: "rgba(168,85,247,.13)", line: "rgba(168,85,247,.34)", grad: "linear-gradient(135deg,#9333EA,#C084FC)" };
