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

// Coloured day-over-day change cell.
function Delta({ v }) {
  if (v == null) return <span className="bs-muted">—</span>;
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "flat";
  return <span className={`bs-d ${cls}`}>{v > 0 ? "▲" : v < 0 ? "▼" : "·"} {fmtNum(Math.abs(v), 2)}</span>;
}

// Align a pair's spread with its commodity stock (forward-fill lagging stock).
function buildSeries(spreadHist, stockSeries) {
  if (!spreadHist || !stockSeries) return [];
  const out = [];
  for (const sp of spreadHist) {
    let stk = null;
    for (const r of stockSeries) {
      if (r.date <= sp.date) stk = r.units; else break;
    }
    if (stk != null) out.push({ date: sp.date, stock: stk, spread: sp.spread });
  }
  return out;
}

// Responsive single-series line chart — fills its box at any size.
function StockTrend({ series }) {
  if (!series || series.length < 2) return null;
  const vals = series.map((d) => d.units);
  const mn = Math.min(...vals), mx = Math.max(...vals), span = (mx - mn) || 1, n = series.length;
  const X = (i) => (i / (n - 1)) * 100;
  const Y = (v) => 100 - ((v - mn) / span) * 96 - 2; // 2% padding top/bottom
  const line = series.map((d, i) => `${i ? "L" : "M"}${X(i).toFixed(2)},${Y(d.units).toFixed(2)}`).join(" ");
  const area = `M0,100 ${series.map((d, i) => `L${X(i).toFixed(2)},${Y(d.units).toFixed(2)}`).join(" ")} L100,100 Z`;
  return (
    <svg className="bs-trend" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Daily stock trend">
      {[25, 50, 75].map((y) => (
        <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="var(--border-light)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      ))}
      <path d={area} fill="var(--accent)" opacity="0.09" />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

// Two normalised lines (stock vs spread) for the correlation view.
function MiniChart({ series }) {
  if (series.length < 2) return null;
  const norm = (vals) => {
    const mn = Math.min(...vals), mx = Math.max(...vals), span = mx - mn || 1;
    return vals.map((v) => 100 - ((v - mn) / span) * 96 - 2);
  };
  const sN = norm(series.map((d) => d.stock));
  const pN = norm(series.map((d) => d.spread));
  const X = (i) => (i / (series.length - 1)) * 100;
  const path = (arr) => arr.map((n, i) => `${i ? "L" : "M"}${X(i).toFixed(2)},${n.toFixed(2)}`).join(" ");
  return (
    <svg className="bs-trend" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Stock vs spread">
      <path d={path(sN)} fill="none" stroke="var(--yellow)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <path d={path(pN)} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

export default function BullionStock() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [selected, setSelected] = useState(null);        // correlation pair_name
  const [histCommodity, setHistCommodity] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
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

  // Fetch ONCE on mount — daily data, so no polling (keeps load near zero).
  useEffect(() => { load(); }, [load]);

  const fetchNow = useCallback(async () => {
    setFetching(true); setErr(null);
    try {
      const res = await api.bullionRefresh();
      if (!res?.ok && res?.status?.msg) setErr(`Fetch: ${res.status.msg}`);
      await load();
    } catch (e) {
      setErr(e.message || "Fetch failed");
    } finally {
      setFetching(false);
    }
  }, [load]);

  const openPdf = useCallback(async (download) => {
    setPdfBusy(true); setErr(null);
    try {
      const blob = await api.bullionPdf(download);
      const url = URL.createObjectURL(blob);
      if (download) {
        const a = document.createElement("a");
        a.href = url;
        a.download = data?.pdf_name || `mcxccl-bullion-${data?.as_on_date || "latest"}.pdf`;
        document.body.appendChild(a); a.click(); a.remove();
      } else {
        window.open(url, "_blank", "noopener");
      }
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(e.message || "PDF failed");
    } finally {
      setPdfBusy(false);
    }
  }, [data]);

  // Per-commodity day-over-day change (for the Δ column).
  const deltaFor = useCallback((commodity) => {
    const s = data?.stock_history?.[commodity];
    if (!s || s.length < 2) return null;
    return s[s.length - 1].units - s[s.length - 2].units;
  }, [data]);

  const selectedCorr = useMemo(
    () => data?.correlation?.find((c) => c.pair_name === selected) || data?.correlation?.[0],
    [data, selected]
  );
  const corrSeries = useMemo(() => {
    if (!data || !selectedCorr) return [];
    return buildSeries(data.spread_history?.[selectedCorr.pair_name], data.stock_history?.[selectedCorr.commodity]);
  }, [data, selectedCorr]);

  const commodities = useMemo(() => (data ? Object.keys(data.stock_history || {}) : []), [data]);
  const effHist = histCommodity && commodities.includes(histCommodity) ? histCommodity : commodities[0];
  const histSeries = data?.stock_history?.[effHist] || [];
  const histRows = useMemo(
    () => histSeries.map((d, i) => ({ date: d.date, units: d.units, delta: i > 0 ? d.units - histSeries[i - 1].units : null })).reverse(),
    [histSeries]
  );
  const histUnit = data?.latest?.find((r) => r.commodity === effHist)?.unit || "";
  const histLatest = histSeries.length ? histSeries[histSeries.length - 1].units : null;
  const histDelta = histSeries.length > 1 ? histSeries[histSeries.length - 1].units - histSeries[histSeries.length - 2].units : null;

  const stale = data?.stale_days;
  const staleBad = stale != null && stale > 5;

  const actions = (
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
  );

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
        {actions}
      </div>

      {err && <div className="bs-note bad">Error: {err}</div>}
      {!err && data && !data.latest?.length && (
        <div className="bs-note">No data yet — the daily scrape runs at <b>18:00 IST</b>. Press <b>Fetch now</b> to pull immediately.</div>
      )}

      {data?.latest?.length > 0 && (
        <>
          <div className="bs-grid">
            {/* Latest eligible units + 1-day change */}
            <div className="bs-card">
              <div className="bs-card-h">Eligible Units <span className="bs-muted">· {data.as_on_date}</span></div>
              <div className="bs-tbl-scroll">
                <table className="bs-table">
                  <thead><tr><th>Commodity</th><th>Unit</th><th className="num">Eligible Units</th><th className="num">Δ 1 day</th></tr></thead>
                  <tbody>
                    {data.latest.map((r) => (
                      <tr key={r.commodity} className={effHist === r.commodity ? "hl" : ""} onClick={() => setHistCommodity(r.commodity)} title="Show history">
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

            {/* Daily history for the selected commodity */}
            <div className="bs-card">
              <div className="bs-card-h">
                Daily Stock History
                {histSeries.length ? <span className="bs-muted"> · {histSeries.length} days</span> : null}
              </div>
              <div className="bs-chips">
                {commodities.map((c) => (
                  <button key={c} className={`bs-chip ${c === effHist ? "on" : ""}`} onClick={() => setHistCommodity(c)}>{c}</button>
                ))}
              </div>
              {histSeries.length >= 2 ? (
                <>
                  <div className="bs-hist-top">
                    <span className="bs-hist-val">{fmtNum(histLatest, 2)} <span className="bs-unit">{histUnit}</span></span>
                    <span className="bs-hist-delta"><Delta v={histDelta} /> <span className="bs-muted">vs prev day</span></span>
                  </div>
                  <StockTrend series={histSeries} />
                  <div className="bs-axis"><span>{histSeries[0].date}</span><span>{histSeries[histSeries.length - 1].date}</span></div>
                  <div className="bs-hist-scroll">
                    <table className="bs-table">
                      <thead><tr><th>Date</th><th className="num">Eligible Units</th><th className="num">Δ</th></tr></thead>
                      <tbody>
                        {histRows.map((r) => (
                          <tr key={r.date}><td>{r.date}</td><td className="num">{fmtNum(r.units, 2)}</td><td className="num"><Delta v={r.delta} /></td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="bs-note">Only one day of data so far — the chart builds as new daily files publish.</div>
              )}
            </div>
          </div>

          {/* Correlation strip */}
          <div className="bs-card bs-corr-card">
            <div className="bs-card-h">Stock ↔ Spread Correlation</div>
            {!data.correlation?.length ? (
              <div className="bs-note bs-slim">
                Building automatically — appears after a few days of history once the warehouse stock has changed. No action needed.
              </div>
            ) : (
              <div className="bs-corr-grid">
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
                {corrSeries.length >= 2 && (
                  <div>
                    <div className="bs-legend">
                      <span><i className="dot" style={{ background: "var(--yellow)" }} /> Stock</span>
                      <span><i className="dot" style={{ background: "var(--accent)" }} /> Spread</span>
                      <span className="bs-muted">{selectedCorr.pair}</span>
                    </div>
                    <MiniChart series={corrSeries} />
                    <div className="bs-axis"><span>{corrSeries[0].date}</span><span>{corrSeries[corrSeries.length - 1].date}</span></div>
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
