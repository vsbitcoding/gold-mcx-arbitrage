import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Colour a correlation coefficient by strength + sign.
function corrColor(r) {
  if (Math.abs(r) < 0.3) return "var(--text-muted)";
  return r < 0 ? "var(--red)" : "var(--green)";
}
function corrText(r) {
  const a = Math.abs(r);
  const strength = a >= 0.7 ? "Strong" : a >= 0.4 ? "Moderate" : a >= 0.2 ? "Weak" : "No clear";
  if (strength === "No clear") return "no clear link";
  // r<0 ⇒ stock and spread move opposite ways.
  return r < 0 ? `${strength}: stock ↑ → spread ↓` : `${strength}: stock ↑ → spread ↑`;
}

// Align a pair's spread series with its commodity stock (forward-fill the
// lagging stock value to each spread date) — mirrors the backend.
function buildSeries(spreadHist, stockSeries) {
  if (!spreadHist || !stockSeries) return [];
  const out = [];
  for (const sp of spreadHist) {
    let stk = null;
    for (const r of stockSeries) {
      if (r.date <= sp.date) stk = r.units;
      else break;
    }
    if (stk != null) out.push({ date: sp.date, stock: stk, spread: sp.spread });
  }
  return out;
}

// Two normalised polylines (stock vs spread) — dependency-free inline SVG.
function MiniChart({ series }) {
  if (series.length < 2) return null;
  const W = 560, H = 150, padL = 6, padR = 6, padT = 12, padB = 16;
  const norm = (vals) => {
    const mn = Math.min(...vals), mx = Math.max(...vals), span = mx - mn || 1;
    return vals.map((v) => (v - mn) / span);
  };
  const sN = norm(series.map((d) => d.stock));
  const pN = norm(series.map((d) => d.spread));
  const X = (i) => padL + (i / (series.length - 1)) * (W - padL - padR);
  const Y = (n) => padT + (1 - n) * (H - padT - padB);
  const path = (arr) => arr.map((n, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(n).toFixed(1)}`).join(" ");
  return (
    <svg className="bs-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Stock vs spread">
      <path d={path(sN)} fill="none" stroke="var(--yellow)" strokeWidth="2" />
      <path d={path(pN)} fill="none" stroke="var(--accent)" strokeWidth="2" />
    </svg>
  );
}

// Single-series line chart of one commodity's eligible units over time.
function StockTrend({ series }) {
  if (!series || series.length < 2) return null;
  const W = 760, H = 210, padL = 72, padR = 16, padT = 14, padB = 26;
  const vals = series.map((d) => d.units);
  const mn = Math.min(...vals), mx = Math.max(...vals), span = (mx - mn) || 1;
  const X = (i) => padL + (i / (series.length - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - mn) / span) * (H - padT - padB);
  const path = series.map((d, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(d.units).toFixed(1)}`).join(" ");
  return (
    <svg className="bs-trend" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Daily stock history">
      {[mx, (mx + mn) / 2, mn].map((v, k) => (
        <g key={k}>
          <line x1={padL} y1={Y(v)} x2={W - padR} y2={Y(v)} stroke="var(--border-light)" strokeWidth="1" />
          <text x={padL - 8} y={Y(v) + 4} textAnchor="end" fontSize="12" fill="var(--text-muted)">{fmtNum(v, 0)}</text>
        </g>
      ))}
      <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2.5" />
      {series.map((d, i) => <circle key={i} cx={X(i)} cy={Y(d.units)} r="3" fill="var(--accent)" />)}
      <text x={padL} y={H - 6} fontSize="12" fill="var(--text-muted)">{series[0].date}</text>
      <text x={W - padR} y={H - 6} textAnchor="end" fontSize="12" fill="var(--text-muted)">{series[series.length - 1].date}</text>
    </svg>
  );
}

export default function BullionStock() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [selected, setSelected] = useState(null); // pair_name
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

  // Fetch ONCE on mount — the warehouse data changes ~once a day, so there is
  // no polling here (keeps server/DB load near zero).
  useEffect(() => { load(); }, [load]);

  // Trigger the scrape now (on-demand) — takes ~15-20s, then reload the report.
  const fetchNow = useCallback(async () => {
    setFetching(true);
    setErr(null);
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

  // View / Download the stored PDF. Fetched with the auth header → object URL.
  const openPdf = useCallback(async (download) => {
    setPdfBusy(true);
    setErr(null);
    try {
      const blob = await api.bullionPdf(download);
      const url = URL.createObjectURL(blob);
      if (download) {
        const a = document.createElement("a");
        a.href = url;
        a.download = data?.pdf_name || `mcxccl-bullion-${data?.as_on_date || "latest"}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
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

  const selectedCorr = useMemo(
    () => data?.correlation?.find((c) => c.pair_name === selected) || data?.correlation?.[0],
    [data, selected]
  );
  const chartSeries = useMemo(() => {
    if (!data || !selectedCorr) return [];
    return buildSeries(data.spread_history?.[selectedCorr.pair_name], data.stock_history?.[selectedCorr.commodity]);
  }, [data, selectedCorr]);

  // Daily stock history (per commodity), independent of the correlation.
  const commodities = useMemo(() => (data ? Object.keys(data.stock_history || {}) : []), [data]);
  const effHist = histCommodity && commodities.includes(histCommodity) ? histCommodity : commodities[0];
  const histSeries = data?.stock_history?.[effHist] || [];
  const histRows = useMemo(
    () => histSeries.map((d, i) => ({ date: d.date, units: d.units, delta: i > 0 ? d.units - histSeries[i - 1].units : null })).reverse(),
    [histSeries]
  );

  const stale = data?.stale_days;
  const staleBad = stale != null && stale > 35;

  return (
    <div className="bs-wrap">
      <div className="bs-head">
        <div>
          <h2 className="bs-title">Bullion Warehouse Stock <span className="bs-src">· MCXCCL</span></h2>
          <div className="bs-sub">
            {data?.as_on_date ? (
              <>As on <b>{data.as_on_date}</b>{" "}
                {stale != null && (
                  <span className={`bs-pill ${staleBad ? "bad" : "ok"}`}>{stale}d old</span>
                )}
              </>
            ) : "No stock fetched yet"}
          </div>
        </div>
        <div className="bs-actions">
          {data?.pdf_available && (
            <>
              <button className="btn btn-secondary btn-sm" onClick={() => openPdf(false)} disabled={pdfBusy}>
                👁 View PDF
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => openPdf(true)} disabled={pdfBusy}>
                ⬇ Download
              </button>
            </>
          )}
          <button className="btn btn-secondary btn-sm" onClick={load} disabled={loading}>
            {loading ? "Loading…" : "↻ Refresh"}
          </button>
          <button className="btn btn-primary btn-sm" onClick={fetchNow} disabled={fetching} title="Scrape MCXCCL now">
            {fetching ? "Fetching…" : "⟳ Fetch now"}
          </button>
        </div>
      </div>

      {err && <div className="bs-note bad">Error: {err}</div>}

      {!err && data && !data.latest?.length && (
        <div className="bs-note">
          No data yet. The daily scrape runs at <b>18:00 IST</b>.{" "}
          {data.status?.msg ? <span className="bs-muted">({data.status.msg})</span> : null}
        </div>
      )}

      {data?.latest?.length > 0 && (
        <>
        <div className="bs-grid">
          {/* Latest eligible units (the headline PDF numbers) */}
          <div className="bs-card">
            <div className="bs-card-h">Eligible Units</div>
            <table className="bs-table">
              <thead><tr><th>Commodity</th><th>Unit</th><th className="num">Eligible Units</th></tr></thead>
              <tbody>
                {data.latest.map((r) => (
                  <tr key={r.commodity}>
                    <td>{r.commodity}</td>
                    <td className="bs-unit">{r.unit}</td>
                    <td className="num">{fmtNum(r.eligible_units, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Stock ↔ spread correlation */}
          <div className="bs-card">
            <div className="bs-card-h">Stock ↔ Spread correlation</div>
            {!data.correlation?.length ? (
              <div className="bs-note">
                Building history. Correlation appears once we have a few days of spread
                snapshots <i>and</i> the warehouse stock has changed at least once.
              </div>
            ) : (
              <>
                <table className="bs-table bs-corr">
                  <thead><tr><th>Pair</th><th>Commodity</th><th className="num">Days</th><th className="num">r</th><th>Reading</th></tr></thead>
                  <tbody>
                    {data.correlation.map((c) => (
                      <tr
                        key={c.pair_name + c.commodity}
                        className={selectedCorr && c.pair_name === selectedCorr.pair_name && c.commodity === selectedCorr.commodity ? "sel" : ""}
                        onClick={() => setSelected(c.pair_name)}
                      >
                        <td>{c.pair}</td>
                        <td>{c.commodity}</td>
                        <td className="num">{c.n}</td>
                        <td className="num" style={{ color: corrColor(c.r), fontWeight: 700 }}>{c.r.toFixed(2)}</td>
                        <td className="bs-muted">{corrText(c.r)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {chartSeries.length >= 2 && (
                  <div className="bs-chart-wrap">
                    <div className="bs-legend">
                      <span><i className="dot" style={{ background: "var(--yellow)" }} /> Stock ({selectedCorr.commodity})</span>
                      <span><i className="dot" style={{ background: "var(--accent)" }} /> Spread ({selectedCorr.pair})</span>
                    </div>
                    <MiniChart series={chartSeries} />
                    <div className="bs-muted bs-axis">{chartSeries[0].date} → {chartSeries[chartSeries.length - 1].date}</div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Daily stock history — the day-by-day data the correlation is built on */}
        <div className="bs-card bs-history">
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
              <StockTrend series={histSeries} />
              <table className="bs-table bs-hist-tbl">
                <thead><tr><th>Date</th><th className="num">Eligible Units</th><th className="num">Δ vs prev day</th></tr></thead>
                <tbody>
                  {histRows.map((r) => (
                    <tr key={r.date}>
                      <td>{r.date}</td>
                      <td className="num">{fmtNum(r.units, 2)}</td>
                      <td className="num" style={{ color: r.delta == null ? "var(--text-muted)" : r.delta > 0 ? "var(--green)" : r.delta < 0 ? "var(--red)" : "var(--text-muted)" }}>
                        {r.delta == null ? "—" : (r.delta > 0 ? "▲ " : r.delta < 0 ? "▼ " : "") + fmtNum(Math.abs(r.delta), 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <div className="bs-note">Only one day of data so far — the history chart builds as new daily files publish.</div>
          )}
        </div>
        </>
      )}
    </div>
  );
}
