/* Projects grid — real projects derived from the persisted library (grouped by model.project),
 * with search + the design's grid/list toggle and sort dropdown affordances. */
import { useRef, useState } from "react";
import { useExit } from "../motion";
import { sx } from "../sx";
import { I } from "../icons";
import { Confirm, KebabMenu } from "./Kebab";
import { useStudio } from "../store";

export function Projects() {
  const st = useStudio();
  const [q, setQ] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [toDelete, setToDelete] = useState<string | null>(null);
  const confirmEx = useExit(!!toDelete, 140);
  const lastDelete = useRef("");
  if (toDelete) lastDelete.current = toDelete;
  const modelCount = (name: string) => st.library.filter((m) => m.project === name).length;

  const groups = st.projects
    .filter((p) => !q.trim() || p.toLowerCase().includes(q.trim().toLowerCase()))
    .map((p) => {
      const models = st.library.filter((m) => (m.project || "My Project") === p);
      return { name: p, models };
    });

  const countLabel = (g: { models: any[] }) => {
    const n = g.models.length;
    if (n === 0) return "Empty project";
    const asm = g.models.filter((m) => m.engine === "assembly").length;
    const mesh = g.models.filter((m) => m.engine === "mesh").length;
    const cad = n - asm - mesh;
    const bits = [cad && `${cad} CAD`, asm && `${asm} assembly`, mesh && `${mesh} mesh`].filter(Boolean);
    return bits.join(" · ") || `${n} models`;
  };

  return (
    <div style={sx("animation:mlk-fade .3s ease;")}>
      <div style={sx("display:flex; align-items:center; gap:18px; margin-bottom:26px;")}>
        <h1 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:28px; color:#fff;")}>My Projects</h1>
        <div style={{ flex: 1 }} />
        <div style={sx("display:flex; padding:3px; background:var(--panel); border:1px solid var(--border); border-radius:4px;")}>
          <button data-press onClick={() => setView("grid")}
            style={sx("width:36px; height:34px; border:none; border-radius:3px; display:flex; align-items:center; justify-content:center; cursor:pointer;" +
              (view === "grid" ? "background:var(--accent,#4d9eff); color:var(--on-accent,#06111c);" : "background:transparent; color:var(--text-2);"))}>
            <I k="grid" size={17} />
          </button>
          <button data-press className="hv-white" onClick={() => setView("list")}
            style={sx("width:36px; height:34px; border:none; border-radius:3px; display:flex; align-items:center; justify-content:center; cursor:pointer;" +
              (view === "list" ? "background:var(--accent,#4d9eff); color:var(--on-accent,#06111c);" : "background:transparent; color:var(--text-2);"))}>
            <I k="list" size={17} />
          </button>
        </div>
        <div data-focusaccent style={sx("display:flex; align-items:center; gap:10px; padding:0 14px; height:44px; width:280px; background:var(--panel); border:1px solid var(--border); border-radius:4px; color:var(--text-2); transition:border-color .15s;")}>
          <I k="search" size={17} />
          <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)}
            style={sx("flex:1; min-width:0; border:none; background:transparent; color:var(--text); font-size:15px;")} />
        </div>
        <button data-press data-focusaccent onClick={() => st.showToast("Sorting — newest first (default)")}
          style={sx("display:flex; align-items:center; gap:10px; padding:0 15px; height:44px; background:var(--panel); border:1px solid var(--border); border-radius:4px; color:var(--text-2); font-size:15px; cursor:pointer; transition:border-color .15s;")}>
          No sorting<I k="chev-down" size={16} />
        </button>
      </div>

      {view === "grid" ? (
        <div data-cardstagger style={sx("display:grid; grid-template-columns:repeat(auto-fill,minmax(248px,300px)); gap:22px;")}>
          {groups.map((g) => {
            const tiles = [g.models[0], g.models[1], g.models[2], g.models[3]];
            return (
              <div key={g.name} data-press className="hv-card" onClick={() => st.openProject(g.name)}
                style={sx("cursor:pointer; padding:10px; border:1px solid transparent; border-radius:8px; transition:border-color .18s, background-color .18s;")}>
                <div style={sx("display:grid; grid-template-columns:1fr 1fr; grid-template-rows:1fr 1fr; gap:8px; aspect-ratio:16/11;")}>
                  {tiles.map((m, i) => (
                    <div key={i} style={sx(m
                      ? "border-radius:5px; overflow:hidden; background-color:#6a6a6d; display:flex; align-items:center; justify-content:center;"
                      : "border-radius:5px; background:var(--panel-2);")}>
                      {m && (m.thumb
                        ? <img src={m.thumb} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                        : <I k="cube" size={46} style={{ color: "#e8e8e8" }} />)}
                    </div>
                  ))}
                </div>
                <div style={sx("display:flex; align-items:center; justify-content:space-between; margin-top:14px; padding:0 4px;")}>
                  <div style={sx("font-size:17.5px; font-weight:600; color:#fff;")}>{g.name}</div>
                  <KebabMenu size={18} items={[{ label: "Delete project", danger: true, onClick: () => setToDelete(g.name) }]} />
                </div>
                <div style={sx("margin-top:4px; padding:0 4px; font-size:14px; color:var(--text-2);")}>{countLabel(g)}</div>
              </div>
            );
          })}
        </div>
      ) : (
        <div data-cardstagger style={sx("display:flex; flex-direction:column; gap:8px; max-width:760px;")}>
          {groups.map((g) => (
            <div key={g.name} data-press className="hv-row" onClick={() => st.openProject(g.name)}
              style={sx("display:flex; align-items:center; gap:14px; padding:13px 14px; border:1px solid var(--border); border-radius:6px; cursor:pointer; background:var(--panel);")}>
              <I k="folder" size={19} style={{ color: "var(--text-2)" }} />
              <div style={sx("font-size:15.5px; font-weight:600; color:#fff;")}>{g.name}</div>
              <div style={{ flex: 1 }} />
              <div style={sx("font-size:13.5px; color:var(--text-2);")}>{countLabel(g)}</div>
              <KebabMenu items={[{ label: "Delete project", danger: true, onClick: () => setToDelete(g.name) }]} />
              <I k="chev-right" size={17} style={{ color: "var(--text-3)" }} />
            </div>
          ))}
        </div>
      )}

      {confirmEx.mounted && (
        <Confirm closing={confirmEx.closing}
          title="Delete project?"
          body={`"${toDelete || lastDelete.current}" and its ${modelCount(toDelete || lastDelete.current)} model(s) will be permanently deleted. This cannot be undone.`}
          confirmLabel="DELETE PROJECT"
          onCancel={() => setToDelete(null)}
          onConfirm={() => { const nm = toDelete!; setToDelete(null); st.deleteProject(nm); }} />
      )}
    </div>
  );
}
