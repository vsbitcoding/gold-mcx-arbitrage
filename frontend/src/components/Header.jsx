import React from "react";
import FeedStatus from "./FeedStatus.jsx";

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
  const wsLabel = wsState === "live" ? "STREAMING" : wsState === "connecting" ? "CONNECTING" : "POLLING";
  const wsCls = wsState === "live" ? "ws-live" : wsState === "connecting" ? "ws-connecting" : "ws-poll";
  return (
    <div className="header">
      <div className="header-left">
        <div className="brand">
          <span className="accent">Arbi</span>
          <span>Dash</span>
          <span className="dot" title="Live" />
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
        <span className={`ws-pill ${wsCls}`} title={`Browser ↔ server: ${wsState}`}>
          <span className="ws-dot" />
          {wsLabel}
        </span>
        <FeedStatus status={feedStatus} />
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
