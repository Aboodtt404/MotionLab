/* Bridge to the Track A pipeline (cad_pipeline/server.py). Converts the Studio Spec to
 * the backend contract, POSTs /generate, and returns the REAL verifier report + mesh. */
import type { InspectionRow, Spec } from "./types";

const API_BASE = (import.meta as any).env?.VITE_CAD_API || "http://127.0.0.1:8765";

export interface BackendRow {
  name: string; expected: number | string; measured: number | string | null;
  delta: number | null; within_tol: boolean; category: string;
}
export interface GenerateResponse {
  passed: boolean; attempts: number; history: any[]; code: string | null;
  spec?: any; // the interpreted backend spec (when generated from a prompt)
  inspection: BackendRow[]; mesh_stl_b64: string | null;
}

/** Studio Spec ({type,params}) → backend Spec (flat feature fields). */
export function specToBackend(spec: Spec): any {
  return {
    object: spec.object,
    shape: spec.shape,
    envelope: spec.envelope,
    features: spec.features.map((f) => ({ type: f.type, ...f.params })),
    tolerance: spec.tolerance,
  };
}

/** Backend verifier rows → the flat InspectionRow the ResultCard renders. */
export function toInspection(rows: BackendRow[], tol: number): InspectionRow[] {
  return rows.map((r) => {
    const req = typeof r.expected === "number" ? r.expected.toFixed(2) : String(r.expected);
    const meas = r.measured == null ? "—" : typeof r.measured === "number" ? r.measured.toFixed(2) : String(r.measured);
    const delta = typeof r.delta === "number" ? r.delta : 0;
    const left = Math.max(4, Math.min(96, 50 + (delta / (2 * (tol || 0.1))) * 50));
    return { name: r.name, req, meas, pass: r.within_tol, gaugeLeft: left.toFixed(1) + "%" };
  });
}

async function post(body: any, route = "/generate"): Promise<any> {
  const res = await fetch(API_BASE + route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`backend ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
}

/** Generate from a typed spec (right-panel editor / image mode). */
export const generateBackend = (spec: Spec, useModel = false, maxAttempts = 3): Promise<GenerateResponse> =>
  post({ spec: specToBackend(spec), use_model: useModel, max_attempts: maxAttempts });

/** Generate from a natural-language prompt — the model interprets it into a spec (Track A text→spec). */
export const generateFromPrompt = (prompt: string, useModel = false, maxAttempts = 3): Promise<GenerateResponse> =>
  post({ prompt, use_model: useModel, max_attempts: maxAttempts });

export interface AssemblyResponse {
  passed: boolean; assembly: any; components: number; object: string;
  inspection: BackendRow[]; mesh_stl_b64: string | null;
}
/** PLAN a multi-part assembly from a prompt (the planner). */
export const planAssembly = (prompt: string): Promise<AssemblyResponse> => post({ prompt }, "/plan");
/** EDIT the current assembly with an instruction (the edit-loop). */
export const editAssembly = (assembly: any, instruction: string): Promise<AssemblyResponse> =>
  post({ assembly, instruction }, "/edit");

/** Backend spec (flat features) → Studio Spec ({type,params}) so the editor reflects the interpretation. */
export function backendToSpec(bs: any, base: Spec): Spec {
  const features = (bs.features || []).map((f: any, i: number) => {
    const { type, ...params } = f;
    return { id: `f${Date.now()}_${i}`, type, params };
  });
  return {
    object: bs.object ?? base.object,
    shape: bs.shape ?? base.shape,
    envelope: bs.envelope ?? base.envelope,
    features,
    tolerance: bs.tolerance ?? base.tolerance,
  } as unknown as Spec;
}
