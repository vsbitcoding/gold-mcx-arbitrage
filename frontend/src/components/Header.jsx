import React from "react";

export default function Header({
  user,
  onPause,
  onLogout,
  theme,
  onToggleTheme,
  positionsCount,
  historyCount,
  onOpenPositions,
  onOpenHistory,
  feedStatus,
  wsState,
}) {
  // Combined health: worst of (browser↔server WS) and (server↔Dhan feed)
  const dhanMode = feedStatus?.mode;
  const tickAge = feedStatus?.last_tick_age_seconds;
  const tokenSecs = feedStatus?.token_expires_in_seconds;

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
        `Client: ${feedStatus.client_name || "—"}`,
        `Token expires in: ${extra || "—"}`,
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
          <button className="nav-tab" onClick={onOpenPositions}>
            Positions
            {positionsCount > 0 && <span className="nav-badge live">{positionsCount}</span>}
          </button>
          <button className="nav-tab" onClick={onOpenHistory}>
            History
            {historyCount > 0 && <span className="nav-badge">{historyCount}</span>}
          </button>
        </nav>
      </div>
      <div className="header-right">
        <span className={`health-pill ${cls}`} title={tooltip}>
          <span className="health-dot" />
          <span className="health-label">{label}</span>
          {extra && <span className="health-meta">{extra}</span>}
        </span>
        <button className="theme-toggle" onClick={onToggleTheme} title="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button className="btn btn-secondary" onClick={onPause}>Pause All</button>
        <span className="username-chip">{user || "User"}</span>
        <button className="btn btn-secondary" onClick={onLogout}>Logout</button>
      </div>
    </div>
  );
}
