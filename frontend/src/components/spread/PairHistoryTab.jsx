import React, { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { useToast } from "../Toast.jsx";
import { useConfirm } from "../ConfirmDialog.jsx";
import { fmtDateTime, fmtDuration, fmtNum, fmtPnl } from "../../utils/format.js";
import { PER_PAGE } from "./constants.js";

export default function PairHistoryTab({ pairName }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState({ trades: [], summaries: [] });
  const [page, setPage] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    async function load() {
      const r = await api.history(7, pairName).catch(() => null);
      if (alive && r) setData(r);
    }
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [pairName, reloadKey]);

  async function deleteRow(id, pnl) {
    const ok = await confirm({
      title: "Delete history record?",
      message: `Remove this trade record (PnL ${pnl >= 0 ? "+" : ""}${pnl})? This cannot be undone.`,
      confirmText: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteHistory(id);
      toast.success("Record deleted");
      setReloadKey((k) => k + 1);
    } catch (e) { toast.error(e.message); }
  }

  const total = data.trades.length;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PER_PAGE;
  const slice = data.trades.slice(start, start + PER_PAGE);

  return (
    <div className="modal-tab-pane">
      {data.summaries.length > 0 && (
        <div className="summary-block">
          <div className="summary-title">Aggregate <span className="summary-sub">(weighted by gram)</span></div>
          <div className="info-table-wrap">
            <table className="info-table">
              <thead>
                <tr>
                  <th>Mode</th><th>Trades</th><th>Total Weight</th><th>Avg Entry</th><th>Avg Exit</th><th>Total PnL</th>
                </tr>
              </thead>
              <tbody>
                {data.summaries.map((s) => (
                  <tr key={s.mode}>
                    <td><span className={`badge ${s.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{s.mode}</span></td>
                    <td className="num">{s.count}</td>
                    <td className="num"><strong>{s.total_weight_grams}</strong> g</td>
                    <td className="num">{fmtNum(s.avg_entry_spread)}</td>
                    <td className="num">{fmtNum(s.avg_exit_spread)}</td>
                    <td className={`num ${s.total_pnl >= 0 ? "pnl-positive" : "pnl-negative"}`}>{fmtPnl(s.total_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {total === 0 ? (
        <div className="empty-state">No history for this pair.</div>
      ) : (
        <>
          <div className="info-table-wrap">
            <table className="info-table">
              <thead>
                <tr>
                  <th>Mode</th><th>Entry</th><th>Exit</th><th>Move</th><th>Weight</th><th>Duration</th><th>Closed At</th><th>PnL</th><th></th>
                </tr>
              </thead>
              <tbody>
                {slice.map((r) => {
                  const move = r.exit_spread - r.entry_spread;
                  return (
                    <tr key={r.id}>
                      <td><span className={`badge ${r.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{r.mode}</span></td>
                      <td className="num">{fmtNum(r.entry_spread)}</td>
                      <td className="num">{fmtNum(r.exit_spread)}</td>
                      <td className={`num ${move >= 0 ? "pnl-positive" : "pnl-negative"}`}>{fmtPnl(move)}</td>
                      <td className="num"><strong>{r.weight_grams}</strong> g</td>
                      <td className="num">{fmtDuration(r.duration_seconds)}</td>
                      <td className="num time-cell">{fmtDateTime(r.exit_time)}</td>
                      <td className={`num ${r.pnl >= 0 ? "pnl-positive" : "pnl-negative"}`}>{fmtPnl(r.pnl)}</td>
                      <td>
                        <button className="ldr-icon danger" onClick={() => deleteRow(r.id, r.pnl)} title="Delete record">×</button>
                      </td>
                    </tr>
                  );
                })}
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
