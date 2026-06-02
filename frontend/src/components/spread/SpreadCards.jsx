import React, { useEffect, useState } from "react";
import { fmtSpread } from "../../utils/format.js";
import { STATUS_LABEL } from "./constants.js";

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

  return (
    <div className="spread-cards">
      {groups.map((g) => {
        // Front month first (chronological), regardless of any active sort.
        const rows = [...g.rows].sort((a, b) =>
          String(a.big_expiry || a.expiry_label || "").localeCompare(
            String(b.big_expiry || b.expiry_label || "")
          )
        );
        return (
          <div className="sc-card" key={g.label}>
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
                  <span className="sc-exp-txt">{row.expiry_label || "—"}</span>
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
                <span className="sc-dec">{fmtSpread(row.decrease_spread)}</span>
                <span className="sc-inc">{fmtSpread(row.increase_spread)}</span>
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
