import React, { useEffect, useState, useRef } from "react";
import Login from "./components/Login.jsx";
import Header from "./components/Header.jsx";
import LiveSpreadTable from "./components/LiveSpreadTable.jsx";
import Calculator from "./components/Calculator.jsx";
import MakingPrice from "./components/MakingPrice.jsx";
import PremiumInputs from "./components/PremiumInputs.jsx";
import OptionsSpread from "./components/OptionsSpread.jsx";
import GoldOptions from "./components/GoldOptions.jsx";
import BankOptions from "./components/BankOptions.jsx";
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
import HolidaysPage from "./components/HolidaysPage.jsx";
import { api, getToken, clearToken, getRole, getPages, storeSession } from "./api/client.js";
import { createLiveSocket } from "./api/livesocket.js";
import { usePolling } from "./api/usePolling.js";

const SPREAD_TABS = ["signals", "cross", "calendar", "metals", "price", "othercomm"];
const VALID_PAGES = [...SPREAD_TABS, "calculator", "making", "premium", "options", "goldopt", "bankoptions", "stock", "mcxnymex", "nsemcx", "ivcalc", "intl", "autotrades"];
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
  if (pages === "all") return [...VALID_PAGES, "users", "holidays"];
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
  const socketSnapshot = useRef(0);
  const boardActive = hasBoardAccess() && ["cross", "calendar", "signals"].includes(page);

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
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT" || e.target.isContentEditable)) return;
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

  const feedPoll = usePolling(api.feedStatus, {
    key: "feed-status", interval: 10000, onData: setFeedStatus,
  });
  useEffect(() => {
    if (!boardActive) setWsState(feedStatus?.mode === "live" ? "live" : "connecting");
  }, [feedStatus, boardActive]);

  // Open the rates stream only while a rates board is visible. REST is a
  // single-flight fallback; a socket snapshot invalidates every older read.
  useEffect(() => {
    if (!boardActive) return undefined;
    let active = true;
    const socket = createLiveSocket({
      onSnapshot: (data) => {
        if (!active) return;
        socketSnapshot.current += 1;
        setPairs(data);
      },
      onState: (state) => { if (active) setWsState(state); },
    });
    return () => { active = false; socketSnapshot.current += 1; socket.close(); };
  }, [boardActive]);
  usePolling(async (signal) => {
    const version = socketSnapshot.current;
    const data = await api.livePairs(signal);
    return { version, data };
  }, {
    key: "pairs", enabled: boardActive && wsState !== "live", interval: 3000,
    onData: ({ version, data }) => {
      if (version === socketSnapshot.current) setPairs(data);
    },
  });

  // Only the visible watch board needs fresh prices. Previously every allowed
  // watch page was fetched every two seconds, even while using a calculator.
  const watchPage = page === "making" ? "price" : page;
  const watchAllowed = allowedPages().includes(page) && ["metals", "othercomm", "price"].includes(watchPage);
  const watch = usePolling((signal) => ({
    metals: api.metalsSpread, othercomm: api.otherCommSpread, price: api.priceTable,
  })[watchPage](signal), {
    key: watchPage, enabled: watchAllowed, interval: 2000,
    onData: (data) => {
      if (watchPage === "metals") setMetalData(data);
      else if (watchPage === "othercomm") setOtherCommData(data);
      else setPriceData(data);
    },
  });

  // Pick up grants/revocations in an open session without hammering the user
  // table. Hidden tabs stop polling and revalidate immediately on return.
  usePolling(api.me, {
    key: "session", interval: 30000,
    onData: (session) => {
      const before = JSON.stringify([getRole(), getPages(), localStorage.getItem("arbi_user")]);
      storeSession(session);
      if (JSON.stringify([getRole(), getPages(), localStorage.getItem("arbi_user")]) !== before) window.location.reload();
    },
  });

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

  const counts = {
    signals: pairs.filter((r) => r.signal).length,
    cross: pairs.filter((r) => r.type === "cross").length,
    calendar: pairs.filter((r) => r.type === "calendar").length,
    metals: metalData?.count ?? 0,
    price: priceData?.count ?? 0,
    othercomm: otherCommData?.count ?? 0,
  };

  return (
    <div className={`app${page === "bankoptions" ? " bo-workspace" : ""}`}>
      <Header
        role={getRole()}
        pages={getPages()}
        user={user}
        onLogout={logout}
        theme={theme}
        onToggleTheme={toggleTheme}
        density={density}
        onToggleDensity={toggleDensity}
        feedStatus={feedPoll.error || feedPoll.pending ? null : feedStatus}
        wsState={wsState}
        page={page}
        onNavigate={setPage}
        counts={counts}
      />
      <div className="container">
        {watchAllowed && watch.error && <div className="settings-banner danger" role="alert">Displayed prices may be stale. {watch.error}</div>}
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
        {page === "making" && <MakingPrice priceData={priceData} fresh={!watch.error && !watch.pending && !watch.paused} />}
        {page === "premium" && <PremiumInputs />}
        {page === "mcxnymex" && <McxNymex />}
        {/* Same screen, US side restated in rupees at the USD/INR future. A
            separate tab because the client wants the dollar view kept. */}
      {page === "nsemcx" && <NseMcxCrude />}
      {page === "ivcalc" && <IvCalculator />}
      {page === "intl" && <International />}
      {page === "autotrades" && <AutoTrades />}
        {page === "users" && getRole() === "admin" && <UsersPage />}
        {page === "holidays" && getRole() === "admin" && <HolidaysPage />}
        {page === "options" && <OptionsSpread />}
        {page === "goldopt" && <GoldOptions />}
        {page === "bankoptions" && <BankOptions />}
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
