/* Shell — sidebar + header (breadcrumb, engine status pills, primary action), hosting the
 * dashboard / projects / project-detail / settings bodies. Transcribed from the prototype's
 * SHELL section. Engine pills are the written brief's §6 requirement, driven by real /health
 * polling (the pill styles come from the prototype's computed enginePills). */
import { useState } from "react";
import { useExit } from "../motion";
import { sx } from "../sx";
import { useStudio } from "../store";
import { I } from "../icons";
import { Dashboard } from "./Dashboard";
import { Projects } from "./Projects";
import { ProjectDetail } from "./ProjectDetail";
import { Settings } from "./Settings";

const navBase = "display:flex;align-items:center;gap:12px;width:100%;padding:11px 14px;border:none;color:var(--text-2);font-family:'Ufficio','IBM Plex Sans',sans-serif;font-size:15px;font-weight:500;text-align:left;cursor:pointer;border-radius:3px;clip-path:var(--notch);";
// background:transparent is load-bearing — without it the button falls back to the UA default
// (white-ish) face; the highlight itself is the [data-navactive] pill in theme.css
const navActive = "background:transparent;font-weight:600;";

export function Shell() {
  const st = useStudio();
  const [profileOpen, setProfileOpen] = useState(false);
  const profileEx = useExit(profileOpen);
  const screen = st.screen;
  const isDashboard = screen === "dashboard";
  const isProjects = screen === "projects";
  const isProjectDetail = screen === "project";
  const isSettings = screen === "settings";
  const navKey = st.nav;
  const user = st.user;
  const initials = (((user?.first?.[0] || "") + (user?.last?.[0] || "")).toUpperCase() || "U");
  const userName = ((user?.first || "") + " " + (user?.last || "")).trim() || "User";

  const navItems = [
    { key: "dashboard", label: "Dashboard", icon: "home", onClick: () => st.go("dashboard", "dashboard") },
    { key: "projects", label: "Projects", icon: "folder", onClick: () => st.go("projects", "projects") },
  ];

  return (
    <div style={sx("position:absolute; inset:0; z-index:2; display:flex; background:var(--bg);")}>
      {/* SIDEBAR */}
      <aside style={sx("width:262px; flex-shrink:0; background:var(--sidebar); border-right:1px solid var(--border); display:flex; flex-direction:column; padding:20px 14px 12px; overflow-y:auto;")}>
        <button data-press data-accentfill onClick={() => st.go("dashboard", "dashboard")} title="Go to Dashboard"
          style={sx("align-self:flex-start; display:inline-flex; align-items:center; gap:9px; margin:2px 0 20px; padding:2px 6px; border:none; border-radius:5px; background:transparent; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:22px; letter-spacing:.01em; color:#fff; cursor:pointer; transition:background-color .16s,color .16s;")}>
          <svg width="22" height="22" viewBox="0 0 24 24" style={{ color: "var(--accent,#4d9eff)", flexShrink: 0 }}>
            <path d="M12 3 20 7.4v9.2L12 21l-8-4.4V7.4Z" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
          MOTIONLAB
        </button>

        <nav style={sx("display:flex; flex-direction:column; gap:4px;")}>
          {navItems.map((n) => (
            <button key={n.key} data-press data-accentfill {...(navKey === n.key ? { "data-navactive": "" } : {})}
              onClick={n.onClick}
              style={sx(navBase + (navKey === n.key ? navActive : "background:transparent;"))}>
              <I k={n.icon} size={21} />
              <span>{n.label}</span>
            </button>
          ))}
        </nav>

        <div style={sx("padding:26px 10px 9px; font-family:'Spline Sans Mono',monospace; font-size:11px; letter-spacing:.13em; text-transform:uppercase; color:var(--text-3);")}>Latest Projects</div>
        {st.projects.map((p) => (
          <button key={p} data-press data-accentfill onClick={() => st.openProject(p)}
            style={sx("display:flex; align-items:center; gap:11px; width:100%; padding:9px 12px; border:none; background:transparent; color:var(--text-2); font-family:'Ufficio','IBM Plex Sans',sans-serif; font-size:14px; text-align:left; cursor:pointer; border-radius:3px; transition:background-color .15s,color .15s;")}>
            <I k="folder" size={17} /><span>{p}</span>
          </button>
        ))}

        <div style={sx("flex:1; min-height:22px;")} />

        <button data-press data-whitehover onClick={() => st.go("settings", "settings")}
          style={sx("display:flex; align-items:center; gap:12px; padding:10px; border:none; background:transparent; color:var(--text-2); font-family:'Ufficio','IBM Plex Sans',sans-serif; font-size:14px; cursor:pointer; border-radius:5px;")}>
          <I k="gear" size={18} /><span>Settings</span>
        </button>
        <button data-press data-whitehover onClick={() => st.showToast("Need a hand? Ping me \u2014 Tete")}
          style={sx("display:flex; align-items:center; gap:12px; padding:10px; border:none; background:transparent; color:var(--text-2); font-family:'Ufficio','IBM Plex Sans',sans-serif; font-size:14px; cursor:pointer; border-radius:5px;")}>
          <I k="help" size={18} /><span>Get Help</span>
        </button>

        <div data-press data-whitehover onClick={() => setProfileOpen((o) => !o)}
          style={sx("display:flex; align-items:center; gap:11px; margin-top:12px; padding:10px 8px; border-top:1px solid var(--border); cursor:pointer; border-radius:6px;")}>
          <div style={sx("width:38px; height:38px; flex-shrink:0; border-radius:7px; background:linear-gradient(140deg,#3a3a40,#1c1c20); border:1px solid var(--border-2); display:flex; align-items:center; justify-content:center; font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; color:#fff;")}>{initials}</div>
          <div style={sx("min-width:0; flex:1;")}>
            <div style={sx("font-size:14px; font-weight:600; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{userName}</div>
            <div style={sx("font-size:12px; color:var(--text-3); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;")}>{user?.email || ""}</div>
          </div>
          <I k="kebab" size={17} style={{ color: "var(--text-3)" }} />
        </div>
      </aside>

      {profileEx.mounted && (
        <>
          <div onClick={() => setProfileOpen(false)} style={sx("position:fixed; inset:0; z-index:55;")} />
          <div {...(profileEx.closing ? { "data-closing": "" } : {})}
            style={sx("position:fixed; left:270px; bottom:16px; z-index:56; background:var(--panel); border:1px solid var(--border-2); border-radius:8px; padding:6px; box-shadow:0 16px 40px rgba(0,0,0,.5); animation:mlk-pop .16s var(--ease-out);")}>
            <button data-press data-whitehover onClick={() => { setProfileOpen(false); st.signOut(); }}
              style={sx("display:flex; align-items:center; gap:10px; padding:10px 18px 10px 12px; border:none; background:transparent; color:var(--text); font-family:'Ufficio','IBM Plex Sans',sans-serif; font-size:14px; cursor:pointer; border-radius:6px; white-space:nowrap;")}>
              <I k="logout" size={18} /><span>Log out</span>
            </button>
          </div>
        </>
      )}

      {/* MAIN */}
      <div style={sx("flex:1; min-width:0; display:flex; flex-direction:column;")}>
        <div style={sx("height:62px; flex-shrink:0; display:flex; align-items:center; gap:14px; padding:0 22px; border-bottom:1px solid var(--border);")}>
          <I k="panel" size={22} style={{ color: "var(--text-2)" }} />
          {isDashboard && <span style={sx("font-size:16px; color:var(--text);")}>Dashboard</span>}
          {isProjects && (
            <>
              <span style={sx("font-size:16px; color:var(--text-2);")}>Dashboard</span>
              <span style={{ color: "var(--text-3)" }}>|</span>
              <span style={sx("font-size:16px; color:var(--text);")}>Projects</span>
            </>
          )}
          {isProjectDetail && (
            <>
              <span onClick={() => st.go("projects", "projects")} style={sx("font-size:16px; color:var(--text-2); cursor:pointer;")}>Projects</span>
              <span style={{ color: "var(--text-3)" }}>|</span>
              <span style={sx("font-size:16px; color:var(--text);")}>{st.activeProject}</span>
            </>
          )}
          {isSettings && (
            <>
              <span onClick={() => st.go("dashboard", "dashboard")} style={sx("font-size:16px; color:var(--text-2); cursor:pointer;")}>Dashboard</span>
              <span style={{ color: "var(--text-3)" }}>|</span>
              <span style={sx("font-size:16px; color:var(--text);")}>Settings</span>
            </>
          )}
          <div style={{ flex: 1 }} />

          {isProjects ? (
            <button data-press data-primary onClick={() => st.newProject()}
              style={sx("display:flex; align-items:center; gap:8px; padding:11px 20px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
              <I k="plus" size={16} /><span data-ulw>NEW PROJECT</span>
            </button>
          ) : isProjectDetail ? (
            <button data-press data-primary onClick={() => st.startGenerate()}
              style={sx("display:flex; align-items:center; gap:8px; padding:11px 20px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
              <I k="plus" size={16} /><span data-ulw>GENERATE</span>
            </button>
          ) : (
            <button data-press data-primary onClick={() => st.startGenerate()}
              style={sx("padding:11px 22px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
              <span data-ulw>GENERATE</span>
            </button>
          )}
        </div>

        <div style={sx("flex:1; overflow-y:auto; padding:18px;")}>
          {isDashboard && <Dashboard />}
          {isProjects && <Projects />}
          {isProjectDetail && <ProjectDetail />}
          {isSettings && <Settings />}
        </div>
      </div>
    </div>
  );
}
