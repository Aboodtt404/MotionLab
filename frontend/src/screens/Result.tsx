/* Result / verification — the product's signature screen. Three phases:
 *   running — attempt timeline + stage chips while the real job polls (queue + est hints, not spinners)
 *   done    — the verification card: seal (VERIFIED / N FAILED), animated N-of-M counter, category
 *             chips, evidence rows (feature · expected · measured · ±tol · pass) from the REAL
 *             inspection[] the deterministic verifier returns, exports, open-in-editor / re-generate
 *   error   — calm, typed failure with retry (failures are first-class, never a dead-end toast)
 * Assemblies additionally get the joint panel with the articulation slider. */
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Tick } from "../motion";
import { sx } from "../sx";
import { I } from "../icons";
import { Attempt, Theater, catColor, fmtVal, toServer, useStudio } from "../store";
import { VP } from "../viewport";
import { downloadB64 } from "../gltf";
import * as api from "../api";
import { ProjectPicker } from "./ProjectPicker";

export type ResultPhase = "running" | "done" | "error";

/** Live spec panel — the assembly JSON streaming token-by-token (real planner tokens), or the
 * parsed part Spec typewritten client-side. The tokens arrive in POLL BURSTS (~1.5s apart); an
 * adaptive cursor consumes the backlog at a continuous rate sized to drain just before the next
 * burst lands — so the typing never stalls and never jumps. Auto-follows the tail. */
function LiveSpec({ theater }: { theater: Theater }) {
  const streaming = theater.specStream != null;
  const target = theater.specStream ?? (theater.specObj ? JSON.stringify(theater.specObj, null, 1) : "");
  const targetRef = useRef(target);
  targetRef.current = target;
  const shownRef = useRef(0);
  const [shown, setShown] = useState(0);
  const preRef = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let raf = 0, last = performance.now();
    const step = (now: number) => {
      raf = requestAnimationFrame(step);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const tgt = targetRef.current;
      if (shownRef.current > tgt.length) shownRef.current = 0;   // stream restarted (next attempt)
      const backlog = tgt.length - shownRef.current;
      if (backlog <= 0) return;
      // pace the backlog over ~1.3s (just under the poll interval) — smooth, gapless typing
      const rate = Math.min(900, Math.max(45, backlog / 1.3));
      shownRef.current = Math.min(tgt.length, shownRef.current + rate * dt);
      setShown(Math.floor(shownRef.current));
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);
  useEffect(() => { const el = preRef.current; if (el) el.scrollTop = el.scrollHeight; }, [shown]);
  const text = target.slice(0, shown);
  if (!target) return null;
  return (
    <div style={sx("width:430px; max-width:36vw; background:rgba(15,15,17,.86); border:1px solid var(--border-2); border-radius:9px; overflow:hidden; backdrop-filter:blur(8px); animation:mlk-pop .3s ease; pointer-events:auto;")}>
      <div style={sx("display:flex; align-items:center; gap:9px; padding:10px 14px; border-bottom:1px solid var(--border);")}>
        <span style={sx("width:7px; height:7px; border-radius:50%; flex-shrink:0; background:#5aa9e6; box-shadow:0 0 7px #5aa9e688; animation:mlk-pulse 1.6s ease-in-out infinite;")} />
        <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:11px; letter-spacing:.08em; color:var(--text-2);")}>
          {streaming ? "ASSEMBLY SPEC · streaming" : "PART SPEC · parsed"}
        </span>
        {theater.attempt != null && (
          <span style={sx("margin-left:auto; padding:2px 8px; border:1px solid var(--border-2); border-radius:10px; font-family:'Spline Sans Mono',monospace; font-size:10px; color:var(--text-2);")}>
            attempt {theater.attempt}
          </span>
        )}
      </div>
      <pre ref={preRef} style={sx("margin:0; padding:12px 14px; max-height:38vh; overflow-y:auto; font-family:'Spline Sans Mono',monospace; font-size:10.5px; line-height:1.55; color:#c8d2b0; white-space:pre-wrap; overflow-wrap:anywhere;")}>
        {text}<span style={sx("display:inline-block; width:7px; height:12px; margin-left:2px; background:var(--accent,#4d9eff); vertical-align:-2px; animation:mlk-pulse 1s steps(2,end) infinite;")} />
      </pre>
      {theater.partNames.length > 0 && (
        <div style={sx("border-top:1px solid var(--border); padding:9px 14px 11px; max-height:20vh; overflow-y:auto;")}>
          <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3); margin-bottom:7px;")}>CONSTRUCTING</div>
          {theater.partNames.map((n) => (
            <div key={n} style={sx("display:flex; align-items:center; gap:8px; padding:3.5px 0; animation:mlk-flyout .35s ease both;")}>
              <svg width="13" height="13" viewBox="0 0 24 24" style={{ color: "var(--verified)", flexShrink: 0 }}>
                <path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:11.5px; color:var(--text);")}>{n}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Mesh theater — the FLUX concept slides in the moment it exists; MV views fly in from the
 * screen corners; the mesh itself reveals bottom-up in the viewport when generation completes. */
function MeshTheater({ theater }: { theater: Theater }) {
  if (!theater.concept && theater.views.length === 0) return null;
  return (
    <div style={sx("display:flex; flex-direction:column; gap:12px; pointer-events:auto;")}>
      {theater.concept && (
        <div style={sx("width:232px; background:rgba(15,15,17,.86); border:1px solid var(--border-2); border-radius:9px; overflow:hidden; backdrop-filter:blur(8px); animation:mlk-pop .35s ease both;")}>
          <div style={sx("display:flex; align-items:center; gap:9px; padding:9px 13px; border-bottom:1px solid var(--border);")}>
            <span style={sx("width:7px; height:7px; border-radius:50%; flex-shrink:0; background:#e879c5; box-shadow:0 0 7px #e879c588;")} />
            <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10.5px; letter-spacing:.08em; color:var(--text-2);")}>CONCEPT · FLUX</span>
          </div>
          <img src={theater.concept} alt="" style={{ width: "100%", display: "block" }} />
        </div>
      )}
      {theater.views.length > 0 && (
        <div style={sx("width:232px;")}>
          <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3); margin:2px 0 7px;")}>MULTI-VIEW · MV-ADAPTER</div>
          <div style={sx("display:grid; grid-template-columns:1fr 1fr; gap:8px;")}>
            {theater.views.map((v, i) => (
              <div key={i} style={{
                ...sx("border:1px solid var(--border-2); border-radius:7px; overflow:hidden; background:#111;"),
                animation: `mlk-flyin-${i % 4} .6s cubic-bezier(.2,.7,.3,1) both`, animationDelay: (i * 0.09) + "s",
              }}>
                <img src={v} alt="" style={{ width: "100%", display: "block" }} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Mesh results get a stats card, not the engineering checklist — the gate rows (M1…W5) are QA
 * internals for CAD-style verification and read as noise on an organic asset. This shows what a
 * mesh artist actually wants: polycount, size, texture channels, print-readiness. */
function MeshDoneCard({ m, onOpenEditor, onReGenerate, showToast, onAssignProject }: {
  m: any; onOpenEditor: () => void; onReGenerate: () => void; showToast: (s: string) => void;
  onAssignProject: (id: string, project: string) => void;
}) {
  const rep = m.report || {};
  const nameBase = (m.name || "asset").toLowerCase().replace(/\s+/g, "-");
  const rows: [string, ReactNode][] = [
    ["Triangles", rep.faces != null ? <Tick value={Number(rep.faces)} /> : "—"],
    ["Vertices", rep.verts != null ? <Tick value={Number(rep.verts)} /> : "—"],
    ["File size", rep.size_mb != null ? <Tick value={Number(rep.size_mb)} fmt={(x) => x.toFixed(1) + " MB"} /> : "—"],
    ["Generation", m.seconds ? Math.round(m.seconds) + " s · " + (m.tier || "quality").toUpperCase() : (m.tier || "quality").toUpperCase()],
  ];
  const pbr: string[] = (rep.pbr || []).map((c: string) => c.replace(/Texture$/, ""));
  const printReady = !!rep.watertight;
  const [rigging, setRigging] = useState(false);
  const [rigged, setRigged] = useState<boolean>(!!m.rigged);
  const doRig = async () => {
    if (!m.glb || rigging || rigged) return;
    setRigging(true);
    showToast("Rigging — skeleton + skin weights (~2 min)");
    try {
      const res = await api.rig(m.glb);
      if (res.passed && res.glb_b64) {
        m.glb = res.glb_b64; m.rigged = true;                 // rigged GLB replaces the asset (exports pick it up)
        api.studio.saveModel(toServer(m)).catch(() => { });   // POST /models is an upsert — persist in place
        await VP.revealGlb(res.glb_b64);
        setRigged(true);
        showToast(`Rigged ✓ ${res.rig_report?.bones ?? "?"} bones · single root · ≤4 weights/vertex — game-ready`);
      } else {
        const bad = (res.rig_report?.rows || []).filter((r: any) => !r.within_tol).map((r: any) => r.name).join(", ");
        showToast("Rig gate failed (" + (bad || res.error || "unknown") + ") — original kept");
      }
    } catch (e: any) { showToast("Rig failed: " + (e?.message || e)); }
    setRigging(false);
  };
  return (
    <div style={sx("flex:1; display:flex; flex-direction:column; min-height:0; position:relative;")}>
      <div style={sx("position:absolute; inset:0; overflow:hidden; pointer-events:none; z-index:3;")}>
        <div style={sx("position:absolute; top:0; bottom:0; width:40%; left:-45%; background:linear-gradient(100deg, transparent, rgba(232,121,197,.08), transparent); animation:mlk-scan .85s .1s ease both;")} />
      </div>
      <div style={sx("padding:20px 20px 18px; border-bottom:1px solid var(--border); background:linear-gradient(180deg, rgba(232,121,197,.08), transparent);")}>
        <div style={sx("display:flex; align-items:center; gap:13px;")}>
          <div style={sx("width:44px; height:44px; border-radius:50%; flex-shrink:0; background:rgba(232,121,197,.13); border:1.5px solid #e879c5; display:flex; align-items:center; justify-content:center; animation:mlk-stamp .4s .25s ease both;")}>
            <I k="layers" size={22} style={{ color: "#e879c5" }} />
          </div>
          <div>
            <div style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:21px; letter-spacing:.02em; color:#fff;")}>MESH READY</div>
            <div style={sx("margin-top:2px; font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text-2);")}>textured GLB · PBR</div>
          </div>
        </div>
      </div>
      <div style={sx("flex:1; overflow-y:auto; padding:8px 20px 16px;")}>
        {rows.map(([k, v]) => (
          <div key={k} style={sx("display:flex; align-items:center; padding:11px 0; border-bottom:1px solid var(--border);")}>
            <span style={sx("flex:1; font-size:13.5px; color:var(--text-2);")}>{k}</span>
            <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text);")}>{v}</span>
          </div>
        ))}
        <div style={sx("display:flex; align-items:center; padding:11px 0; border-bottom:1px solid var(--border);")}>
          <span style={sx("flex:1; font-size:13.5px; color:var(--text-2);")}>Texture channels</span>
          <span style={sx("display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;")}>
            {pbr.length ? pbr.map((c) => (
              <span key={c} style={sx("padding:2px 8px; border-radius:4px; background:rgba(232,121,197,.13); color:#e879c5; font-family:'Spline Sans Mono',monospace; font-size:9.5px; letter-spacing:.05em;")}>{c}</span>
            )) : <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text-3);")}>none</span>}
          </span>
        </div>
        <div style={sx("display:flex; align-items:center; padding:11px 0;")}>
          <span style={sx("flex:1; font-size:13.5px; color:var(--text-2);")}>3D-print ready</span>
          {printReady ? (
            <span style={sx("display:inline-flex; align-items:center; gap:6px; font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--verified);")}>
              <svg width="13" height="13" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              WATERTIGHT
            </span>
          ) : (
            <span title="Fine for rendering — run the repair pass before printing"
              style={sx("font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--warn);")}>RENDER-READY · repair to print</span>
          )}
        </div>
      </div>
      <div style={sx("padding:14px 20px 16px; border-top:1px solid var(--border);")}>
        <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-bottom:11px;")}>
          <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3);")}>PROJECT</span>
          <ProjectPicker compact value={m.project || "My Project"} onPick={(p) => onAssignProject(m.id, p)} />
        </div>
        <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3); margin-bottom:9px;")}>EXPORT</div>
        <div style={sx("display:flex; gap:8px;")}>
          {m.glb && (
            <button data-press data-accenthover onClick={() => { downloadB64(m.glb, nameBase + ".glb", "model/gltf-binary"); showToast(`Exported ${nameBase}.glb`); }}
              style={sx("flex:1; padding:11px 6px; border:1px solid var(--border-2); background:transparent; color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:11.5px; letter-spacing:.06em; cursor:pointer; border-radius:5px;")}>
              GLB
            </button>
          )}
        </div>
        {m.glb && (
          <button data-press data-accenthover onClick={doRig} disabled={rigging || rigged}
            title={rigged ? "Skeleton + skin weights embedded — animates in any engine" : "Auto-rig: skeleton + skinning (SkinTokens), verified game-ready"}
            style={sx("width:100%; margin-top:10px; padding:11px; border:1px solid " + (rigged ? "var(--verified)" : "var(--border-2)") + "; background:transparent; color:" + (rigged ? "var(--verified)" : "var(--text)") + "; font-family:'Spline Sans Mono',monospace; font-size:11.5px; letter-spacing:.08em; cursor:" + (rigged ? "default" : "pointer") + "; border-radius:5px;" + (rigging ? "opacity:.6;" : ""))}>
            {rigged ? "RIGGED ✓ · GAME-READY SKELETON" : rigging ? "RIGGING… (~2 min)" : "RIG FOR ANIMATION"}
          </button>
        )}
        <div style={sx("display:flex; gap:10px; margin-top:11px;")}>
          <button data-press onClick={onOpenEditor}
            style={sx("flex:1; padding:12px; border:1px solid var(--border-2); background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; cursor:pointer; clip-path:var(--notch);")}>
            <span data-ulw>OPEN IN EDITOR</span>
          </button>
          <button data-press data-primary onClick={onReGenerate}
            style={sx("flex:1; padding:12px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; cursor:pointer;")}>
            <span data-ulw>RE-GENERATE</span>
          </button>
        </div>
      </div>
    </div>
  );
}

export function Result({ phase, attempts, error, theater }: { phase: ResultPhase; attempts: Attempt[]; error: string | null; theater: Theater }) {
  const st = useStudio();
  const m = st.current;
  const t = st.liveTask;
  const [verifCount, setVerifCount] = useState(0);
  const [jointAngle, setJointAngle] = useState(0);
  const vcT = useRef<any>(null);

  const rows = (m?.inspection || []).map((r, i) => ({
    name: r.name, expected: fmtVal(r.expected), measured: fmtVal(r.measured),
    delta: r.delta == null ? "—" : (r.delta > 0 ? "+" : "") + (typeof r.delta === "number" ? r.delta.toFixed(2) : r.delta),
    pass: !!r.within_tol, cat: r.category || "check",
    delay: Math.min(i, 14) * 35 + "ms", stampDelay: (Math.min(i, 14) * 35 + 240) + "ms",
  }));
  const passedN = rows.filter((r) => r.pass).length;
  const failedN = rows.length - passedN;
  const verified = m?.status === "verified";

  useEffect(() => {
    if (phase !== "done") return;
    clearInterval(vcT.current);
    setVerifCount(0);
    let n = 0;
    vcT.current = setInterval(() => {
      n++;
      setVerifCount(Math.min(n, passedN));
      if (n >= passedN) clearInterval(vcT.current);
    }, 80);
    return () => clearInterval(vcT.current);
  }, [phase, passedN, m?.id]);

  const cats: string[] = [];
  rows.forEach((r) => { if (!cats.includes(r.cat)) cats.push(r.cat); });

  const isAsm = m?.engine === "assembly";
  const joints = (m?.assembly?.joints || []) as any[];
  const kinematicOk = rows.some((r) => r.cat === "kinematic" && r.pass);
  const showJointPanel = phase === "done" && isAsm;

  const exports: { label: string; run: () => void }[] = [];
  const nameBase = (m?.name || "asset").toLowerCase().replace(/\s+/g, "-");
  if (m?.stl) exports.push({ label: "STL", run: () => downloadB64(m.stl!, nameBase + ".stl", "model/stl") });
  if (m?.step) exports.push({ label: "STEP", run: () => downloadB64(m.step!, nameBase + ".step", "application/step") });
  if (m?.glb) exports.push({ label: "GLB", run: () => downloadB64(m.glb!, nameBase + ".glb", "model/gltf-binary") });
  if (m?.code) exports.push({
    label: "CODE", run: () => {
      const blob = new Blob([m.code!], { type: "text/x-python" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = nameBase + ".py"; a.click();
    },
  });

  const attemptDot = (a: Attempt) => {
    const col = a.status === "passed" ? "#37d67a" : a.status === "failed" ? "#e5645f" : "#e0a63a";
    return { dot: sx(`width:10px;height:10px;border-radius:50%;flex-shrink:0;background:${col};box-shadow:0 0 8px ${col}77;`), col };
  };
  const attemptLabel = (a: Attempt) =>
    a.status === "passed" ? "passed" : a.fails < 0 ? "repair" : `${a.fails} fail${a.fails === 1 ? "" : "s"}`;

  const title = t?.name || m?.name || "Generating";
  const trackLabel = m ? (m.engine === "mesh" ? "MESH · " + (m.tier || "").toUpperCase() : m.engine === "assembly" ? "CAD · ASSEMBLY" : "CAD · PART")
    : t ? (t.engine === "mesh" ? "MESH" : t.engine === "assembly" ? "CAD · ASSEMBLY" : "CAD · PART") : "";
  const est = t ? `~${t.estSec >= 120 ? Math.round(t.estSec / 60) + " min" : t.estSec + " s"}` : "";

  const startJointDrag = (e: React.PointerEvent) => {
    e.preventDefault();
    // REAL articulation: wrap the jointed parts in pivot groups on first touch (the per-part
    // meshes + joint axes/limits are all present on saved assemblies)
    if (joints.length) VP.configureJoints(joints);
    const track = e.currentTarget as HTMLElement;
    const rect = track.getBoundingClientRect();
    const set = (cx: number) => {
      let v = (cx - rect.left) / rect.width;
      v = Math.max(0, Math.min(1, v));
      const deg = Math.round(v * 360);
      setJointAngle(deg);
      VP.setJointAngle(deg);
    };
    set(e.clientX);
    const mv = (ev: PointerEvent) => set(ev.clientX);
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  };

  return (
    <div style={sx("position:absolute; inset:0; z-index:3; pointer-events:none; animation:mlk-fade .3s ease;")}>
      <div style={sx("position:absolute; inset:0; pointer-events:none; z-index:1; background:radial-gradient(130% 130% at 50% 50%, transparent 52%, rgba(0,0,0,.6) 100%); animation:mlk-poweron .9s .15s ease forwards;")}>
        <div style={sx("position:absolute; left:0; right:0; height:2px; top:-3%; background:linear-gradient(90deg, transparent, rgba(255,255,255,.28), transparent); animation:mlk-scanv .7s ease-out both;")} />
      </div>

      {phase === "running" && (
        <div style={sx("position:absolute; left:38px; top:120px; bottom:110px; pointer-events:none; z-index:2; display:flex; flex-direction:column; align-items:flex-start; gap:10px; overflow:hidden;")}>
          {/* the generation theater: live artifacts replace the static stage chips as they arrive */}
          {t?.engine === "mesh" ? <MeshTheater theater={theater} /> : <LiveSpec theater={theater} />}
          {!theater.concept && theater.views.length === 0 && !theater.specStream && !theater.specObj && (
            <>
              {(t?.engine === "mesh"
                ? [["#e879c5", "CONCEPT · flux hero view"], ["#5aa9e6", "MESH · trellis o-voxels"], ["#43c9b0", "TEXTURE · pbr channels"]]
                : [["#5aa9e6", "BUILD · cadquery / occt"], ["#43c9b0", "MEASURE · envelope ±0.1 mm"], ["#b58cff", "CHECK · hole census ⌀ / positions"]]
              ).map(([col, label], i) => (
                <div key={label} style={{ ...sx("display:flex; align-items:center; gap:8px; padding:7px 11px; background:rgba(15,15,17,.78); border:1px solid var(--border-2); border-radius:6px; font-family:'Spline Sans Mono',monospace; font-size:11px; letter-spacing:.05em; color:var(--text-2); animation:mlk-stagger .4s ease both;"), animationDelay: (0.5 + i * 1.2) + "s" }}>
                  <span style={{ ...sx("width:6px; height:6px; border-radius:50%; flex-shrink:0;"), background: col }} />{label}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      <div style={sx("position:absolute; left:22px; top:18px; pointer-events:auto;")}>
        <span style={sx("display:inline-flex; clip-path:var(--notch); background:var(--border-2);")}>
          <button data-press className="hv-back" onClick={() => st.go("dashboard", "dashboard")}
            style={sx("clip-path:var(--notch); margin:1px; display:flex; align-items:center; gap:8px; padding:10px 18px 10px 13px; border:none; background:var(--inset); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:500; letter-spacing:.09em; cursor:pointer;")}>
            <I k="chev-left" size={16} /><span data-ulw>BACK</span>
          </button>
        </span>
      </div>
      <div style={sx("position:absolute; left:50%; top:24px; transform:translateX(-50%); pointer-events:none; text-align:center;")}>
        <div style={sx("font-size:16px; color:var(--text);")}>{title}</div>
        <div style={sx("margin-top:3px; font-family:'Spline Sans Mono',monospace; font-size:11px; letter-spacing:.1em; color:var(--text-3);")}>{trackLabel}</div>
      </div>

      {/* the card */}
      <div className={phase === "running" ? "mlk-tracing mlk-tracing-in" : undefined}
        style={sx("position:absolute; right:20px; top:80px; bottom:22px; width:452px; pointer-events:auto; display:flex; flex-direction:column; background:var(--panel); border:1px solid var(--border-2); border-radius:10px; overflow:hidden; box-shadow:0 24px 60px rgba(0,0,0,.5); animation:mlk-rise .3s var(--ease-out) both;")}>

        {phase === "running" && (
          <div style={sx("flex:1; display:flex; flex-direction:column; padding:24px;")}>
            <div style={sx("display:flex; align-items:center; gap:11px;")}>
              <span style={sx("width:18px; height:18px; border:2px solid rgba(255,255,255,.16); border-top-color:#ededed; border-radius:50%; animation:mlk-spin .8s linear infinite; flex-shrink:0;")} />
              <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:13px; letter-spacing:.08em; color:#fff;")}>GENERATING</span>
              <span style={sx("margin-left:auto; font-family:'Spline Sans Mono',monospace; font-size:11.5px; color:var(--text-3);")}>queue 1 · est {est}</span>
            </div>
            <div style={sx("margin-top:9px; font-size:13.5px; color:var(--text-2);")}>Generate → verify → repair · up to 3 attempts</div>
            <div style={sx("margin-top:22px; display:flex; flex-direction:column;")}>
              <div style={sx("display:flex; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid var(--border);")}>
                <span style={sx("width:10px;height:10px;border-radius:50%;flex-shrink:0;background:#e0a63a;box-shadow:0 0 8px #e0a63a77;animation:mlk-pulse 1.4s ease-in-out infinite;")} />
                <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:13px; color:var(--text);")}>{t?.stage || "running"}</span>
                <span style={sx("margin-left:auto; font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text-2);")}>{t?.elapsed ? Math.round(t.elapsed) + "s" : ""}</span>
              </div>
            </div>
            <div style={sx("flex:1; min-height:20px;")} />
            <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--text-3); line-height:1.6;")}>
              Every attempt is re-measured by the deterministic verifier. Failures feed typed repair feedback — not thrown away.
            </div>
          </div>
        )}

        {phase === "error" && (
          <div style={sx("flex:1; display:flex; flex-direction:column; padding:24px;")}>
            <div style={sx("display:flex; align-items:center; gap:13px;")}>
              <div style={sx("width:44px; height:44px; border-radius:50%; flex-shrink:0; background:rgba(224,166,58,.14); border:1.5px solid var(--warn); display:flex; align-items:center; justify-content:center;")}>
                <I k="close" size={20} style={{ color: "var(--warn)" }} />
              </div>
              <div>
                <div style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:21px; letter-spacing:.02em; color:var(--warn);")}>ENGINE ERROR</div>
                <div style={sx("margin-top:2px; font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text-2);")}>the job did not complete</div>
              </div>
            </div>
            <div style={sx("margin-top:18px; padding:14px; border:1px solid var(--border); border-radius:6px; background:var(--inset); font-family:'Spline Sans Mono',monospace; font-size:12px; line-height:1.65; color:var(--text-2); overflow-wrap:anywhere;")}>
              {error || "unknown error"}
            </div>
            <div style={sx("margin-top:14px; font-size:13px; line-height:1.55; color:var(--text-3);")}>
              This engine's model server may be paused (fine-tunes borrow the GPU) — try again once it's back online.
            </div>
            <div style={sx("flex:1;")} />
            <div style={sx("display:flex; gap:10px;")}>
              <button data-press onClick={() => st.go("dashboard", "dashboard")}
                style={sx("flex:1; padding:12px; border:1px solid var(--border-2); background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; cursor:pointer; clip-path:var(--notch);")}>
                <span data-ulw>BACK TO DASHBOARD</span>
              </button>
              <button data-press data-primary onClick={() => st.reGenerate()}
                style={sx("flex:1; padding:12px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; cursor:pointer;")}>
                <span data-ulw>RETRY</span>
              </button>
            </div>
          </div>
        )}

        {phase === "done" && m && m.engine === "mesh" && (
          <MeshDoneCard m={m} onOpenEditor={() => st.openModel(m, "editor")} onReGenerate={() => st.reGenerate()} showToast={st.showToast} onAssignProject={st.assignProject} />
        )}

        {phase === "done" && m && m.engine !== "mesh" && (
          <div style={sx("flex:1; display:flex; flex-direction:column; min-height:0; position:relative;")}>
            <div style={sx("position:absolute; inset:0; overflow:hidden; pointer-events:none; z-index:3;")}>
              <div style={{ ...sx("position:absolute; top:0; bottom:0; width:40%; left:-45%; animation:mlk-scan .85s .1s ease both;"), background: `linear-gradient(100deg, transparent, ${verified ? "rgba(55,214,122,.09)" : "rgba(229,100,95,.07)"}, transparent)` }} />
            </div>
            <div style={{ ...sx("padding:20px 20px 18px; border-bottom:1px solid var(--border);"), background: `linear-gradient(180deg, ${verified ? "rgba(55,214,122,.10)" : "rgba(229,100,95,.09)"}, transparent)` }}>
              <div style={sx("display:flex; align-items:center; gap:13px;")}>
                {verified ? (
                  <div style={sx("width:44px; height:44px; border-radius:50%; flex-shrink:0; background:rgba(55,214,122,.16); border:1.5px solid var(--verified); display:flex; align-items:center; justify-content:center; animation:mlk-ring .9s .5s ease-out both;")}>
                    <svg width="24" height="24" viewBox="0 0 24 24" style={{ color: "var(--verified)" }}>
                      <path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
                        style={{ strokeDasharray: 30, strokeDashoffset: 30, animation: "mlk-drawcheck .45s .25s ease forwards" }} />
                    </svg>
                  </div>
                ) : (
                  <div style={sx("width:44px; height:44px; border-radius:50%; flex-shrink:0; background:rgba(229,100,95,.14); border:1.5px solid var(--fail); display:flex; align-items:center; justify-content:center; animation:mlk-stamp .4s .3s ease both;")}>
                    <I k="close" size={20} style={{ color: "var(--fail)" }} />
                  </div>
                )}
                <div>
                  <div style={{ ...sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:21px; letter-spacing:.02em;"), color: verified ? "var(--verified)" : "var(--fail)" }}>
                    {verified ? "VERIFIED" : `${failedN} CHECK${failedN === 1 ? "" : "S"} FAILED`}
                  </div>
                  <div style={sx("margin-top:2px; font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text-2);")}>
                    <span style={{ fontVariantNumeric: "tabular-nums" }}>{Math.min(verifCount, passedN)}</span> of {rows.length} checks passed
                  </div>
                </div>
              </div>
              {attempts.length > 0 && (
                <div style={sx("display:flex; align-items:center; gap:8px; margin-top:15px; flex-wrap:wrap;")}>
                  {attempts.map((a) => (
                    <div key={a.n} style={sx("display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border:1px solid var(--border); border-radius:20px;")}>
                      <span style={attemptDot(a).dot} />
                      <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10.5px; color:var(--text-2);")}>a{a.n} · {attemptLabel(a)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={sx("padding:14px 20px 10px; display:flex; flex-wrap:wrap; gap:7px;")}>
              {cats.map((c, i) => {
                const col = catColor(c);
                return (
                  <span key={c} style={{
                    ...sx("display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:5px;font-family:'Spline Sans Mono',monospace;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;animation:mlk-stagger .35s ease both;"),
                    background: col + "1c", color: col, animationDelay: (i * 60 + 120) + "ms",
                  }}>
                    <span style={{ ...sx("width:6px;height:6px;border-radius:50%;flex-shrink:0;"), background: col }} />{c}
                  </span>
                );
              })}
            </div>
            <div style={sx("flex:1; overflow-y:auto; padding:4px 20px 16px;")}>
              <div style={sx("display:flex; align-items:center; padding:6px 0; font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:var(--text-3); border-bottom:1px solid var(--border);")}>
                <span style={{ flex: 1 }}>Feature</span>
                <span style={{ width: 92, textAlign: "right" }}>Expected</span>
                <span style={{ width: 92, textAlign: "right" }}>Measured</span>
                <span style={{ width: 48, textAlign: "right" }}>±tol</span>
                <span style={{ width: 28 }} />
              </div>
              {rows.map((r, i) => {
                const col = catColor(r.cat);
                return (
                  <div key={i} style={{ ...sx("display:flex; align-items:center; padding:9px 0; border-bottom:1px solid var(--border); animation:mlk-stagger .4s ease both;"), animationDelay: r.delay }}>
                    <div style={sx("flex:1; min-width:0; padding-right:8px;")}>
                      <div style={sx("font-size:13px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{r.name}</div>
                      <div style={{ marginTop: 4 }}>
                        <span style={{
                          ...sx("display:inline-flex;align-items:center;padding:2px 7px;border-radius:4px;font-family:'Spline Sans Mono',monospace;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;"),
                          background: col + "22", color: col, border: `1px solid ${col}44`,
                        }}>{r.cat}</span>
                      </div>
                    </div>
                    <span style={sx("width:92px; text-align:right; font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--text-3); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")} title={r.expected}>{r.expected}</span>
                    <span style={sx("width:92px; text-align:right; font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")} title={r.measured}>{r.measured}</span>
                    <span style={sx("width:48px; text-align:right; font-family:'Spline Sans Mono',monospace; font-size:10.5px; color:var(--text-3);")}>{r.delta}</span>
                    <span style={{ width: 28, display: "flex", justifyContent: "flex-end" }}>
                      {r.pass ? (
                        <svg width="16" height="16" viewBox="0 0 24 24" style={{ color: "var(--verified)", animation: "mlk-stamp .3s ease both", animationDelay: r.stampDelay } as any}>
                          <path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      ) : (
                        <svg width="14" height="14" viewBox="0 0 24 24" style={{ color: "var(--fail)", animation: "mlk-stamp .3s ease both", animationDelay: r.stampDelay } as any}>
                          <use href="#i-close" />
                        </svg>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
            <div style={sx("padding:14px 20px 16px; border-top:1px solid var(--border);")}>
              <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-bottom:11px;")}>
                <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3);")}>PROJECT</span>
                <ProjectPicker compact value={m.project || "My Project"} onPick={(p) => st.assignProject(m.id, p)} />
              </div>
              <div style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3); margin-bottom:9px;")}>EXPORT</div>
              <div style={sx("display:flex; gap:8px;")}>
                {exports.map((x) => (
                  <button key={x.label} data-press data-accenthover onClick={() => { x.run(); st.showToast(`Exported ${nameBase}.${x.label.toLowerCase()}`); }}
                    style={sx("flex:1; padding:11px 6px; border:1px solid var(--border-2); background:transparent; color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:11.5px; letter-spacing:.06em; cursor:pointer; border-radius:5px;")}>
                    {x.label}
                  </button>
                ))}
                {exports.length === 0 && <span style={sx("font-size:12.5px; color:var(--text-3);")}>No artifacts returned.</span>}
              </div>
              <div style={sx("display:flex; gap:10px; margin-top:11px;")}>
                <button data-press onClick={() => st.openModel(m, "editor")}
                  style={sx("flex:1; padding:12px; border:1px solid var(--border-2); background:var(--panel-2); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; cursor:pointer; clip-path:var(--notch);")}>
                  <span data-ulw>OPEN IN EDITOR</span>
                </button>
                <button data-press data-primary onClick={() => st.reGenerate()}
                  style={sx("flex:1; padding:12px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12px; letter-spacing:.08em; cursor:pointer;")}>
                  <span data-ulw>RE-GENERATE</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* joint slider (assemblies) */}
      {showJointPanel && (
        <div style={sx("position:absolute; left:34px; right:492px; bottom:58px; pointer-events:auto; background:rgba(23,23,26,.9); border:1px solid var(--border-2); border-radius:10px; padding:15px 18px; backdrop-filter:blur(8px);")}>
          <div style={sx("display:flex; align-items:center; gap:10px;")}>
            <I k="ruler" size={17} style={{ color: "#b58cff" }} />
            <span style={{ ...sx("font-family:'Spline Sans Mono',monospace; font-size:11.5px; letter-spacing:.06em;"), color: kinematicOk ? "var(--verified)" : "var(--warn)" }}>
              {joints.length || "0"} REVOLUTE JOINT{joints.length === 1 ? "" : "S"} · {kinematicOk ? "VERIFIED 0–360°" : "SWEEP NOT CLEAN"}
            </span>
            <span style={sx("margin-left:auto; font-family:'Spline Sans Mono',monospace; font-size:13px; color:#fff;")}>{jointAngle}°</span>
            {jointAngle >= 358 && (
              <span style={sx("margin-left:10px; padding:3px 9px; border-radius:4px; background:rgba(55,214,122,.15); border:1px solid var(--verified); color:var(--verified); font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.06em; animation:mlk-stamp .3s ease both;")}>SWEEP COMPLETE</span>
            )}
          </div>
          <div style={sx("margin-top:5px; font-size:13px; color:var(--text-2);")}>
            {kinematicOk
              ? "Motion-range sweep is collision-free."
              : "The kinematic rows flagged this sweep — check the report."}
          </div>
          <div onPointerDown={startJointDrag}
            style={sx("position:relative; height:20px; margin-top:12px; cursor:pointer; display:flex; align-items:center; touch-action:none;")}>
            <div style={sx("position:absolute; left:0; right:0; height:5px; border-radius:3px; background:rgba(255,255,255,.13);")} />
            <div style={{ ...sx("position:absolute; left:0; height:5px; border-radius:3px; background:var(--verified);"), width: (jointAngle / 360 * 100) + "%" }} />
            <div style={{ ...sx("position:absolute; top:50%; width:15px; height:15px; border-radius:50%; background:var(--verified); border:2px solid #0d0d0d; transform:translate(-50%,-50%);"), left: (jointAngle / 360 * 100) + "%" }} />
          </div>
        </div>
      )}

    </div>
  );
}
