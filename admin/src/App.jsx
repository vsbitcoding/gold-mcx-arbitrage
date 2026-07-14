import React, { useState } from "react";
import { getToken, clearToken, login } from "./api.js";
import ScripMaster from "./ScripMaster.jsx";

const NAV = [
  { key: "scrip", label: "Scrip Master", icon: "▤", ready: true },
  { key: "rpanel", label: "R-Panel", icon: "≣" },
  { key: "news", label: "News", icon: "✎" },
  { key: "push", label: "Push Notification", icon: "🔔" },
  { key: "ticker", label: "Ticker", icon: "↔" },
  { key: "trading", label: "Trading App", icon: "⇄" },
  { key: "report", label: "Report", icon: "▦" },
  { key: "settings", label: "Settings", icon: "⚙" },
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
    catch (e) { setErr(e.message || "Login failed"); }
    finally { setBusy(false); }
  }
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <span className="login-mark">◆</span>
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
  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  const active = NAV.find((n) => n.key === page) || NAV[0];
  return (
    <div className="app">
      <aside className="side">
        <div className="side-brand">
          <span className="side-mark">◆</span>
          <span className="side-name">Gurukrupa <b>Bullion</b></span>
        </div>
        <nav className="side-nav">
          {NAV.map((n) => (
            <button key={n.key}
              className={`side-item${page === n.key ? " active" : ""}${n.ready ? "" : " soon"}`}
              onClick={() => setPage(n.key)}>
              <span className="side-ic">{n.icon}</span>
              <span className="side-lbl">{n.label}</span>
              {!n.ready && <span className="side-badge">soon</span>}
            </button>
          ))}
        </nav>
        <button className="side-logout" onClick={() => { clearToken(); setAuthed(false); }}>⎋ Logout</button>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>{active.label}</h1>
          <span className="top-spacer" />
          <span className="top-user">Gurukrupa</span>
        </header>
        <div className="content">
          {page === "scrip" ? <ScripMaster /> : (
            <div className="soon-panel">
              <div className="soon-ic">{active.icon}</div>
              <h2>{active.label}</h2>
              <p>This screen is part of the modern rebuild — coming next.</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
