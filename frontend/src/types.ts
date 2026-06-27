export type Team = "robotics" | "film";   // the two user teams; drives branch (robotics→hard, film→organic)
export type Branch = "hard" | "organic";
export type Mode = "text" | "image";
export type QualityTier = "512" | "1024" | "1024_cascade" | "1536_cascade";
export type Fab = "render" | "fabricate";
export type View = "solid" | "wire" | "xray";
// core mechanical feature set (matches cad_pipeline/spec.py discriminators)
export type FeatureType =
  | "through_hole" | "hole_pattern" | "counterbore" | "countersink"
  | "fillet" | "chamfer" | "pocket" | "shell";
export type Shape = "box" | "cylinder" | "loft" | "revolve" | "sweep";

export interface Feature {
  id: string;
  type: FeatureType;
  params: Record<string, number | string | number[]>;   // number · enum (axis/pattern/open_face) · tuple (pos)
}

export interface Spec {
  object: string;
  shape: Shape;
  envelope: Record<string, number>; // box: length/width/height · cylinder: diameter/height · loft: +width_top/height_top
  features: Feature[];
  tolerance: number;
  fabrication?: Fab;                 // render | fabricate (drives DFM gates backend-side)
  min_wall?: number;                 // mm — DFM min wall when fabricating
  profile?: number[][];              // revolve meridian [(r,z)…] — preserved on round-trip
  path?: number[][];                 // sweep path [(x,y,z)…]
}

export interface InspectionRow {
  name: string;
  req: string;
  meas: string;
  pass: boolean;
  gaugeLeft: string;
}

export interface OrganicCheck {
  label: string;
  value: string;
  ok: boolean;
}

export interface Asset {
  id: string;
  name: string;
  cls: Branch;
  ver: string;
  pass: boolean;
  thumb?: string | null;   // viewport snapshot (PNG data URL) captured at generation time
}
