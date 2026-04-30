import React, { useEffect, useState, useCallback } from "react";
import Login from "./components/Login.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import ActivePositions from "./components/ActivePositions.jsx";
import TradeHistory from "./components/TradeHistory.jsx";
import { api, getToken, clearToken } from "./api/client.js";

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [pairs, setPairs] = useState([]);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState([]);
  const [mode, setMode] = useState("paper");

  const refreshAll = useCallback(async () => {
    try {
      const [p, op, h, hh] = await Promise.all([
        api.livePairs(),
        api.positions(),
        api.history(30),
        api.health(),
      ]);
      setPairs(p);
      setPositions(op);
      setHistory(h);
      setMode(hh.mode);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    refreshAll();
    const t = setInterval(refreshAll, 1500);
    return () => clearInterval(t);
  }, [authed, refreshAll]);

  async function pauseAll() {
    if (!confirm("Clear all entry/exit values across all pairs?")) return;
    try {
      await api.pauseAll();
      refreshAll();
    } catch (e) {
      alert(e.message);
    }
  }

  function logout() {
    clearToken();
    setAuthed(false);
  }

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  return (
    <div className="app">
      <div className="header">
        <h1>Gold MCX Arbitrage</h1>
        <div className="actions">
          <button className="primary" onClick={pauseAll}>Pause All</button>
          <button onClick={logout}>Logout</button>
        </div>
      </div>
      {mode === "paper" && (
        <div className="banner">PAPER TRADING MODE — orders are simulated, no real trades placed.</div>
      )}
      <div className="container">
        <LiveSpreadTable rows={pairs} onSaved={refreshAll} />
        <ActivePositions rows={positions} onChange={refreshAll} />
        <TradeHistory rows={history} />
      </div>
    </div>
  );
}
