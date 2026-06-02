import React, { useEffect, useState } from "react";
import { fmtSpread } from "../../utils/format.js";
import { STATUS_LABEL } from "./constants.js";

// Price multiplier per instrument (mirror of backend config.MULTIPLIERS).
// % = spread ÷ (near-leg price × multiplier) × 100  — per client:
//   Petal ×10, Guinea ×1.25, Silver100 ×100 (its price is quoted ×100),
//   every other instrument ×1 = direct division.
const MULT = {
  petal: 10, guinea: 1.25, ten: 1, mini: 1, gold: 1,
  silver: 1, silverm: 1, silvermic: 1, silver100: 100,
};
function calcPct(spread, nearPrice, instrument) {
  if (spread == null || !nearPrice) return null;
  const m = MULT[instrument] ?? 1;
  return (spread / (nearPrice * m)) * 100;
}
function fmtPct(v) {
  if (v == null) return null;
  return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
}

/**
 * Card view of cross / calendar pairs. One card per pair-group, all expiries
 * shown (spreads only). A gear icon per expiry opens a small menu with
 * Manage / Positions / History (the existing modals).
 */
export default function SpreadCards({ groups, onManage, onPositions, onHistory }) {
  const [menuFor, setMenuFor] = useState(null); // row.name whose gear menu is open

  useEffect(() => {
    if (!menuFor) return;
    function onDoc(e) {
      if (!e.target.closest(".sc-gear-wrap")) setMenuFor(null);
    }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [menuFor]);

  if (!groups.length) {
    return <div className="empty-state">No pairs match.</div>;
  }

  // Show fuller cards first (6 expiries, then 5, …) so the grid looks even.
  const ordered = [...groups].sort((a, b) => b.rows.length - a.rows.length);
  // Calendar expiries are long ("31 Jul 2026 − 30 Jun 2026") → wider expiry column.
  const isCalendar = groups[0]?.rows?.[0]?.type === "calendar";

  return (
    <div className={`spread-cards ${isCalendar ? "sc-cal" : ""}`}>
      {ordered.map((g) => {
        // Front month first (chronological), regardless of any active sort.
        const rows = [...g.rows].sort((a, b) =>
          String(a.big_expiry || a.expiry_label || "").localeCompare(
            String(b.big_expiry || b.expiry_label || "")
          )
        );
        const isSilver = String(g.label || "").toUpperCase().includes("SILVER");
        return (
          <div className={`sc-card ${isSilver ? "sc-silver" : "sc-gold"}`} key={g.label}>
            <div className="sc-card-head">
              <span className="sc-pair">{g.label}</span>
              <span className="sc-count">{rows.length} exp</span>
            </div>
            <div className="sc-row sc-colhead">
              <span>Expiry</span>
              <span className="sc-c">▼ Dec</span>
              <span className="sc-c">▲ Inc</span>
              <span />
            </div>
            {rows.map((row, i) => (
              <div className={`sc-row status-${row.status}`} key={row.name}>
                <span className="sc-exp">
                  <span
                    className={`sc-dot sd-${row.status}`}
                    title={STATUS_LABEL[row.status] || row.status}
                  />
                  <span className="sc-exp-txt">{(row.expiry_label || "—").replace(/\b(Far|Near)\s+/g, "")}</span>
                  {i === 0 && <span className="sc-front" title="Front month">★</span>}
                  {row.open_positions_count > 0 && (
                    <span
                      className={`sc-open ${row.orphan_open_count > 0 ? "orphan" : ""}`}
                      title={`${row.open_positions_count} open trade(s)`}
                    >
                      {row.open_positions_count}
                    </span>
                  )}
                </span>
                <div className="sc-spread">
                  <span className="sc-dec">{fmtSpread(row.decrease_spread)}</span>
                  {isCalendar && calcPct(row.decrease_spread, row.small_ask, row.small) != null && (
                    <span className="sc-pct dec">{fmtPct(calcPct(row.decrease_spread, row.small_ask, row.small))}</span>
                  )}
                </div>
                <div className="sc-spread">
                  <span className="sc-inc">{fmtSpread(row.increase_spread)}</span>
                  {isCalendar && calcPct(row.increase_spread, row.small_bid, row.small) != null && (
                    <span className="sc-pct inc">{fmtPct(calcPct(row.increase_spread, row.small_bid, row.small))}</span>
                  )}
                </div>
                <span className="sc-gear-wrap">
                  <button
                    className="sc-gear"
                    title="Settings"
                    onClick={(e) => {
                      e.stopPropagation();
                      setMenuFor(menuFor === row.name ? null : row.name);
                    }}
                  >
                    ⚙
                  </button>
                  {menuFor === row.name && (
                    <div className="sc-menu">
                      <button onClick={() => { onManage(row.name); setMenuFor(null); }}>Manage</button>
                      <button onClick={() => { onPositions(row.name); setMenuFor(null); }}>Positions</button>
                      <button onClick={() => { onHistory(row.name); setMenuFor(null); }}>History</button>
                    </div>
                  )}
                </span>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
