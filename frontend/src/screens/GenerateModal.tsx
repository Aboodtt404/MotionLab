/* Generate modal — the image→3D configurator (rail · config panel · center viewport · gallery),
 * transcribed from the prototype's GENERATE MODAL. Real wiring: drop/upload an image → preview →
 * GENERATE posts /api/trackb/image2mesh (Multi-view toggle maps to the backend's multiview flag —
 * the side-profile rule for vehicles). The gallery shows the real mesh library. */
import { useEffect, useRef, useState } from "react";
import { sx } from "../sx";
import { I } from "../icons";
import { useStudio } from "../store";
import { fileToB64 } from "../gltf";

export function GenerateModal({ closing }: { closing?: boolean }) {
  const st = useStudio();
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [imageName, setImageName] = useState("");
  const [modelType, setModelType] = useState<"standard" | "lowpoly">("standard");
  const [license, setLicense] = useState<"cc" | "private">("private");
  const [enhance, setEnhance] = useState(true);
  const [multi, setMulti] = useState(true);   // MV-Adapter default-on — toggle off for quick drafts
  const [pose, setPose] = useState(false);
  const [poseType, setPoseType] = useState<"a" | "t" | "c">("a");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") st.setGenModalOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [st]);

  const onFile = async (f: File | null) => {
    if (!f) return;
    setImageB64(await fileToB64(f));
    setImageName(f.name);
  };

  const seg = (active: boolean) =>
    sx("flex:1;padding:9px 8px;border:none;border-radius:4px;font-family:'Ufficio','IBM Plex Sans',sans-serif;font-size:13.5px;cursor:pointer;transition:background .15s,color .15s;white-space:nowrap;" +
      (active ? "background:var(--accent,#4d9eff);color:var(--on-accent,#06111c);font-weight:600;" : "background:transparent;color:var(--text-2);"));
  const tglTrack = (on: boolean) =>
    sx("position:relative;width:42px;height:23px;border-radius:12px;border:none;cursor:pointer;transition:background .2s;flex-shrink:0;background:" +
      (on ? "var(--accent,#4d9eff)" : "rgba(255,255,255,.16)") + ";");
  const tglKnob = (on: boolean) =>
    sx("position:absolute;top:2.5px;left:2.5px;width:18px;height:18px;border-radius:50%;background:#fff;transition:transform .2s;transform:translateX(" + (on ? "19px" : "0") + ");");

  const railMeta: [string, string][] = [["Assets", "grid"], ["Agent", "community"], ["Image", "image"], ["Model", "cube"], ["Print", "layers"], ["Animate", "star"]];
  const meshLib = st.library.filter((m) => m.engine === "mesh");
  const grad = (a: string, b: string) => `linear-gradient(150deg,${a} 0%,${b} 100%)`;
  const galFill = [["#4a4d52", "#232427"], ["#6b4a2a", "#2a1c12"], ["#3c5a3a", "#16241a"], ["#2f3f52", "#141c26"], ["#5a2f3a", "#26121a"], ["#52462f", "#241f12"], ["#3a2f52", "#191226"], ["#2f5250", "#122624"]];

  const doGenerate = () => {
    if (!imageB64) { st.showToast("Drop a concept image first"); return; }
    st.setTrack("mesh");
    st.setGenModalOpen(false);
    st.startGenerate({ prompt: st.prompt || imageName.replace(/\.[^.]+$/, ""), imageB64, multiview: multi });
  };

  const est = st.meshTier === "fast" ? "~1 min" : st.meshTier === "hero" ? "~5 min" : "~2 min";
  const imgUrl = imageB64 ? "data:image/png;base64," + imageB64 : null;

  return (
    <div onClick={() => st.setGenModalOpen(false)}
      {...(closing ? { "data-closing": "", "data-exit": "fade" } : {})}
      style={sx("position:absolute; inset:0; z-index:50; display:flex; align-items:center; justify-content:center; overflow:auto; padding:22px; background:rgba(6,6,7,.76); backdrop-filter:blur(6px); animation:mlk-backdrop .22s ease;")}>
      <section onClick={(e) => e.stopPropagation()}
        {...(closing ? { "data-closing": "" } : {})}
        style={sx("position:relative; flex-shrink:0; width:1240px; max-width:96vw; height:min(884px, 92vh); min-height:640px; background:var(--bg); border:1px solid var(--border-2); border-radius:9px; overflow:hidden; display:flex; box-shadow:0 40px 120px rgba(0,0,0,.6); animation:mlk-pop .28s var(--ease-out);")}>

        <button data-press className="hv-closeacc" onClick={() => st.setGenModalOpen(false)} title="Close"
          style={sx("position:absolute; right:14px; top:13px; z-index:8; width:34px; height:34px; border:1px solid var(--border-2); border-radius:7px; background:rgba(0,0,0,.45); color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
          <I k="close" size={19} />
        </button>

        {/* rail */}
        <div style={sx("width:76px; flex-shrink:0; border-right:1px solid var(--border); background:var(--sidebar); display:flex; flex-direction:column; gap:3px; padding:14px 8px;")}>
          {railMeta.map(([label, icon], i) => (
            <button key={label} data-press title={label}
              onClick={() => { if (i !== 2) st.showToast(label + " — coming soon"); }}
              style={sx("width:100%;padding:11px 0;border:none;border-radius:8px;background:" +
                (i === 2 ? "rgba(var(--accent-rgb),.14)" : "transparent") +
                ";display:flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;font-family:'Spline Sans Mono',monospace;font-size:9.5px;letter-spacing:.04em;transition:background .15s,color .15s;color:" +
                (i === 2 ? "var(--accent,#4d9eff)" : "var(--text-2)") + ";")}>
              <I k={icon} size={21} /><span>{label}</span>
            </button>
          ))}
        </div>

        {/* config panel */}
        <div style={sx("width:318px; flex-shrink:0; border-right:1px solid var(--border); background:var(--sidebar); display:flex; flex-direction:column;")}>
          <div style={sx("display:flex; gap:10px; padding:16px 18px 6px;")}>
            <button data-press title="Image to 3D"
              style={sx("width:48px; height:42px; border:1px solid var(--accent,#4d9eff); border-radius:6px; background:rgba(var(--accent-rgb),.14); color:var(--accent,#4d9eff); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="image" size={22} />
            </button>
            <button data-press className="hv-white-b2" title="Retexture" onClick={() => st.showToast("Retexture — coming with the Paint pass")}
              style={sx("width:48px; height:42px; border:1px solid var(--border); border-radius:6px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="mesh" size={22} />
            </button>
            <button data-press className="hv-white-b2" title="Refine" onClick={() => st.showToast("Refine — coming soon")}
              style={sx("width:48px; height:42px; border:1px solid var(--border); border-radius:6px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="cube" size={22} />
            </button>
          </div>

          <div style={sx("flex:1; overflow-y:auto; padding:12px 18px 18px;")}>
            <div style={sx("font-size:14px; font-weight:600; color:#fff; margin-bottom:10px;")}>Image</div>
            <div data-press onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files?.[0] || null); }}
              style={sx("border:1px dashed var(--border-2); border-radius:6px; height:168px; overflow:hidden; background:var(--inset); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              {imgUrl
                ? <img src={imgUrl} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                : (
                  <div style={sx("display:flex; flex-direction:column; align-items:center; gap:9px; color:var(--text-3);")}>
                    <I k="image" size={34} /><span style={{ fontSize: 12.5 }}>Drop an image</span>
                  </div>
                )}
            </div>
            <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
              onChange={(e) => onFile(e.target.files?.[0] || null)} />

            <div style={sx("margin-top:20px;")}>
              <div style={sx("font-size:13.5px; color:var(--text); margin-bottom:9px;")}>Quality Tier</div>
              <div style={sx("display:flex; gap:3px; padding:3px; background:var(--inset); border:1px solid var(--border); border-radius:6px;")}>
                <button data-press data-seg {...(st.meshTier === "fast" ? { "data-on": "" } : {})} onClick={() => st.setMeshTier("fast")} style={seg(st.meshTier === "fast")}>Fast</button>
                <button data-press data-seg {...(st.meshTier === "quality" ? { "data-on": "" } : {})} onClick={() => st.setMeshTier("quality")} style={seg(st.meshTier === "quality")}>Quality</button>
                <button data-press data-seg {...(st.meshTier === "hero" ? { "data-on": "" } : {})} onClick={() => st.setMeshTier("hero")} style={seg(st.meshTier === "hero")}>Hero</button>
              </div>
            </div>

            <div style={sx("margin-top:20px;")}>
              <div style={sx("font-size:13.5px; color:var(--text); margin-bottom:9px;")}>Model Type</div>
              <div style={sx("display:flex; gap:3px; padding:3px; background:var(--inset); border:1px solid var(--border); border-radius:6px;")}>
                <button data-press data-seg {...(modelType === "standard" ? { "data-on": "" } : {})} onClick={() => setModelType("standard")} style={seg(modelType === "standard")}>Standard</button>
                <button data-press data-seg onClick={() => { setModelType("standard"); st.showToast("Low-poly runs as a post pass (/lowpoly) — coming to this modal"); }} style={seg(false)}>Low Poly</button>
              </div>
            </div>

            <div style={sx("margin-top:20px;")}>
              <div style={sx("font-size:13.5px; color:var(--text); margin-bottom:9px;")}>AI Model</div>
              <button data-press className="hv-accentborder"
                style={sx("width:100%; display:flex; align-items:center; justify-content:space-between; padding:11px 13px; border:1px solid var(--border); border-radius:6px; background:var(--panel); color:var(--text); font-size:14px; cursor:pointer;")}>
                TRELLIS.2<I k="chev-down" size={16} style={{ color: "var(--text-2)" }} />
              </button>
            </div>

            <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-top:22px;")}>
              <span style={sx("font-size:13.5px; color:var(--text);")}>Image Enhancement</span>
              <button data-press onClick={() => setEnhance((v) => !v)} style={tglTrack(enhance)}><span style={tglKnob(enhance)} /></button>
            </div>
            <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-top:18px;")}>
              <span style={sx("font-size:13.5px; color:var(--text);")}>Multi-view <span style={sx("color:var(--text-3); font-size:12px;")}>(Beta)</span></span>
              <button data-press onClick={() => setMulti((v) => !v)} style={tglTrack(multi)}><span style={tglKnob(multi)} /></button>
            </div>
            <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-top:18px;")}>
              <span style={sx("font-size:13.5px; color:var(--text);")}>Pose</span>
              <button data-press onClick={() => setPose((v) => !v)} style={tglTrack(pose)}><span style={tglKnob(pose)} /></button>
            </div>
            {pose && (
              <div style={sx("display:flex; gap:3px; padding:3px; background:var(--inset); border:1px solid var(--border); border-radius:6px; margin-top:11px;")}>
                <button data-press data-seg {...(poseType === "a" ? { "data-on": "" } : {})} onClick={() => setPoseType("a")} style={seg(poseType === "a")}>A-Pose</button>
                <button data-press data-seg {...(poseType === "t" ? { "data-on": "" } : {})} onClick={() => setPoseType("t")} style={seg(poseType === "t")}>T-Pose</button>
                <button data-press data-seg {...(poseType === "c" ? { "data-on": "" } : {})} onClick={() => setPoseType("c")} style={seg(poseType === "c")}>Custom</button>
              </div>
            )}

            <div style={sx("margin-top:22px;")}>
              <div style={sx("font-size:13.5px; color:var(--text); margin-bottom:9px;")}>License</div>
              <div style={sx("display:flex; gap:3px; padding:3px; background:var(--inset); border:1px solid var(--border); border-radius:6px;")}>
                <button data-press data-seg {...(license === "cc" ? { "data-on": "" } : {})} onClick={() => setLicense("cc")} style={seg(license === "cc")}>CC BY 4.0</button>
                <button data-press data-seg {...(license === "private" ? { "data-on": "" } : {})} onClick={() => setLicense("private")} style={seg(license === "private")}>Private</button>
              </div>
            </div>
          </div>

          <div style={sx("border-top:1px solid var(--border); padding:14px 18px; display:flex; flex-direction:column; gap:11px;")}>
            <div style={sx("display:flex; align-items:center; justify-content:center; gap:9px; font-family:'Spline Sans Mono',monospace; font-size:12.5px; color:var(--text-2);")}>
              <span>{est}</span><span style={{ color: "var(--text-3)" }}>·</span>
              <span style={sx("color:var(--accent,#4d9eff); font-weight:500;")}>local GPU</span>
            </div>
            <button data-press onClick={doGenerate}
              style={sx("width:100%;padding:16px;border:none;clip-path:var(--notch);background:#ededed;color:#0d0d0d;cursor:pointer;font-family:'Spline Sans Mono',monospace;font-size:13.5px;font-weight:500;letter-spacing:.1em;" + (imageB64 ? "" : "opacity:.55;"))}>
              <span data-ulw>GENERATE</span>
            </button>
          </div>
        </div>

        {/* center viewport */}
        <div style={sx("flex:1; min-width:0; position:relative; background:radial-gradient(120% 120% at 50% 40%, #141416 0%, #0a0a0b 82%); display:flex; align-items:center; justify-content:center;")}>
          <div style={sx("position:absolute; left:18px; top:16px; width:236px; display:flex; flex-direction:column; gap:8px;")}>
            <div style={sx("border:1px solid var(--border); background:rgba(17,17,20,.85); border-radius:6px; padding:13px 15px; display:flex; flex-direction:column; gap:10px; backdrop-filter:blur(6px);")}>
              <div style={sx("display:flex; align-items:center; justify-content:space-between; font-size:13px;")}><span style={{ color: "var(--text-2)" }}>Topology</span><span style={{ color: "#fff" }}>Triangle</span></div>
              <div style={sx("display:flex; align-items:center; justify-content:space-between; font-size:13px;")}><span style={{ color: "var(--text-2)" }}>Faces</span><span style={sx("color:#fff; font-family:'Spline Sans Mono',monospace; font-size:12.5px;")}>{meshLib[0]?.report?.faces?.toLocaleString?.() || "—"}</span></div>
              <div style={sx("display:flex; align-items:center; justify-content:space-between; font-size:13px;")}><span style={{ color: "var(--text-2)" }}>Vertices</span><span style={sx("color:#fff; font-family:'Spline Sans Mono',monospace; font-size:12.5px;")}>{meshLib[0]?.report?.verts?.toLocaleString?.() || "—"}</span></div>
            </div>
            <div style={sx("border:1px solid var(--border); background:rgba(17,17,20,.85); border-radius:6px; padding:12px 15px; display:flex; align-items:center; justify-content:space-between; backdrop-filter:blur(6px);")}>
              <span style={sx("font-size:13px; color:var(--text-2);")}>Printability</span>
              <span style={sx("width:22px; height:22px; border-radius:50%; background:var(--accent,#4d9eff); display:flex; align-items:center; justify-content:center;")}>
                <I k="check" size={14} style={{ color: "var(--on-accent,#06111c)" }} />
              </span>
            </div>
          </div>

          <div style={sx("width:min(58%, 440px); aspect-ratio:4/3; display:flex; align-items:center; justify-content:center; color:rgba(240,240,240,.5); overflow:hidden;")}>
            {imgUrl
              ? <img src={imgUrl} alt="" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", display: "block" }} />
              : meshLib[0]?.thumb
                ? <img src={meshLib[0].thumb!} alt="" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", display: "block" }} />
                : <I k="cube" size={160} />}
          </div>

          <div style={sx("position:absolute; left:50%; bottom:22px; transform:translateX(-50%); display:flex; align-items:center; gap:7px; padding:8px 10px; background:rgba(15,15,17,.82); border:1px solid var(--border); border-radius:12px; backdrop-filter:blur(8px);")}>
            <button data-press className="hv-panel2" title="Settings" onClick={() => st.showToast("Tier + toggles on the left panel")}
              style={sx("width:38px; height:38px; border:none; border-radius:8px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="sliders" size={20} />
            </button>
            <button data-press className="hv-accent2" onClick={() => st.showToast("PBR texture channels ship with every TRELLIS.2 result")}
              data-primary style={sx("display:flex; align-items:center; gap:8px; padding:0 15px; height:38px; border:none; border-radius:8px; font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:600; letter-spacing:.05em; cursor:pointer;")}>
              <I k="layers" size={17} />Texture
            </button>
            <button data-press className="hv-panel2" title="Remesh" onClick={() => st.showToast("Remesh/low-poly — /lowpoly post pass")}
              style={sx("width:38px; height:38px; border:none; border-radius:8px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="mesh" size={20} />
            </button>
            <button data-press className="hv-panel2" title="Transform" onClick={() => st.showToast("Transform in the editor after generating")}
              style={sx("width:38px; height:38px; border:none; border-radius:8px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="scale" size={20} />
            </button>
            <div style={sx("width:1px; height:24px; background:var(--border-2);")} />
            <button data-press className="hv-accent2" title="Generate" onClick={doGenerate}
              data-primary style={sx("width:38px; height:38px; border:none; border-radius:8px; display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="export" size={20} />
            </button>
          </div>
        </div>

        {/* gallery */}
        <div style={sx("width:346px; flex-shrink:0; border-left:1px solid var(--border); background:var(--sidebar); display:flex; flex-direction:column;")}>
          <div style={sx("display:flex; align-items:flex-start; gap:12px; padding:16px 16px 14px; border-bottom:1px solid var(--border);")}>
            <div style={sx("flex:1; font-size:12.5px; line-height:1.45; color:var(--text-2);")}>Every generation lands in the session library — re-open, re-run, iterate.</div>
          </div>
          <div style={sx("display:flex; gap:9px; padding:14px 16px 10px;")}>
            <div style={sx("flex:1; display:flex; align-items:center; gap:9px; min-width:0; padding:0 12px; height:40px; background:var(--panel); border:1px solid var(--border); border-radius:5px; color:var(--text-2);")}>
              <I k="search" size={16} />
              <input placeholder="Search my generation" style={sx("flex:1; min-width:0; border:none; background:transparent; color:var(--text); font-size:13.5px;")} />
            </div>
            <button data-press onClick={() => fileRef.current?.click()}
              data-primary style={sx("flex-shrink:0; display:flex; align-items:center; gap:7px; padding:0 14px; height:40px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:11.5px; font-weight:500; letter-spacing:.07em; cursor:pointer;")}>
              <I k="upload" size={15} /><span data-ulw>UPLOAD</span>
            </button>
          </div>
          <div style={sx("flex:1; overflow-y:auto; padding:6px 16px 16px;")}>
            <div style={sx("display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;")}>
              {meshLib.map((m, i) => (
                <div key={m.id} data-press className="hv-cardborder" title={m.name}
                  onClick={() => { st.setGenModalOpen(false); st.openModel(m, "editor"); }}
                  style={{
                    ...sx("position:relative;aspect-ratio:1/1;border-radius:6px;overflow:hidden;border:1px solid " + (i === 0 ? "var(--accent,#4d9eff)" : "var(--border)") + ";display:flex;align-items:center;justify-content:center;cursor:pointer;"),
                    background: m.thumb ? "#6a6a6d" : grad(galFill[i % galFill.length][0], galFill[i % galFill.length][1]),
                  }}>
                  {m.thumb
                    ? <img src={m.thumb} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                    : <I k="cube" size={34} style={{ color: "rgba(255,255,255,.5)" }} />}
                </div>
              ))}
              {meshLib.length === 0 && galFill.map((c, i) => (
                <div key={i} style={{
                  ...sx("position:relative;aspect-ratio:1/1;border-radius:6px;overflow:hidden;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;"),
                  background: grad(c[0], c[1]),
                }}>
                  <span style={sx("position:absolute; left:6px; top:6px; padding:2px 6px; background:rgba(0,0,0,.55); border-radius:3px; font-family:'Spline Sans Mono',monospace; font-size:8.5px; letter-spacing:.08em; color:#fff;")}>EXAMPLE</span>
                  <I k="cube" size={34} style={{ color: "rgba(255,255,255,.5)" }} />
                </div>
              ))}
            </div>
          </div>
          <div style={sx("border-top:1px solid var(--border); padding:11px 16px; display:flex; align-items:center; justify-content:space-between; font-family:'Spline Sans Mono',monospace; font-size:12px; color:var(--text-2);")}>
            <div style={sx("display:flex; align-items:center; gap:10px;")}><I k="list" size={16} /><I k="grid" size={16} style={{ color: "var(--text-3)" }} /></div>
            <span>{meshLib.length || 1} / {meshLib.length || 1}</span>
            <span>20 ▾</span>
          </div>
        </div>
      </section>
    </div>
  );
}
