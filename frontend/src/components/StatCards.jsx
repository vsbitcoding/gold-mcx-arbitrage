import React from "react";

function fmt(n) {
  if (n === null || n === undefined) return "—";
  const sign = n >= 0 ? "+" : "";
  return sign + Number(n).toFixed(2);
}

export default function StatCards({ pairs, positions, history }) {
  const armedCount = pairs.filter((p) => p.status === "armed").length;
  const inPositionCount = positions.length;
  const todayPnl = history.reduce((s, r) => s + (r.pnl || 0), 0);
  const livePnl = positions.reduce((s, p) => s + (p.live_pnl || 0), 0);

  return (
    <div className="stats-grid">
      <div className="stat-card">
        <div className="stat-label">Armed Pairs</div>
        <div className="stat-value">{armedCount} / {pairs.length}</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">Open Positions</div>
        <div className="stat-value">{inPositionCount}</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">Net P&amp;L (30d)</div>
        <div className={`stat-value ${todayPnl >= 0 ? "pos" : "neg"}`}>{fmt(todayPnl)}</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">Live PnL</div>
        <div className={`stat-value ${livePnl >= 0 ? "pos" : "neg"}`}>{fmt(livePnl)}</div>
      </div>
    </div>
  );
}
