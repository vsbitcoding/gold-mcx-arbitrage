import React from "react";
import { fmtPnl, fmtNum } from "../utils/format.js";

export default function StatCards({ pairs, positions, history, account }) {
  const armedCount = pairs.filter((p) => p.status === "armed").length;
  const inPositionCount = positions.length;
  const todayPnl = history.reduce((s, r) => s + (r.pnl || 0), 0);
  const livePnl = positions.reduce((s, p) => s + (p.live_pnl || 0), 0);
  const totalOpenWeight = positions.reduce((s, p) => s + (p.weight_grams || 0), 0);

  const capConfigured = account && account.cap > 0 && account.margin_per_fire > 0;
  const usagePct = account?.usage_percent;
  const fillCls = usagePct == null ? "low" : usagePct >= 100 ? "full" : usagePct >= 80 ? "high" : usagePct >= 50 ? "mid" : "low";

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
        <div className="stat-label">
          Live PnL
          {capConfigured && (
            <span className={`margin-chip ${fillCls === "full" ? "danger" : fillCls === "high" ? "warn" : ""}`}
              title={`Margin used: ₹${fmtNum(account.used)} of ₹${fmtNum(account.cap)} (${fmtNum(usagePct)}% of cap)`}>
              {fmtNum(usagePct)}% used
            </span>
          )}
        </div>
        <div className={`stat-value ${livePnl >= 0 ? "pos" : "neg"}`}>{fmtPnl(livePnl)}</div>
        {capConfigured && (
          <div className="margin-bar">
            <div className={`fill ${fillCls}`} style={{ width: `${Math.min(100, usagePct)}%` }} />
          </div>
        )}
      </div>
    </div>
  );
}
