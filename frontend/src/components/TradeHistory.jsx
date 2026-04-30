import React from "react";

function fmt(d) {
  return new Date(d).toLocaleString("en-IN", { hour12: false });
}

export default function TradeHistory({ rows }) {
  const total = rows.reduce((sum, r) => sum + (r.pnl || 0), 0);
  return (
    <div className="card">
      <h2>
        <span>Trade History ({rows.length})</span>
        <span className={total >= 0 ? "pnl-pos" : "pnl-neg"}>
          Net: {total >= 0 ? "+" : ""}{total.toFixed(2)}
        </span>
      </h2>
      {rows.length === 0 ? (
        <div className="empty">No trades yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Entry Time</th>
              <th>Exit Time</th>
              <th>Pair</th>
              <th>Mode</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Lots</th>
              <th>Closed By</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{fmt(r.entry_time)}</td>
                <td>{fmt(r.exit_time)}</td>
                <td><strong>{r.pair_name}</strong></td>
                <td style={{ textTransform: "capitalize" }}>{r.mode}</td>
                <td className="spread-val">{r.entry_spread}</td>
                <td className="spread-val">{r.exit_spread}</td>
                <td>{r.big_lots}/{r.small_lots}</td>
                <td style={{ textTransform: "capitalize" }}>{r.closed_by}</td>
                <td className={r.pnl >= 0 ? "pnl-pos" : "pnl-neg"}>
                  {r.pnl >= 0 ? "+" : ""}{r.pnl}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
