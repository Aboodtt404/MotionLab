/* Dashboard — hero carousel (CAD / MESH engine slides), Recent Models (real library),
 * Generation panel (track/type/tier + prompt + suggested), Generation Tasks (real async jobs).
 * Compact layout: the whole tab fits the viewport (column flex, height-bounded cards with
 * internal scrolling) — no page scroll. */
import { useEffect, useRef, useState } from "react";
import { sx } from "../sx";
import { I } from "../icons";
import * as api from "../api";
import { Model, Task, timeAgo, useStudio } from "../store";
import { fileToB64 } from "../gltf";
import { KebabMenu } from "./Kebab";
import { ProjectPicker } from "./ProjectPicker";

const SUGGESTED: Record<string, string[]> = {
  cad_part: ["Hex standoff", "Bearing block", "Chassis plate", "Hose connector", "Motor mount", "Shelled enclosure", "Greebled hull panel"],
  cad_assembly: ["Utility cart", "Hinged door", "4-legged stool", "Quadcopter frame", "Shaft + bearings", "PCB enclosure"],
  mesh: ["Alien relic", "Rock formation", "Sci-fi crate", "Weathered droid", "Coral creature", "Cliff terrain"],
};
const SUGGEST_FULL: Record<string, string> = {
  "Hex standoff": "M3 hex standoff, 6 mm across flats, 20 mm tall, threaded through-bore",
  "Bearing block": "bearing block 40×30×20 mm with a ⌀12 mm through-bore and 4× M4 corner holes",
  "Chassis plate": "220×120×6 mm chassis plate, 4× ⌀5 mm corner holes, filleted edges",
  "Hose connector": "hose connector: ⌀20 barbed end to ⌀25 threaded end, 60 mm long",
  "Motor mount": "NEMA17 motor mount plate with 31 mm bolt circle and ⌀22 pilot hole",
  "Shelled enclosure": "shelled enclosure 90×60×30 mm, 2 mm walls, open top, corner fillets",
  "Greebled hull panel": "sci-fi hull panel 160×90 mm with greeble detail pass and chamfered rim",
  "Utility cart": "a four-wheeled utility cart: chassis plate, stub axles, wheels on revolute joints",
  "Hinged door": "an enclosure door on two hinges with a handle, door swings on revolute joints",
  "4-legged stool": "a 4-legged stool, ~120 mm tall, round seat ⌀140, legs splayed 10°",
  "Quadcopter frame": "quadcopter frame: central hub, four arms, motor pads with bolt circles",
  "Shaft + bearings": "a shaft riding in two pillow-block bearings on a base plate",
  "PCB enclosure": "PCB enclosure with standoffs, shelled base and lid",
  "Alien relic": "an ancient alien relic, weathered stone with glowing rune engravings",
  "Rock formation": "a jagged desert rock formation, layered sandstone",
  "Sci-fi crate": "a sci-fi military supply crate, hard-surface with worn paint decals",
  "Weathered droid": "a weathered maintenance droid, cyclopean head, chipped orange paint",
  "Coral creature": "an alien coral-like creature with translucent fronds",
  "Cliff terrain": "a cliff-face terrain chunk with strata and scree",
};

export function Dashboard() {
  const st = useStudio();
  const [carousel, setCarousel] = useState(0);
  const [img, setImg] = useState<{ b64: string; name: string } | null>(null);
  const imgRef = useRef<HTMLInputElement>(null);
  const [rolling, setRolling] = useState(false);
  const rollDice = async () => {
    if (rolling) return;
    setRolling(true);
    const brief = await api.cadSuggest(st.track);
    setRolling(false);
    if (brief) st.setPrompt(brief);
    else st.showToast("The dice needs the CAD engine online");
  };
  const carT = useRef<any>(null);
  useEffect(() => {
    carT.current = setInterval(() => setCarousel((c) => (c + 1) % 2), 7000);
    return () => clearInterval(carT.current);
  }, []);

  const isCad = st.track === "cad";
  useEffect(() => { if (isCad) setImg(null); }, [isCad]);
  const doGenerate = () => st.startGenerate(img && !isCad ? { prompt: st.prompt || img.name.replace(/\.[^.]+$/, ""), imageB64: img.b64 } : undefined);
  const suggested = SUGGESTED[isCad ? (st.cadKind === "assembly" ? "cad_assembly" : "cad_part") : "mesh"];
  // an attached image is a complete mesh input on its own (image2mesh; prompt falls back to the
  // filename) — the buttons must not read as "prompt required" when one is staged
  const genEnabled = st.prompt.trim().length > 0 || (!!img && !isCad);

  const trackSeg = (active: boolean) =>
    sx("flex:1;padding:8px 10px;border:none;border-radius:5px;font-family:'Spline Sans Mono',monospace;font-size:12px;letter-spacing:.06em;cursor:pointer;transition:background .15s,color .15s;" +
      (active ? "background:#ededed;color:#0d0d0d;font-weight:600;" : "background:transparent;color:var(--text-2);"));
  const subSeg = (active: boolean) =>
    sx("padding:6px 13px;border-radius:5px;border:1px solid " + (active ? "var(--border-2)" : "transparent") +
      ";font-family:'Spline Sans Mono',monospace;font-size:11px;letter-spacing:.05em;cursor:pointer;transition:background-color .15s,color .15s,border-color .15s;background:" +
      (active ? "rgba(255,255,255,.09)" : "transparent") + ";color:" + (active ? "#fff" : "var(--text-2)") + ";");

  const dotStyle = (on: boolean) =>
    sx("height:5px;border:none;border-radius:3px;cursor:pointer;transition:width .3s,background .3s;padding:0;" +
      (on ? "width:28px;background:var(--accent,#4d9eff);" : "width:10px;background:rgba(255,255,255,.28);"));

  const tryIt = (track: "cad" | "mesh") => {
    st.setTrack(track);
    const seed = track === "cad"
      ? "bearing block 40×30×20 mm with a ⌀12 mm through-bore and 4× M4 corner holes"
      : "an ancient alien relic, weathered stone with glowing rune engravings";
    const p = st.prompt.trim() || seed;
    st.setPrompt(p);
    st.startGenerate({ prompt: p });
  };

  const recent = st.library.slice(0, 5);
  const taskCount = st.tasks.filter((t) => t.done).length + "/" + st.tasks.length;

  return (
    <div style={sx("animation:mlk-fade .3s ease; height:100%; display:flex; flex-direction:column; min-height:0;")}>
      {/* ---- carousel (slim) ---- */}
      <div style={sx("position:relative; height:212px; flex-shrink:0; border:1px solid var(--border); background:linear-gradient(180deg,var(--panel-2),var(--inset)); border-radius:4px; overflow:hidden; animation:mlk-stagger .45s ease both;")}>
        <div style={sx("position:absolute; right:0; top:0; bottom:0; width:54%; overflow:hidden;")}>
          <div style={sx("position:absolute; inset:0; background-image:linear-gradient(rgba(255,255,255,.055) 1px, transparent 1px),linear-gradient(90deg, rgba(255,255,255,.055) 1px, transparent 1px); background-size:52px 52px; -webkit-mask-image:linear-gradient(to left,#000 25%,transparent 92%); mask-image:linear-gradient(to left,#000 25%,transparent 92%);")} />
          <svg width="270" height="270" viewBox="0 0 100 100" style={sx("position:absolute; right:-12px; top:50%; transform:translateY(-50%);")}>
            <path d="M50 8 88 30 50 52 12 30Z" fill="#fff" fillOpacity=".96" />
            <path d="M12 30 50 52 50 94 12 72Z" fill="#fff" fillOpacity=".5" />
            <path d="M88 30 50 52 50 94 88 72Z" fill="#fff" fillOpacity=".76" />
            <g fill="none" stroke="#0d0d0d" strokeOpacity=".22" strokeWidth="1" strokeLinejoin="round"><path d="M50 8 88 30 50 52 12 30Z" /><path d="M12 30 50 52 50 94 12 72M88 30 50 52 50 94 88 72" /></g>
          </svg>
        </div>

        {([
          { chip: "CAD ENGINE", chipCol: "#5aa9e6", h: "Generate a verified CAD part", p: "Dimensioned, editable, fabricable — exported as STEP & STL, every measurement proven.", track: "cad" as const },
          { chip: "MESH ENGINE", chipCol: "#e879c5", h: "Generate an organic mesh", p: "Textured GLB creatures, props, and hulls — from a text prompt or a concept image.", track: "mesh" as const },
        ]).map((s, i) => (
          <div key={s.chip} style={{
            ...sx("position:absolute; left:0; top:0; bottom:0; width:62%; padding:20px 36px; display:flex; flex-direction:column; justify-content:center; transition:opacity .4s ease;"),
            opacity: carousel === i ? 1 : 0, pointerEvents: carousel === i ? "auto" : "none",
          }}>
            <span style={{ ...sx("align-self:flex-start; padding:4px 11px; border-radius:4px; font-family:'Spline Sans Mono',monospace; font-size:10.5px; letter-spacing:.08em;"), border: `1px solid ${s.chipCol}88`, color: s.chipCol }}>{s.chip}</span>
            <h2 style={sx("margin:11px 0 0; font-family:'Spline Sans Mono',monospace; font-weight:700; font-size:21px; line-height:1.12; letter-spacing:-.01em; color:#fff; max-width:440px;")}>{s.h}</h2>
            <p style={sx("margin:8px 0 0; font-size:14px; color:var(--text-2); max-width:430px;")}>{s.p}</p>
            <div style={sx("display:flex; gap:11px; margin-top:15px;")}>
              <button data-press data-primary onClick={() => tryIt(s.track)}
                style={sx("padding:10px 18px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:500; letter-spacing:.1em; white-space:nowrap; cursor:pointer;")}>
                <span data-ulw>TRY IT NOW</span>
              </button>
              <span style={sx("display:inline-flex; clip-path:var(--notch); background:var(--border-2);")}>
                <button data-press onClick={() => st.showToast(s.track === "cad" ? "Every CAD result ships with a deterministic verification report" : "Mesh tiers: fast / quality / hero-1536")}
                  style={sx("clip-path:var(--notch); margin:1px; padding:9px 16px; border:none; background:var(--inset); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:500; letter-spacing:.1em; white-space:nowrap; cursor:pointer;")}>
                  <span data-ulw>LEARN MORE</span>
                </button>
              </span>
            </div>
          </div>
        ))}

        <button data-press className="hv-white" onClick={() => setCarousel((c) => (c + 1) % 2)} title="Previous"
          style={sx("position:absolute; left:16px; top:50%; transform:translateY(-50%); width:34px; height:34px; border-radius:50%; border:1px solid var(--border-2); background:rgba(0,0,0,.42); color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
          <I k="chev-left" size={18} />
        </button>
        <button data-press className="hv-white" onClick={() => setCarousel((c) => (c + 1) % 2)} title="Next"
          style={sx("position:absolute; right:16px; top:50%; transform:translateY(-50%); width:34px; height:34px; border-radius:50%; border:1px solid var(--border-2); background:rgba(0,0,0,.42); color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
          <I k="chev-right" size={18} />
        </button>
        <div style={sx("position:absolute; left:36px; bottom:13px; display:flex; gap:7px;")}>
          <button data-press className="hv-white-b2" title="Slide 1" onClick={() => setCarousel(0)} style={dotStyle(carousel === 0)} />
          <button data-press className="hv-white-b2" title="Slide 2" onClick={() => setCarousel(1)} style={dotStyle(carousel === 1)} />
        </div>
      </div>

      {/* ---- 3-column grid (fills the rest of the viewport, cards scroll internally) ---- */}
      <div data-dash-grid style={sx("display:grid; grid-template-columns:minmax(248px,310px) minmax(0,1fr) minmax(248px,310px); gap:14px; margin-top:14px; flex:1; min-height:0;")}>

        {/* Recent Models */}
        <section style={sx("border:1px solid var(--border); background:var(--panel); border-radius:4px; padding:14px; display:flex; flex-direction:column; min-height:0; overflow:hidden;")}>
          <div style={sx("display:flex; align-items:center; justify-content:space-between; flex-shrink:0;")}>
            <h3 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:17px; color:#fff;")}>Recent Models</h3>
            <span style={sx("display:inline-flex; clip-path:var(--notch); background:var(--border-2);")}>
              <button data-press onClick={() => st.go("projects", "projects")}
                style={sx("clip-path:var(--notch); margin:1px; padding:7px 12px; border:none; background:var(--panel); color:var(--text-2); font-family:'Spline Sans Mono',monospace; font-size:11px; font-weight:500; letter-spacing:.09em; cursor:pointer;")}>
                <span data-ulw>VIEW ALL</span>
              </button>
            </span>
          </div>
          <div data-cardstagger style={sx("margin-top:10px; display:flex; flex-direction:column; gap:6px; flex:1; min-height:0; overflow-y:auto;")}>
            {recent.length === 0 && (
              <div style={sx("padding:14px 6px; font-size:13px; line-height:1.55; color:var(--text-3);")}>
                Nothing generated yet — your verified models will appear here.
              </div>
            )}
            {recent.map((m: Model) => (
              <div key={m.id} data-press className="hv-row" onClick={() => st.openModel(m, "editor")}
                style={sx("display:flex; align-items:center; gap:11px; padding:7px 8px; border-radius:5px; cursor:pointer; border:1px solid transparent; flex-shrink:0;")}>
                <div style={sx("width:46px; height:46px; flex-shrink:0; border-radius:5px; overflow:hidden; background-color:#6a6a6d; display:flex; align-items:center; justify-content:center;")}>
                  {m.thumb ? <img src={m.thumb} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                    : <I k="cube" size={26} style={{ color: "#e8e8e8" }} />}
                </div>
                <div style={sx("min-width:0; flex:1;")}>
                  <div style={sx("font-size:14px; font-weight:600; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{m.name}</div>
                  <div style={sx("margin-top:2px; display:flex; align-items:center; gap:8px; font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--text-2);")}>
                    <span>{timeAgo(m.ts)}</span>
                    <span style={sx("display:inline-flex; align-items:center; gap:4px; color:var(--text-3); font-family:'Ufficio','IBM Plex Sans',sans-serif; font-size:12px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;")}>
                      <I k="folder" size={12} />{m.project}
                    </span>
                  </div>
                </div>
                <KebabMenu items={[{ label: "Delete model", danger: true, onClick: () => st.deleteModel(m.id) }]} />
              </div>
            ))}
          </div>
        </section>

        {/* Generation panel */}
        <section style={sx("border:1px solid var(--border); background:var(--panel); border-radius:4px; padding:14px 16px; display:flex; flex-direction:column; min-height:0; overflow:hidden;")}>
          <div style={sx("display:flex; align-items:center; justify-content:space-between; flex-shrink:0;")}>
            <div style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:20px; letter-spacing:.01em; color:#fff;")}>MOTIONLAB</div>
            <div style={sx("display:flex; align-items:center; gap:9px;")}>
              <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.12em; color:var(--text-3);")}>TRACK</span>
              <div style={sx("display:flex; padding:3px; background:var(--inset); border:1px solid var(--border); border-radius:7px; width:164px;")}>
                <button data-press data-seg {...(isCad ? { "data-on": "" } : {})} onClick={() => st.setTrack("cad")} style={trackSeg(isCad)}>CAD</button>
                <button data-press data-seg {...(!isCad ? { "data-on": "" } : {})} onClick={() => st.setTrack("mesh")} style={trackSeg(!isCad)}>MESH</button>
              </div>
            </div>
          </div>

          <div style={sx("display:flex; align-items:center; gap:8px; margin-top:10px; flex-shrink:0;")}>
            <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3); margin-right:2px;")}>{isCad ? "TYPE" : "TIER"}</span>
            <span style={{ order: 9, marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 7 }}>
              <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.1em; color:var(--text-3);")}>PROJECT</span>
              <ProjectPicker compact value={st.activeProject} onPick={(p) => st.selectProject(p)} />
            </span>
            {isCad ? (
              <>
                <button data-press data-seg {...(st.cadKind === "part" ? { "data-on": "" } : {})} onClick={() => st.setCadKind("part")} style={subSeg(st.cadKind === "part")}>PART</button>
                <button data-press data-seg {...(st.cadKind === "assembly" ? { "data-on": "" } : {})} onClick={() => st.setCadKind("assembly")} style={subSeg(st.cadKind === "assembly")}>ASSEMBLY</button>
              </>
            ) : (
              <>
                <button data-press data-seg {...(st.meshTier === "fast" ? { "data-on": "" } : {})} onClick={() => st.setMeshTier("fast")} style={subSeg(st.meshTier === "fast")}>FAST</button>
                <button data-press data-seg {...(st.meshTier === "quality" ? { "data-on": "" } : {})} onClick={() => st.setMeshTier("quality")} style={subSeg(st.meshTier === "quality")}>QUALITY</button>
                <button data-press data-seg {...(st.meshTier === "hero" ? { "data-on": "" } : {})} onClick={() => st.setMeshTier("hero")} style={subSeg(st.meshTier === "hero")}>HERO</button>
              </>
            )}
          </div>

          <div style={sx("display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; flex-shrink:0;")}>
            <input ref={imgRef} type="file" accept="image/*" style={{ display: "none" }}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setImg({ b64: await fileToB64(f), name: f.name });
                e.currentTarget.value = "";
              }} />
            {img && !isCad ? (
              <div style={sx("border:1px solid rgba(var(--accent-rgb),.45); background:rgba(var(--accent-rgb),.07); border-radius:4px; padding:6px 8px 6px 6px; display:flex; align-items:center; gap:9px; min-width:0;")}>
                <img src={"data:image/png;base64," + img.b64} alt=""
                  style={{ width: 30, height: 30, objectFit: "cover", borderRadius: 3, flexShrink: 0 }} />
                <span style={sx("flex:1; min-width:0; font-size:12.5px; font-weight:600; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{img.name}</span>
                <button data-press data-iconbtn title="Remove image" onClick={() => setImg(null)}
                  style={sx("width:24px; height:24px; flex-shrink:0; border:none; border-radius:4px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
                  <I k="close" size={14} />
                </button>
              </div>
            ) : (
              <button data-press data-accenthover
                onClick={() => { if (isCad) st.showToast("Image \u2192 CAD \u2014 coming soon"); else imgRef.current?.click(); }}
                style={sx("border:1px solid var(--border); background:transparent; border-radius:4px; padding:10px 12px; display:flex; align-items:center; justify-content:center; gap:10px; cursor:pointer; color:var(--text);" + (isCad ? "opacity:.6;" : ""))}>
                <I k="image" size={19} style={{ color: "var(--text-2)" }} />
                <span style={sx("font-size:13.5px; font-weight:600; color:var(--text);")}>{isCad ? "Upload images (soon)" : "Upload images"}</span>
              </button>
            )}
            <button data-press data-accenthover onClick={() => st.showToast("Context manager — coming soon")}
              style={sx("border:1px solid var(--border); background:transparent; border-radius:4px; padding:10px 12px; display:flex; align-items:center; justify-content:center; gap:10px; cursor:pointer; color:var(--text);")}>
              <I k="check" size={19} style={{ color: "var(--text-2)" }} />
              <span style={sx("font-size:13.5px; font-weight:600; color:var(--text);")}>Add references</span>
            </button>
          </div>

          <textarea value={st.prompt} onChange={(e) => st.setPrompt(e.target.value)}
            placeholder={img && !isCad
              ? "Optional — a short description improves color & texture, or generate straight from your image"
              : "Enter a description to generate a 3D model with MotionLab"}
            style={sx("margin-top:10px; flex:1; min-height:64px; width:100%; padding:12px 14px; border:1px solid var(--border); background:var(--inset); color:var(--text); border-radius:4px; font-size:14.5px; line-height:1.5;")} />

          <div style={sx("margin-top:10px; display:flex; align-items:center; gap:10px; flex-shrink:0;")}>
            <button data-press data-accenthover onClick={rollDice} title="Surprise me"
              style={sx("flex-shrink:0; display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; border:1px solid var(--border-2); border-radius:5px; background:transparent; color:var(--text-2); font-size:15px; cursor:pointer;")}>
              <span style={rolling ? { display: "inline-block", animation: "mlk-spin .6s linear infinite" } : undefined}>🎲</span>
            </button>
            <span style={sx("font-size:13px; color:var(--text-2); flex-shrink:0;")}>Suggested prompts:</span>
            <div style={sx("display:flex; gap:8px; overflow-x:auto; padding-bottom:3px; min-width:0;")}>
              {suggested.map((s) => (
                <button key={s} data-press data-accenthover onClick={() => st.setPrompt(SUGGEST_FULL[s] || s)}
                  style={sx("flex-shrink:0; padding:6px 11px; border:1px solid var(--border-2); background:transparent; color:var(--text-2); font-size:13px; white-space:nowrap; cursor:pointer;")}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          <button data-press onClick={doGenerate}
            style={sx("margin-top:10px; flex-shrink:0; width:100%;padding:13px;border:none;clip-path:var(--notch);background:#ededed;color:#0d0d0d;cursor:pointer;font-family:'Spline Sans Mono',monospace;font-size:13px;font-weight:500;letter-spacing:.1em;" + (genEnabled ? "" : "opacity:.55;"))}>
            <span data-ulw>GENERATE</span>
          </button>
        </section>

        {/* Generation Tasks */}
        <section style={sx("border:1px solid var(--border); background:var(--panel); border-radius:4px; padding:14px; display:flex; flex-direction:column; min-height:0; overflow:hidden;")}>
          <div style={sx("display:flex; align-items:center; justify-content:space-between; flex-shrink:0;")}>
            <h3 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:17px; color:#fff;")}>Generation Tasks</h3>
            <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:12px; color:var(--text-2);")}>{taskCount}</span>
          </div>

          {st.tasks.length > 0 ? (
            <div style={sx("margin-top:10px; flex:1; min-height:0; display:flex; flex-direction:column; gap:8px; overflow-y:auto;")}>
              {st.tasks.map((t: Task) => {
                const pct = t.done ? 100 : t.error ? 0 : Math.min(97, Math.round((t.elapsed / t.estSec) * 100));
                return (
                  <div key={t.id} data-press className={t.running ? "mlk-tracing" : undefined}
                    onClick={() => { const m = st.library.find((x) => x.id === t.modelId); if (m) st.openModel(m, "result"); }}
                    style={sx("border:1px solid var(--border); background:var(--inset); border-radius:4px; padding:10px 11px; flex-shrink:0;" + (t.modelId ? "cursor:pointer;" : ""))}>
                    <div style={sx("display:flex; align-items:center; gap:9px;")}>
                      {t.running && <span style={sx("width:14px; height:14px; flex-shrink:0; border:2px solid rgba(255,255,255,.18); border-top-color:var(--accent,#4d9eff); border-radius:50%; animation:mlk-spin .8s linear infinite;")} />}
                      {t.done && <I k="check" size={15} style={{ color: "var(--verified)", animation: "mlk-stamp .35s ease" } as any} />}
                      {t.error && <span style={sx("width:9px; height:9px; flex-shrink:0; border-radius:50%; background:var(--fail);")} />}
                      <span style={sx("font-size:13.5px; font-weight:600; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{t.name}</span>
                      <span style={sx("margin-left:auto; font-family:'Spline Sans Mono',monospace; font-size:11px; color:var(--text-3);")}>{t.error ? "—" : pct + "%"}</span>
                    </div>
                    <div style={sx("margin-top:6px; font-family:'Spline Sans Mono',monospace; font-size:11px; letter-spacing:.04em; color:var(--text-2); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>
                      {t.error ? "error · " + t.error : t.done ? "Completed · ready in Library" : t.stage + (t.elapsed ? ` · ${Math.round(t.elapsed)}s` : "")}
                    </div>
                    <div style={sx("margin-top:6px; height:4px; border-radius:3px; background:rgba(255,255,255,.08); overflow:hidden;")}>
                      <div style={{ height: "100%", background: t.error ? "var(--fail)" : "var(--accent,#4d9eff)", width: pct + "%", transition: "width .9s linear" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={sx("flex:1; min-height:0; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; padding:12px;")}>
              <I k="star" size={40} style={{ color: "var(--text-3)" }} />
              <div style={sx("margin-top:11px; font-size:15px; font-weight:600; color:var(--text);")}>No generation task</div>
              <div style={sx("margin-top:5px; font-size:13px; line-height:1.5; color:var(--text-2); max-width:230px;")}>Start a generation and your progress will appear here.</div>
            </div>
          )}

          <button data-press onClick={doGenerate}
            data-primary style={sx("margin-top:10px; flex-shrink:0; width:100%; padding:12px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
            <span data-ulw>START TO GENERATE</span>
          </button>
        </section>
      </div>
    </div>
  );
}
