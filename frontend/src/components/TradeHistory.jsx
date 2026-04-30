import React, { useMemo, useState } from "react";

function fmt(d) {
  return new Date(d).toLocaleString("en-IN", { hour12: false });
}

export default function TradeHistory({ rows }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const PER = 10;

  const totals = useMemo(() => {
    const wins = rows.filter((r) => r.pnl > 0);
    const losses = rows.filter((r) => r.pnl <= 0);
    const net = rows.reduce((s, r) => s + (r.pnl || 0), 0);
    return { net, wins: wins.length, losses: losses.length };
  }, [rows]);

  const filtered = rows.filter((r) => {
    if (search && !r.pair_name.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "win") return r.pnl > 0;
    if (filter === "loss") return r.pnl <= 0;
    return true;
  });
  const start = (page - 1) * PER;
  const slice = filtered.slice(start, start + PER);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PER));

  return (
    <div className="card">
      <div className="card-head">
        <h2>
          Trade History <span style={{ color: "var(--text-muted)", fontWeight: 500, marginLeft: 6 }}>({rows.length})</span>
          <span style={{ marginLeft: 14, fontSize: 13, fontWeight: 500 }} className={totals.net >= 0 ? "pnl-pos" : "pnl-neg"}>
            Net: {totals.net >= 0 ? "+" : ""}{totals.net.toFixed(2)}
          </span>
        </h2>
        <div className="toolbar">
          <input className="search" placeholder="Search pair..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <button className={`pill ${filter === "all" ? "active" : ""}`} onClick={() => { setFilter("all"); setPage(1); }}>
            All <span className="count">{rows.length}</span>
          </button>
          <button className={`pill ${filter === "win" ? "active" : ""}`} onClick={() => { setFilter("win"); setPage(1); }}>
            Wins <span className="count">{totals.wins}</span>
          </button>
          <button className={`pill ${filter === "loss" ? "active" : ""}`} onClick={() => { setFilter("loss"); setPage(1); }}>
            Losses <span className="count">{totals.losses}</span>
          </button>
        </div>
      </div>
      <div className="table-wrap">
        {filtered.length === 0 ? (
          <div className="empty">No trades match the filter.</div>
        ) : (
          <table>
            <thead className="grouped">
              <tr className="cols">
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
              {slice.map((r) => (
                <tr key={r.id}>
                  <td style={{ color: "var(--text-muted)" }}>{fmt(r.entry_time)}</td>
                  <td style={{ color: "var(--text-muted)" }}>{fmt(r.exit_time)}</td>
                  <td className="pair-name">{r.pair_name}</td>
                  <td style={{ textTransform: "capitalize" }}>{r.mode}</td>
                  <td className="spread">{r.entry_spread}</td>
                  <td className="spread">{r.exit_spread}</td>
                  <td>{r.big_lots}/{r.small_lots}</td>
                  <td style={{ textTransform: "capitalize", color: "var(--text-muted)" }}>{r.closed_by}</td>
                  <td className={r.pnl >= 0 ? "pnl-pos" : "pnl-neg"}>
                    {r.pnl >= 0 ? "+" : ""}{r.pnl}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {filtered.length > 0 && (
        <div className="foot">
          <div>Showing {start + 1}-{Math.min(start + PER, filtered.length)} of {filtered.length}</div>
          <div className="right">
            <button onClick={() => setPage(1)} disabled={page === 1}>«</button>
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
            <button className="active">{page}</button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>›</button>
            <button onClick={() => setPage(totalPages)} disabled={page === totalPages}>»</button>
          </div>
        </div>
      )}
    </div>
  );
}
