import React, { useEffect, useState } from "react";
import BrandMark from "./BrandMark.jsx";

const NAV_ITEMS = [
  { key: "cross", label: "Cross Pairs" },
  { key: "calendar", label: "Calendar" },
  { key: "metals", label: "Metal" },
  { key: "price", label: "Price" },
  { key: "othercomm", label: "Other Commodity" },
  { key: "calculator", label: "ETF vs MCX" },
  { key: "making", label: "Making Price" },
  { key: "premium", label: "Premium" },
  { key: "options", label: "Nifty / Sensex" },
  { key: "goldopt", label: "Commodity Options" },
  { key: "stock", label: "Bullion Stock" },
  { key: "signals", label: "⚡ Signals" },
];

// Clean monochrome line icons.
function NavIcon({ name }) {
  const c = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (name) {
    case "signals": return <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 3 14h7l-1 8 10-12h-7z" /></svg>;
    case "cross": return <svg {...c}><path d="M16 3l4 4-4 4M20 7H8M8 21l-4-4 4-4M4 17h12" /></svg>;
    case "calendar": return <svg {...c}><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>;
    case "metals": return <svg {...c}><path d="M12 2l9 5-9 5-9-5 9-5z" /><path d="M3 12l9 5 9-5M3 17l9 5 9-5" /></svg>;
    case "price": return <svg {...c}><rect x="2" y="6" width="20" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /></svg>;
    case "othercomm": return <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.7l5.7 5.6a8 8 0 1 1-11.4 0z" /></svg>;
    case "calculator": return <svg {...c}><rect x="4" y="2" width="16" height="20" rx="2" /><path d="M8 6h8M8 11h.01M12 11h.01M16 11h.01M8 15h.01M12 15h.01M16 15h.01M8 19h8" /></svg>;
    case "options": return <svg {...c}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>;
    case "stock": return <svg {...c}><path d="M3 21h18" /><rect x="5" y="11" width="4" height="7" /><rect x="15" y="11" width="4" height="7" /><path d="M7 11V7l5-4 5 4v4" /></svg>;
    case "goldopt": return <svg {...c}><circle cx="12" cy="12" r="9" /><path d="M8 12h8M12 8v8" /></svg>;
    case "making": return <svg {...c}><path d="M20.6 13.4 12 22l-9-9V4h9z" /><circle cx="7.5" cy="7.5" r="1.5" /></svg>;
    case "premium": return <svg {...c}><path d="M3 17l6-6 4 4 8-8" /><path d="M17 7h4v4" /></svg>;
    default: return null;
  }
}

export default function Header({ user, onLogout, theme, onToggleTheme, feedStatus, wsState, page, onNavigate, counts = {}, onToggleCollapse }) {
  const [open, setOpen] = useState(false);

  // Close mobile drawer on Escape; lock page scroll while open.
  useEffect(() => {
    if (!open) return;
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open]);

  // Combined health: worst of (browser↔server WS) and (server↔Dhan feed)
  const dhanMode = feedStatus?.mode;
  const tickAge = feedStatus?.last_tick_age_seconds;
  const tokenSecs = feedStatus?.token_expires_in_seconds;
  const marketOpen = feedStatus?.market_open;

  let label = "LIVE";
  let cls = "health-live";
  let extra = "";
  if (wsState !== "live") {
    label = wsState === "connecting" ? "CONNECTING" : "POLLING";
    cls = wsState === "connecting" ? "health-warn" : "health-poll";
  } else if (!feedStatus) {
    label = "LOADING"; cls = "health-warn";
  } else if (dhanMode === "simulated") {
    label = "DEMO"; cls = "health-poll";
  } else if (dhanMode !== "live") {
    label = "FEED DOWN"; cls = "health-down";
  } else if (!marketOpen) {
    label = "MARKET CLOSED"; cls = "health-poll";
  } else if (tickAge !== null && tickAge > 30) {
    label = "STALE"; cls = "health-warn"; extra = `${tickAge}s`;
  } else {
    const h = Math.floor((tokenSecs || 0) / 3600);
    const m = Math.floor(((tokenSecs || 0) % 3600) / 60);
    extra = h > 0 ? `${h}h ${m}m` : `${m}m`;
  }
  const tooltip = feedStatus
    ? [
        `Browser ↔ Server: ${wsState}`,
        `Server ↔ Dhan: ${dhanMode || "—"}`,
        `Market: ${marketOpen ? "OPEN" : "CLOSED"}`,
        `Client: ${feedStatus.client_name || "—"}`,
        `Token expires in: ${tokenSecs ? Math.floor(tokenSecs / 3600) + "h " + Math.floor((tokenSecs % 3600) / 60) + "m" : "—"}`,
        `Last tick: ${tickAge === null ? "never" : tickAge + "s ago"}`,
      ].join("\n")
    : "Connecting...";

  const pill = (
    <span className={`health-pill ${cls}`} title={tooltip}>
      <span className="health-dot" />
      <span className="health-label">{label}</span>
      {extra && <span className="health-meta">{extra}</span>}
    </span>
  );

  const go = (key) => { onNavigate(key); setOpen(false); };

  return (
    <>
      {/* Mobile top bar (hidden on desktop) */}
      <div className="mobile-bar">
        <button className="sb-burger" onClick={() => setOpen(true)} aria-label="Menu">☰</button>
        <div className="brand">
          <BrandMark size={24} />
          <span className="brand-name">Gurukrupa</span>
          <span className="brand-sub">Bullion</span>
        </div>
        {pill}
      </div>

      {open && <div className="sidebar-overlay" onClick={() => setOpen(false)} />}

      <aside className={`sidebar${open ? " open" : ""}`}>
        <div className="sidebar-brand">
          <BrandMark size={30} />
          <span className="brand-name">Gurukrupa</span>
          <span className="brand-sub">Bullion</span>
          <button className="sidebar-collapse" onClick={onToggleCollapse} aria-label="Collapse menu" title="Collapse menu">«</button>
          <button className="sidebar-x" onClick={() => setOpen(false)} aria-label="Close">×</button>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((it) => (
            <button
              key={it.key}
              className={`sidebar-item${page === it.key ? " active" : ""}${it.key === "signals" ? " sidebar-item-signals" : ""}`}
              onClick={() => go(it.key)}
            >
              <span className="sidebar-ic"><NavIcon name={it.key} /></span>
              <span className="sidebar-lbl">{it.label.replace(/^⚡\s*/, "")}</span>
              {counts[it.key] != null && <span className="sidebar-count">{counts[it.key]}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          {pill}
          <div className="sidebar-user">
            <span className="user-avatar">{(user || "U").charAt(0).toUpperCase()}</span>
            <span className="sidebar-user-name">{user || "User"}</span>
            <button className="sidebar-act" onClick={onToggleTheme} title={theme === "dark" ? "Light mode" : "Dark mode"}>{theme === "dark" ? "☀" : "☾"}</button>
          </div>
          <button className="sidebar-logout" onClick={onLogout} title="Logout"><span className="sidebar-logout-ic">⎋</span><span className="sidebar-logout-lbl">Logout</span></button>
        </div>
      </aside>
    </>
  );
}
