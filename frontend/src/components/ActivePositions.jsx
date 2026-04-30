import React from "react";
import { api } from "../api/client.js";

function fmtTime(t) {
  return new Date(t).toLocaleTimeString("en-IN", { hour12: false });
}

export default function ActivePositions({ rows, onChange }) {
  async function close(id) {
    if (!confirm("Square off this position?")) return;
    try {
      await api.closePosition(id);
      onChange();
    } catch (e) {
      alert(e.message);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Active Positions <span style={{ color: "var(--text-muted)", fontWeight: 500, marginLeft: 6 }}>({rows.length})</span></h2>
      </div>
      <div className="table-wrap">
        {rows.length === 0 ? (
          <div className="empty">No active positions.</div>
        ) : (
          <table>
            <thead className="grouped">
              <tr className="cols">
                <th>Pair</th>
                <th>Mode</th>
                <th>Entry Spread</th>
                <th>Lots (Big / Small)</th>
                <th>Big Px</th>
                <th>Small Px</th>
                <th>Time</th>
                <th>Live PnL</th>
                <th style={{ textAlign: "right" }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="pair-name">{p.pair_name}</td>
                  <td>
                    <span className={`status ${p.mode === "decrease" ? "in_position" : "armed"}`}>
                      <span className="blip" />
                      {p.mode === "decrease" ? "Decrease" : "Increase"}
                    </span>
                  </td>
                  <td className="spread">{p.entry_spread}</td>
                  <td>{p.big_lots} / {p.small_lots}</td>
                  <td className="spread">{p.big_price}</td>
                  <td className="spread">{p.small_price}</td>
                  <td style={{ color: "var(--text-muted)" }}>{fmtTime(p.entry_time)}</td>
                  <td className={p.live_pnl >= 0 ? "pnl-pos" : "pnl-neg"}>
                    {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="btn-sm danger" onClick={() => close(p.id)}>Square Off</button>
                    </div>
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
