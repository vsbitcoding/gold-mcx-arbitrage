import React from "react";

export default function Header({ user, mode, onPause, onLogout, theme, onToggleTheme }) {
  return (
    <div className="header">
      <div className="header-left">
        <div className="brand">
          <span className="accent">Arbi</span>
          <span>Dash</span>
          <span className="dot" title="Live" />
        </div>
      </div>
      <div className="header-right">
        <button className="theme-toggle" onClick={onToggleTheme} title="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button className="btn-outline" onClick={onPause}>Pause All</button>
        <span className="user-chip">{user || "User"}</span>
        <button className="btn-outline" onClick={onLogout}>Logout</button>
      </div>
    </div>
  );
}
