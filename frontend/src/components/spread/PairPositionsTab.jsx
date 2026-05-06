import React, { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { fmtDateTime, fmtNum, fmtPnl } from "../../utils/format.js";
import { PER_PAGE } from "./constants.js";

export default function PairPositionsTab({ pairName }) {
  const [data, setData] = useState({ positions: [], summaries: [] });
  const [page, setPage] = useState(1);

  useEffect(() => {
    let alive = true;
    async function load() {
      const r = await api.positions(pairName).catch(() => null);
      if (alive && r) setData(r);
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [pairName]);

  const total = data.positions.length;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PER_PAGE;
  const slice = data.positions.slice(start, start + PER_PAGE);

  return (
    <div className="modal-tab-pane">
      {data.summaries.length > 0 && (
        <div className="summary-block">
          <div className="summary-title">Aggregate <span className="summary-sub">(weighted by gram)</span></div>
          <div className="info-table-wrap">
            <table className="info-table">
              <thead>
                <tr>
                  <th>Mode</th><th>Trades</th><th>Total Weight</th><th>Avg Entry</th><th>Cover</th><th>Live PnL</th>
                </tr>
              </thead>
              <tbody>
                {data.summaries.map((s) => (
                  <tr key={s.mode}>
                    <td><span className={`badge ${s.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{s.mode}</span></td>
                    <td className="num">{s.count}</td>
                    <td className="num"><strong>{s.total_weight_grams}</strong> g</td>
                    <td className="num">{fmtNum(s.avg_entry_spread)}</td>
                    <td className="num">{fmtNum(s.cover_spread)}</td>
                    <td className={`num ${s.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}`}>{fmtPnl(s.live_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {total === 0 ? (
        <div className="empty-state">No active positions for this pair.</div>
      ) : (
        <>
          <div className="info-table-wrap">
            <table className="info-table">
              <thead>
                <tr>
                  <th>Mode</th><th>Entry</th><th>Cover</th><th>Lots (B/S)</th><th>Weight</th><th>Opened At</th><th>Live PnL</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((p) => (
                  <tr key={p.id}>
                    <td><span className={`badge ${p.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{p.mode}</span></td>
                    <td className="num">{fmtNum(p.entry_spread)}</td>
                    <td className="num">{fmtNum(p.cover_spread)}</td>
                    <td className="num">{p.big_lots}/{p.small_lots}</td>
                    <td className="num"><strong>{p.weight_grams}</strong> g</td>
                    <td className="num time-cell">{fmtDateTime(p.entry_time)}</td>
                    <td className={`num ${p.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}`}>{fmtPnl(p.live_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="ladder-pager">
              <span>Page {safePage} / {totalPages} · {total} total</span>
              <div className="pager-buttons">
                <button onClick={() => setPage(1)} disabled={safePage === 1}>«</button>
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage === 1}>‹</button>
                <span className="pager-cur">{safePage}</span>
                <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}>›</button>
                <button onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
