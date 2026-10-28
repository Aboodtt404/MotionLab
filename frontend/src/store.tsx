/* Studio state + the real wiring layer.
 *
 * Everything is REAL: generation tasks submit to the async job APIs (Track A CAD :8765 via /api/cad,
 * Track B mesh :8770 via /api/trackb) and poll until done; auth + per-user projects/library live in
 * the studio service (/api/studio → studio_api/server.py, SQLite + bearer sessions). Model lists are
 * light metadata; artifacts hydrate on open. persist.ts (IndexedDB) remains only as the one-time
 * migration source for pre-auth libraries. See docs/design/frontend-wiring.md. */
import { createContext, useContext } from "react";
import * as api from "./api";
import { loadState } from "./persist";

export type Screen = "login" | "dashboard" | "projects" | "project" | "settings" | "editor" | "result" | "docs";
export type Track = "cad" | "mesh";
export type CadKind = "part" | "assembly";
export type MeshTier = "fast" | "quality" | "hero";
export type EngineKind = "cad" | "assembly" | "mesh";

export const TIER_LABEL: Record<MeshTier, string> = { fast: "Preview", quality: "High", hero: "Max detail" };
export const TIER_EST: Record<MeshTier, string> = { fast: "~40 s", quality: "~2 min", hero: "~5 min" };

export interface Attempt { n: number; fails: number; status: "passed" | "repair" | "failed"; }

export interface Model {
  id: string;
  name: string;
  prompt: string;
  project: string;
  engine: EngineKind;
  status: "verified" | "failed";
  ts: number;
  thumb?: string | null;
  // artifacts — CAD
  stl?: string | null;
  step?: string | null;
  code?: string | null;
  spec?: any;
  assembly?: any;
  inspection?: api.CadRow[];
  attempts?: number;
  history?: any[];
  // artifacts — mesh
  glbId?: string | null;
  glb?: string | null;
  report?: any;
  tier?: MeshTier;
  seconds?: number;
  // per-part meshes streamed during assembly construction (kept → real per-part interaction)
  parts?: api.CadPart[];
}

/** Live mid-job artifacts for the generation theater (Result screen, running phase). */
export interface Theater {
  concept?: string | null;        // FLUX concept (or the uploaded image) — data URL
  views: string[];                // MV-Adapter multi-view renders — data URLs
  specStream?: string;            // assembly spec growing token-by-token (planner streaming)
  specObj?: any;                  // parsed part Spec (published whole, typewritten client-side)
  assembly?: any;                 // locked assembly JSON of the current attempt
  attempt?: number;
  partNames: string[];            // construction checklist, in placement order
}

export interface Task {
  id: string;
  name: string;
  engine: EngineKind;
  stage: string;
  elapsed: number;
  estSec: number;
  running: boolean;
  done: boolean;
  error?: string | null;
  modelId?: string;      // set when the finished result lands in the library
}

export interface User { first: string; last: string; email: string; }

export interface EngineStatus { cad: api.EngineHealth | "unknown"; assembly: api.EngineHealth | "unknown"; mesh: api.EngineHealth | "unknown"; }

/* ------------------------------ helpers ------------------------------ */

export function catColor(c: string): string {
  return ({
    dimensional: "#5aa9e6", kinematic: "#b58cff", structural: "#43c9b0", fit: "#e0a63a",
    budget: "#4bd0d8", uv: "#e879c5", render: "#37d67a", component: "#9a9aa0",
    assembly: "#b58cff", statics: "#43c9b0", frame: "#5aa9e6",
  } as Record<string, string>)[c] || "#9a9aa0";
}

export function timeAgo(ts: number): string {
  const s = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return s + "s ago";
  const m = Math.round(s / 60);
  if (m < 60) return m + "m ago";
  const h = Math.round(m / 60);
  if (h < 48) return h + "h ago";
  return Math.round(h / 24) + "d ago";
}

export function fmtVal(v: any): string {
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2);
  if (Array.isArray(v)) return v.map(fmtVal).join(" × ");
  return String(v);
}

export function titleFromPrompt(p: string): string {
  const t = (p || "").trim().replace(/\s+/g, " ");
  if (!t) return "Untitled model";
  const cut = t.slice(0, 42);
  return (cut.length < t.length ? cut.replace(/\s\S*$/, "") + "…" : cut).replace(/^./, (c) => c.toUpperCase());
}

/** Real attempt timeline from the CAD server's history[] (one entry per verify round). */
export function attemptsFromHistory(history: any[] | undefined, passed: boolean, attempts?: number): Attempt[] {
  if (history && history.length) {
    return history.map((h: any, i: number) => {
      const fails = typeof h?.fails === "number" ? h.fails
        : Array.isArray(h?.rows) ? h.rows.filter((r: any) => !r.within_tol).length
        : Array.isArray(h) ? h.length
        : typeof h === "number" ? h : 0;
      const last = i === history.length - 1;
      return { n: i + 1, fails, status: last ? (passed ? "passed" : "failed") : "repair" } as Attempt;
    });
  }
  const n = Math.max(1, attempts || 1);
  return Array.from({ length: n }, (_, i) => ({
    n: i + 1, fails: i === n - 1 && passed ? 0 : -1,
    status: i === n - 1 ? (passed ? "passed" : "failed") : "repair",
  }));
}

/* ------------------------------ the store contract ------------------------------ */

export interface Studio {
  // routing
  screen: Screen;
  nav: string;
  go: (screen: Screen, nav?: string) => void;

  // auth (real — studio_api service, bearer token)
  user: User | null;
  authBusy: boolean;
  signIn: (email: string, password: string) => Promise<string | null>;      // error msg or null
  signUp: (data: { email: string; password: string; first: string; last: string }) => Promise<string | null>;
  signOut: () => void;
  updateUser: (u: Partial<User> & { password?: string }) => Promise<void>;

  // generation inputs
  track: Track; setTrack: (t: Track) => void;
  cadKind: CadKind; setCadKind: (k: CadKind) => void;
  meshTier: MeshTier; setMeshTier: (t: MeshTier) => void;
  prompt: string; setPrompt: (p: string) => void;

  // engines + tasks
  engines: EngineStatus;
  tasks: Task[];
  startGenerate: (opts?: { prompt?: string; imageB64?: string; multiview?: boolean }) => void;

  // library / projects (per-user, server-backed)
  library: Model[];
  projects: string[];
  activeProject: string;
  openProject: (name: string) => void;
  selectProject: (name: string) => void;          // generation destination (no navigation)
  newProject: (name?: string) => void;
  assignProject: (modelId: string, project: string) => void;   // move a model between projects
  deleteModel: (id: string) => void;
  deleteProject: (name: string) => void;

  // result + editor focus (openModel hydrates artifacts from the server when absent)
  current: Model | null;
  liveTask: Task | null;
  openModel: (m: Model, where: "result" | "editor") => void;
  reGenerate: () => void;
  editInstruction: (instruction: string) => void;

  // toast
  toast: string | null;
  showToast: (msg: string) => void;

  // generate modal
  genModalOpen: boolean;
  setGenModalOpen: (b: boolean) => void;
}

export const StudioCtx = createContext<Studio>(null as any);
export const useStudio = () => useContext(StudioCtx);

/* ------------------------------ pure wiring helpers used by App ------------------------------ */

export async function pollHealth(): Promise<EngineStatus> {
  const [cad, mesh] = await Promise.all([api.health("cad"), api.health("trackb")]);
  return { cad, assembly: cad, mesh };   // Assembly = the CAD process's /plan lane
}

/** One-time migration: the pre-auth builds kept the library in IndexedDB (per browser). On first
 * sign-in with an empty server library, push those models up so nothing generated tonight is lost,
 * then leave IndexedDB alone (it stops being written). */
export async function migrateLocalLibrary(): Promise<Model[]> {
  try {
    const st = await loadState();
    return (st?.library as Model[]) || [];
  } catch { return []; }
}

/** Server model → the shape the UI uses (list responses are light: no meshes until hydrated). */
export function fromServer(m: any): Model {
  return { ...m, ts: typeof m.ts === "number" ? m.ts : Date.now() } as Model;
}

/** Strip the fields that shouldn't round-trip (glbId is an IndexedDB-era key). */
export function toServer(m: Model): any {
  const { glbId, ...rest } = m as any;
  return rest;
}

