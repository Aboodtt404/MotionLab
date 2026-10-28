/* Login / signup + reset-password modal — transcribed from the prototype's LOGIN section.
 * Wired to the real studio_api auth service: signup/login return a bearer session; errors from the
 * server render inline (wrong password, duplicate email, weak password…). */
import { useState } from "react";
import { useExit } from "../motion";
import { sx } from "../sx";
import { useStudio } from "../store";
import { LoginFx } from "./LoginFx";

const inputStyle = sx("width:100%; padding:13px 15px; border:1px solid transparent; border-radius:4px; background:rgba(255,255,255,.09); color:#f4f4f5; font-size:15px; transition:border-color .15s;");
const labelStyle = sx("display:block; font-size:13px; font-weight:600; color:var(--text); margin-bottom:8px;");

export function Login() {
  const st = useStudio();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [resetOpen, setResetOpen] = useState(false);
  const resetEx = useExit(resetOpen, 140);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const isSignup = mode === "signup";
  const busy = st.authBusy;

  const submit = async () => {
    if (busy) return;
    setError(null);
    if (!email.trim()) { setError("enter your email address"); return; }
    if (!password) { setError("enter your password"); return; }
    if (isSignup && password !== confirm) { setError("passwords don't match"); return; }
    const err = isSignup
      ? await st.signUp({ email: email.trim(), password, first: first.trim(), last: last.trim() })
      : await st.signIn(email.trim(), password);
    if (err) setError(err);
  };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") submit(); };

  return (
    <div style={sx("position:absolute; inset:0; z-index:45; background:var(--bg); display:flex; flex-direction:column; animation:mlk-fade .3s ease;")}>
      <LoginFx />
      <div style={sx("position:relative; height:78px; flex-shrink:0; display:flex; align-items:center; padding:0 34px; border-bottom:1px solid var(--border);")}>
        <div style={sx("display:flex; align-items:center; gap:10px; font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:24px; letter-spacing:.01em; color:#fff;")}>
          <svg width="24" height="24" viewBox="0 0 24 24" style={{ color: "var(--accent,#4d9eff)", flexShrink: 0 }}>
            <path d="M12 3 20 7.4v9.2L12 21l-8-4.4V7.4Z" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
          MOTIONLAB
        </div>
        <div style={{ flex: 1 }} />
        <span style={sx("font-size:15px; color:var(--text-2); margin-right:26px;")}>English</span>
        <button data-press data-primary onClick={() => setMode(isSignup ? "signin" : "signup")}
          style={sx("padding:11px 22px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:500; letter-spacing:.1em; cursor:pointer;")}>
          <span data-ulw>{isSignup ? "SIGN IN" : "GET STARTED"}</span>
        </button>
      </div>
      <div style={sx("position:relative; flex:1; display:flex; align-items:center; justify-content:center; padding:24px; overflow:auto;")}>
        <div style={sx("width:472px; max-width:100%; border:1px solid var(--border-2); border-radius:8px; background:rgba(23,23,26,.88); backdrop-filter:blur(7px); padding:40px 46px 46px; box-shadow:0 30px 80px rgba(0,0,0,.45);")}>
          <div style={{ textAlign: "center" }}>
            <div style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:44px; letter-spacing:.02em; color:#fff; line-height:1;")}>MOTIONLAB</div>
            <div style={sx("margin-top:12px; font-size:14.5px; color:var(--text-2);")}>
              {isSignup ? "Create your account to get started." : "Log in and let MotionLab verify your 3D pipeline."}
            </div>
          </div>
          <div style={{ marginTop: 30 }}>
            {isSignup && (
              <div style={sx("display:flex; gap:14px; margin-bottom:18px;")}>
                <div style={sx("flex:1; min-width:0;")}>
                  <label style={labelStyle}>First Name</label>
                  <input data-focusaccent placeholder="John" value={first} onChange={(e) => setFirst(e.target.value)} onKeyDown={onKey} style={inputStyle} />
                </div>
                <div style={sx("flex:1; min-width:0;")}>
                  <label style={labelStyle}>Last Name</label>
                  <input data-focusaccent placeholder="Doe" value={last} onChange={(e) => setLast(e.target.value)} onKeyDown={onKey} style={inputStyle} />
                </div>
              </div>
            )}
            <label style={labelStyle}>Email</label>
            <input data-focusaccent placeholder="john@example.com" type="email" autoComplete="email"
              value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={onKey} style={inputStyle} />
            <label style={{ ...labelStyle, margin: "18px 0 8px" }}>Password</label>
            <input data-focusaccent type="password" placeholder={isSignup ? "At least 6 characters" : "Enter your password"}
              autoComplete={isSignup ? "new-password" : "current-password"}
              value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={onKey} style={inputStyle} />
            {isSignup && (
              <>
                <label style={{ ...labelStyle, margin: "18px 0 8px" }}>Confirm Password</label>
                <input data-focusaccent type="password" placeholder="Confirm your password" autoComplete="new-password"
                  value={confirm} onChange={(e) => setConfirm(e.target.value)} onKeyDown={onKey} style={inputStyle} />
              </>
            )}
          </div>

          {error && (
            <div style={sx("margin-top:18px; padding:11px 14px; border:1px solid rgba(229,100,95,.5); border-radius:5px; background:rgba(229,100,95,.09); font-size:13.5px; color:var(--fail); animation:mlk-pop .2s ease;")}>
              {error}
            </div>
          )}

          <button data-press data-primary onClick={submit}
            style={sx("width:100%; margin-top:26px; padding:15px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:13px; font-weight:600; letter-spacing:.12em; cursor:pointer;" + (busy ? "opacity:.6;" : ""))}>
            <span data-ulw>{busy ? "PLEASE WAIT…" : isSignup ? "CREATE ACCOUNT" : "SIGN IN"}</span>
          </button>
          {!isSignup ? (
            <>
              <div style={sx("margin-top:22px; text-align:center; font-size:14px; color:var(--text-2);")}>
                Don't have an account?{" "}
                <span onClick={() => { setMode("signup"); setError(null); }} style={sx("color:var(--accent,#4d9eff); cursor:pointer; text-decoration:underline;")}>Sign up</span>
              </div>
              <div style={sx("margin-top:9px; text-align:center; font-size:14px; color:var(--text-2);")}>
                Forgot password?{" "}
                <span onClick={() => setResetOpen(true)} style={sx("color:var(--accent,#4d9eff); cursor:pointer; text-decoration:underline;")}>Reset here</span>
              </div>
            </>
          ) : (
            <div style={sx("margin-top:22px; text-align:center; font-size:14px; color:var(--text-2);")}>
              Already have an account?{" "}
              <span onClick={() => { setMode("signin"); setError(null); }} style={sx("color:var(--accent,#4d9eff); cursor:pointer; text-decoration:underline;")}>Sign in</span>
            </div>
          )}
        </div>
      </div>

      {resetEx.mounted && (
        <div onClick={() => setResetOpen(false)}
          {...(resetEx.closing ? { "data-closing": "", "data-exit": "fade" } : {})}
          style={sx("position:absolute; inset:0; z-index:60; background:rgba(6,6,7,.7); display:flex; align-items:center; justify-content:center; padding:24px; animation:mlk-backdrop .2s ease;")}>
          <div onClick={(e) => e.stopPropagation()}
            style={sx("position:relative; width:440px; max-width:100%; background:var(--panel); border:1px solid var(--border-2); clip-path:polygon(0 0,100% 0,100% calc(100% - 16px),calc(100% - 16px) 100%,0 100%); padding:26px 26px 24px; animation:mlk-cutin .34s cubic-bezier(.25,.7,.25,1) both, mlk-rise .28s var(--ease-out) both;")}>
            <button data-press data-iconbtn onClick={() => setResetOpen(false)}
              style={sx("position:absolute; right:14px; top:14px; width:30px; height:30px; border:none; border-radius:6px; background:transparent; color:var(--text-2); display:flex; align-items:center; justify-content:center; cursor:pointer;")}>
              <svg width="18" height="18" viewBox="0 0 24 24"><use href="#i-close" /></svg>
            </button>
            <div style={sx("font-family:'Ufficio','IBM Plex Sans',sans-serif; font-weight:700; font-size:23px; color:#fff;")}>Reset Password</div>
            <div style={sx("margin-top:8px; font-size:14px; line-height:1.5; color:var(--text-2);")}>
              Password resets are handled by the team admin — ping the workspace channel and we'll reset your account.
            </div>
            <div style={sx("display:flex; justify-content:flex-end; align-items:center; gap:12px; margin-top:22px;")}>
              <button data-press data-primary onClick={() => setResetOpen(false)}
                style={sx("padding:12px 20px; border:none; clip-path:var(--notch); font-family:'Spline Sans Mono',monospace; font-size:12.5px; font-weight:600; letter-spacing:.08em; cursor:pointer;")}>
                <span data-ulw>GOT IT</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
