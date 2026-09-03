import React, { useEffect, useState, useCallback, useRef } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import Calculator from "./components/Calculator.jsx";
import MakingPrice from "./components/MakingPrice.jsx";
import PremiumInputs from "./components/PremiumInputs.jsx";
import OptionsSpread from "./components/OptionsSpread.jsx";
import GoldOptions from "./components/GoldOptions.jsx";
import BullionStock from "./components/BullionStock.jsx";
import McxNymex from "./components/McxNymex.jsx";
import NseMcxCrude from "./components/NseMcxCrude.jsx";
import IvCalculator from "./components/IvCalculator.jsx";
import International from "./components/International.jsx";
import AutoTrades from "./components/AutoTrades.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import { ConfirmProvider, useConfirm } from "./components/ConfirmDialog.jsx";
import UsersPage from "./components/UsersPage.jsx";
import { api, getToken, clearToken, getRole, getPages, storeSession } from "./api/client.js";
import { createLiveSocket } from "./api/livesocket.js";

const SPREAD_TABS = ["signals", "cross", "calendar", "metals", "price", "othercomm"];
const VALID_PAGES = [...SPREAD_TABS, "calculator", "making", "premium", "options", "goldopt", "stock", "mcxnymex", "nsemcx", "ivcalc", "intl", "autotrades"];
// The two crude tabs became one page with a switch inside; a saved old key lands there.
const LEGACY_PAGES = { crude: "mcxnymex", crudeinr: "mcxnymex" };

function getStoredTheme() {
  return localStorage.getItem("arbi_theme") || "light";
}
function getStoredDensity() {
  return localStorage.getItem("arbi_density") || "comfortable";
}
// The pages this login may open, in the menu's order. An admin gets every
// page plus Manage Users; a user only what the admin ticked.
function allowedPages() {
  const pages = getPages();
  if (pages === "all") return [...VALID_PAGES, "users"];
  return VALID_PAGES.filter((k) => pages.includes(k));
}
// The live board (Cross / Calendar / Signals) rides the rates socket, which the
// server refuses to a login without one of those pages.
function hasBoardAccess() {
  const pages = getPages();
  return pages === "all" || ["cross", "calendar", "signals"].some((k) => pages.includes(k));
}

function getStoredPage() {
  const allowed = allowedPages();
  const p = localStorage.getItem("arbi_page");
  const q = LEGACY_PAGES[p] || p;
  if (allowed.includes(q)) return q;
  return allowed[0] || "cross";
}

function Dashboard() {
  const confirm = useConfirm();
  const [pairs, setPairs] = useState([]);
  const [metalData, setMetalData] = useState(null);
  const [otherCommData, setOtherCommData] = useState(null);
  const [priceData, setPriceData] = useState(null);
  const [feedStatus, setFeedStatus] = useState(null);
  const [wsState, setWsState] = useState("connecting");
  const [theme, setTheme] = useState(getStoredTheme());
  const [density, setDensity] = useState(getStoredDensity());
  // Who is actually signed in - was hardcoded "Vivek_Bitcoding", which the
  // trader login then displayed too and reasonably read as a security hole.
  const [user] = useState(() => localStorage.getItem("arbi_user") || "User");
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
        const tabs = Array.from(document.querySelectorAll(".nav-tabs .nav-tab"));
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

  // The header pill tracks the browser-to-server rates socket, which a trader
  // deliberately never opens (the server refuses it for that role) - so for a
  // trader it stayed "CONNECTING" for ever. For that login the pill follows the
  // MARKET feed instead: the thing the paper trades actually price off.
  useEffect(() => {
    if (hasBoardAccess() || !feedStatus) return;
    // `mode` is the feed's own state machine ("live", "starting", ...) - checked
    // against the real payload; the first guess (`ws_connected`) is not in it,
    // and a key that is never there would have pinned the pill on LIVE for ever,
    // dead feed included.
    setWsState(feedStatus.mode === "live" ? "live" : "connecting");
  }, [feedStatus]);

  // Slow-cadence fetch for feed status (the only thing WS doesn't push).
  const refreshSlow = useCallback(async () => {
    try {
      setFeedStatus(await api.feedStatus().catch(() => null));
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
    // "trader" here = any login without the board pages (trader role, or a
    // user whose ticked pages do not include Cross / Calendar / Signals).
    const trader = !hasBoardAccess();
    if (!trader) refreshPairsFallback(); // initial pairs load (also covers if WS slow to connect)

    // Slow REST cadence: feed status every 10s. Paused while the tab is hidden.
    let slowTimer = setInterval(refreshSlow, 10000);

    function onVisibility() {
      if (document.hidden) {
        clearInterval(slowTimer); slowTimer = null;
      } else {
        // Came back into view → refresh immediately so status isn't stale.
        refreshSlow();
        if (!slowTimer) slowTimer = setInterval(refreshSlow, 10000);
      }
    }
    document.addEventListener("visibilitychange", onVisibility);

    // A trader login has no board - the server answers 403 for it now, so the
    // pair socket would only manufacture errors. The status timer above still
    // runs (the LIVE pill is on the trader's allowed list) and still needs the
    // same teardown.
    if (trader) {
      return () => {
        if (slowTimer) clearInterval(slowTimer);
        document.removeEventListener("visibilitychange", onVisibility);
      };
    }

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
      document.removeEventListener("visibilitychange", onVisibility);
      stopFallback();
      sock.close();
    };
  }, [refreshSlow, refreshPairsFallback]);

  // Watch-tab data (Metal / Other Commodity / Price) — polled here so the nav
  // badges show counts and the tabs render instantly. Paused when hidden.
  useEffect(() => {
    let alive = true, timer = null;
    async function load() {
      try {
        // only the watch tabs this login may open - the others would 403
        const [m, o, p] = await Promise.all([
          can("metals") ? api.metalsSpread().catch(() => null) : null,
          can("othercomm") ? api.otherCommSpread().catch(() => null) : null,
          (can("price") || can("making")) ? api.priceTable().catch(() => null) : null,
        ]);
        if (!alive) return;
        if (m) setMetalData(m);
        if (o) setOtherCommData(o);
        if (p) setPriceData(p);
      } catch { /* keep last */ }
    }
    const allowed = allowedPages();
    const can = (k) => allowed.includes(k);
    if (!can("metals") && !can("othercomm") && !can("price") && !can("making")) return undefined;
    function start() { if (!timer) timer = setInterval(load, 2000); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function onVis() { if (document.hidden) stop(); else { load(); start(); } }
    load(); start();
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; stop(); document.removeEventListener("visibilitychange", onVis); };
  }, []);

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

  async function logout() {
    const ok = await confirm({
      title: "Log out?",
      message: "You'll need to sign in again to access the dashboard.",
      confirmText: "Logout",
      danger: true,
    });
    if (!ok) return;
    clearToken();
    window.location.reload();
  }

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }
  function toggleDensity() {
    setDensity((d) => (d === "compact" ? "comfortable" : "compact"));
  }

  // Re-read this login's pages on every load: the admin may have edited them.
  // A change updates storage and reloads once, so the menu and the wall agree.
  useEffect(() => {
    api.me().then((m) => {
      const before = JSON.stringify([getRole(), getPages()]);
      storeSession(m);
      if (JSON.stringify([getRole(), getPages()]) !== before) window.location.reload();
    }).catch(() => {});
  }, []);

  const counts = {
    signals: pairs.filter((r) => r.signal).length,
    cross: pairs.filter((r) => r.type === "cross").length,
    calendar: pairs.filter((r) => r.type === "calendar").length,
    metals: metalData?.count ?? 0,
    price: priceData?.count ?? 0,
    othercomm: otherCommData?.count ?? 0,
  };

  return (
    <div className="app">
      <Header
        role={getRole()}
        pages={getPages()}
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
        counts={counts}
      />
      <div className="container">
        {SPREAD_TABS.includes(page) && (
          <LiveSpreadTable
            rows={pairs}
            tab={page}
            metalData={metalData}
            otherCommData={otherCommData}
            priceData={priceData}
          />
        )}
        {page === "calculator" && <Calculator />}
        {page === "making" && <MakingPrice priceData={priceData} />}
        {page === "premium" && <PremiumInputs />}
        {page === "mcxnymex" && <McxNymex />}
        {/* Same screen, US side restated in rupees at the USD/INR future. A
            separate tab because the client wants the dollar view kept. */}
      {page === "nsemcx" && <NseMcxCrude />}
      {page === "ivcalc" && <IvCalculator />}
      {page === "intl" && <International />}
      {page === "autotrades" && <AutoTrades />}
        {page === "users" && getRole() === "admin" && <UsersPage />}
        {page === "options" && <OptionsSpread />}
        {page === "goldopt" && <GoldOptions />}
        {page === "stock" && <BullionStock />}
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
