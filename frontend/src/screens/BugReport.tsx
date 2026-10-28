/* Bug report modal — opened by the corner critter's button. A description box plus an optional
 * screenshot (click to upload, drag-drop, or just Ctrl/⌘-V paste one anywhere in the modal).
 * Submits to the studio API, which files the report (JSON + image) into the repo's bug_reports/
 * directory for the team to triage. */
import { useRef, useState } from "react";
import * as api from "../api";
import { sx } from "../sx";
import { I } from "../icons";
import { fileToB64 } from "../gltf";

export function BugReport({ closing, context, onClose, onDone }: {
  closing?: boolean;
  context: Record<string, any>;
  onClose: () => void;
  onDone: () => void;
}) {
  const [desc, setDesc] = useState("");
  const [img, setImg] = useState<{ b64: string; mime: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const takeFile = async (f: File | null | undefined) => {
    if (!f || !f.type.startsWith("image/")) return;
    setImg({ b64: await fileToB64(f), mime: f.type, name: f.name || "pasted image" });
  };

  const submit = async () => {
    if (busy) return;
    if (!desc.trim()) { setError("Describe what went wrong first"); return; }
    setBusy(true);
    setError(null);
    try {
      await api.studio.reportBug({
        description: desc.trim(), image_b64: img?.b64, mime: img?.mime,
        context: { ...context, ua: navigator.userAgent, viewport: `${innerWidth}x${innerHeight}` },
      });
      onDone();
    } catch (e: any) {
      setError(e?.message || "Could not save the report — is the studio service up?");
      setBusy(false);
    }
  };

  return (
    <div onClick={onClose}
      {...(closing ? { "data-closing": "", "data-exit": "fade" } : {})}
      onPaste={(e) => takeFile(e.clipboardData?.files?.[0])}
      style={sx("position:absolute; inset:0; z-index:50; background:rgba(6,6,7,.7); backdrop-filter:blur(5px); display:flex; align-items:center; justify-content:center; padding:24px; animation:mlk-backdrop .2s ease;")}>
      <div onClick={(e) => e.stopPropagation()}
        {...(closing ? { "data-closing": "" } : {})}
        style={sx("position:relative; width:480px; max-width:100%; background:var(--panel); border:1px solid var(--border-2); clip-path:polygon(0 0,100% 0,100% calc(100% - 16px),calc(100% - 16px) 100%,0 100%); padding:24px 26px 24px; box-shadow:0 30px 80px rgba(0,0,0,.5); animation:mlk-cutin .3s var(--ease-out) both, mlk-rise .25s var(--ease-out) both;")}>

        <button data-press data-iconbtn onClick={onClose} title="Close"
          style={sx("position:absolute; right:14px; top:14px; width:30px; height:30px; border:none; border-radius:6px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
          <I k="close" size={18} />
        </button>

        <div style={sx("display:flex; align-items:center; gap:10px;")}>
          <svg width="20" height="20" viewBox="0 0 24 24" style={{ color: "var(--accent,#4d9eff)" }}><use href="#i-bug" /></svg>
          <span style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:21px; color:#fff;")}>Report a Bug</span>
        </div>
        <div style={sx("margin-top:6px; font-size:13.5px; line-height:1.5; color:var(--text-2);")}>
          Tell me what broke — your report comes straight to me and I'll review it personally. — Tete
        </div>

        <textarea autoFocus value={desc} onChange={(e) => setDesc(e.target.value)}
          placeholder="What happened? What did you expect instead?"
          style={sx("margin-top:16px; width:100%; min-height:110px; padding:13px 14px; border:1px solid var(--border); background:var(--inset); color:var(--text); border-radius:4px; font-size:14.5px; line-height:1.5;")} />

        <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
          onChange={(e) => { takeFile(e.target.files?.[0]); e.currentTarget.value = ""; }} />
        {img ? (
          <div style={sx("margin-top:12px; position:relative; border:1px solid var(--border-2); border-radius:6px; overflow:hidden; background:var(--inset);")}>
            <img src={`data:${img.mime};base64,${img.b64}`} alt=""
              style={{ width: "100%", maxHeight: 180, objectFit: "contain", display: "block" }} />
            <span style={sx("position:absolute; left:10px; bottom:8px; padding:2px 8px; border-radius:4px; background:rgba(0,0,0,.55); font-family:'Spline Sans Mono',monospace; font-size:10px; letter-spacing:.05em; color:var(--text-2); max-width:70%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;")}>{img.name}</span>
            <button data-press data-iconbtn onClick={() => setImg(null)} title="Remove image"
              style={sx("position:absolute; right:8px; top:8px; width:26px; height:26px; border:none; border-radius:5px; background:rgba(0,0,0,.55); color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <I k="close" size={15} />
            </button>
          </div>
        ) : (
          <div data-press data-accenthover onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); takeFile(e.dataTransfer.files?.[0]); }}
            style={sx("margin-top:12px; border:1px dashed var(--border-2); border-radius:6px; padding:16px 14px; display:flex; align-items:center; justify-content:center; gap:10px; color:var(--text-2); font-size:13px; cursor:pointer;")}>
            <I k="image" size={18} />
            Attach a screenshot — click, drop, or paste (Ctrl+V)
          </div>
        )}

        {error && (
          <div style={sx("margin-top:12px; padding:10px 13px; border:1px solid rgba(229,100,95,.5); border-radius:5px; background:rgba(229,100,95,.09); font-size:13px; color:var(--fail); animation:mlk-pop .2s var(--ease-out);")}>
            {error}
          </div>
        )}

        <div style={sx("display:flex; justify-content:flex-end; align-items:center; gap:11px; margin-top:18px;")}>
          <button data-press className="hv-white-b2" onClick={onClose}
            style={sx("padding:11px 18px; border:1px solid var(--border-2); border-radius:5px; background:transparent; color:var(--text-2); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:500; letter-spacing:.08em; cursor:pointer;")}>
            CANCEL
          </button>
          <button data-press data-primary onClick={submit}
            style={sx("padding:11px 22px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12px; font-weight:600; letter-spacing:.08em; cursor:pointer;" + (busy ? "opacity:.6;" : ""))}>
            <span data-ulw>{busy ? "SENDING…" : "SUBMIT REPORT"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
