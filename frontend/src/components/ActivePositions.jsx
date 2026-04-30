import React, { useState } from "react";
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
  if (entry === null || live === null) return null;
  return Number(live) - Number(entry);
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : ""; }

function LegBlock({ leg, action, instrument, lots, entryPx, livePx }) {
  const d = delta(entryPx, livePx);
  const cls = action === "BUY" ? "leg-buy" : "leg-sell";
  return (
    <div className={`leg-block ${cls}`}>
      <div className="leg-head">
        <span className="leg-action">{action}</span>
        <span className="leg-instrument">{cap(instrument)}</span>
        <span className="leg-lots">{lots} lots</span>
      </div>
      <div className="leg-prices">
        <div>
          <span className="leg-label">Entry @</span>
          <span className="leg-price">{fmtPx(entryPx)}</span>
        </div>
        <div className="leg-arrow">→</div>
        <div>
          <span className="leg-label">Live @</span>
          <span className="leg-price">{fmtPx(livePx)}</span>
        </div>
        {d !== null && (
          <div className={`leg-delta ${d >= 0 ? "pos" : "neg"}`}>
            {d >= 0 ? "+" : ""}{d.toFixed(2)}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ActivePositions({ rows, onChange }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [expanded, setExpanded] = useState({});

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

  function toggle(id) {
    setExpanded((e) => ({ ...e, [id]: !e[id] }));
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
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Pair</th>
                <th>Mode</th>
                <th>Entry Spread</th>
                <th>Cover Spread</th>
                <th>Move</th>
                <th>Weight</th>
                <th>Opened</th>
                <th>Live PnL</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const isOpen = !!expanded[p.id];
                const move = p.cover_spread !== null && p.entry_spread !== null
                  ? Number(p.cover_spread) - Number(p.entry_spread)
                  : null;
                const moveCls = move === null ? "" : (move >= 0 ? "pnl-positive" : "pnl-negative");
                return (
                  <React.Fragment key={p.id}>
                    <tr className={isOpen ? "expanded" : ""}>
                      <td style={{ width: 30 }}>
                        <button className="row-toggle" onClick={() => toggle(p.id)} title="Show details">
                          <span className="caret">{isOpen ? "▾" : "▸"}</span>
                        </button>
                      </td>
                      <td className="pair-name">{p.pair_name}</td>
                      <td>
                        <span className={`badge ${p.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>
                          {p.mode === "decrease" ? "Decrease" : "Increase"}
                        </span>
                      </td>
                      <td className="spread-num">{Number(p.entry_spread).toFixed(2)}</td>
                      <td className="spread-num">{p.cover_spread === null ? "—" : Number(p.cover_spread).toFixed(2)}</td>
                      <td className={`spread-num ${moveCls}`}>
                        {move === null ? "—" : (move >= 0 ? "+" : "") + move.toFixed(2)}
                      </td>
                      <td>{p.weight_grams}g</td>
                      <td style={{ color: "var(--text-muted)" }}>
                        {fmtTime(p.entry_time)}<br/>
                        <span style={{ fontSize: 10 }}>{ageOf(p.entry_time)} ago</span>
                      </td>
                      <td className={p.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                        {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                      </td>
                      <td>
                        <button className="btn btn-danger btn-sm" onClick={() => close(p)}>Square Off</button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="position-detail-row">
                        <td colSpan={10}>
                          <div className="position-detail">
                            <LegBlock
                              action={p.big_action}
                              instrument={p.big_instrument}
                              lots={p.big_lots}
                              entryPx={p.big_entry_price}
                              livePx={p.big_live_price}
                            />
                            <LegBlock
                              action={p.small_action}
                              instrument={p.small_instrument}
                              lots={p.small_lots}
                              entryPx={p.small_entry_price}
                              livePx={p.small_live_price}
                            />
                            <div className="leg-block info">
                              <div className="leg-head">
                                <span className="leg-instrument">PnL Calculation</span>
                              </div>
                              <div className="leg-prices small">
                                <div>
                                  <span className="leg-label">{p.mode === "decrease" ? "Entry − Cover" : "Cover − Entry"}</span>
                                </div>
                                <div className="leg-arrow"></div>
                                <div>
                                  <span className="leg-price">
                                    {p.mode === "decrease"
                                      ? `${Number(p.entry_spread).toFixed(2)} − ${p.cover_spread === null ? "—" : Number(p.cover_spread).toFixed(2)}`
                                      : `${p.cover_spread === null ? "—" : Number(p.cover_spread).toFixed(2)} − ${Number(p.entry_spread).toFixed(2)}`}
                                  </span>
                                </div>
                                <div className="leg-arrow">×</div>
                                <div>
                                  <span className="leg-price">{p.big_lots} lots</span>
                                </div>
                                <div className="leg-arrow">=</div>
                                <div>
                                  <span className={`leg-price ${p.live_pnl >= 0 ? "pos" : "neg"}`}>
                                    {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
