import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Webhook paper trades (client, 20-Aug). TradingView fires buy/sell webhooks;
// each becomes a DUMMY trade at that moment's exchange LTP, flipped by the
// opposite signal, one position per symbol. Nothing here is a real order.
//
// Three tabs, centred, exactly as asked: Live (open positions, running P/L),
// History (closed trades with the calculations), Log (every webhook received,
// the ignored and rejected ones with their reason - that column is how a
// mis-configured alert gets debugged). Symbol and side filters top right work
// on all three; everything is paginated.

const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) =>
  v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d);

// "19-08 6:04 PM" - the 12-hour Indian clock, date only when it is not today.
function when(iso) {
  if (!iso) return "—";
  const [d, t] = String(iso).split(" ");
  if (!t) return iso;
  const [hh, mm] = t.split(":");
  const h = Number(hh);
  const label = `${h % 12 === 0 ? 12 : h % 12}:${mm} ${h < 12 ? "AM" : "PM"}`;
  const today = new Date();
  const iso_today = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (d === iso_today) return label;
  const [, m, day] = d.split("-");
  return `${day}/${m} ${label}`;
}

function dur(s) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

// "2h 05m" since entry, ticking - a position card that shows its age reads as
// alive; a frozen timestamp reads as a report.
function liveDur(iso, nowMs) {
  if (!iso) return "";
  const t = new Date(String(iso).replace(" ", "T")).getTime();
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, Math.floor((nowMs - t) / 1000));
  return dur(s);
}

function SideTag({ side }) {
  const buyish = side === "long" || side === "buy";
  return <span className={`pt-side ${buyish ? "buy" : "sell"}`}>{(side || "").toUpperCase()}</span>;
}

function Pager({ page, pages, total, onPage }) {
  if (!total) return null;
  return (
    <div className="pt-pager">
      <span className="pt-pager-total">{total} total</span>
      <button type="button" className="oh-chip" disabled={page <= 1}
        onClick={() => onPage(page - 1)}>‹ Prev</button>
      <span className="pt-pager-page">page {page} / {pages}</span>
      <button type="button" className="oh-chip" disabled={page >= pages}
        onClick={() => onPage(page + 1)}>Next ›</button>
    </div>
  );
}

const VIEWS = [
  { key: "live", label: "Live" },
  { key: "history", label: "History" },
  { key: "log", label: "Log" },
];

export default function AutoTrades() {
  const [view, setView] = useState(() => {
    try { return localStorage.getItem("arbi_pt_view") || "live"; } catch { return "live"; }
  });
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [symbols, setSymbols] = useState([]);

  const [live, setLive] = useState(null);
  const [hist, setHist] = useState(null);
  const [logs, setLogs] = useState(null);
  const [histPage, setHistPage] = useState(1);
  const [logPage, setLogPage] = useState(1);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => { try { localStorage.setItem("arbi_pt_view", view); } catch {} }, [view]);
  // Filters reset their pagination - page 3 of a different filter is nonsense.
  useEffect(() => { setHistPage(1); setLogPage(1); }, [symbol, side]);

  // Live polls; the other two tabs are event-shaped data and fetch on demand.
  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.paperPositions();
        if (alive) { setLive(r); setSymbols(r.symbols || []); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
  }, []);

  useEffect(() => {
    if (view !== "history") return undefined;
    let alive = true;
    api.paperTrades({ symbol, side, page: histPage })
      .then((r) => { if (alive) { setHist(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [view, symbol, side, histPage]);

  useEffect(() => {
    if (view !== "log") return undefined;
    let alive = true;
    // History filters speak long/short; the log speaks buy/sell. One dropdown
    // serves both, translated here.
    const logSide = side === "long" ? "buy" : side === "short" ? "sell" : "";
    api.paperSignals({ symbol, side: logSide, page: logPage })
      .then((r) => { if (alive) { setLogs(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [view, symbol, side, logPage]);

  const positions = useMemo(() => {
    let p = live?.positions || [];
    if (symbol) p = p.filter((x) => x.symbol === symbol);
    if (side) p = p.filter((x) => x.side === side);
    return p;
  }, [live, symbol, side]);

  const runningPnl = useMemo(
    () => positions.reduce((a, x) => a + (x.pnl || 0), 0), [positions]);

  // The Live strip shows booked totals too, so the summary must exist before
  // anyone visits History - one light fetch, refreshed when a position closes
  // (the open-position count dropping is the only way one ever does).
  useEffect(() => {
    let alive = true;
    api.paperTrades({ symbol, side, page: 1, page_size: 5 })
      .then((r) => { if (alive) setHist((h) => (view === "history" ? h : r)); })
      .catch(() => {});
    return () => { alive = false; };
  }, [symbol, side, live?.positions?.length]);

  // One clock for every card's "since entry" - ticking once a second beats
  // 3-second jumps, and one interval beats one per card.
  const [nowMs, setNowMs] = useState(Date.now());
  useEffect(() => {
    if (view !== "live") return undefined;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [view]);

  const sum = hist?.summary;

  return (
    <div className="pt-page">
      <div className="nm-head">
        <div className="nm-head-left">
          <h2>Auto Trades</h2>
          <span className="intl-status on" title="Dummy trades fired by webhook, monitored on the live MCX feed. No real orders anywhere.">
            ● Paper only
          </span>
        </div>

        {/* centred, same level - the layout the client drew */}
        <div className="oh-group pt-tabs" role="tablist" aria-label="View">
          {VIEWS.map((v) => (
            <button key={v.key} type="button" role="tab" aria-selected={view === v.key}
              className={`oh-chip ${view === v.key ? "on" : ""}`}
              onClick={() => setView(v.key)}>{v.label}</button>
          ))}
        </div>

        <div className="nm-head-end pt-filters">
          <select className="oh-weeks" value={symbol} onChange={(e) => setSymbol(e.target.value)}
            aria-label="Symbol filter">
            <option value="">All symbols</option>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="oh-weeks" value={side} onChange={(e) => setSide(e.target.value)}
            aria-label="Side filter">
            <option value="">Buy + Sell</option>
            <option value="long">Buy (long)</option>
            <option value="short">Sell (short)</option>
          </select>
        </div>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      {view === "live" && (
        <>
          <div className="pt-strip">
            <div className="pt-stat">
              <em>Open positions</em>
              <b>{positions.length}</b>
            </div>
            <div className="pt-stat">
              <em>Running P/L ₹</em>
              <b className={runningPnl >= 0 ? "pos" : "neg"}>
                {positions.length ? signed(runningPnl) : "—"}
              </b>
            </div>
            <div className="pt-stat">
              <em>Closed trades</em>
              <b>{sum ? sum.trades : "—"}</b>
            </div>
            <div className="pt-stat">
              <em>Booked P/L ₹</em>
              <b className={sum && sum.pnl < 0 ? "neg" : "pos"}>{sum ? signed(sum.pnl) : "—"}</b>
            </div>
            <div className="pt-stat">
              <em>Win rate</em>
              <b>{sum && sum.win_rate != null ? `${sum.win_rate}%` : "—"}</b>
              <i>{sum ? `${sum.wins}W / ${sum.losses}L` : ""}</i>
            </div>
          </div>

          {positions.length === 0 ? (
            <div className="nmg-empty">
              <b>No open position{symbol ? ` on ${symbol}` : ""}</b>
              <span>
                The next webhook opens one at that moment's exchange price. Every
                signal, including ignored ones, appears in the Log tab.
              </span>
            </div>
          ) : (
            <div className="pt-cards">
              {positions.map((p) => {
                const up = (p.pnl ?? 0) >= 0;
                return (
                  <section className={`pt-card ${p.side}`} key={p.id}>
                    <div className="pt-card-top">
                      <div className="pt-card-id">
                        <b>{p.symbol}</b>
                        <SideTag side={p.side} />
                      </div>
                      <span className="pt-card-meta" title={p.contract || ""}>
                        {num(p.lots, 0)} lot{p.lots === 1 ? "" : "s"}
                        {p.timeframe ? ` · ${p.timeframe}` : ""}
                      </span>
                    </div>

                    <div className="pt-card-pnl">
                      <b className={up ? "pos" : "neg"}>{signed(p.pnl)}</b>
                      <em className={up ? "pos" : "neg"}>
                        {signed(p.points)} pts
                        {p.lot_units ? ` × ${num(p.lot_units, 0)}` : ""}
                      </em>
                    </div>

                    <div className="pt-card-px">
                      <div>
                        <em>Entry</em>
                        <b>{num(p.entry_ltp)}</b>
                        <i>{when(p.entry_time)}</i>
                      </div>
                      <span className={`pt-arrow ${up ? "pos" : "neg"}`}>→</span>
                      <div>
                        <em>LTP
                          <u className={`pt-dot ${p.ltp_age != null && p.ltp_age > 120 ? "stale" : ""}`}
                            title={p.ltp_age != null && p.ltp_age > 120
                              ? `price ${Math.round(p.ltp_age)}s old`
                              : "live from the exchange feed"} />
                        </em>
                        <b>{num(p.ltp)}</b>
                        <i>open {liveDur(p.entry_time, nowMs)}</i>
                      </div>
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}

      {view === "history" && (
        <section className="nmg-card">
          <div className="pt-tablewrap">
            <table className="cru-table pt-table">
              <thead>
                <tr>
                  <th>#</th><th>Symbol</th><th>Side</th><th>Lots</th><th>TF</th>
                  <th>Entry</th><th>Entry ₹</th><th>Exit</th><th>Exit ₹</th>
                  <th>Points</th><th>P/L ₹</th><th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {(hist?.rows || []).map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td className="pt-sym">{r.symbol}</td>
                    <td><SideTag side={r.side} /></td>
                    <td>{num(r.lots, 0)}</td>
                    <td>{r.timeframe || "—"}</td>
                    <td className="pt-time">{when(r.entry_time)}</td>
                    <td>{num(r.entry_ltp)}</td>
                    <td className="pt-time">{when(r.exit_time)}</td>
                    <td>{num(r.exit_ltp)}</td>
                    <td className={r.points >= 0 ? "pos" : "neg"}>{signed(r.points)}</td>
                    <td className={`pt-pnl ${r.pnl >= 0 ? "pos" : "neg"}`}>{signed(r.pnl)}</td>
                    <td>{dur(r.duration_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(hist?.rows || []).length === 0 && (
              <div className="nmg-empty"><b>No closed trades yet</b>
                <span>A trade closes when the opposite signal arrives for its symbol.</span></div>
            )}
          </div>
          <Pager page={hist?.page || 1} pages={hist?.pages || 1} total={hist?.total || 0}
            onPage={setHistPage} />
        </section>
      )}

      {view === "log" && (
        <section className="nmg-card">
          <div className="pt-tablewrap">
            <table className="cru-table pt-table">
              <thead>
                <tr>
                  <th>Received</th><th>Symbol</th><th>Side</th><th>Lots</th><th>TF</th>
                  <th>LTP used</th><th>Action</th><th>Reason</th><th>ms</th>
                </tr>
              </thead>
              <tbody>
                {(logs?.rows || []).map((r) => (
                  <tr key={r.id} className={`pt-act-${r.action}`}>
                    <td className="pt-time">{when(r.received_at)}</td>
                    <td className="pt-sym">{r.symbol || "—"}</td>
                    <td><SideTag side={r.side} /></td>
                    <td>{num(r.lots, 0)}</td>
                    <td>{r.timeframe || "—"}</td>
                    <td>{num(r.ltp)}</td>
                    <td><span className={`pt-act pt-act-${r.action}`}>{r.action}</span></td>
                    <td className="pt-reason">{r.reason || "—"}</td>
                    <td>{r.latency_ms ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(logs?.rows || []).length === 0 && (
              <div className="nmg-empty"><b>No webhooks received yet</b>
                <span>Every webhook lands here, including ignored and rejected ones,
                  with the reason.</span></div>
            )}
          </div>
          <Pager page={logs?.page || 1} pages={logs?.pages || 1} total={logs?.total || 0}
            onPage={setLogPage} />
        </section>
      )}
    </div>
  );
}
