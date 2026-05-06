import React, { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { useToast } from "../Toast.jsx";
import { useConfirm } from "../ConfirmDialog.jsx";
import { fmtDateTime, fmtNum, fmtPnl } from "../../utils/format.js";
import { PER_PAGE } from "./constants.js";

export default function PairPositionsTab({ pairName }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState({ positions: [], summaries: [] });
  const [page, setPage] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);
  const [sqMode, setSqMode] = useState("");
  const [sqWeight, setSqWeight] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      const r = await api.positions(pairName).catch(() => null);
      if (alive && r) setData(r);
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [pairName, reloadKey]);

  // Per-mode totals for the square-off panel
  const totalsByMode = data.positions.reduce((acc, p) => {
    const k = p.mode;
    if (!acc[k]) acc[k] = { count: 0, weight: 0 };
    acc[k].count += 1;
    acc[k].weight += p.weight_grams || 0;
    return acc;
  }, {});
  const modeOptions = Object.keys(totalsByMode);
  const activeTotal = sqMode && totalsByMode[sqMode] ? totalsByMode[sqMode] : null;

  async function squareOff() {
    if (!sqMode) { toast.error("Select mode (decrease / increase)"); return; }
    const w = Number(sqWeight);
    if (!w || w <= 0) { toast.error("Enter weight (g)"); return; }
    if (activeTotal && w > activeTotal.weight) {
      toast.error(`Max ${activeTotal.weight}g available`);
      return;
    }
    const ok = await confirm({
      title: "Square off?",
      message: `Close oldest trades from ${sqMode.toUpperCase()} until ≥ ${w}g is squared off (FIFO).`,
      confirmText: "Square Off",
      danger: true,
    });
    if (!ok) return;
    setSubmitting(true);
    try {
      const res = await api.squareOff({ pair_name: pairName, mode: sqMode, weight_grams: w });
      toast.success(`Closed ${res.closed_count} trade(s) · ${res.actual_weight_grams}g · PnL ${res.total_pnl >= 0 ? "+" : ""}${res.total_pnl}`);
      setSqWeight("");
      setReloadKey((k) => k + 1);
    } catch (e) { toast.error(e.message); }
    finally { setSubmitting(false); }
  }

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
      {modeOptions.length > 0 && (
        <div className="square-off-panel">
          <div className="sq-title">Manual Square Off <span className="sq-sub">(FIFO — oldest first)</span></div>
          <div className="sq-controls">
            <select
              value={sqMode}
              onChange={(e) => setSqMode(e.target.value)}
              className="sq-mode"
            >
              <option value="">Select side…</option>
              {modeOptions.map((m) => (
                <option key={m} value={m}>
                  {m.toUpperCase()} ({totalsByMode[m].count} trades · {totalsByMode[m].weight}g)
                </option>
              ))}
            </select>
            <input
              type="number"
              min="1"
              step="1"
              placeholder="Weight (g)"
              value={sqWeight}
              onChange={(e) => setSqWeight(e.target.value)}
              className="sq-weight"
              disabled={!sqMode}
            />
            {activeTotal && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setSqWeight(String(activeTotal.weight))}
              >
                All ({activeTotal.weight}g)
              </button>
            )}
            <button
              className="btn btn-primary btn-sm"
              onClick={squareOff}
              disabled={submitting || !sqMode || !sqWeight}
            >
              {submitting ? "…" : "Square Off"}
            </button>
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
