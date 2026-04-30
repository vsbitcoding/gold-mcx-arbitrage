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
        <h1>Gold MCX Arbitrage</h1>
        {err && <div className="err">{err}</div>}
        <label>Username</label>
        <input value={u} onChange={(e) => setU(e.target.value)} autoFocus />
        <label>Password</label>
        <input type="password" value={p} onChange={(e) => setP(e.target.value)} />
        <button disabled={loading}>{loading ? "Signing in..." : "Sign In"}</button>
      </form>
    </div>
  );
}
