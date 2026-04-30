import React, { useEffect, useState, useCallback } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import StatCards from "./components/StatCards.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import ActivePositions from "./components/ActivePositions.jsx";
import TradeHistory from "./components/TradeHistory.jsx";
import { api, getToken, clearToken } from "./api/client.js";

function getStoredTheme() {
  return localStorage.getItem("arbi_theme") || "light";
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [pairs, setPairs] = useState([]);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState([]);
  const [mode, setMode] = useState("paper");
  const [theme, setTheme] = useState(getStoredTheme());
  const [user] = useState("Vivek_Bitcoding");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("arbi_theme", theme);
  }, [theme]);

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

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  return (
    <div className="app">
      <Header
        user={user}
        mode={mode}
        onPause={pauseAll}
        onLogout={logout}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
      {mode === "paper" && (
        <div className="banner">PAPER TRADING MODE — orders are simulated, no real trades placed</div>
      )}
      <div className="container">
        <StatCards pairs={pairs} positions={positions} history={history} />
        <LiveSpreadTable rows={pairs} onSaved={refreshAll} />
        <ActivePositions rows={positions} onChange={refreshAll} />
        <TradeHistory rows={history} />
      </div>
    </div>
  );
}
