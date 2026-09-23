import React, { useState } from "react";
import { fmtSpread } from "../../utils/format.js";
import SignalModal from "../SignalModal.jsx";

// Price multiplier per instrument (mirror of backend config.MULTIPLIERS).
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

// Client: on Calendar, also show the raw "simple minus" (spread ÷ multiplier) in
// brackets — only for Petal (×10), Guinea (×1.25) and Silver 100 (×100).
const RAW_INSTR = new Set(["petal", "guinea", "silver100"]);
function calRaw(spread, instrument) {
  if (spread == null || !RAW_INSTR.has(instrument)) return null;
  return <span className="sc-raw">({fmtSpread(spread / (MULT[instrument] ?? 1))})</span>;
}

const CROSS_ORDER = [
  "PETAL / GUINEA", "PETAL / TEN", "PETAL / MINI",
  "GUINEA / TEN", "GUINEA / MINI", "TEN / MINI", "MINI / GOLD",
  "SILVER 100 / SILVER MIC", "SILVER 100 / SILVER MINI",
  "SILVER MIC / SILVER MINI", "SILVER MINI / SILVER",
];
const CAL_ORDER = ["PETAL", "GUINEA", "TEN", "MINI", "GOLD", "SILVER 100", "SILVER MIC", "SILVER MINI", "SILVER"];

function rankOf(label, order) {
  const i = order.indexOf(String(label || "").toUpperCase().trim());
  return i === -1 ? 999 : i;
}
function fmtCalExpiry(label) {
  const clean = String(label || "—").replace(/\b(Far|Near)\s+/g, "");
  const parts = clean.split(/\s[−–-]\s/);
  if (parts.length === 2) return `${parts[1].trim()} − ${parts[0].trim()}`;
  return clean;
}
function frontExpiry(row) {
  // Live snapshots carry the ISO contract month in the pair name even when
  // big_expiry is absent. Calendar names start with the near contract.
  return String(row?.name || "").match(/@(\d{4}-\d{2}-\d{2})/)?.[1]
    || String(row?.big_expiry || "").slice(0, 10);
}

/**
 * Card view of cross / calendar pairs (WATCH-ONLY). For cross pairs, a signaled
 * row gets a colored tint + a ⚡ icon at the end — click it for the popup detail.
 */
export default function SpreadCards({ groups, onHistory }) {
  // Store only the row key, then re-resolve the live row each render so the
  // popup updates in real time as new snapshots poll in (not a frozen snapshot).
  const [selectedName, setSelectedName] = useState(null);

  if (!groups.length) {
    return <div className="empty-state">No pairs match.</div>;
  }

  const selectedRow = selectedName
    ? groups.flatMap((g) => g.rows).find((r) => r.name === selectedName && r.signal) || null
    : null;

  const isCalendar = groups[0]?.rows?.[0]?.type === "calendar";
  const order = isCalendar ? CAL_ORDER : CROSS_ORDER;
  const ordered = [...groups].sort((a, b) => rankOf(a.label, order) - rankOf(b.label, order));

  return (
    <>
      <div className={`spread-cards ${isCalendar ? "sc-cal" : ""}`}>
        {ordered.map((g) => {
          const rows = [...g.rows].sort((a, b) =>
            String(frontExpiry(a) || a.expiry_label || "").localeCompare(
              String(frontExpiry(b) || b.expiry_label || "")
            )
          );
          const isSilver = String(g.label || "").toUpperCase().includes("SILVER");
          const hasSig = rows.some((r) => r.signal);
          const frontRow = rows.reduce((front, row) => {
            const date = frontExpiry(row), current = frontExpiry(front);
            return date && (!current || date < current) ? row : front;
          }, rows[0]);
          return (
            <section className={`sc-card ${isSilver ? "sc-silver" : "sc-gold"}${hasSig ? " sc-card-signal" : ""}`} key={g.label} aria-label={`${g.label} spreads`}>
              <div className="sc-card-head">
                <h2 className="sc-pair">{g.label}</h2>
                <span className="sc-count">{rows.length} {rows.length === 1 ? "expiry" : "expiries"}</span>
              </div>
              <div role="table" aria-label={`${g.label} expiry spreads`}>
              <div className={`sc-row sc-colhead${onHistory ? " sc-hist" : ""}`} role="row">
                <span role="columnheader">{isCalendar ? "Expiry months" : "Expiry"}</span>
                <span role="columnheader" className="sc-c">Decrease</span>
                <span role="columnheader" className="sc-c">Increase</span>
                <span role="columnheader" className="sc-c" title={isCalendar ? "Decrease spread as a percentage of the near price" : "Active signal"}>{isCalendar ? "%" : "Alert"}</span>
                {onHistory && <span role="columnheader" className="sc-c sc-histhead">History</span>}
              </div>
              {rows.map((row) => (
                <div role="row" className={`sc-row${onHistory ? " sc-hist" : ""}${row.signal ? ` sc-rowsig sc-rowsig-${row.signal.direction}` : ""}`} key={row.name}>
                  <span role="cell" className="sc-exp">
                    <span className="sc-exp-txt">{isCalendar ? fmtCalExpiry(row.expiry_label) : (row.expiry_label || "—")}</span>
                    {row === frontRow && <span className="sc-front" title="Front month" aria-label="Front month">★</span>}
                  </span>
                  <span role="cell" className="sc-dec">{fmtSpread(row.decrease_spread)}{isCalendar && calRaw(row.decrease_spread, row.small)}</span>
                  <span role="cell" className="sc-inc">{fmtSpread(row.increase_spread)}{isCalendar && calRaw(row.increase_spread, row.small)}</span>
                  {isCalendar ? (
                    <span role="cell" className={`sc-pct ${(calcPct(row.decrease_spread, row.small_ask, row.small) ?? 0) >= 0 ? "pos" : "neg"}`}>
                      {fmtPct(calcPct(row.decrease_spread, row.small_ask, row.small)) ?? "—"}
                    </span>
                  ) : (
                    <span role="cell" className="sc-iconcell">
                      {row.signal && (
                        <button
                          type="button"
                          className={`sc-sigbtn sc-sigbtn-${row.signal.direction}`}
                          title="View signal details"
                          aria-label={`View ${row.signal.direction} signal for ${g.label}, ${row.expiry_label}`}
                          onClick={() => setSelectedName(row.name)}
                        >
                          ⚡
                        </button>
                      )}
                      {!row.signal && <span className="sc-no-signal" aria-label="No active signal">—</span>}
                    </span>
                  )}
                  {onHistory && (
                    <span role="cell" className="sc-histcell">
                      <button type="button" className="sc-histbtn"
                        title={`Day-by-day spread history of this ${isCalendar ? "pair of months" : "contract month"} only`}
                        aria-label={`View history for ${g.label}, ${row.expiry_label}`}
                        onClick={() => onHistory(row)}>
                        <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"><path d="M3 16h14M3 16V4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/><path d="M5 13l3.5-4.5 3 2.5L16 5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/><circle cx="16" cy="5" r="1.6" fill="currentColor"/></svg></button>
                    </span>
                  )}
                </div>
              ))}
              </div>
            </section>
          );
        })}
      </div>
      {selectedRow && <SignalModal row={selectedRow} onClose={() => setSelectedName(null)} />}
    </>
  );
}
