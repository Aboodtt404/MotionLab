/* Kebab (⋮) menu + confirm dialog — the shared card-action idiom. KebabMenu renders the
 * three-dot button and its popup (outside-click close, exit animation, stopPropagation so the
 * host card's own onClick doesn't fire). The popup PORTALS to #mlk with fixed positioning so no
 * ancestor can clip it (overflow:hidden panels) or paint over it (sibling stacking contexts).
 * Confirm is the destructive-action gate. */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useExit } from "../motion";
import { sx } from "../sx";
import { I } from "../icons";

export function KebabMenu({ items, size = 16 }: {
  items: { label: string; danger?: boolean; onClick: () => void }[];
  size?: number;
}) {
  const [open, setOpen] = useState(false);
  const menu = useExit(open);
  const [pos, setPos] = useState<{ right: number; top?: number; bottom?: number }>({ right: 0, top: 0 });
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const toggle = () => {
    if (!open && rootRef.current) {
      const r = rootRef.current.getBoundingClientRect();
      const right = Math.max(8, window.innerWidth - r.right);
      const needed = items.length * 38 + 20;
      setPos(r.bottom + needed + 10 > window.innerHeight
        ? { right, bottom: window.innerHeight - r.top + 4 }
        : { right, top: r.bottom + 4 });
    }
    setOpen((o) => !o);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!rootRef.current?.contains(t) && !menuRef.current?.contains(t)) setOpen(false);
    };
    const onScroll = (e: Event) => {
      if (menuRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    return () => { window.removeEventListener("mousedown", onDown); window.removeEventListener("scroll", onScroll, true); };
  }, [open]);

  const host = typeof document !== "undefined" ? document.getElementById("mlk") : null;

  return (
    <div ref={rootRef} onClick={(e) => e.stopPropagation()} style={{ position: "relative", display: "inline-flex", flexShrink: 0 }}>
      <button data-press data-iconbtn title="Actions" onClick={toggle}
        style={sx("width:26px; height:26px; border:none; border-radius:5px; background:transparent; color:var(--text-3); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
        <I k="kebab" size={size} />
      </button>
      {menu.mounted && host && createPortal(
        <div ref={menuRef} onClick={(e) => e.stopPropagation()}
          {...(menu.closing ? { "data-closing": "" } : {})}
          style={{ ...sx("position:fixed; min-width:150px; z-index:48; background:var(--panel-2); border:1px solid var(--border-2); border-radius:7px; overflow:hidden; padding:5px; box-shadow:0 14px 34px rgba(0,0,0,.5); animation:mlk-pop .16s var(--ease-out);"), ...pos }}>
          {items.map((it) => (
            <button key={it.label} data-press data-seg
              onClick={() => { setOpen(false); it.onClick(); }}
              style={sx("display:flex; align-items:center; gap:9px; width:100%; padding:8px 10px; border:none; border-radius:5px; background:transparent; font-size:13px; text-align:left; cursor:pointer; white-space:nowrap; color:" +
                (it.danger ? "var(--fail)" : "var(--text)") + ";")}>
              {it.danger && <I k="trash" size={13} />}
              {it.label}
            </button>
          ))}
        </div>, host)}
    </div>
  );
}

export function Confirm({ title, body, confirmLabel = "DELETE", closing, onCancel, onConfirm }: {
  title: string; body: string; confirmLabel?: string; closing?: boolean;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div onClick={onCancel}
      {...(closing ? { "data-closing": "", "data-exit": "fade" } : {})}
      style={sx("position:fixed; inset:0; z-index:55; background:rgba(6,6,7,.7); backdrop-filter:blur(4px); display:flex; align-items:center; justify-content:center; padding:24px; animation:mlk-backdrop .18s ease;")}>
      <div onClick={(e) => e.stopPropagation()}
        {...(closing ? { "data-closing": "" } : {})}
        style={sx("position:relative; width:420px; max-width:100%; background:var(--panel); border:1px solid var(--border-2); clip-path:polygon(0 0,100% 0,100% calc(100% - 16px),calc(100% - 16px) 100%,0 100%); padding:24px 26px 22px; box-shadow:0 30px 80px rgba(0,0,0,.5); animation:mlk-cutin .28s var(--ease-out) both, mlk-rise .22s var(--ease-out) both;")}>
        <div style={sx("display:flex; align-items:center; gap:10px;")}>
          <span style={sx("width:32px; height:32px; flex-shrink:0; border-radius:50%; background:rgba(var(--fail-rgb),.13); border:1.5px solid var(--fail); display:flex; align-items:center; justify-content:center; color:var(--fail);")}>
            <I k="trash" size={15} />
          </span>
          <span style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:19px; color:#fff;")}>{title}</span>
        </div>
        <div style={sx("margin-top:12px; font-size:14px; line-height:1.55; color:var(--text-2);")}>{body}</div>
        <div style={sx("display:flex; justify-content:flex-end; align-items:center; gap:11px; margin-top:20px;")}>
          <button data-press className="hv-white-b2" onClick={onCancel}
            style={sx("padding:11px 18px; border:1px solid var(--border-2); border-radius:5px; background:transparent; color:var(--text-2); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:500; letter-spacing:.08em; cursor:pointer;")}>
            CANCEL
          </button>
          <button data-press onClick={onConfirm}
            style={sx("padding:11px 20px; border:none; clip-path:var(--notch); background:var(--fail); color:#fff; font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:600; letter-spacing:.08em; cursor:pointer;")}>
            <span data-ulw>{confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
