import React from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { useConfirm } from "./ConfirmDialog.jsx";

function fmtTime(t) {
  return new Date(t).toLocaleTimeString("en-IN", { hour12: false });
}

export default function ActivePositions({ rows, onChange }) {
  const toast = useToast();
  const confirm = useConfirm();

  async function close(p) {
    const ok = await confirm({
      title: "Square off position?",
      message: `Close the ${p.mode} trade on ${p.pair_name} (entry @ ${p.entry_spread})? PnL is currently ${p.live_pnl >= 0 ? "+" : ""}${p.live_pnl}.`,
      confirmText: "Square Off",
      danger: true,
    });
    if (!ok) return;
    try {
      const r = await api.closePosition(p.id);
      toast.success(`${p.pair_name} ${p.mode} closed. PnL ${r.pnl >= 0 ? "+" : ""}${r.pnl}`);
      onChange();
    } catch (e) {
      toast.error(e.message);
    }
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>Active Positions <span style={{ color: "var(--text-muted)", fontWeight: 500, marginLeft: 6 }}>({rows.length})</span></h2>
      </div>
      <div className="table-container">
        {rows.length === 0 ? (
          <div className="empty-state">No active positions.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th>Mode</th>
                <th>Entry Spread</th>
                <th>Lots (B / S)</th>
                <th>Big Px</th>
                <th>Small Px</th>
                <th>Time</th>
                <th>Live PnL</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="pair-name">{p.pair_name}</td>
                  <td>
                    <span className={`badge ${p.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>
                      {p.mode === "decrease" ? "Decrease" : "Increase"}
                    </span>
                  </td>
                  <td className="spread-num">{p.entry_spread}</td>
                  <td>{p.big_lots} / {p.small_lots}</td>
                  <td className="spread-num">{p.big_price}</td>
                  <td className="spread-num">{p.small_price}</td>
                  <td style={{ color: "var(--text-muted)" }}>{fmtTime(p.entry_time)}</td>
                  <td className={p.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                    {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm" onClick={() => close(p)}>Square Off</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
