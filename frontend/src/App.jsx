import React, { useEffect, useState, useCallback, useRef } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import ExpiryBar from "./components/ExpiryBar.jsx";
import StatCards from "./components/StatCards.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import ActivePositions from "./components/ActivePositions.jsx";
import TradeHistory from "./components/TradeHistory.jsx";
import Drawer from "./components/Drawer.jsx";
import { ToastProvider, useToast } from "./components/Toast.jsx";
import { ConfirmProvider, useConfirm } from "./components/ConfirmDialog.jsx";
import { api, getToken, clearToken } from "./api/client.js";
import { createLiveSocket } from "./api/livesocket.js";

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
  const [wsState, setWsState] = useState("connecting"); // connecting | live | reconnecting
  const [theme, setTheme] = useState(getStoredTheme());
  const [user] = useState("Vivek_Bitcoding");
  const [openDrawer, setOpenDrawer] = useState(null);
  const fallbackRef = useRef(null);

  useEffect(() => {
    document.body.classList.toggle("dark", theme === "dark");
    localStorage.setItem("arbi_theme", theme);
  }, [theme]);

  // Slow-cadence fetch for things WS doesn't push (positions, history, feed status)
  const refreshSlow = useCallback(async () => {
    try {
      const [op, h, fs] = await Promise.all([
        api.positions(),
        api.history(30),
        api.feedStatus().catch(() => null),
      ]);
      setPositions(op);
      setHistory(h);
      setFeedStatus(fs);
    } catch (e) {
      console.error(e);
    }
  }, []);

  // REST fallback for live pairs when WS is not connected
  const refreshPairsFallback = useCallback(async () => {
    try {
      const p = await api.livePairs();
      setPairs(p);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refreshSlow();
    refreshPairsFallback(); // initial pairs load (also covers if WS slow to connect)

    const slowTimer = setInterval(refreshSlow, 3000);

    const sock = createLiveSocket({
      onSnapshot: (data) => setPairs(data),
      onState: (s) => setWsState(s),
    });

    function startFallback() {
      if (fallbackRef.current) return;
      fallbackRef.current = setInterval(refreshPairsFallback, 2000);
    }
    function stopFallback() {
      if (fallbackRef.current) {
        clearInterval(fallbackRef.current);
        fallbackRef.current = null;
      }
    }

    return () => {
      clearInterval(slowTimer);
      stopFallback();
      sock.close();
    };
  }, [refreshSlow, refreshPairsFallback]);

  // Engage REST fallback only if WS keeps failing
  useEffect(() => {
    if (wsState === "live") {
      if (fallbackRef.current) {
        clearInterval(fallbackRef.current);
        fallbackRef.current = null;
      }
    } else if (wsState === "reconnecting") {
      if (!fallbackRef.current) {
        fallbackRef.current = setInterval(() => {
          api.livePairs().then(setPairs).catch(() => {});
        }, 3000);
      }
    }
  }, [wsState]);

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
      refreshSlow();
      refreshPairsFallback();
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

  const onLocalSaved = () => {
    refreshSlow();
    // pairs will refresh via WS push within ~100ms
  };

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
        wsState={wsState}
      />
      <div className="container">
        <ExpiryBar instruments={feedStatus?.instruments} />
        <StatCards pairs={pairs} positions={positions} history={history} />
        <LiveSpreadTable rows={pairs} onSaved={onLocalSaved} />
      </div>

      <Drawer
        open={openDrawer === "positions"}
        title={`Active Positions (${positions.length})`}
        onClose={() => setOpenDrawer(null)}
      >
        <ActivePositions rows={positions} onChange={refreshSlow} />
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
