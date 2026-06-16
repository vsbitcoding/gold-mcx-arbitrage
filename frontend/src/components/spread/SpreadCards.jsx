import React from "react";
import { fmtSpread } from "../../utils/format.js";

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

// Client-specified card order: all gold pairs (Petal → Guinea → Ten → Mini/Gold last),
// then silver (smallest unit first).
const CROSS_ORDER = [
  "PETAL / GUINEA", "PETAL / TEN", "PETAL / MINI",
  "GUINEA / TEN", "GUINEA / MINI", "TEN / MINI", "MINI / GOLD",
  "SILVER 100 / SILVER MIC", "SILVER 100 / SILVER MINI",
  "SILVER MIC / SILVER MINI", "SILVER MINI / SILVER",
];
// Calendar (single-instrument groups): gold by size, then silver by size.
const CAL_ORDER = ["PETAL", "GUINEA", "TEN", "MINI", "GOLD", "SILVER 100", "SILVER MIC", "SILVER MINI", "SILVER"];

function rankOf(label, order) {
  const i = order.indexOf(String(label || "").toUpperCase().trim());
  return i === -1 ? 999 : i;
}

// Calendar expiry: show near month first, far second (client) e.g. "5 Jun 2026 − 3 Jul 2026".
function fmtCalExpiry(label) {
  const clean = String(label || "—").replace(/\b(Far|Near)\s+/g, "");
  const parts = clean.split(/\s[−–-]\s/);
  if (parts.length === 2) return `${parts[1].trim()} − ${parts[0].trim()}`;
  return clean;
}

/**
 * Card view of cross / calendar pairs (WATCH-ONLY). One card per pair-group, all
 * expiries shown — spreads (and calendar %) only. No trade actions.
 */
export default function SpreadCards({ groups }) {
  if (!groups.length) {
    return <div className="empty-state">No pairs match.</div>;
  }

  const isCalendar = groups[0]?.rows?.[0]?.type === "calendar";
  // Client-specified card order (gold family first, then silver).
  const order = isCalendar ? CAL_ORDER : CROSS_ORDER;
  const ordered = [...groups].sort((a, b) => rankOf(a.label, order) - rankOf(b.label, order));

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
              {isCalendar && <span className="sc-c">%</span>}
            </div>
            {rows.map((row, i) => (
              <div className={`sc-row${row.signal ? " sc-has-signal" : ""}`} key={row.name}>
                <span className="sc-exp">
                  <span className="sc-exp-txt">{isCalendar ? fmtCalExpiry(row.expiry_label) : (row.expiry_label || "—")}</span>
                  {i === 0 && <span className="sc-front" title="Front month">★</span>}
                  {row.signal && (
                    <span
                      className={`sc-sig sc-sig-${row.signal.direction}`}
                      title={`Signal: spread likely to ${row.signal.direction === "narrow" ? "NARROW (fall)" : "WIDEN (rise)"} → target ${row.signal.target}${row.signal.probability != null ? ` · ${row.signal.probability}% chance` : ""}`}
                    >
                      ⚡{row.signal.direction === "narrow" ? "▼" : "▲"}{row.signal.probability != null ? `${row.signal.probability}%` : Math.round(row.signal.target).toLocaleString("en-IN")}
                    </span>
                  )}
                </span>
                <span className="sc-dec">{fmtSpread(row.decrease_spread)}</span>
                <span className="sc-inc">{fmtSpread(row.increase_spread)}</span>
                {isCalendar && (
                  <span className={`sc-pct ${(calcPct(row.decrease_spread, row.small_ask, row.small) ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {fmtPct(calcPct(row.decrease_spread, row.small_ask, row.small)) ?? "—"}
                  </span>
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
