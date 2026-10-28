/* Project picker — a compact folder chip that pops a menu of the user's projects plus an inline
 * "new project" row. Used in the dashboard generation panel (destination for the NEXT generation)
 * and on the result cards (move THIS model). The menu PORTALS to #mlk with fixed positioning so
 * no ancestor can clip it (overflow:hidden panels) or paint over it (sibling stacking contexts). */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useExit } from "../motion";
import { sx } from "../sx";
import { I } from "../icons";
import { useStudio } from "../store";

export function ProjectPicker({ value, onPick, compact }: {
  value: string;
  onPick: (project: string) => void;
  compact?: boolean;
}) {
  const st = useStudio();
  const [open, setOpen] = useState(false);
  const menu = useExit(open);
  const [draft, setDraft] = useState("");
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number }>({ left: 0, top: 0 });
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const toggle = () => {
    if (!open && rootRef.current) {
      const r = rootRef.current.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.left, window.innerWidth - 226));
      // flip upward when there's no room below (result cards sit near the bottom edge)
      setPos(r.bottom + 300 > window.innerHeight
        ? { left, bottom: window.innerHeight - r.top + 5 }
        : { left, top: r.bottom + 5 });
    }
    setOpen((o) => !o);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!rootRef.current?.contains(t) && !menuRef.current?.contains(t)) setOpen(false);
    };
    const onScroll = (e: Event) => {   // fixed menu would detach from its anchor — close instead
      if (menuRef.current?.contains(e.target as Node)) return;   // the list inside may scroll
      setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    return () => { window.removeEventListener("mousedown", onDown); window.removeEventListener("scroll", onScroll, true); };
  }, [open]);

  const create = () => {
    const nm = draft.trim();
    if (!nm) return;
    st.newProject(nm);
    onPick(nm);
    setDraft("");
    setOpen(false);
  };

  const host = typeof document !== "undefined" ? document.getElementById("mlk") : null;

  return (
    <div ref={rootRef} style={{ position: "relative", display: "inline-flex" }}>
      <button data-press data-focusaccent onClick={toggle} title="Project"
        style={sx(`display:inline-flex; align-items:center; gap:8px; padding:${compact ? "6px 10px" : "8px 12px"}; border:1px solid var(--border); border-radius:5px; background:var(--panel-2); color:var(--text); font-size:${compact ? "12.5px" : "13.5px"}; cursor:pointer; max-width:200px; transition:border-color .15s;`)}>
        <I k="folder" size={compact ? 14 : 15} style={{ color: "var(--text-2)" }} />
        <span style={sx("white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{value}</span>
        <I k="chev-down" size={13} style={{ color: "var(--text-3)" }} />
      </button>
      {menu.mounted && host && createPortal(
        <div ref={menuRef} {...(menu.closing ? { "data-closing": "" } : {})}
          style={{ ...sx("position:fixed; min-width:218px; z-index:48; background:var(--panel-2); border:1px solid var(--border-2); border-radius:7px; overflow:hidden; box-shadow:0 14px 34px rgba(0,0,0,.5); animation:mlk-pop .16s var(--ease-out);"), ...pos }}>
          <div style={sx("max-height:220px; overflow-y:auto; padding:5px;")}>
            {st.projects.map((p) => (
              <button key={p} data-press data-seg {...(p === value ? { "data-on": "" } : {})}
                onClick={() => { onPick(p); setOpen(false); }}
                style={sx("display:flex; align-items:center; gap:9px; width:100%; padding:8px 10px; border:none; border-radius:5px; background:" +
                  (p === value ? "rgba(var(--accent-rgb),.14)" : "transparent") +
                  "; color:" + (p === value ? "var(--accent,#4d9eff)" : "var(--text)") +
                  "; font-size:13.5px; text-align:left; cursor:pointer; transition:background .12s;")}>
                <I k="folder" size={14} style={{ color: p === value ? "var(--accent,#4d9eff)" : "var(--text-2)" }} />
                <span style={sx("flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{p}</span>
                {p === value && (
                  <svg width="13" height="13" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
                )}
              </button>
            ))}
          </div>
          <div style={sx("display:flex; gap:6px; padding:7px; border-top:1px solid var(--border);")}>
            <input data-focusaccent placeholder="New project…" value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") create(); }}
              style={sx("flex:1; min-width:0; padding:7px 9px; border:1px solid var(--border); border-radius:5px; background:var(--inset); color:var(--text); font-size:13px; transition:border-color .15s;")} />
            <button data-press data-primary onClick={create}
              style={sx("padding:0 11px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:11px; font-weight:600; letter-spacing:.05em; cursor:pointer;")}>
              ADD
            </button>
          </div>
        </div>, host)}
    </div>
  );
}
