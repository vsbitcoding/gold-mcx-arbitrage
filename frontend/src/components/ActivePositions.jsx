import React from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { useConfirm } from "./ConfirmDialog.jsx";

function fmtTime(t) {
  return new Date(t).toLocaleTimeString("en-IN", { hour12: false });
}
function ageOf(t) {
  const ms = Date.now() - new Date(t).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "<1m";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
function fmtPx(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(2);
}
function delta(entry, live) {
  if (entry === null || live === null || entry === undefined || live === undefined) return null;
  return Number(live) - Number(entry);
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : ""; }

function LegInline({ action, instrument, lots, entryPx, livePx }) {
  const d = delta(entryPx, livePx);
  const cls = action === "BUY" ? "leg-inline buy" : "leg-inline sell";
  return (
    <div className={cls}>
      <div className="leg-inline-head">
        <span className="leg-action">{action}</span>
        <span className="leg-instrument">{cap(instrument)}</span>
        <span className="leg-lots">{lots} lot{lots > 1 ? "s" : ""}</span>
      </div>
      <div className="leg-inline-prices">
        <span className="leg-price">{fmtPx(entryPx)}</span>
        <span className="leg-arrow">→</span>
        <span className="leg-price">{fmtPx(livePx)}</span>
        {d !== null && (
          <span className={`leg-delta-mini ${d >= 0 ? "pos" : "neg"}`}>
            {d >= 0 ? "+" : ""}{d.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  );
}

export default function ActivePositions({ rows, onChange }) {
  const toast = useToast();
  const confirm = useConfirm();

  async function close(p) {
    const ok = await confirm({
      title: "Square off this position?",
      message: `Close ${p.mode} trade on ${p.pair_name}? Live PnL: ${p.live_pnl >= 0 ? "+" : ""}${p.live_pnl}`,
      confirmText: "Square Off",
      danger: true,
    });
    if (!ok) return;
    try {
      const r = await api.closePosition(p.id);
      toast.success(`${p.pair_name} closed. PnL ${r.pnl >= 0 ? "+" : ""}${r.pnl}`);
      onChange();
    } catch (e) {
      toast.error(e.message);
    }
  }

  const totalPnl = rows.reduce((s, p) => s + (p.live_pnl || 0), 0);
  const totalWeight = rows.reduce((s, p) => s + (p.weight_grams || 0), 0);

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>
          Active Positions
          <span style={{ color: "var(--text-muted)", fontWeight: 500, marginLeft: 6 }}>({rows.length})</span>
          {rows.length > 0 && (
            <>
              <span style={{ marginLeft: 14, fontSize: 13, fontWeight: 600 }} className={totalPnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                Live PnL: {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}
              </span>
              <span style={{ marginLeft: 14, fontSize: 13, color: "var(--text-muted)" }}>
                Total Weight: {totalWeight}g
              </span>
            </>
          )}
        </h2>
      </div>
      <div className="table-container">
        {rows.length === 0 ? (
          <div className="empty-state">No active positions.</div>
        ) : (
          <table className="positions-table">
            <thead>
              <tr>
                <th>Pair</th>
                <th>Mode</th>
                <th>Big Leg</th>
                <th>Small Leg</th>
                <th>Entry / Cover</th>
                <th>Move</th>
                <th>Weight</th>
                <th>Opened</th>
                <th>Live PnL</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const move = p.cover_spread !== null && p.entry_spread !== null
                  ? Number(p.cover_spread) - Number(p.entry_spread)
                  : null;
                const moveCls = move === null ? "" : (move >= 0 ? "pnl-positive" : "pnl-negative");
                return (
                  <tr key={p.id}>
                    <td className="pair-name">{p.pair_name}</td>
                    <td>
                      <span className={`badge ${p.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>
                        {cap(p.mode)}
                      </span>
                    </td>
                    <td>
                      <LegInline
                        action={p.big_action}
                        instrument={p.big_instrument}
                        lots={p.big_lots}
                        entryPx={p.big_entry_price}
                        livePx={p.big_live_price}
                      />
                    </td>
                    <td>
                      <LegInline
                        action={p.small_action}
                        instrument={p.small_instrument}
                        lots={p.small_lots}
                        entryPx={p.small_entry_price}
                        livePx={p.small_live_price}
                      />
                    </td>
                    <td className="spread-num">
                      <div className="stack-cell">
                        <span>{Number(p.entry_spread).toFixed(2)}</span>
                        <span className="stack-arrow">→</span>
                        <span>{p.cover_spread === null ? "—" : Number(p.cover_spread).toFixed(2)}</span>
                      </div>
                    </td>
                    <td className={`spread-num ${moveCls}`}>
                      {move === null ? "—" : (move >= 0 ? "+" : "") + move.toFixed(2)}
                    </td>
                    <td>{p.weight_grams}g</td>
                    <td style={{ color: "var(--text-muted)", fontSize: 11 }}>
                      <div>{fmtTime(p.entry_time)}</div>
                      <div style={{ fontSize: 10 }}>{ageOf(p.entry_time)} ago</div>
                    </td>
                    <td className={p.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                      {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                    </td>
                    <td>
                      <button className="btn btn-danger btn-sm" onClick={() => close(p)}>Square Off</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
