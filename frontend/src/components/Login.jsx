import React, { useState } from "react";
import { login } from "../api/client.js";

export default function Login({ onSuccess }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      await login(u, p);
      onSuccess();
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-header">
          <div className="logo">📊</div>
          <h1>ArbiDash Login</h1>
          <p>Enter your credentials to access the dashboard</p>
        </div>
        {err && <div className="err">⚠️ {err}</div>}
        <label>Username</label>
        <input value={u} onChange={(e) => setU(e.target.value)} placeholder="Enter your username" autoFocus />
        <label>Password</label>
        <input type="password" value={p} onChange={(e) => setP(e.target.value)} placeholder="Enter your password" />
        <button className="btn-login" disabled={loading}>{loading ? "Signing in..." : "🔐 Sign In"}</button>
        <div className="login-footer">ArbiDash © 2026 | Live Spread Monitor</div>
      </form>
    </div>
  );
}
