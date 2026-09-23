import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import BrandMark from "./BrandMark.jsx";
import "./Header.css";

// Keep every market page directly visible, in the established menu order.
const NAV_ITEMS = [
  { key: "cross", label: "Cross Pair", group: "Spreads", hint: "Compare spreads between gold and silver contracts" },
  { key: "calendar", label: "Calendar Spread", group: "Spreads", hint: "Compare the same instrument across expiry months" },
  { key: "metals", label: "Metal Spread", group: "Spreads", hint: "Base-metal calendar spreads" },
  { key: "othercomm", label: "Other Commodity Spread", group: "Spreads", hint: "Watch spreads across other commodities" },
  { key: "price", label: "Metal Price", group: "Markets", hint: "View current metal prices" },
  { key: "calculator", label: "ETF vs MCX", group: "Tools", hint: "Compare ETF and MCX fair values" },
  { key: "premium", label: "Premium", group: "Tools", hint: "Manage bullion premiums" },
  { key: "goldopt", label: "Commodity Option", group: "Options", hint: "Gold and commodity options" },
  { key: "nsemcx", label: "NSE vs MCX", group: "Markets", hint: "Compare NSE and MCX contracts" },
  { key: "mcxnymex", label: "MCX vs NYMEX", group: "Markets", hint: "Compare domestic and international crude prices" },
  { key: "making", label: "Making Price", group: "Tools", hint: "Calculate bullion making prices" },
  { key: "stock", label: "Bullion Stock", group: "Markets", hint: "Track bullion stock and availability" },
  { key: "intl", label: "COMEX + NYMEX", group: "Markets", hint: "International futures and market prices" },
  { key: "ivcalc", label: "IV Calculator", group: "Tools", hint: "Calculate implied volatility" },
  { key: "options", label: "Nifty / Sensex", group: "Options", hint: "Compare Nifty and Sensex options" },
  { key: "bankoptions", label: "BANKEX / BANKNIFTY", group: "Options", hint: "Bank index options and paper positions" },
  { key: "signals", label: "Signals", group: "Spreads", hint: "Review active spread signals" },
  { key: "autotrades", label: "Auto Trades", group: "Trading", hint: "Monitor automated trades and activity" },
];
const ADMIN_ITEMS = [
  { key: "users", label: "Manage Users", group: "Management", hint: "Create logins and manage page access" },
  { key: "holidays", label: "Market Holidays", group: "Management", hint: "Manage exchange holidays and market hours" },
];

function Icon({ name, size = 18 }) {
  const paths = {
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>,
    cross: <path d="m16 3 4 4-4 4M20 7H5m3 14-4-4 4-4M4 17h15" />,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 11h18" /></>,
    metals: <path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" />,
    price: <><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="12" cy="12" r="3" /><path d="M6 12h.01M18 12h.01" /></>,
    othercomm: <path d="M12 3C9 7 5 10 5 14a7 7 0 0 0 14 0c0-4-4-7-7-11Z" />,
    calculator: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M8 11h1m6 0h1m-8 4h1m6 0h1m-8 3h1m6 0h1" /></>,
    options: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    stock: <><path d="m3 7 9-4 9 4-9 4-9-4Zm0 0v10l9 4 9-4V7M12 11v10" /></>,
    making: <><path d="m20 14-7 7L3 11V3h8l9 10v1Z" /><circle cx="7.5" cy="7.5" r="1" /></>,
    premium: <path d="m3 17 6-6 4 4 8-10m-6 0h6v6" />,
    autotrades: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    signals: <path d="m13 2-9 12h7l-1 8 10-12h-7l1-8Z" />,
    globe: <><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3m1-17a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 4v3" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
    moon: <path d="M20 14a8.5 8.5 0 0 1-10-10 9 9 0 1 0 10 10Z" />,
    density: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M3 15h18" /></>,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    chevron: <path d="m8 10 4 4 4-4" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    logout: <><path d="M9 4H4v16h5m5-12 4 4-4 4M8 12h12" /></>,
  };
  const aliases = { goldopt: "options", bankoptions: "options", holidays: "calendar", ivcalc: "calculator", nsemcx: "cross", mcxnymex: "cross", intl: "globe" };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[aliases[name] || name] || paths.globe}</svg>;
}

function useDialogFocus(ref, open, close) {
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(ref.current?.querySelectorAll('button:not(:disabled), input, [tabindex="0"]') || []);
    (ref.current?.querySelector("[data-autofocus]") || focusable()[0])?.focus();
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); closeRef.current(); }
      if (e.key !== "Tab") return;
      const items = focusable();
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
      if (previous?.isConnected) previous.focus();
    };
  }, [open, ref]);
}

function feedHealth(feed, wsState) {
  if (!feed) return { label: "Connecting", tone: "warn", detail: "Checking the market-data connection." };
  if (feed.mode === "simulated") return { label: "Demo data", tone: "neutral", detail: "Prices are simulated." };
  if (feed.mode !== "live") return { label: "Feed unavailable", tone: "danger", detail: "Market data is unavailable. Displayed prices may be stale." };
  if (feed.market_open === false) return { label: feed.market?.state === "holiday" ? "Market holiday" : "Market closed", tone: "neutral", detail: feed.market?.reason || "Showing the latest available prices." };
  if (feed.last_tick_age_seconds == null || feed.last_tick_age_seconds > 30) return { label: "Waiting for prices", tone: "warn", detail: "Fresh market prices have not arrived. Displayed values may be stale." };
  if (wsState !== "live") return { label: "Reconnecting", tone: "warn", detail: "Reconnecting the live stream. Prices refresh periodically in the meantime." };
  return { label: "Live market", tone: "live", detail: "Market data is connected and updating." };
}

export default function Header({ user, onLogout, theme, onToggleTheme, density, onToggleDensity, feedStatus, wsState, page, onNavigate, counts = {}, role = "user", pages = [] }) {
  const nav = pages === "all" ? NAV_ITEMS : NAV_ITEMS.filter((item) => pages.includes(item.key));
  const destinations = [...nav, ...(role === "admin" ? ADMIN_ITEMS : [])];
  const current = destinations.find((item) => item.key === page);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [popover, setPopover] = useState(null);
  const drawerRef = useRef(null);
  const searchRef = useRef(null);
  const toolsRef = useRef(null);
  const accountTrigger = useRef(null);
  const feedTrigger = useRef(null);
  useDialogFocus(drawerRef, drawerOpen, () => setDrawerOpen(false));
  useDialogFocus(searchRef, searchOpen, () => setSearchOpen(false));

  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        // An open form or confirmation keeps its keyboard focus.
        if (document.querySelector('[role="dialog"], [role="alertdialog"], .confirm-overlay, dialog[open]') && !searchRef.current) return;
        e.preventDefault(); setPopover(null); setDrawerOpen(false); setSearchOpen((value) => !value); setQuery("");
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!popover) return;
    function outside(e) { if (!toolsRef.current?.contains(e.target)) setPopover(null); }
    function escape(e) {
      if (e.key === "Escape") {
        setPopover(null);
        (popover === "account" ? accountTrigger : feedTrigger).current?.focus();
      }
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [popover]);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 901px)");
    const close = () => { if (media.matches) setDrawerOpen(false); };
    media.addEventListener("change", close);
    return () => media.removeEventListener("change", close);
  }, []);

  function go(key) {
    onNavigate(key); setDrawerOpen(false); setSearchOpen(false); setPopover(null); setQuery("");
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function openSearch() { setPopover(null); setQuery(""); setSearchOpen(true); }
  const health = feedHealth(feedStatus, wsState);
  const searchWords = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = destinations.filter((item) => searchWords.every((word) => `${item.label} ${item.group} ${item.hint}`.toLowerCase().includes(word)));
  const roleLabel = { admin: "Administrator", user: "Member", trader: "Trader" }[role] || role;
  const tickAge = feedStatus?.last_tick_age_seconds;

  const navButton = (item, mobile = false) => (
    <button key={item.key} type="button" data-key={item.key} className={`${mobile ? "workspace-drawer-link" : "nav-tab"}${page === item.key ? " active" : ""}`}
      onClick={() => go(item.key)} aria-current={page === item.key ? "page" : undefined} title={item.hint}>
      <Icon name={item.key} size={16} /><span>{item.label}</span>
      {item.key === "signals" && counts.signals > 0 && <span className="workspace-signal-count">{counts.signals}</span>}
    </button>
  );

  return (
    <>
      <header className="header workspace-header">
        <div className="workspace-topbar">
          <div className="workspace-identity">
            <button type="button" className="workspace-icon-button workspace-menu-button" onClick={() => { setPopover(null); setDrawerOpen(true); }} aria-label="Open navigation" aria-expanded={drawerOpen}><Icon name="menu" /></button>
            <div className="workspace-brand"><BrandMark size={36} /><div><strong>Gurukrupa <span>Bullion</span></strong><small>Trading workspace</small></div></div>
          </div>
          <button type="button" className="workspace-search-trigger" onClick={openSearch} aria-label="Find a page" aria-haspopup="dialog"><Icon name="search" /><span>Find a page…</span><kbd>Ctrl K</kbd></button>
          <div className="workspace-tools" ref={toolsRef}>
            <div className="workspace-popover-anchor">
              <button type="button" ref={feedTrigger} className={`workspace-health ${health.tone}`} onClick={() => setPopover(popover === "feed" ? null : "feed")} aria-expanded={popover === "feed"} aria-controls="feed-details" aria-label={`Market status: ${health.label}`}><span className="workspace-health-dot" /><span>{health.label}</span><Icon name="chevron" size={13} /></button>
              {popover === "feed" && <div id="feed-details" className="workspace-popover workspace-feed-details"><strong>Market connection</strong><p>{health.detail}</p><dl><div><dt>Data source</dt><dd>{feedStatus?.mode === "simulated" ? "Demo" : feedStatus?.mode === "live" ? "Live feed" : "Unavailable"}</dd></div><div><dt>Market</dt><dd>{feedStatus?.market?.label || (feedStatus?.market_open === true ? "Open" : feedStatus?.market_open === false ? "Closed" : "Checking…")}</dd></div><div><dt>Last price received</dt><dd>{tickAge == null ? "Not available" : `${Math.max(0, Math.round(tickAge))}s ago`}</dd></div></dl><button type="button" className="workspace-text-button" onClick={() => { setPopover(null); feedTrigger.current?.focus(); }}>Close details</button></div>}
            </div>
            <span className="workspace-tools-divider" />
            <button type="button" className="workspace-icon-button workspace-desktop-tool" onClick={onToggleDensity} aria-label={density === "compact" ? "Use comfortable layout" : "Use compact layout"} aria-pressed={density === "compact"} title={density === "compact" ? "Switch to comfortable layout" : "Switch to compact layout"}><Icon name="density" /></button>
            <button type="button" className="workspace-icon-button workspace-desktop-tool" onClick={onToggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} title={theme === "dark" ? "Light mode" : "Dark mode"}><Icon name={theme === "dark" ? "sun" : "moon"} /></button>
            {role === "admin" && <button type="button" className={`workspace-manage-button${page === "users" ? " active" : ""}`} onClick={() => go("users")}><Icon name="users" size={16} />Manage users</button>}
            <div className="workspace-popover-anchor">
              <button type="button" className="workspace-account-trigger" ref={accountTrigger} onClick={() => setPopover(popover === "account" ? null : "account")} aria-label={`Account settings for ${user}`} aria-expanded={popover === "account"} aria-controls="account-settings"><span className="workspace-avatar">{(user || "U").charAt(0).toUpperCase()}</span><span className="workspace-account-name">{user}</span><Icon name="chevron" size={13} /></button>
              {popover === "account" && <div id="account-settings" className="workspace-popover workspace-account-panel"><div className="workspace-account-info"><strong>{user}</strong><span>{roleLabel}</span></div><button type="button" onClick={onToggleTheme}><Icon name={theme === "dark" ? "sun" : "moon"} />{theme === "dark" ? "Light appearance" : "Dark appearance"}</button><button type="button" onClick={onToggleDensity}><Icon name="density" />{density === "compact" ? "Comfortable layout" : "Compact layout"}</button>{role === "admin" && <div className="workspace-account-section">{ADMIN_ITEMS.map((item) => <button key={item.key} type="button" onClick={() => go(item.key)}><Icon name={item.key} />{item.label}</button>)}</div>}<div className="workspace-account-section"><button type="button" className="workspace-signout" onClick={() => { setPopover(null); onLogout(); }}><Icon name="logout" />Sign out</button></div></div>}
            </div>
          </div>
        </div>
        <nav className="nav-tabs workspace-nav" aria-label="Main navigation">{nav.map((item) => navButton(item))}</nav>
        <div className="workspace-mobile-location"><span>{current?.group || "Workspace"}</span><Icon name="arrow" size={12} /><strong>{current?.label || "Dashboard"}</strong><button type="button" onClick={() => setDrawerOpen(true)}>All pages<Icon name="chevron" size={13} /></button></div>
      </header>

      {drawerOpen && createPortal(<div className="workspace-overlay" onClick={(e) => { if (e.target === e.currentTarget) setDrawerOpen(false); }}><div className="workspace-drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-labelledby="workspace-drawer-title"><div className="workspace-drawer-head"><div><strong id="workspace-drawer-title">Your workspace</strong><span>Markets, tools & management</span></div><button type="button" className="workspace-icon-button" onClick={() => setDrawerOpen(false)} aria-label="Close navigation"><Icon name="close" /></button></div><nav className="workspace-drawer-nav" aria-label="Mobile navigation">{[...new Set(destinations.map((item) => item.group))].map((group) => <section key={group}><h2>{group}</h2>{destinations.filter((item) => item.group === group).map((item) => navButton(item, true))}</section>)}</nav><div className="workspace-drawer-footer"><span className="workspace-avatar">{(user || "U").charAt(0).toUpperCase()}</span><div><strong>{user}</strong><small>{roleLabel}</small></div><button type="button" className="workspace-icon-button" onClick={() => { setDrawerOpen(false); onLogout(); }} aria-label="Sign out"><Icon name="logout" /></button></div></div></div>, document.body)}

      {searchOpen && createPortal(<div className="workspace-overlay workspace-search-overlay" onClick={(e) => { if (e.target === e.currentTarget) setSearchOpen(false); }}><div className="workspace-command" role="dialog" aria-modal="true" aria-labelledby="workspace-search-title" ref={searchRef}><div className="workspace-command-heading"><h2 id="workspace-search-title">Find a page</h2><button type="button" className="workspace-icon-button" onClick={() => setSearchOpen(false)} aria-label="Close page search"><Icon name="close" /></button></div><div className="workspace-command-input"><Icon name="search" size={20} /><input data-autofocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search markets, tools or settings…" aria-label="Search pages" autoComplete="off" onKeyDown={(e) => { if (e.key === "Enter" && matches.length) { e.preventDefault(); go(matches[0].key); } if (e.key === "ArrowDown") { e.preventDefault(); searchRef.current?.querySelector(".workspace-command-result")?.focus(); } }} /><kbd>Esc</kbd></div><div className="workspace-command-results" onKeyDown={(e) => { if (!["ArrowDown", "ArrowUp"].includes(e.key)) return; const buttons = Array.from(e.currentTarget.querySelectorAll("button")); const index = buttons.indexOf(document.activeElement); if (index < 0) return; e.preventDefault(); const next = index + (e.key === "ArrowDown" ? 1 : -1); if (next < 0) searchRef.current?.querySelector("input")?.focus(); else buttons[next % buttons.length]?.focus(); }}><div className="workspace-command-caption" role="status">{query ? `${matches.length} ${matches.length === 1 ? "page" : "pages"} found` : "Go directly to a page"}</div>{matches.map((item) => <button type="button" key={item.key} className={`workspace-command-result${page === item.key ? " current" : ""}`} onClick={() => go(item.key)}><span className="workspace-result-icon"><Icon name={item.key} /></span><span className="workspace-result-copy"><strong>{item.label}</strong><small>{item.hint}</small></span><span className="workspace-result-group">{item.group}</span><Icon name="arrow" size={15} /></button>)}{matches.length === 0 && <div className="workspace-command-empty"><strong>No pages found</strong><p>Try a market name, “users” or “calculator”.</p><button type="button" className="workspace-text-button" onClick={() => { setQuery(""); searchRef.current?.querySelector("input")?.focus(); }}>Clear search</button></div>}</div><div className="workspace-command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> to browse</span><span><kbd>Enter</kbd> to open</span></div></div></div>, document.body)}
    </>
  );
}
