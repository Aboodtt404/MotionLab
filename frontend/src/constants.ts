import type { Branch } from "./types";

/** Art-style swatches → the style index drives the viewport material (and, in the
 * real pipeline, the T2I concept-art look that seeds image-to-3D — Track C). */
export const ART_STYLES = [
  { label: "Steel", swatch: "linear-gradient(135deg,#d4d8e2,#8a8fa0)" },
  { label: "Matte", swatch: "linear-gradient(135deg,#a6abb6,#6e7280)" },
  { label: "Aluminum", swatch: "linear-gradient(135deg,#cfd4dc,#9aa0ac)" },
  { label: "Amethyst", swatch: "linear-gradient(135deg,#b9a6f5,#6d5bb0)" },
];

export const EXAMPLES: Record<Branch, string[]> = {
  hard: ["80×50×30 bracket, 4mm fillet, ⌀12 hole", "⌀40 collar, 25mm tall", "vent grille 60×60×4"],
  organic: ["weathered gargoyle bust", "alien rock cluster", "ornate dagger hilt"],
};

export const placeholder = (branch: Branch, mode: "text" | "image") =>
  mode === "image"
    ? "Describe the part in the image — add any dimensions you know"
    : branch === "hard"
    ? "Describe a part with dimensions — e.g. 80×50×30 bracket, ⌀12 hole, ±0.1"
    : "Describe a creature, prop, or environment";
