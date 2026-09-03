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
function SpreadHistory({ kind, onClose }) {
  // kind: "calendar" | "cross" (follows the tab the button was pressed on).
  // Data: MCX's daily bhavcopy closes, 2021 to yesterday - one value per day.
  const [opts, setOpts] = useState(null);
  const [mode, setMode] = useState("continuous");      // continuous | month
  const [sym, setSym] = useState("");                  // calendar: symbol key
  const [cross, setCross] = useState("");              // cross: "big|small"
  const [rank, setRank] = useState(0);                 // calendar continuous: M1-M2, M2-M3...
  const [nearExp, setNearExp] = useState("");          // month mode: chosen near/big expiry
  const [year, setYear] = useState(String(new Date().getFullYear()));   // "all" | "YYYY"
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [hover, setHover] = useState(null);
  const reqSeq = useRef(0);

  useEffect(() => {
    let alive = true;
    api.bhavOptions()
      .then((r) => {
        if (!alive) return;
        setOpts(r);
        if (!sym && r.symbols?.length) setSym(r.symbols[0].key);
        if (!cross && r.cross?.length) setCross(`${r.cross[0].big}|${r.cross[0].small}`);
      })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, []);

  const symObj = useMemo(() => opts?.symbols?.find((s) => s.key === sym), [opts, sym]);
  const crossObj = useMemo(() => {
    const [b, s] = cross.split("|");
    return opts?.cross?.find((c) => c.big === b && c.small === s);
  }, [opts, cross]);
  const bigKey = kind === "calendar" ? sym : crossObj?.big;
  const expList = useMemo(() => {
    const k = kind === "calendar" ? sym : crossObj?.big;
    return (opts?.symbols?.find((s) => s.key === k)?.expiries || []).slice().reverse();  // newest first
  }, [opts, kind, sym, crossObj]);
  useEffect(() => { if (expList.length && !expList.includes(nearExp)) setNearExp(expList[0]); }, [expList]);

  useEffect(() => {
    if (!opts || !bigKey) return undefined;
    if (mode === "month" && !nearExp) return undefined;
    // The previous table stays on screen, dimmed, until the new one arrives -
    // blanking it made every click look like a page reload. A sequence number
    // drops answers that arrive out of order after fast clicking.
    const seq = ++reqSeq.current;
    setLoading(true); setHover(null);
    const params = {
      kind, big: bigKey, small: kind === "cross" ? crossObj?.small : undefined,
      mode, rank: kind === "calendar" ? rank : 0,
      start: mode !== "continuous" ? "2015-01-01" : (year === "all" ? "2015-01-01" : `${year}-01-01`),
      end: mode === "continuous" && year !== "all" ? `${year}-12-31` : undefined,
      big_exp: mode === "month" ? nearExp : undefined,
    };
    setPage(1);
    api.bhavSeries(params)
      .then((r) => { if (seq === reqSeq.current) { setData(r); setErr(null); setLoading(false); } })
      .catch((e) => { if (seq === reqSeq.current) { setErr(e.message); setLoading(false); } });
    return undefined;
  }, [opts, kind, bigKey, crossObj, mode, rank, nearExp, year]);

  const n = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
  const sgn = (v, d = 2) => (v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d));
  const when = (iso) => {
    const [y, m, d] = String(iso).split("-");
    const M = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][Number(m) - 1];
    return `${d} ${M} ${y.slice(2)}`;
  };
  const expLabel = (iso) => (iso ? when(iso) : "—");

  const series = useMemo(() => (data?.rows || []).slice().reverse(), [data]);
  // Lowest and highest carry the day and the contracts that made them
  // (client, 02-Sep: "date and contract name niche add karvanu").
  const stats = useMemo(() => {
    const rows = series.filter((r) => r.diff != null);
    if (!rows.length) return null;
    let lo = rows[0], hi = rows[0], sum = 0;
    rows.forEach((r) => { sum += r.diff; if (r.diff < lo.diff) lo = r; if (r.diff > hi.diff) hi = r; });
    return { latest: rows[rows.length - 1], avg: sum / rows.length, lo, hi, days: rows.length };
  }, [series]);
  const legsOf = (r) => (kind === "calendar"
    ? `${expLabel(r.near_exp)} / ${expLabel(r.far_exp)}`
    : `${expLabel(r.big_exp)} / ${expLabel(r.small_exp)}`);

  // The chart is drawn in the box's real pixels (measured, re-measured on
  // resize) rather than scaled from a fixed viewBox - scaling stretched every
  // axis label into an unreadable smear on wide screens.
  const chartBox = useRef(null);
  const [dims, setDims] = useState({ w: 1000, h: 300 });
  useEffect(() => {
    const el = chartBox.current;
    if (!el) return undefined;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      if (r.width > 50 && r.height > 50) setDims({ w: Math.round(r.width), h: Math.round(r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [data]);
  const W = dims.w, H = dims.h, PX = 62, PY = 18, PB = 30;
  const chart = useMemo(() => {
    if (!stats || series.length < 2) return null;
    // y range padded a little so the extremes do not sit on the frame
    const pad = (stats.hi.diff - stats.lo.diff || 1) * 0.06;
    const lo = stats.lo.diff - pad, hi = stats.hi.diff + pad, span = hi - lo || 1;
    const x = (i) => PX + (i / (series.length - 1)) * (W - PX - 16);
    const y = (v) => PY + (1 - (v - lo) / span) * (H - PY - PB);
    const pts = series.map((r, i) => [x(i), y(r.diff)]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const base = y(Math.max(lo, Math.min(hi, 0)));
    const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${base.toFixed(1)} L${pts[0][0].toFixed(1)},${base.toFixed(1)} Z`;
    // 20-day average: the trend under the daily spikes
    const win = Math.min(20, Math.max(2, Math.floor(series.length / 8)));
    const ma = [];
    let acc = 0;
    for (let i = 0; i < series.length; i += 1) {
      acc += series[i].diff;
      if (i >= win) acc -= series[i - win].diff;
      if (i >= win - 1) ma.push([x(i), y(acc / win)]);
    }
    const maPath = ma.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    // y ticks: 5 round-ish values; x ticks: first trading day of each year (or month if short)
    const yTicks = [];
    for (let k = 0; k <= 4; k += 1) { const v = lo + (span * k) / 4; yTicks.push({ v, y: y(v) }); }
    const seen = new Set(); const xTicks = [];
    const byYear = series.length > 400;
    series.forEach((r, i) => {
      const key = byYear ? r.date.slice(0, 4) : r.date.slice(0, 7);
      if (!seen.has(key)) { seen.add(key); xTicks.push({ x: x(i), label: byYear ? key : when(r.date).slice(3) }); }
    });
    const zero = lo <= 0 && hi >= 0 ? y(0) : null;
    return { pts, line, area, maPath, win, yTicks, xTicks: xTicks.slice(0, 14), zero, x, y };
  }, [series, stats, W, H]);
  const onMove = (e) => {
    if (!chart) return;
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    let best = 0, bd = Infinity;
    chart.pts.forEach((p, i) => { const d = Math.abs(p[0] - px); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const hv = hover != null ? series[hover] : null;
  // Paging by YEAR: All years pages through 2015, 2016, ... one full year at a
  // time; a chosen year is one page. Hundred-row pages cut a year mid-month.
  const pageYears = useMemo(() => {
    if (year !== "all") return [];
    return Array.from(new Set(series.map((r) => r.date.slice(0, 4))));
  }, [series, year]);
  const pageRows = useMemo(() => {
    if (year !== "all") return series;
    const y = pageYears[page - 1];
    return y ? series.filter((r) => r.date.startsWith(y)) : series;
  }, [series, year, pageYears, page]);
  // From-year chips follow the data: the archive reaches back to May-2015,
  // and whatever it holds is offered, so a longer backfill shows up here
  // without another change.
  const years = [];
  const firstYear = Number((opts?.coverage?.from || "2021").slice(0, 4)) || 2021;
  for (let y = firstYear; y <= new Date().getFullYear(); y += 1) years.push(y);
  const isCal = kind === "calendar";

  return (
    <div className="pt-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pt-modal sh-modal" role="dialog" aria-label="Spread history">
        <div className="pt-modal-head">
          <div>
            <b>Spread history · {isCal ? "Calendar" : "Cross pair"}</b>
            <span className="sh-sub">
              One value per day from MCX closing prices
              {opts?.coverage?.from ? ` · data ${when(opts.coverage.from)} to ${when(opts.coverage.to)}` : ""}
              {isCal ? " · far month minus near month" : " · big leg minus small leg, board multipliers"}
            </span>
          </div>
          <div className="sh-controls sh-toolbar">
            <label><span>{isCal ? "Symbol" : "Pair"}</span>
              {isCal ? (
                <select className="oh-weeks pt-form-select" value={sym} onChange={(e) => setSym(e.target.value)}>
                  {(opts?.symbols || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              ) : (
                <select className="oh-weeks pt-form-select" value={cross} onChange={(e) => setCross(e.target.value)}>
                  {(opts?.cross || []).map((c) => <option key={`${c.big}|${c.small}`} value={`${c.big}|${c.small}`}>{c.label}</option>)}
                </select>
              )}
            </label>
            <label><span>View</span>
              <div className="oh-group">
                <button type="button" className={`oh-chip ${mode === "continuous" ? "on" : ""}`}
                  onClick={() => setMode("continuous")}>Continuous</button>
                <button type="button" className={`oh-chip ${mode === "month" ? "on" : ""}`}
                  onClick={() => setMode("month")}>Month-wise</button>
              </div></label>

            {mode === "continuous" ? (
              <>
                <label><span>Year</span>
                  <select className="oh-weeks pt-form-select sh-year" value={year}
                    onChange={(e) => setYear(e.target.value)}>
                    <option value="all">All years (2015 to today)</option>
                    {years.slice().reverse().map((y) => <option key={y} value={String(y)}>{y}</option>)}
                  </select></label>
                {isCal && (
                  <label><span>Months</span>
                    <div className="oh-group">
                      {[[0, "M1-M2"], [1, "M2-M3"], [2, "M3-M4"]].map(([r, l]) => (
                        <button key={r} type="button" className={`oh-chip ${rank === r ? "on" : ""}`}
                          onClick={() => setRank(r)}>{l}</button>
                      ))}
                    </div></label>
                )}
              </>
            ) : (
              <label><span>{isCal ? "Near month" : "Big leg month"}</span>
                <select className="oh-weeks pt-form-select" value={nearExp} onChange={(e) => setNearExp(e.target.value)}>
                  {expList.map((x) => <option key={x} value={x}>{expLabel(x)}</option>)}
                </select></label>
            )}
          </div>

          <button type="button" className="pt-modal-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className={`sh-body sh-layout ${loading ? "sh-refreshing" : ""}`}>
          {data && mode === "month" && (
            <div className="sh-sub">
              {isCal
                ? `${data.label}: ${expLabel(data.near_exp)} (near) vs ${expLabel(data.far_exp)} (far)`
                : `${data.label}: ${expLabel(data.big_exp)} vs ${expLabel(data.small_exp)} - months matched the board's way`}
            </div>
          )}

          {err && <div className="settings-banner danger">⚠ {err}</div>}
          {!data && !err && <div className="empty-state">Loading…</div>}
          {loading && data && <div className="sh-progress" aria-hidden="true" />}
          {data && stats && (
            <div className="sh-stats">
              <div><em>Latest</em><b className={stats.latest.diff >= 0 ? "pos" : "neg"}>{sgn(stats.latest.diff)}</b>
                <i>{when(stats.latest.date)}</i><i className="sh-legs">{legsOf(stats.latest)}</i></div>
              <div><em>Average</em><b>{sgn(stats.avg)}</b><i>{stats.days} days</i></div>
              <div><em>Lowest</em><b className="neg">{sgn(stats.lo.diff)}</b>
                <i>{when(stats.lo.date)}</i><i className="sh-legs">{legsOf(stats.lo)}</i></div>
              <div><em>Highest</em><b className="pos">{sgn(stats.hi.diff)}</b>
                <i>{when(stats.hi.date)}</i><i className="sh-legs">{legsOf(stats.hi)}</i></div>
            </div>
          )}

          {chart && (
            <div className="sh-chart">
              <div className="sh-legend">
                <span><i className="sh-lg-line" /> daily difference</span>
                <span><i className="sh-lg-ma" /> {chart.win}-day average</span>
                {chart.zero != null && <span><i className="sh-lg-zero" /> zero</span>}
              </div>
              <div className="sh-chartbox" ref={chartBox}>
              <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
                onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
                {chart.yTicks.map((tk) => (
                  <g key={tk.y}>
                    <line x1={PX} x2={W - 16} y1={tk.y} y2={tk.y} className="sh-grid-y" />
                    <text x={PX - 8} y={tk.y + 4} className="sh-axis" textAnchor="end">{fmtNum(tk.v, 0)}</text>
                  </g>
                ))}
                {chart.xTicks.map((tk) => (
                  <g key={tk.x}>
                    <line x1={tk.x} x2={tk.x} y1={PY} y2={H - PB} className="sh-grid-x" />
                    <text x={tk.x + 4} y={H - 10} className="sh-axis">{tk.label}</text>
                  </g>
                ))}
                {chart.zero != null && (
                  <line x1={PX} x2={W - 16} y1={chart.zero} y2={chart.zero} className="sh-zero" />
                )}
                <path d={chart.area} className="sh-area" />
                <path d={chart.line} className="sh-line" />
                <path d={chart.maPath} className="sh-ma" />
                {hv && (
                  <>
                    <line x1={chart.x(hover)} x2={chart.x(hover)} y1={PY} y2={H - PB} className="sh-cross" />
                    <circle cx={chart.x(hover)} cy={chart.y(hv.diff)} r="4.5" className="sh-dot" />
                  </>
                )}
              </svg>
              </div>
              <div className="sh-tip">
                {hv ? (
                  isCal
                    ? <><b>{when(hv.date)}</b> · difference <b className={hv.diff >= 0 ? "pos" : "neg"}>{sgn(hv.diff)}</b> ({sgn(hv.pct)}%) · near {n(hv.near)} ({expLabel(hv.near_exp)}) · far {n(hv.far)} ({expLabel(hv.far_exp)})</>
                    : <><b>{when(hv.date)}</b> · difference <b className={hv.diff >= 0 ? "pos" : "neg"}>{sgn(hv.diff)}</b> ({sgn(hv.pct)}%) · big {n(hv.big_rate)} ({expLabel(hv.big_exp)}) · small {n(hv.small_rate)} ({expLabel(hv.small_exp)})</>
                ) : "Move over the line for a day's numbers"}
              </div>
            </div>
          )}

          {data && (
            <div className="pt-tablewrap sh-tablewrap sh-tablefull">
              <table className="pt-table sh-table">
                <thead><tr>
                  <th>Date</th>
                  {isCal ? <><th>Near close</th><th>Far close</th></> : <><th>Big (rate)</th><th>Small (rate)</th></>}
                  <th>Difference</th>
                  {isCal && (data.std_mult || 1) !== 1 && <th title={`difference × ${data.std_mult} - the board's common basis`}>Diff {data.std_unit || "per 10 gm"}</th>}
                  <th>%</th>
                  {mode === "continuous" && <th>Contracts</th>}
                </tr></thead>
                <tbody>
                  {pageRows.map((r) => (
                    <tr key={r.date}>
                      <td>{when(r.date)}</td>
                      {isCal
                        ? <><td className="sh-muted">{n(r.near)}</td><td className="sh-muted">{n(r.far)}</td></>
                        : <><td className="sh-muted">{n(r.big_rate)}</td><td className="sh-muted">{n(r.small_rate)}</td></>}
                      <td className={r.diff >= 0 ? "pos" : "neg"}><b>{sgn(r.diff)}</b></td>
                      {isCal && (data.std_mult || 1) !== 1 && <td className={(r.diff_std ?? r.diff) >= 0 ? "pos" : "neg"}><b>{sgn(r.diff_std ?? r.diff)}</b></td>}
                      <td className={r.pct >= 0 ? "pos" : "neg"}>{sgn(r.pct)}</td>
                      {mode === "continuous" && (
                        <td className="sh-muted sh-contracts">
                          {isCal ? `${expLabel(r.near_exp)} / ${expLabel(r.far_exp)}` : `${expLabel(r.big_exp)} / ${expLabel(r.small_exp)}`}
                        </td>
                      )}
                    </tr>
                  ))}
                  {data.rows.length === 0 && (
                    <tr><td colSpan={8} className="sh-empty">
                      No closing prices for this selection. The archive starts in 2021 and a
                      contract only has closes from its first trade; Gold Ten and Silver 100
                      were listed later than the others.
                    </td></tr>
                  )}
                </tbody>
              </table>
              {year === "all" && pageYears.length > 1 && (
                <div className="pt-pager sh-pager">
                  <span className="pt-pager-total">{data.rows.length} days · one year per page, January to December</span>
                  <button type="button" className="oh-chip" disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}>‹ {pageYears[page - 2] || ""}</button>
                  <span className="pt-pager-page"><b>{pageYears[page - 1]}</b> · {pageRows.length} days</span>
                  <button type="button" className="oh-chip" disabled={page >= pageYears.length}
                    onClick={() => setPage((p) => p + 1)}>{pageYears[page] || ""} ›</button>
                </div>
              )}
              {year !== "all" && (
                <div className="pt-pager sh-pager">
                  <span className="pt-pager-total">{data.rows.length} days · January to December</span>
                </div>
              )}
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

      {isSpread && (
        <div className="sh-btnrow">
          <button type="button" className="oh-chip"
            title="Day-by-day spread from MCX closing prices, 2021 to yesterday"
            onClick={() => setHistOpen(true)}>Spread History</button>
        </div>
      )}
      {histOpen && <SpreadHistory kind={tab} onClose={() => setHistOpen(false)} />}

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
