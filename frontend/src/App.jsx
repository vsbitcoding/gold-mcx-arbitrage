import React, { useEffect, useState, useCallback, useRef } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import StatCards from "./components/StatCards.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import Activity from "./components/Activity.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import { ConfirmProvider } from "./components/ConfirmDialog.jsx";
import { api, getToken, clearToken } from "./api/client.js";
import { createLiveSocket } from "./api/livesocket.js";

function getStoredTheme() {
  return localStorage.getItem("arbi_theme") || "light";
}

function Dashboard() {
  const [pairs, setPairs] = useState([]);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState([]);
  const [feedStatus, setFeedStatus] = useState(null);
  const [wsState, setWsState] = useState("connecting"); // connecting | live | reconnecting
  const [theme, setTheme] = useState(getStoredTheme());
  const [user] = useState("Vivek_Bitcoding");
  const [page, setPage] = useState("dashboard");
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
        api.history(7),
        api.feedStatus().catch(() => null),
      ]);
      if (op && Array.isArray(op.positions)) setPositions(op.positions);
      else setPositions(op || []);
      if (h && Array.isArray(h.trades)) setHistory(h.trades);
      else setHistory(h || []);
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

  function logout() {
    clearToken();
    window.location.reload();
  }

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }

  const onLocalSaved = () => {
    refreshSlow();
  };

  return (
    <div className="app">
      <Header
        user={user}
        onLogout={logout}
        theme={theme}
        onToggleTheme={toggleTheme}
        feedStatus={feedStatus}
        wsState={wsState}
        page={page}
        onNavigate={setPage}
      />
      <div className="container">
        {page === "dashboard" ? (
          <>
            <StatCards pairs={pairs} positions={positions} history={history} />
            <LiveSpreadTable rows={pairs} onSaved={onLocalSaved} />
          </>
        ) : (
          <Activity />
        )}
      </div>
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
