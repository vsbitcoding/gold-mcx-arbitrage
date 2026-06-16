import React, { useEffect, useState } from "react";

const NAV_ITEMS = [
  { key: "signals", label: "⚡ Signals" },
  { key: "cross", label: "Cross Pairs" },
  { key: "calendar", label: "Calendar" },
  { key: "metals", label: "Metal" },
  { key: "price", label: "Price" },
  { key: "othercomm", label: "Other Commodity" },
  { key: "calculator", label: "Calculator" },
  { key: "options", label: "Nifty / Sensex" },
];

export default function Header({
  user,
  onLogout,
  theme,
  onToggleTheme,
  density,
  onToggleDensity,
  feedStatus,
  wsState,
  page,
  onNavigate,
  counts = {},
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  // Close drawer on Escape; lock page scroll while open.
  useEffect(() => {
    if (!menuOpen) return;
    function onKey(e) { if (e.key === "Escape") setMenuOpen(false); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [menuOpen]);

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
    label = "LOADING";
    cls = "health-warn";
  } else if (dhanMode === "simulated") {
    label = "DEMO";
    cls = "health-poll";
  } else if (dhanMode !== "live") {
    label = "FEED DOWN";
    cls = "health-down";
  } else if (!marketOpen) {
    label = "MARKET CLOSED";
    cls = "health-poll";
    extra = "";
  } else if (tickAge !== null && tickAge > 30) {
    label = "STALE";
    cls = "health-warn";
    extra = `${tickAge}s`;
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
        `Token expires in: ${tokenSecs ? Math.floor(tokenSecs/3600)+"h "+Math.floor((tokenSecs%3600)/60)+"m" : "—"}`,
        `Last tick: ${tickAge === null ? "never" : tickAge + "s ago"}`,
      ].join("\n")
    : "Connecting...";

  const go = (key) => { onNavigate(key); setMenuOpen(false); };

  return (
    <div className="header">
      <div className="header-left">
        <button className="nav-hamburger" onClick={() => setMenuOpen(true)} aria-label="Menu">☰</button>
        <div className="brand">
          <img src="/favicon.svg" className="brand-logo" alt="Arbi" width="26" height="26" />
          <span className="accent">Arbi</span>
          <span>Dash</span>
        </div>
        <nav className="nav-tabs">
          {NAV_ITEMS.map((it) => (
            <button
              key={it.key}
              className={`nav-tab ${page === it.key ? "active" : ""}${it.key === "signals" ? " nav-tab-signals" : ""}`}
              onClick={() => onNavigate(it.key)}
            >
              {it.label}
              {counts[it.key] != null && <span className="nav-count">{counts[it.key]}</span>}
            </button>
          ))}
        </nav>
      </div>
      <div className="header-right">
        <span className={`health-pill ${cls}`} title={tooltip}>
          <span className="health-dot" />
          <span className="health-label">{label}</span>
          {extra && <span className="health-meta">{extra}</span>}
        </span>
        <button className="theme-toggle hide-mobile" onClick={onToggleTheme} title="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <span className="username-chip hide-mobile">{user || "User"}</span>
        <button className="btn btn-secondary hide-mobile" onClick={onLogout}>Logout</button>
      </div>

      {/* Mobile slide-in navigation drawer */}
      {menuOpen && (
        <>
          <div className="nav-drawer-overlay" onClick={() => setMenuOpen(false)} />
          <nav className="nav-drawer">
            <div className="nav-drawer-head">
              <span className="brand"><span className="accent">Arbi</span> <span>Dash</span></span>
              <button className="nav-drawer-x" onClick={() => setMenuOpen(false)} aria-label="Close">×</button>
            </div>
            <div className="nav-drawer-list">
              {NAV_ITEMS.map((it) => (
                <button
                  key={it.key}
                  className={`nav-drawer-item ${page === it.key ? "active" : ""}`}
                  onClick={() => go(it.key)}
                >
                  <span>{it.label}</span>
                  {counts[it.key] != null && <span className="nav-drawer-count">{counts[it.key]}</span>}
                </button>
              ))}
            </div>
            <div className="nav-drawer-foot">
              <span className="username-chip">{user || "User"}</span>
              <button className="theme-toggle" onClick={onToggleTheme} title="Toggle theme">
                {theme === "dark" ? "☀" : "☾"}
              </button>
              <button className="btn btn-secondary" onClick={() => { setMenuOpen(false); onLogout(); }}>Logout</button>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
