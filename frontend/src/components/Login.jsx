import React, { useEffect, useRef, useState } from "react";
import { login } from "../api/client.js";
import BrandMark from "./BrandMark.jsx";
import "./Login.css";

function LoginIcon({ name, size = 20 }) {
  const paths = {
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /><path d="M12 14v3" /></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>,
    eyeOff: <><path d="m3 3 18 18M10.6 5.1A12 12 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.9M6.3 6.3A21 21 0 0 0 2 12s3.5 7 10 7a13 13 0 0 0 5.7-1.3" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></>,
    chart: <><path d="M4 4v16h16" /><path d="m7 14 4-4 4 2 5-6" /></>,
    layers: <><path d="m12 3 10 5-10 5L2 8l10-5Z" /><path d="m2 12 10 5 10-5M2 16l10 5 10-5" /></>,
    sliders: <><path d="M4 6h4m4 0h8M4 12h10m4 0h2M4 18h2m4 0h10" /><circle cx="10" cy="6" r="2" /><circle cx="16" cy="12" r="2" /><circle cx="8" cy="18" r="2" /></>,
    alert: <><circle cx="12" cy="12" r="9" /><path d="M12 7v6m0 3h.01" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export default function Login({ onSuccess }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const errorRef = useRef(null);

  useEffect(() => {
    if (err) errorRef.current?.focus();
  }, [err]);

  async function submit(e) {
    e.preventDefault();
    if (loading) return;
    setErr("");
    setLoading(true);
    try {
      await login(u.trim(), p);
      onSuccess();
    } catch (e) {
      setErr(e.message || "We couldn’t sign you in. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="gk-login">
      <div className="gk-login-layout">
        <section className="gk-login-story" aria-labelledby="login-story-title">
          <div className="gk-login-brand">
            <span className="gk-login-brand-mark"><BrandMark size={39} /></span>
            <div>Gurukrupa <span>Bullion</span><small>YOUR TRADING WORKSPACE</small></div>
          </div>
          <div className="gk-login-intro">
            <span className="gk-login-eyebrow">Clarity for every trading day</span>
            <h1 id="login-story-title">Your bullion desk.<br /><span>One clear view.</span></h1>
            <p>Stay close to the market and in control of your day, with your spreads, positions, and tools in one place.</p>
          </div>
          <ul className="gk-login-features">
            <li><span><LoginIcon name="chart" /></span><div><strong>Follow the spreads</strong><p>Keep the market in view.</p></div></li>
            <li><span><LoginIcon name="layers" /></span><div><strong>Stay on top of positions</strong><p>Review your trading activity.</p></div></li>
            <li><span><LoginIcon name="sliders" /></span><div><strong>Make the workspace yours</strong><p>Manage your tools in one place.</p></div></li>
          </ul>
          <div className="gk-login-story-footer">A focused workspace. A clearer trading day.</div>
        </section>

        <div className="gk-login-form-area">
          <form className="gk-login-form" onSubmit={submit} aria-labelledby="login-title" aria-busy={loading}>
            <span className="gk-login-welcome-mark"><LoginIcon name="lock" size={23} /></span>
            <h2 id="login-title">Welcome back</h2>
            <p className="gk-login-description">Sign in to your trading workspace.</p>

            {err && <div className="gk-login-error" id="login-error" role="alert" tabIndex={-1} ref={errorRef}><LoginIcon name="alert" /><span>{err}</span></div>}

            <div className="gk-login-field">
              <label htmlFor="login-username">Username</label>
              <div className="gk-login-input-wrap">
                <LoginIcon name="user" size={18} />
                <input id="login-username" name="username" value={u} onChange={(e) => setU(e.target.value)} placeholder="Enter your username" autoComplete="username" autoCapitalize="none" spellCheck={false} required disabled={loading} aria-describedby={err ? "login-error" : undefined} />
              </div>
            </div>
            <div className="gk-login-field">
              <label htmlFor="login-password">Password</label>
              <div className="gk-login-input-wrap">
                <LoginIcon name="lock" size={18} />
                <input id="login-password" name="password" type={showPassword ? "text" : "password"} value={p} onChange={(e) => setP(e.target.value)} onKeyDown={(e) => setCapsLock(e.getModifierState("CapsLock"))} onKeyUp={(e) => setCapsLock(e.getModifierState("CapsLock"))} onBlur={() => setCapsLock(false)} placeholder="Enter your password" autoComplete="current-password" required disabled={loading} aria-describedby={[err && "login-error", capsLock && "login-caps-lock"].filter(Boolean).join(" ") || undefined} />
                <button className="gk-login-password-toggle" type="button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} disabled={loading} title={showPassword ? "Hide password" : "Show password"}><LoginIcon name={showPassword ? "eyeOff" : "eye"} size={19} /></button>
              </div>
              {capsLock && <p className="gk-login-caps" id="login-caps-lock" role="status">Caps Lock is on.</p>}
            </div>

            <button type="submit" className="gk-login-submit" disabled={loading}>
              {loading ? <><span className="gk-login-spinner" aria-hidden="true" />Signing in…</> : <>Sign in <LoginIcon name="arrow" size={19} /></>}
            </button>
            <p className="gk-login-help">Need access or help signing in?<br /><span>Contact your account administrator.</span></p>
          </form>
          <p className="gk-login-copyright">© {new Date().getFullYear()} Gurukrupa Bullion</p>
        </div>
      </div>
    </main>
  );
}
