/* Settings — account (wired to the local profile), language, theme cards. Dark is the product
 * theme; the light card exists per the design but stays a preview (dark-first instrument panel). */
import { useState } from "react";
import { sx } from "../sx";
import { useStudio } from "../store";

const inputStyle = sx("width:100%; padding:13px 15px; border:1px solid transparent; border-radius:4px; background:rgba(255,255,255,.09); color:#f4f4f5; font-size:15px; transition:border-color .15s;");

export function Settings() {
  const st = useStudio();
  const [first, setFirst] = useState(st.user?.first || "");
  const [last, setLast] = useState(st.user?.last || "");
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  const cardStyle = (sel: boolean, bg: string) =>
    sx(`width:190px; border-radius:8px; overflow:hidden; cursor:pointer; background:${bg}; transition:border-color .15s; ` +
      (sel ? "border:2px solid var(--accent,#4d9eff);" : "border:2px solid var(--border-2);"));
  const footerStyle = (sel: boolean) =>
    sx("display:flex; align-items:center; gap:9px; padding:9px 12px; font-size:13.5px; font-weight:600; " +
      (sel ? "background:var(--accent,#4d9eff); color:var(--on-accent,#06111c);" : "background:#1a1a1d; color:var(--text-2);"));

  return (
    <div style={sx("animation:mlk-fade .3s ease; max-width:900px; margin:0 auto; padding:10px 6px 60px;")}>
      <h1 style={sx("margin:0 0 32px; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:34px; color:#fff;")}>General Settings</h1>

      <h2 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:22px; color:#fff;")}>Accounts</h2>
      <p style={sx("margin:6px 0 0; font-size:14px; color:var(--text-2);")}>Manage your account information and settings.</p>
      <div style={sx("margin-top:22px; display:flex; flex-direction:column;")}>
        <label style={sx("font-size:13px; font-weight:600; color:var(--text); margin-bottom:8px;")}>First Name</label>
        <input data-focusaccent value={first} onChange={(e) => setFirst(e.target.value)} style={inputStyle} />
        <label style={sx("font-size:13px; font-weight:600; color:var(--text); margin:18px 0 8px;")}>Last Name</label>
        <input data-focusaccent value={last} onChange={(e) => setLast(e.target.value)} style={inputStyle} />
        <button data-press data-accentfill
          onClick={() => st.updateUser({ first, last }).then(() => st.showToast("Profile updated")).catch((e) => st.showToast("Update failed: " + (e?.message || e)))}
          style={sx("margin-top:20px; width:100%; padding:14px; border:1px solid var(--border-2); clip-path:var(--notch); background:#17171a; color:var(--text); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.12em; cursor:pointer;")}>
          UPDATE PROFILE
        </button>
      </div>

      <div style={sx("height:1px; background:var(--border); margin:34px 0;")} />

      <div style={sx("display:flex; align-items:center; gap:28px;")}>
        <h2 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:22px; color:#fff;")}>Languages</h2>
        <button data-press data-focusaccent onClick={() => st.showToast("English only for now")}
          style={sx("display:inline-flex; align-items:center; justify-content:space-between; gap:30px; min-width:180px; padding:10px 14px; border:1px solid var(--border-2); border-radius:4px; background:var(--panel); color:var(--text); font-size:14px; cursor:pointer; transition:border-color .15s;")}>
          English<svg width="16" height="16" viewBox="0 0 24 24" style={{ color: "var(--text-2)" }}><use href="#i-chev-down" /></svg>
        </button>
      </div>

      <div style={sx("height:1px; background:var(--border); margin:34px 0;")} />

      <h2 style={sx("margin:0; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:22px; color:#fff;")}>Themes</h2>
      <p style={sx("margin:6px 0 0; font-size:14px; color:var(--text-2);")}>Change the appearance of the application by selecting between light or dark.</p>
      <div style={sx("display:flex; gap:16px; margin-top:20px;")}>
        <div data-press onClick={() => setTheme("dark")} style={cardStyle(theme === "dark", "#0d0d0d")}>
          <div style={sx("position:relative; height:112px; background:#0d0d0d; padding:12px;")}>
            <div style={sx("position:absolute; right:10px; top:10px; width:16px; height:10px; border-radius:2px; background:var(--accent,#4d9eff);")} />
            <div style={sx("height:14px; width:70%; background:#26262b; border-radius:2px;")} />
            <div style={sx("display:flex; gap:6px; margin-top:8px;")}>
              <div style={sx("width:34px; height:60px; background:#17171a; border-radius:2px;")} />
              <div style={sx("flex:1; height:60px; background:#141416; border-radius:2px;")} />
            </div>
          </div>
          <div style={footerStyle(theme === "dark")}>
            {theme === "dark"
              ? <svg width="16" height="16" viewBox="0 0 24 24" style={{ color: "var(--on-accent,#06111c)", flexShrink: 0 }}><path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
              : <span style={sx("width:15px; height:15px; border:1.5px solid var(--text-3); border-radius:50%; flex-shrink:0;")} />}
            <span>Dark mode</span>
          </div>
        </div>
        <div data-press onClick={() => { setTheme("dark"); st.showToast("Light theme — coming later; the studio is dark-first"); }} style={cardStyle(false, "#e8e8e8")}>
          <div style={sx("position:relative; height:112px; background:#e8e8e8; padding:12px;")}>
            <div style={sx("position:absolute; right:10px; top:10px; width:16px; height:10px; border-radius:2px; background:var(--accent,#4d9eff);")} />
            <div style={sx("height:14px; width:70%; background:#ffffff; border-radius:2px;")} />
            <div style={sx("display:flex; gap:6px; margin-top:8px;")}>
              <div style={sx("width:34px; height:60px; background:#f2f2f2; border-radius:2px;")} />
              <div style={sx("flex:1; height:60px; background:#fafafa; border-radius:2px;")} />
            </div>
          </div>
          <div style={footerStyle(false)}>
            <span style={sx("width:15px; height:15px; border:1.5px solid var(--text-3); border-radius:50%; flex-shrink:0;")} />
            <span>Light mode</span>
          </div>
        </div>
      </div>
    </div>
  );
}
