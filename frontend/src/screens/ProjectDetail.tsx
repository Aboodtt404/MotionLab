/* Project detail — the models inside one project, each opening its saved verification result.
 * Status seal per model (verified green / failed red), engine tag, delete via kebab-hover trash. */
import { sx } from "../sx";
import { I } from "../icons";
import { timeAgo, useStudio } from "../store";

const ENG_COLOR: Record<string, string> = { cad: "#5aa9e6", assembly: "#b58cff", mesh: "#e879c5" };

export function ProjectDetail() {
  const st = useStudio();
  const models = st.library.filter((m) => (m.project || "My Project") === st.activeProject);

  return (
    <div style={sx("animation:mlk-fade .3s ease;")}>
      <div style={sx("display:flex; align-items:center; gap:16px; margin-bottom:22px;")}>
        <span style={sx("display:inline-flex; clip-path:var(--notch); background:var(--border-2);")}>
          <button data-press onClick={() => st.go("projects", "projects")}
            style={sx("clip-path:var(--notch); margin:1px; display:flex; align-items:center; gap:8px; padding:10px 16px 10px 11px; border:none; background:var(--inset); color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:500; letter-spacing:.09em; cursor:pointer;")}>
            <I k="chev-left" size={16} /><span data-ulw>PROJECTS</span>
          </button>
        </span>
        <h1 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:26px; color:#fff;")}>{st.activeProject}</h1>
        <span style={sx("font-family:'Spline Sans Mono',monospace; font-size:13px; color:var(--text-2);")}>{models.length} model{models.length === 1 ? "" : "s"}</span>
      </div>

      {models.length === 0 && (
        <div style={sx("padding:34px 6px; font-size:14.5px; color:var(--text-3);")}>
          No models yet — hit GENERATE and results will be saved into this project.
        </div>
      )}

      <div data-cardstagger style={sx("display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,280px)); gap:20px;")}>
        {models.map((m) => {
          const ec = ENG_COLOR[m.engine] || "#9a9aa0";
          const verified = m.status === "verified";
          const sealCol = verified ? "var(--verified)" : "var(--fail)";
          const checks = m.inspection ? `${m.inspection.filter((r) => r.within_tol).length}/${m.inspection.length}` : "";
          return (
            <div key={m.id} data-press className="hv-cardborder" onClick={() => st.openModel(m, "editor")}
              style={sx("position:relative; cursor:pointer; border:1px solid var(--border); border-radius:8px; overflow:hidden; background:var(--panel); transition:border-color .18s, transform var(--dur-1) var(--ease-out);")}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = "translateY(-2px)"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ""; }}>
              <div style={sx("aspect-ratio:1/1; background-color:#6a6a6d; display:flex; align-items:center; justify-content:center;")}>
                {m.thumb
                  ? <img src={m.thumb} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                  : <I k="cube" size={52} style={{ color: "#e8e8e8" }} />}
              </div>
              <span title={verified ? `Verified · ${checks} checks` : `Failed · ${checks} checks`}
                style={{ ...sx("position:absolute; top:9px; right:9px; width:26px; height:26px; border-radius:50%; display:flex; align-items:center; justify-content:center;"), background: verified ? "rgba(55,214,122,.15)" : "rgba(229,100,95,.15)", border: `1.5px solid ${sealCol}` }}>
                {verified
                  ? <svg width="14" height="14" viewBox="0 0 24 24" style={{ color: sealCol } as any}><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  : <svg width="12" height="12" viewBox="0 0 24 24" style={{ color: sealCol } as any}><use href="#i-close" /></svg>}
              </span>
              <span style={{ ...sx("position:absolute; top:11px; left:11px; padding:2px 8px; border-radius:4px; font-family:'Spline Sans Mono',monospace; font-size:9.5px; letter-spacing:.06em;"), background: ec + "22", color: ec }}>
                {m.engine.toUpperCase()}
              </span>
              <div style={sx("padding:13px 14px; display:flex; align-items:center; justify-content:space-between; gap:10px;")}>
                <div style={{ minWidth: 0 }}>
                  <div style={sx("font-size:15px; font-weight:600; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{m.name}</div>
                  <div style={sx("margin-top:3px; font-family:'Spline Sans Mono',monospace; font-size:11.5px; color:var(--text-2);")}>
                    {timeAgo(m.ts)}{checks ? ` · ${checks} checks` : ""}
                  </div>
                </div>
                <button data-press data-iconbtn title="Remove" onClick={(e) => { e.stopPropagation(); st.deleteModel(m.id); }}
                  style={sx("width:28px; height:28px; border:none; border-radius:5px; background:transparent; color:var(--text-3); display:flex; align-items:center; justify-content:center; cursor:pointer; flex-shrink:0;")}>
                  <I k="trash" size={16} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
