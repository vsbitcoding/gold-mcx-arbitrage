import React, { useEffect, useState } from "react";
import { getToken, clearToken, login } from "./api.js";
import BrandMark from "./BrandMark.jsx";
import ScripMaster from "./ScripMaster.jsx";

// Top-nav shell (no sidebar — client preference), golden-white light theme
// with dark mode. Only Scrip Master is live; the rest are placeholders.
const NAV = [
  { key: "scrip", label: "Scrip Master", ready: true },
  { key: "rpanel", label: "R-Panel" },
  { key: "news", label: "News" },
  { key: "push", label: "Push Notification" },
  { key: "ticker", label: "Ticker" },
  { key: "trading", label: "Trading App" },
  { key: "report", label: "Report" },
  { key: "settings", label: "Settings" },
];

function Login({ onDone }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true); setErr("");
    try { await login(u.trim(), p); onDone(); }
    catch (e2) { setErr(e2.message || "Login failed"); }
    finally { setBusy(false); }
  }
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <BrandMark size={44} />
          <div>
            <div className="login-title">Gurukrupa <b>Bullion</b></div>
            <div className="login-sub">Admin Panel</div>
          </div>
        </div>
        <label>Username</label>
        <input value={u} onChange={(e) => setU(e.target.value)} autoFocus autoComplete="username" />
        <label>Password</label>
        <input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" />
        {err && <div className="login-err">{err}</div>}
        <button className="btn btn-gold" disabled={busy}>{busy ? "Signing in…" : "Sign In"}</button>
      </form>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [page, setPage] = useState("scrip");
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("gk_admin_theme") || "light"; } catch { return "light"; }
  });
  useEffect(() => {
    document.body.classList.toggle("dark", theme === "dark");
    try { localStorage.setItem("gk_admin_theme", theme); } catch {}
  }, [theme]);

  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  const active = NAV.find((n) => n.key === page) || NAV[0];
  return (
    <div className="app">
      <header className="nav">
        <div className="nav-brand">
          <BrandMark size={30} />
          <span className="nav-name">Gurukrupa <b>Bullion</b></span>
        </div>
        <nav className="nav-tabs">
          {NAV.map((n) => (
            <button key={n.key}
              className={`nav-tab${page === n.key ? " active" : ""}${n.ready ? "" : " soon"}`}
              onClick={() => setPage(n.key)}>
              {n.label}
            </button>
          ))}
        </nav>
        <div className="nav-right">
          <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title={theme === "dark" ? "Light mode" : "Dark mode"}>
            {theme === "dark" ? "☀" : "☾"}
          </button>
          <button className="icon-btn" onClick={() => { clearToken(); setAuthed(false); }} title="Logout">⎋</button>
        </div>
      </header>

      <main className="content">
        {page === "scrip" ? <ScripMaster /> : (
          <div className="soon-panel">
            <BrandMark size={40} />
            <h2>{active.label}</h2>
            <p>This screen is part of the modern rebuild — coming next.</p>
          </div>
        )}
      </main>
    </div>
  );
}
