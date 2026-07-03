import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

function corrColor(r) {
  if (Math.abs(r) < 0.3) return "var(--text-muted)";
  return r < 0 ? "var(--red)" : "var(--green)";
}
function corrText(r) {
  const a = Math.abs(r);
  const s = a >= 0.7 ? "Strong" : a >= 0.4 ? "Moderate" : a >= 0.2 ? "Weak" : "No clear";
  if (s === "No clear") return "no clear link";
  return r < 0 ? `${s}: stock ↑ → spread ↓` : `${s}: stock ↑ → spread ↑`;
}

function Delta({ v }) {
  if (v == null) return <span className="bs-muted">—</span>;
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "flat";
  return <span className={`bs-d ${cls}`}>{v > 0 ? "▲" : v < 0 ? "▼" : "·"} {fmtNum(Math.abs(v), 2)}</span>;
}

function buildSeries(spreadHist, stockSeries) {
  if (!spreadHist || !stockSeries) return [];
  const out = [];
  for (const sp of spreadHist) {
    let stk = null;
    for (const r of stockSeries) { if (r.date <= sp.date) stk = r.units; else break; }
    if (stk != null) out.push({ date: sp.date, stock: stk, spread: sp.spread });
  }
  return out;
}

// Responsive single-series area+line chart. Flat series render centred, not stuck to the floor.
function StockTrend({ series }) {
  if (!series || series.length < 2) return null;
  const vals = series.map((d) => d.units);
  const mn = Math.min(...vals), mx = Math.max(...vals), rawSpan = mx - mn, n = series.length;
  const X = (i) => (i / (n - 1)) * 100;
  const Y = (v) => (rawSpan === 0 ? 50 : 100 - ((v - mn) / rawSpan) * 90 - 5); // 5% pad top/bottom
  const line = series.map((d, i) => `${i ? "L" : "M"}${X(i).toFixed(2)},${Y(d.units).toFixed(2)}`).join(" ");
  const area = `M0,100 ${series.map((d, i) => `L${X(i).toFixed(2)},${Y(d.units).toFixed(2)}`).join(" ")} L100,100 Z`;
  return (
    <svg className="bs-trend" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Daily stock trend">
      {[20, 40, 60, 80].map((y) => (
        <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="var(--border-light)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      ))}
      <path d={area} fill="var(--accent)" opacity="0.1" />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2.25" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function MiniChart({ series }) {
  if (series.length < 2) return null;
  const norm = (vals) => {
    const mn = Math.min(...vals), mx = Math.max(...vals), sp = mx - mn;
    return vals.map((v) => (sp === 0 ? 50 : 100 - ((v - mn) / sp) * 90 - 5));
  };
  const sN = norm(series.map((d) => d.stock));
  const pN = norm(series.map((d) => d.spread));
  const X = (i) => (i / (series.length - 1)) * 100;
  const path = (arr) => arr.map((y, i) => `${i ? "L" : "M"}${X(i).toFixed(2)},${y.toFixed(2)}`).join(" ");
  return (
    <svg className="bs-trend" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Stock vs spread">
      <path d={path(sN)} fill="none" stroke="var(--yellow)" strokeWidth="2.25" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <path d={path(pN)} fill="none" stroke="#4da3ff" strokeWidth="2.25" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

export default function BullionStock() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [selected, setSelected] = useState(null);
  const [histCommodity, setHistCommodity] = useState(null);
  const [view, setView] = useState(() => {
    const v = localStorage.getItem("arbi_bs_view");
    return v === "corr" || v === "stock" ? v : "stock"; // survive refresh
  });
  useEffect(() => { try { localStorage.setItem("arbi_bs_view", view); } catch {} }, [view]);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const d = await api.bullionStock();
      setData(d);
      if (d?.correlation?.length) setSelected((s) => s || d.correlation[0].pair_name);
    } catch (e) {
      setErr(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const fetchNow = useCallback(async () => {
    setFetching(true); setErr(null);
    try {
      const res = await api.bullionRefresh();
      if (!res?.ok && res?.status?.msg) setErr(`Fetch: ${res.status.msg}`);
      await load();
    } catch (e) { setErr(e.message || "Fetch failed"); }
    finally { setFetching(false); }
  }, [load]);

  const openPdf = useCallback(async (download) => {
    setPdfBusy(true); setErr(null);
    try {
      const blob = await api.bullionPdf(download);
      const url = URL.createObjectURL(blob);
      if (download) {
        const a = document.createElement("a");
        a.href = url; a.download = data?.pdf_name || `mcxccl-bullion-${data?.as_on_date || "latest"}.pdf`;
        document.body.appendChild(a); a.click(); a.remove();
      } else { window.open(url, "_blank", "noopener"); }
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { setErr(e.message || "PDF failed"); }
    finally { setPdfBusy(false); }
  }, [data]);

  const deltaFor = useCallback((c) => {
    const s = data?.stock_history?.[c];
    if (!s || s.length < 2) return null;
    return s[s.length - 1].units - s[s.length - 2].units;
  }, [data]);

  const commodities = useMemo(() => (data ? Object.keys(data.stock_history || {}) : []), [data]);

  // Default the trend to GOLD (client preference); fall back to the commodity
  // that moves most, then the first available.
  const defaultHist = useMemo(() => {
    const hist = data?.stock_history || {};
    if (hist["GOLD"]) return "GOLD";
    let best = null, bestRange = -1;
    for (const [c, s] of Object.entries(hist)) {
      if (!s || s.length < 2) continue;
      const vals = s.map((x) => x.units);
      const mx = Math.max(...vals);
      const range = mx ? (mx - Math.min(...vals)) / mx : 0;
      if (range > bestRange) { bestRange = range; best = c; }
    }
    return best || commodities[0];
  }, [data, commodities]);

  const effHist = histCommodity && commodities.includes(histCommodity) ? histCommodity : defaultHist;
  const histSeries = data?.stock_history?.[effHist] || [];
  const histUnit = data?.latest?.find((r) => r.commodity === effHist)?.unit || "";
  const histLatest = histSeries.length ? histSeries[histSeries.length - 1].units : null;
  const histDelta = histSeries.length > 1 ? histSeries[histSeries.length - 1].units - histSeries[histSeries.length - 2].units : null;
  const histFlat = histSeries.length >= 2 && new Set(histSeries.map((d) => d.units)).size === 1;

  // Full history matrix: dates (newest first) × commodities.
  const matrix = useMemo(() => {
    const hist = data?.stock_history || {};
    const dateSet = new Set();
    for (const s of Object.values(hist)) for (const r of s) dateSet.add(r.date);
    const dates = [...dateSet].sort().reverse();
    const byDate = {};
    for (const [c, s] of Object.entries(hist)) for (const r of s) (byDate[r.date] ||= {})[c] = r.units;
    return { dates, byDate };
  }, [data]);

  const selectedCorr = useMemo(
    () => data?.correlation?.find((c) => c.pair_name === selected) || data?.correlation?.[0],
    [data, selected]
  );
  const corrSeries = useMemo(() => {
    if (!data || !selectedCorr) return [];
    return buildSeries(data.spread_history?.[selectedCorr.pair_name], data.stock_history?.[selectedCorr.commodity]);
  }, [data, selectedCorr]);

  const stale = data?.stale_days;
  const staleBad = stale != null && stale > 5;

  return (
    <div className="bs-wrap">
      <div className="bs-head">
        <div className="bs-head-main">
          <h2 className="bs-title">Bullion Warehouse Stock <span className="bs-src">· MCXCCL</span></h2>
          <div className="bs-sub">
            {data?.as_on_date ? (
              <>As on <b>{data.as_on_date}</b>{" "}
                {stale != null && <span className={`bs-pill ${staleBad ? "bad" : "ok"}`}>{stale}d old</span>}
                <span className="bs-hint"> · exchange deliverable stock, updated daily</span>
              </>
            ) : "No stock fetched yet"}
          </div>
        </div>
        {data?.latest?.length > 0 && (
          <div className="bs-viewbar" role="tablist" aria-label="Bullion view">
            <button type="button" role="tab" aria-selected={view === "stock"}
              className={`bs-viewbtn ${view === "stock" ? "active" : ""}`} onClick={() => setView("stock")}>
              Bullion Warehouse Stock
            </button>
            <button type="button" role="tab" aria-selected={view === "corr"}
              className={`bs-viewbtn ${view === "corr" ? "active" : ""}`} onClick={() => setView("corr")}>
              Spread Correlation
            </button>
          </div>
        )}
        <div className="bs-actions">
          {data?.pdf_available && (
            <>
              <button className="btn btn-secondary btn-sm" onClick={() => openPdf(false)} disabled={pdfBusy}>👁 View PDF</button>
              <button className="btn btn-secondary btn-sm" onClick={() => openPdf(true)} disabled={pdfBusy}>⬇ Download</button>
            </>
          )}
          <button className="btn btn-secondary btn-sm" onClick={load} disabled={loading}>{loading ? "…" : "↻ Refresh"}</button>
          <button className="btn btn-primary btn-sm" onClick={fetchNow} disabled={fetching} title="Scrape MCXCCL now">{fetching ? "Fetching…" : "⟳ Fetch now"}</button>
        </div>
      </div>

      {err && <div className="bs-note bad">Error: {err}</div>}
      {!err && data && !data.latest?.length && (
        <div className="bs-note">No data yet — the daily scrape runs at <b>18:00 IST</b>. Press <b>Fetch now</b> to pull immediately.</div>
      )}

      {data?.latest?.length > 0 && (
        <>
          {view === "stock" && (
          <>
          <div className="bs-grid">
            {/* Latest eligible units + 1-day change */}
            <div className="bs-card">
              <div className="bs-card-h">Eligible Units <span className="bs-muted">· {data.as_on_date}</span></div>
              <div className="bs-tbl-scroll bs-eu-scroll">
                <table className="bs-table bs-eu">
                  <thead><tr><th>Commodity</th><th>Unit</th><th className="num">Eligible Units</th><th className="num">Δ 1 day</th></tr></thead>
                  <tbody>
                    {data.latest.map((r) => (
                      <tr key={r.commodity} className={effHist === r.commodity ? "hl" : ""} onClick={() => setHistCommodity(r.commodity)} title="Show this commodity's chart">
                        <td>{r.commodity}</td>
                        <td className="bs-unit">{r.unit}</td>
                        <td className="num">{fmtNum(r.eligible_units, 2)}</td>
                        <td className="num"><Delta v={deltaFor(r.commodity)} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Trend chart for the selected commodity */}
            <div className="bs-card">
              <div className="bs-card-h">Trend</div>
              <div className="bs-chips">
                {commodities.map((c) => (
                  <button key={c} className={`bs-chip ${c === effHist ? "on" : ""}`} onClick={() => setHistCommodity(c)}>{c}</button>
                ))}
              </div>
              {histSeries.length >= 2 ? (
                <>
                  <div className="bs-hist-top">
                    <span className="bs-hist-val">{fmtNum(histLatest, 2)} <span className="bs-unit">{histUnit}</span></span>
                    <span className="bs-hist-delta">
                      {histFlat ? <span className="bs-muted">no change in period</span> : <><Delta v={histDelta} /> <span className="bs-muted">vs prev day</span></>}
                    </span>
                  </div>
                  <StockTrend series={histSeries} />
                  <div className="bs-axis"><span>{histSeries[0].date}</span><span>{histSeries[histSeries.length - 1].date}</span></div>
                </>
              ) : (
                <div className="bs-note">Only one day of data so far — the chart builds as new daily files publish.</div>
              )}
            </div>
          </div>

          {/* Full daily matrix — every commodity, every day */}
          {matrix.dates.length > 0 && (
            <div className="bs-card bs-matrix-card">
              <div className="bs-card-h">Daily History <span className="bs-muted">· {matrix.dates.length} days · all commodities</span></div>
              <div className="bs-tbl-scroll">
                <table className="bs-table bs-matrix">
                  <thead>
                    <tr>
                      <th>Date</th>
                      {commodities.map((c) => <th key={c} className="num">{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.dates.map((d) => (
                      <tr key={d}>
                        <td>{d}</td>
                        {commodities.map((c) => (
                          <td key={c} className="num">{matrix.byDate[d]?.[c] != null ? fmtNum(matrix.byDate[d][c], 2) : "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          </>
          )}

          {/* Spread Correlation view — chart on top, table below (full width) */}
          {view === "corr" && (
            <div className="bs-card bs-corr-card">
              <div className="bs-card-h">Stock ↔ Spread Correlation</div>
              {!data.correlation?.length ? (
                <div className="bs-note bs-slim">Building automatically — appears after a few days of history once the warehouse stock has changed. No action needed.</div>
              ) : (
                <div className="bs-corr-grid">
                  {corrSeries.length >= 2 && (
                    <div className="bs-corr-chart">
                      <div className="bs-legend">
                        <span><i className="dot" style={{ background: "var(--yellow)" }} /> Stock</span>
                        <span><i className="dot" style={{ background: "#4da3ff" }} /> Spread</span>
                        <span className="bs-muted">{selectedCorr.pair}</span>
                      </div>
                      <MiniChart series={corrSeries} />
                      <div className="bs-axis"><span>{corrSeries[0].date}</span><span>{corrSeries[corrSeries.length - 1].date}</span></div>
                    </div>
                  )}
                  <div className="bs-tbl-scroll">
                    <table className="bs-table bs-corr">
                      <thead><tr><th>Pair</th><th>Commodity</th><th className="num">Days</th><th className="num">r</th><th>Reading</th></tr></thead>
                      <tbody>
                        {data.correlation.map((c) => (
                          <tr key={c.pair_name + c.commodity}
                            className={selectedCorr && c.pair_name === selectedCorr.pair_name && c.commodity === selectedCorr.commodity ? "sel" : ""}
                            onClick={() => setSelected(c.pair_name)}>
                            <td>{c.pair}</td><td>{c.commodity}</td><td className="num">{c.n}</td>
                            <td className="num" style={{ color: corrColor(c.r), fontWeight: 700 }}>{c.r.toFixed(2)}</td>
                            <td className="bs-muted">{corrText(c.r)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
