import React, { useEffect, useState, useCallback, useRef } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import StatCards from "./components/StatCards.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import Activity from "./components/Activity.jsx";
import Calculator from "./components/Calculator.jsx";
import Settings from "./components/Settings.jsx";
import OptionsSpread from "./components/OptionsSpread.jsx";
import MetalSpread from "./components/MetalSpread.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import { ConfirmProvider } from "./components/ConfirmDialog.jsx";
import { api, getToken, clearToken } from "./api/client.js";
import { createLiveSocket } from "./api/livesocket.js";

const VALID_PAGES = ["dashboard", "activity", "calculator", "options", "metals", "settings"];

function getStoredTheme() {
  return localStorage.getItem("arbi_theme") || "light";
}
function getStoredDensity() {
  return localStorage.getItem("arbi_density") || "comfortable";
}
function getStoredPage() {
  const p = localStorage.getItem("arbi_page");
  return VALID_PAGES.includes(p) ? p : "dashboard";
}

function Dashboard() {
  const [pairs, setPairs] = useState([]);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState([]);
  const [account, setAccount] = useState(null);
  const [feedStatus, setFeedStatus] = useState(null);
  const [wsState, setWsState] = useState("connecting");
  const [theme, setTheme] = useState(getStoredTheme());
  const [density, setDensity] = useState(getStoredDensity());
  const [user] = useState("Vivek_Bitcoding");
  const [page, setPage] = useState(getStoredPage());
  const fallbackRef = useRef(null);

  useEffect(() => {
    document.body.classList.toggle("dark", theme === "dark");
    localStorage.setItem("arbi_theme", theme);
  }, [theme]);

  useEffect(() => {
    document.body.classList.toggle("density-compact", density === "compact");
    localStorage.setItem("arbi_density", density);
  }, [density]);

  useEffect(() => {
    localStorage.setItem("arbi_page", page);
  }, [page]);

  // Global keyboard shortcuts: '/' focus search, ← → flip tabs (dashboard only)
  useEffect(() => {
    function onKey(e) {
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable)) return;
      if (e.key === "/") {
        const el = document.querySelector('.search-container input');
        if (el) { e.preventDefault(); el.focus(); }
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const tabs = Array.from(document.querySelectorAll(".pair-tabs .pair-tab"));
        const activeIdx = tabs.findIndex((t) => t.classList.contains("active"));
        if (activeIdx === -1) return;
        const nextIdx = e.key === "ArrowRight" ? (activeIdx + 1) % tabs.length : (activeIdx - 1 + tabs.length) % tabs.length;
        tabs[nextIdx]?.click();
      } else if (e.key.toLowerCase() === "d" && (e.ctrlKey || e.metaKey) && e.shiftKey) {
        e.preventDefault();
        setDensity((d) => (d === "compact" ? "comfortable" : "compact"));
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Slow-cadence fetch for things WS doesn't push (positions, history, feed status).
  // Account is fetched on a slower, separate cadence (rarely changes).
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

  const refreshAccount = useCallback(async () => {
    try {
      setAccount(await api.getAccount().catch(() => null));
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
    refreshAccount();
    refreshPairsFallback(); // initial pairs load (also covers if WS slow to connect)

    // Slow REST cadence: positions/history/feed + account every 10s (account on
    // its own timer so its slower-changing data can later be dialed back).
    // Paused entirely while the tab is hidden (no point polling a tab nobody sees).
    let slowTimer = setInterval(refreshSlow, 10000);
    let acctTimer = setInterval(refreshAccount, 10000);

    function onVisibility() {
      if (document.hidden) {
        clearInterval(slowTimer); slowTimer = null;
        clearInterval(acctTimer); acctTimer = null;
      } else {
        // Came back into view → refresh immediately so numbers aren't stale.
        refreshSlow();
        refreshAccount();
        if (!slowTimer) slowTimer = setInterval(refreshSlow, 10000);
        if (!acctTimer) acctTimer = setInterval(refreshAccount, 10000);
      }
    }
    document.addEventListener("visibilitychange", onVisibility);

    const sock = createLiveSocket({
      onSnapshot: (data) => setPairs(data),
      onState: (s) => setWsState(s),
    });

    function stopFallback() {
      if (fallbackRef.current) {
        clearInterval(fallbackRef.current);
        fallbackRef.current = null;
      }
    }

    return () => {
      clearInterval(slowTimer);
      clearInterval(acctTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      stopFallback();
      sock.close();
    };
  }, [refreshSlow, refreshAccount, refreshPairsFallback]);

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
  function toggleDensity() {
    setDensity((d) => (d === "compact" ? "comfortable" : "compact"));
  }

  const onLocalSaved = () => {
    refreshSlow();
    refreshAccount();
  };

  return (
    <div className="app">
      <Header
        user={user}
        onLogout={logout}
        theme={theme}
        onToggleTheme={toggleTheme}
        density={density}
        onToggleDensity={toggleDensity}
        feedStatus={feedStatus}
        wsState={wsState}
        page={page}
        onNavigate={setPage}
      />
      <div className="container">
        {page === "dashboard" && (
          <>
            <StatCards pairs={pairs} positions={positions} history={history} account={account} />
            <LiveSpreadTable rows={pairs} onSaved={onLocalSaved} />
          </>
        )}
        {page === "activity" && <Activity />}
        {page === "calculator" && <Calculator />}
        {page === "options" && <OptionsSpread />}
        {page === "metals" && <MetalSpread />}
        {page === "settings" && <Settings />}
      </div>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;
  return (
    <ErrorBoundary>
      <ToastProvider>
        <ConfirmProvider>
          <Dashboard />
        </ConfirmProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
