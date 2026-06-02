import React from "react";

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
}) {
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
  return (
    <div className="header">
      <div className="header-left">
        <div className="brand">
          <span className="accent">Arbi</span>
          <span>Dash</span>
        </div>
        <nav className="nav-tabs">
          <button
            className={`nav-tab ${page === "dashboard" ? "active" : ""}`}
            onClick={() => onNavigate("dashboard")}
          >
            Dashboard
          </button>
          <button
            className={`nav-tab ${page === "activity" ? "active" : ""}`}
            onClick={() => onNavigate("activity")}
          >
            Activity
          </button>
          <button
            className={`nav-tab ${page === "calculator" ? "active" : ""}`}
            onClick={() => onNavigate("calculator")}
          >
            Calculator
          </button>
          <button
            className={`nav-tab ${page === "options" ? "active" : ""}`}
            onClick={() => onNavigate("options")}
          >
            Nifty / Sensex
          </button>
          <button
            className={`nav-tab ${page === "metals" ? "active" : ""}`}
            onClick={() => onNavigate("metals")}
          >
            Metal
          </button>
          <button
            className={`nav-tab ${page === "settings" ? "active" : ""}`}
            onClick={() => onNavigate("settings")}
          >
            Settings
          </button>
        </nav>
      </div>
      <div className="header-right">
        <span className={`health-pill ${cls}`} title={tooltip}>
          <span className="health-dot" />
          <span className="health-label">{label}</span>
          {extra && <span className="health-meta">{extra}</span>}
        </span>
        <button className="density-toggle" onClick={onToggleDensity} title="Toggle table density (Ctrl+Shift+D)">
          <span className="icon">{density === "compact" ? "⊟" : "▤"}</span>
          {density === "compact" ? "Compact" : "Comfort"}
        </button>
        <button className="theme-toggle" onClick={onToggleTheme} title="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <span className="username-chip">{user || "User"}</span>
        <button className="btn btn-secondary" onClick={onLogout}>Logout</button>
      </div>
    </div>
  );
}
