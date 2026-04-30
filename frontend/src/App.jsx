import React, { useEffect, useState, useCallback } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import FeedStatus from "./components/FeedStatus.jsx";
import StatCards from "./components/StatCards.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import ActivePositions from "./components/ActivePositions.jsx";
import TradeHistory from "./components/TradeHistory.jsx";
import Drawer from "./components/Drawer.jsx";
import { ToastProvider, useToast } from "./components/Toast.jsx";
import { ConfirmProvider, useConfirm } from "./components/ConfirmDialog.jsx";
import { api, getToken, clearToken } from "./api/client.js";

function getStoredTheme() {
  return localStorage.getItem("arbi_theme") || "light";
}

function Dashboard() {
  const toast = useToast();
  const confirm = useConfirm();

  const [pairs, setPairs] = useState([]);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState([]);
  const [feedStatus, setFeedStatus] = useState(null);
  const [mode, setMode] = useState("paper");
  const [theme, setTheme] = useState(getStoredTheme());
  const [user] = useState("Vivek_Bitcoding");
  const [openDrawer, setOpenDrawer] = useState(null);

  useEffect(() => {
    document.body.classList.toggle("dark", theme === "dark");
    localStorage.setItem("arbi_theme", theme);
  }, [theme]);

  const refreshAll = useCallback(async () => {
    try {
      const [p, op, h, hh, fs] = await Promise.all([
        api.livePairs(),
        api.positions(),
        api.history(30),
        api.health(),
        api.feedStatus().catch(() => null),
      ]);
      setPairs(p);
      setPositions(op);
      setHistory(h);
      setMode(hh.mode);
      setFeedStatus(fs);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refreshAll();
    const t = setInterval(refreshAll, 1500);
    return () => clearInterval(t);
  }, [refreshAll]);

  async function pauseAll() {
    const anyOpen = positions.length > 0;
    const ok = await confirm({
      title: "Pause All Pairs?",
      message: anyOpen
        ? `${positions.length} trade${positions.length > 1 ? "s are" : " is"} still open. Pausing only clears entry/exit values — open trades will NOT be closed. Use "Square Off" individually to close them.`
        : "Clear entry/exit values across all 6 pairs. Bot will stop firing new trades until you set new values.",
      confirmText: "Pause All",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.pauseAll();
      toast.success("All pairs paused.");
      refreshAll();
    } catch (e) {
      toast.error(e.message);
    }
  }

  function logout() {
    clearToken();
    window.location.reload();
  }

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }

  return (
    <div className="app">
      <Header
        user={user}
        onPause={pauseAll}
        onLogout={logout}
        theme={theme}
        onToggleTheme={toggleTheme}
        positionsCount={positions.length}
        historyCount={history.length}
        onOpenPositions={() => setOpenDrawer("positions")}
        onOpenHistory={() => setOpenDrawer("history")}
        feedStatus={feedStatus}
      />
      <div className="container">
        <StatCards pairs={pairs} positions={positions} history={history} />
        <LiveSpreadTable rows={pairs} onSaved={refreshAll} />
      </div>

      <Drawer
        open={openDrawer === "positions"}
        title={`Active Positions (${positions.length})`}
        onClose={() => setOpenDrawer(null)}
      >
        <ActivePositions rows={positions} onChange={refreshAll} />
      </Drawer>

      <Drawer
        open={openDrawer === "history"}
        title={`Trade History (${history.length})`}
        onClose={() => setOpenDrawer(null)}
      >
        <TradeHistory rows={history} />
      </Drawer>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;
  return (
    <ToastProvider>
      <ConfirmProvider>
        <Dashboard />
      </ConfirmProvider>
    </ToastProvider>
  );
}
