import React, { useEffect, useMemo, useRef, useState } from "react";
import SpreadCards from "./spread/SpreadCards.jsx";
import { PAIR_PAGE_SIZE } from "./spread/constants.js";
import MetalSpread, { otherCommColorKey } from "./MetalSpread.jsx";
import PriceTable from "./PriceTable.jsx";
import SignalsPanel from "./SignalsPanel.jsx";
import { useToast } from "./Toast.jsx";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Daily history of one pair's spread - ONE value per day from each leg's
// closing price (client, 02-Sep: "increase-decrease karta single value aapi
// de, based on closing price"). Computed from exchange daily closes on demand.
function SpreadHistory({ pairs, onClose }) {
  const [pair, setPair] = useState(pairs[0]?.name || "");
  const [days, setDays] = useState(120);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [hover, setHover] = useState(null);      // index into chronological rows
  // The board only knows LIVE pairs; the server also remembers expired ones
  // (client, 03-Sep: expiry must not erase a pair's history).
  const [allPairs, setAllPairs] = useState(pairs);
  useEffect(() => {
    let alive = true;
    api.historyPairs()
      .then((r) => {
        if (!alive || !r.pairs?.length) return;
        setAllPairs(r.pairs.map((x) => ({
          name: x.name,
          title: x.expired ? `${x.title}  (expired)` : x.title,
        })));
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!pair) return undefined;
    let alive = true;
    setData(null); setHover(null);
    api.spreadHistory(pair, days)
      .then((r) => { if (alive) { setData(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [pair, days]);

  const n = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
  const sgn = (v, d = 2) => (v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d));
  const when = (iso) => {
    const [y, m, d] = String(iso).split("-");
    const M = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][Number(m) - 1];
    return `${d} ${M} ${y.slice(2)}`;
  };

  // Chronological series for the chart and the summary; the table stays
  // newest-first, which is how a person reads a history.
  const series = useMemo(() => (data?.rows || []).slice().reverse(), [data]);
  const stats = useMemo(() => {
    const v = series.map((r) => r.diff).filter((x) => x != null);
    if (!v.length) return null;
    const avg = v.reduce((a, b) => a + b, 0) / v.length;
    return { latest: v[v.length - 1], avg, min: Math.min(...v), max: Math.max(...v), days: v.length };
  }, [series]);

  // Sparkline: one series, 2px line, a 4px dot on the hovered day, direct
  // labels only at the ends. Text stays in text tokens, the line in accent.
  const W = 760, H = 150, PX = 34, PY = 14;
  const chart = useMemo(() => {
    if (!stats || series.length < 2) return null;
    const lo = stats.min, hi = stats.max, span = hi - lo || 1;
    const x = (i) => PX + (i / (series.length - 1)) * (W - PX * 2);
    const y = (v) => PY + (1 - (v - lo) / span) * (H - PY * 2);
    const pts = series.map((r, i) => [x(i), y(r.diff)]);
    const zero = lo <= 0 && hi >= 0 ? y(0) : null;
    return { pts, path: pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" "), zero, x, y };
  }, [series, stats]);
  const onMove = (e) => {
    if (!chart) return;
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    let best = 0, bd = Infinity;
    chart.pts.forEach((p, i) => { const d = Math.abs(p[0] - px); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const hv = hover != null ? series[hover] : null;

  return (
    <div className="pt-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pt-modal sh-modal" role="dialog" aria-label="Spread history">
        <div className="pt-modal-head">
          <div>
            <b>Spread history</b>
            <span className="sh-sub">One value per day, from each leg's closing price · far month minus near month</span>
          </div>
          <button type="button" className="pt-modal-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="sh-body">
          <div className="sh-controls">
            <label><span>Pair</span>
              <select className="oh-weeks pt-form-select" value={pair}
                onChange={(e) => setPair(e.target.value)}>
                {allPairs.map((x) => <option key={x.name} value={x.name}>{x.title}</option>)}
              </select></label>
            <label><span>Period</span>
              <div className="oh-group">
                {[30, 60, 120, 365].map((d) => (
                  <button key={d} type="button" className={`oh-chip ${days === d ? "on" : ""}`}
                    onClick={() => setDays(d)}>{d === 365 ? "1 year" : `${d} days`}</button>
                ))}
              </div></label>
          </div>

          {err && <div className="settings-banner danger">⚠ {err}</div>}
          {!data && !err && <div className="empty-state">Loading…</div>}

          {data && stats && (
            <div className="sh-stats">
              <div><em>Latest</em><b className={stats.latest >= 0 ? "pos" : "neg"}>{sgn(stats.latest)}</b><i>{when(series[series.length - 1].date)}</i></div>
              <div><em>Average</em><b>{sgn(stats.avg)}</b><i>{stats.days} days</i></div>
              <div><em>Lowest</em><b className="neg">{sgn(stats.min)}</b></div>
              <div><em>Highest</em><b className="pos">{sgn(stats.max)}</b></div>
            </div>
          )}

          {chart && (
            <div className="sh-chart">
              <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
                onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
                {chart.zero != null && (
                  <line x1={PX} x2={W - PX} y1={chart.zero} y2={chart.zero} className="sh-zero" />
                )}
                <path d={chart.path} className="sh-line" />
                {hv && (
                  <>
                    <line x1={chart.x(hover)} x2={chart.x(hover)} y1={PY} y2={H - PY} className="sh-cross" />
                    <circle cx={chart.x(hover)} cy={chart.y(hv.diff)} r="4" className="sh-dot" />
                  </>
                )}
                <text x={PX} y={H - 2} className="sh-axis">{when(series[0].date)}</text>
                <text x={W - PX} y={H - 2} className="sh-axis" textAnchor="end">{when(series[series.length - 1].date)}</text>
              </svg>
              <div className="sh-tip">
                {hv ? <><b>{when(hv.date)}</b> · difference <b className={hv.diff >= 0 ? "pos" : "neg"}>{sgn(hv.diff)}</b> ({sgn(hv.pct)}%) · near {n(hv.near)} · far {n(hv.far)}</>
                    : "Move over the line for a day's numbers"}
              </div>
            </div>
          )}

          {data && (
            <div className="pt-tablewrap sh-tablewrap">
              <table className="pt-table sh-table">
                <thead><tr>
                  <th>Date</th><th>Near close</th><th>Far close</th><th>Difference</th><th>%</th>
                </tr></thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.date}>
                      <td>{when(r.date)}</td>
                      <td className="sh-muted">{n(r.near)}</td><td className="sh-muted">{n(r.far)}</td>
                      <td className={r.diff >= 0 ? "pos" : "neg"}><b>{sgn(r.diff)}</b></td>
                      <td className={r.pct >= 0 ? "pos" : "neg"}>{sgn(r.pct)}</td>
                    </tr>
                  ))}
                  {data.rows.length === 0 && (
                    <tr><td colSpan={5} className="sh-empty">
                      {data.error
                        || (data.far_days === 0 || data.near_days === 0
                          ? `No closing prices yet for ${data.far_days === 0 ? (data.far_symbol || "the far month") : (data.near_symbol || "the near month")} - a contract that has not traded has no daily close, so there is nothing to compare until it does.`
                          : "No closing prices for this pair in this period. A far month that has not traded yet has none; try a longer period, or check back after it starts trading.")}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LiveSpreadTable({ rows, tab, metalData, otherCommData, priceData }) {
  const toast = useToast();
  const [histOpen, setHistOpen] = useState(false);
  const sigSeen = useRef(null);
  const seeded = useRef(false);
  const [page, setPage] = useState(1);

  const crossRows = useMemo(() => rows.filter((r) => r.type === "cross"), [rows]);
  const calendarRows = useMemo(() => rows.filter((r) => r.type === "calendar"), [rows]);
  const signalRows = useMemo(() => rows.filter((r) => r.signal), [rows]);

  // In-app alert: toast ONLY when a genuinely new signal appears. The baseline
  // is set once the live data has first loaded, so existing signals never
  // re-notify on a page refresh / reconnect.
  useEffect(() => {
    if (!rows.length) return;                       // wait for the first live snapshot
    const cur = new Map(signalRows.map((r) => [r.name, r.signal.direction]));
    if (!seeded.current) {                          // first loaded snapshot → baseline only
      seeded.current = true;
      sigSeen.current = cur;
      return;
    }
    for (const [name, dir] of cur) {
      if (sigSeen.current.get(name) !== dir) {
        const r = signalRows.find((x) => x.name === name);
        if (r) toast.info(`⚡ ${r.label} ${r.expiry_label}: ${dir === "narrow" ? "NARROW ▼" : "WIDEN ▲"} → target ${r.signal.target}`);
      }
    }
    sigSeen.current = cur;
  }, [rows, signalRows, toast]);

  const isSpread = tab === "cross" || tab === "calendar";
  const tabRows = tab === "cross" ? crossRows : calendarRows;

  const groupedRows = useMemo(() => {
    const map = new Map();
    for (const r of tabRows) {
      const k = r.group_label || r.label;
      if (!map.has(k)) map.set(k, { label: k, rows: [] });
      map.get(k).rows.push(r);
    }
    return Array.from(map.values());
  }, [tabRows]);

  const totalPages = Math.max(1, Math.ceil(groupedRows.length / PAIR_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PAIR_PAGE_SIZE;
  const sliceGroups = groupedRows.slice(start, start + PAIR_PAGE_SIZE);
  useEffect(() => { setPage(1); }, [tab]);

  return (
    <div className="sessions-container">
      {tab === "signals" && <SignalsPanel signals={signalRows} />}
      {tab === "metals" && <MetalSpread data={metalData} embedded />}
      {tab === "price" && <PriceTable data={priceData} embedded />}
      {tab === "othercomm" && (
        <MetalSpread data={otherCommData} embedded showPct={false} colorFn={otherCommColorKey} loadingText="Loading other-commodity data…" />
      )}

      {tab === "calendar" && (
        <div className="sh-btnrow">
          <button type="button" className="oh-chip"
            title="Day-by-day stored spread of any calendar pair"
            onClick={() => setHistOpen(true)}>Spread History</button>
        </div>
      )}
      {histOpen && (
        <SpreadHistory onClose={() => setHistOpen(false)}
          pairs={calendarRows.map((r) => ({ name: r.name, title: r.mcx_label || r.label }))} />
      )}

      {isSpread && (
        rows.length === 0 ? (
          <div className="empty-state" style={{ padding: "24px 16px" }}>Loading…</div>
        ) : (
          <>
            <SpreadCards groups={sliceGroups} />
            {groupedRows.length > PAIR_PAGE_SIZE && (
              <div className="pagination-controls">
                <div>Showing {start + 1}-{Math.min(start + PAIR_PAGE_SIZE, groupedRows.length)} of {groupedRows.length} groups</div>
                <div className="pager">
                  <button onClick={() => setPage(1)} disabled={safePage === 1}>«</button>
                  <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage === 1}>‹</button>
                  <button className="active">{safePage}</button>
                  <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}>›</button>
                  <button onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</button>
                </div>
              </div>
            )}
          </>
        )
      )}
    </div>
  );
}
