export type Branch = "hard" | "organic";
export type Mode = "text" | "image";
export type Fab = "render" | "fabricate";
export type View = "solid" | "wire" | "xray";
export type FeatureType = "through_hole" | "fillet" | "chamfer" | "pocket";

export interface Feature {
  id: string;
  type: FeatureType;
  params: Record<string, number>;
}

export interface Spec {
  object: string;
  shape: "box" | "cylinder";
  envelope: Record<string, number>; // box: length/width/height · cylinder: diameter/height
  features: Feature[];
  tolerance: number;
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
}
