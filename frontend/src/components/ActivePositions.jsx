import React from "react";
import { api } from "../api/client.js";

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
      <h2>Active Positions ({rows.length})</h2>
      {rows.length === 0 ? (
        <div className="empty">No active positions.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Pair</th>
              <th>Mode</th>
              <th>Entry Spread</th>
              <th>Lots (Big / Small)</th>
              <th>Big Px</th>
              <th>Small Px</th>
              <th>Live PnL</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td><strong>{p.pair_name}</strong></td>
                <td style={{ textTransform: "capitalize" }}>{p.mode}</td>
                <td className="spread-val">{p.entry_spread}</td>
                <td>{p.big_lots} / {p.small_lots}</td>
                <td>{p.big_price}</td>
                <td>{p.small_price}</td>
                <td className={p.live_pnl >= 0 ? "pnl-pos" : "pnl-neg"}>
                  {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                </td>
                <td>
                  <button className="btn close-btn" onClick={() => close(p.id)}>
                    Square Off
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
