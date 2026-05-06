import React from "react";
import { fmtPnl } from "../utils/format.js";

export default function StatCards({ pairs, positions, history }) {
  const armedCount = pairs.filter((p) => p.status === "armed").length;
  const inPositionCount = positions.length;
  const todayPnl = history.reduce((s, r) => s + (r.pnl || 0), 0);
  const livePnl = positions.reduce((s, p) => s + (p.live_pnl || 0), 0);
  const totalOpenWeight = positions.reduce((s, p) => s + (p.weight_grams || 0), 0);

  return (
    <div className="stats-grid">
      <div className="stat-card">
        <div className="stat-label">Armed Pairs</div>
        <div className="stat-value">{armedCount} / {pairs.length}</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">Open Positions</div>
        <div className="stat-value">{inPositionCount} <span className="stat-sub">· {totalOpenWeight}g</span></div>
      </div>
      <div className="stat-card">
        <div className="stat-label">Net PnL (7d)</div>
        <div className={`stat-value ${todayPnl >= 0 ? "pos" : "neg"}`}>{fmtPnl(todayPnl)}</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">Live PnL</div>
        <div className={`stat-value ${livePnl >= 0 ? "pos" : "neg"}`}>{fmtPnl(livePnl)}</div>
      </div>
    </div>
  );
}
