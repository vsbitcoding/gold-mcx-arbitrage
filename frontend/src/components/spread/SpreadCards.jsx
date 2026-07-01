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

/**
 * Card view of cross / calendar pairs (WATCH-ONLY). For cross pairs, a signaled
 * row gets a colored tint + a ⚡ icon at the end — click it for the popup detail.
 */
export default function SpreadCards({ groups }) {
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
            String(a.big_expiry || a.expiry_label || "").localeCompare(
              String(b.big_expiry || b.expiry_label || "")
            )
          );
          const isSilver = String(g.label || "").toUpperCase().includes("SILVER");
          const hasSig = rows.some((r) => r.signal);
          return (
            <div className={`sc-card ${isSilver ? "sc-silver" : "sc-gold"}${hasSig ? " sc-card-signal" : ""}`} key={g.label}>
              <div className="sc-card-head">
                <span className="sc-pair">{g.label}</span>
                <span className="sc-count">{rows.length} exp</span>
              </div>
              <div className="sc-row sc-colhead">
                <span>Expiry</span>
                <span className="sc-c">▼ Dec</span>
                <span className="sc-c">▲ Inc</span>
                <span className="sc-c">{isCalendar ? "%" : ""}</span>
              </div>
              {rows.map((row, i) => (
                <div className={`sc-row${row.signal ? ` sc-rowsig sc-rowsig-${row.signal.direction}` : ""}`} key={row.name}>
                  <span className="sc-exp">
                    <span className="sc-exp-txt">{isCalendar ? fmtCalExpiry(row.expiry_label) : (row.expiry_label || "—")}</span>
                    {i === 0 && <span className="sc-front" title="Front month">★</span>}
                  </span>
                  <span className="sc-dec">{fmtSpread(row.decrease_spread)}{isCalendar && calRaw(row.decrease_spread, row.small)}</span>
                  <span className="sc-inc">{fmtSpread(row.increase_spread)}{isCalendar && calRaw(row.increase_spread, row.small)}</span>
                  {isCalendar ? (
                    <span className={`sc-pct ${(calcPct(row.decrease_spread, row.small_ask, row.small) ?? 0) >= 0 ? "pos" : "neg"}`}>
                      {fmtPct(calcPct(row.decrease_spread, row.small_ask, row.small)) ?? "—"}
                    </span>
                  ) : (
                    <span className="sc-iconcell">
                      {row.signal && (
                        <button
                          className={`sc-sigbtn sc-sigbtn-${row.signal.direction}`}
                          title="View signal details"
                          onClick={() => setSelectedName(row.name)}
                        >
                          ⚡
                        </button>
                      )}
                    </span>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </div>
      {selectedRow && <SignalModal row={selectedRow} onClose={() => setSelectedName(null)} />}
    </>
  );
}
