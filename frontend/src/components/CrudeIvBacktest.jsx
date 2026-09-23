import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";
import { EquityChart } from "./NseMcxBacktest.jsx";

// MCX vs NYMEX volatility backtest (client's note, 23-Sep): sell the option
// whose implied volatility is higher, buy the same strike on the other
// exchange, close when the gap narrows. Runs on the half-hourly boards the
// History view stores (since 19-Aug-2026). Every rule is a field here.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dmy = (iso) => (iso ? `${iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}` : "—");
const dmyt = (ts) => (ts ? `${dmy(ts.slice(0, 10))} ${ts.slice(11, 16)}` : "—");
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmtNum(Math.abs(v), d));
const rs = (v) => (v == null ? "—" : (v < 0 ? "−₹" : "₹") + fmtNum(Math.abs(v), 0));
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const PAGE = 25;
const KEY = "arbi_civ_bt_params";
const DEFAULTS = {
  start: "", end: "", entry_diff: 5, exit_diff: 3, direction: "both", sides: "both", strike_step: 500, otm_min: 0, otm_max: 0,
  exit_days: 5, stop_loss: 0, price_rule: "mid", lot_size: 100, max_positions: 0, exclude_wide: true,
};
const NG = { entry_diff: 5, exit_diff: 3, lot_size: 1250, strike_step: 0 };
// Which MCX strikes may open a trade (client, 23-Sep): the liquid crude strikes are the
// 500-multiples (7500, 8000, 8500); the stored crude ladder is 100 points, natural gas 5.
const STEP_CHOICES = {
  crude: [[500, "Liquid: 500 multiples (7500, 8000, 8500…)"], [1000, "1000 multiples (8000, 9000…)"], [0, "All strikes (100-point ladder)"]],
  natgas: [[0, "All strikes (5-point ladder)"], [10, "10 multiples (250, 260, 270…)"], [20, "20 multiples (260, 280, 300…)"], [50, "50 multiples (250, 300, 350…)"]],
};
const EXIT_LABEL = { "gap closed": "IV gap closed", "square off": "squared off before expiry", "stop loss": "stop loss", "data end": "still open, at latest board", "contract rolled": "contract rolled, last mark" };
const keyFor = (product) => `${KEY}_${product}`;
function loadParams(product) {
  const base = product === "natgas" ? { ...DEFAULTS, ...NG } : DEFAULTS;
  try { return { ...base, ...(JSON.parse(localStorage.getItem(keyFor(product)) || "{}")) }; } catch { return { ...base }; }
}

function Field({ label, hint, children }) {
  return <label className="bt-f"><span title={hint}>{label}</span>{children}</label>;
}

function TradePath({ t, lot, onClose }) {
  const curve = useMemo(() => (t.path || []).filter((x) => x.pnl != null).map((x) => ({ date: x.ts, cum_rs: x.pnl * lot })), [t, lot]);
  return (
    <div className="pt-overlay bsc-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pt-modal bsc-modal bt-modal" role="dialog" aria-label="Trade board by board">
        <div className="pt-modal-head">
          <div className="bsc-title">
            <span className="bsc-comm">MCX {fmtNum(t.mcx_strike, 0)} / NYMEX {num(t.us_strike, 1)} {t.side} <span className="bsc-pair-inl">· sell {t.sell_exch} @ {num(t.sell_px)} · buy {t.buy_exch} @ {num(t.buy_px)} (₹/bbl)</span></span>
            <span className="bsc-exp">Entered {dmyt(t.entry_ts)} · USD/INR fixed {num(t.usdinr, 2)} · expiry MCX {dmy(t.mcx_expiry)} / NYMEX {dmy(t.us_expiry)}</span>
          </div>
          <button type="button" className="pt-modal-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="bsc-body">
          <div className="bsc-summary bsc-summary-modal">
            <div className="bsc-stat"><span>Result</span><b className={cls(t.pnl_points)}>{signed(t.pnl_points)} pts</b><small>{rs(t.pnl_rs)} · {dmyt(t.exit_ts)} · {EXIT_LABEL[t.exit_reason] || t.exit_reason}</small></div>
            <div className="bsc-stat"><span>IV at entry</span><b>{num(t.mcx_iv, 1)} / {num(t.us_iv, 1)}</b><small>MCX / NYMEX · gap {signed(t.diff, 2)}</small></div>
            <div className="bsc-stat"><span>IV at exit</span><b>{t.exit_diff == null ? "—" : signed(t.exit_diff, 2)}</b><small>gap MCX − NYMEX</small></div>
            <div className="bsc-stat"><span>Held</span><b>{num(t.hours, 1)} h</b><small>{(t.path || []).length} boards</small></div>
          </div>
          {curve.length > 1 && <EquityChart curve={curve} byDay byTime />}
          <div className="bt-tablewrap bt-daily">
            <table className="nmd-table bt-table">
              <thead><tr><th>Board</th><th>MCX IV</th><th>NYMEX IV</th><th>Gap</th><th>P&L pts</th><th>P&L ₹</th><th>Note</th></tr></thead>
              <tbody>
                {(t.path || []).map((x, i) => (
                  <tr key={i} className={x.note ? "bt-daily-note" : ""}>
                    <td className="nmd-date">{dmyt(x.ts)}</td><td>{num(x.mcx_iv, 2)}</td><td>{num(x.us_iv, 2)}</td>
                    <td>{x.diff == null ? "—" : signed(x.diff, 2)}</td>
                    <td className={cls(x.pnl)}>{signed(x.pnl)}</td><td className={cls(x.pnl)}>{x.pnl == null ? "—" : rs(x.pnl * lot)}</td>
                    <td className="bt-why">{x.note || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function CrudeIvBacktest({ product, month }) {
  const [p, setP] = useState(() => loadParams(product));
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState("entry_ts");
  const [sortDir, setSortDir] = useState(1);
  const [detail, setDetail] = useState(null);
  const loadedFor = useRef(product);
  const runRef = useRef(null);
  useEffect(() => { if (loadedFor.current !== product) return; try { localStorage.setItem(keyFor(product), JSON.stringify(p)); } catch {} }, [p, product]);
  useEffect(() => { loadedFor.current = product; runRef.current?.controller.abort(); runRef.current = null; setBusy(false); setP(loadParams(product)); setRes(null); }, [product]);
  useEffect(() => () => runRef.current?.controller.abort(), []);
  const set = (k) => (e) => setP((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const invalid = (+p.exit_diff >= +p.entry_diff) ? "Exit IV gap must be smaller than the entry IV gap." : (+p.entry_diff <= 0) ? "Entry IV gap must be above zero." : (+p.lot_size <= 0) ? "Lot size must be above zero." : null;
  async function run() {
    if (invalid) { setErr(invalid); return; }
    runRef.current?.controller.abort();
    const controller = new AbortController();
    const mine = { controller, product, month };
    runRef.current = mine;
    setBusy(true); setErr(null);
    try {
      const body = { ...p, commodity: product, month, start: p.start || null, end: p.end || null };
      const r = await api.crudeIvBacktest(body, controller.signal);
      if (runRef.current !== mine || r?.params?.commodity !== product) return;
      setRes(r); setPage(1);
    } catch (e) { if (runRef.current === mine && !controller.signal.aborted) setErr(e.message); }
    finally { if (runRef.current === mine) { setBusy(false); runRef.current = null; } }
  }

  const trades = useMemo(() => {
    const t = (res?.trades || []).slice();
    t.sort((a, b) => { const x = a[sortKey], y = b[sortKey]; if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
    return t;
  }, [res, sortKey, sortDir]);
  const pages = Math.max(1, Math.ceil(trades.length / PAGE));
  const safe = Math.min(page, pages);
  const shown = trades.slice((safe - 1) * PAGE, safe * PAGE);
  const s = res?.summary; const cov = res?.coverage;
  const lot = +p.lot_size || 100;
  const th = (k, l) => <th onClick={() => { if (sortKey === k) setSortDir(-sortDir); else { setSortKey(k); setSortDir(1); } }} className="bt-sort">{l}{sortKey === k ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>;

  function downloadCsv() {
    const head = ["Entry", "Side", "MCX strike", "NYMEX strike", "USD/INR", "Sell on", "Sell price (native)", "Sell price (Rs/bbl)", "Buy on", "Buy price (native)", "Buy price (Rs/bbl)", "MCX IV", "NYMEX IV", "Gap at entry", "Exit", "Exit reason", "Gap at exit", "Sell exit", "Buy exit", "P&L points", "P&L Rs", "Hours"];
    const lines = [head.join(",")];
    trades.forEach((t) => lines.push([t.entry_ts, t.side, t.mcx_strike, t.us_strike, t.usdinr, t.sell_exch, t.sell_px_native, t.sell_px, t.buy_exch, t.buy_px_native, t.buy_px, t.mcx_iv, t.us_iv, t.diff, t.exit_ts || "", t.exit_reason || "", t.exit_diff ?? "", t.sell_exit ?? "", t.buy_exit ?? "", t.pnl_points ?? "", t.pnl_rs ?? "", t.hours ?? ""].join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `iv-backtest-${res?.params?.commodity || product}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  return (
    <div className="bt">
      <div className="bt-panel">
        <div className="bt-row">
          <Field label="From" hint="Blank = first stored board (19 Aug 2026)"><input type="date" className="oh-weeks" value={p.start} onChange={set("start")} /></Field>
          <Field label="To" hint="Blank = latest board"><input type="date" className="oh-weeks" value={p.end} onChange={set("end")} /></Field>
          <Field label="Entry IV gap (pts)" hint="Enter when |MCX IV − NYMEX IV| is at least this many points"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.entry_diff} onChange={set("entry_diff")} /></Field>
          <Field label="Exit IV gap (pts)" hint="Close when the gap has narrowed to this many points or less"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.exit_diff} onChange={set("exit_diff")} /></Field>
          <Field label="Direction" hint="Which side may have the higher IV">
            <select className="oh-weeks" value={p.direction} onChange={set("direction")}><option value="both">Both (sell the higher IV)</option><option value="mcx_high">MCX IV higher only (sell MCX, buy NYMEX)</option><option value="us_high">NYMEX IV higher only (sell NYMEX, buy MCX)</option></select></Field>
          <Field label="Side"><select className="oh-weeks" value={p.sides} onChange={set("sides")}><option value="both">Call + Put</option><option value="CE">Call only</option><option value="PE">Put only</option></select></Field>
          <Field label="Price rule" hint="How each leg is priced at entry and exit">
            <select className="oh-weeks" value={p.price_rule} onChange={set("price_rule")}><option value="mid">Mid price (fair)</option><option value="client">Buy at Bid, sell at Ask (favourable)</option><option value="market">Buy at Ask, sell at Bid (market)</option></select></Field>
        </div>
        <div className="bt-row">
          <Field label="MCX strikes" hint="Only these MCX strikes can open a trade; the NYMEX strike is always the matching one (MCX strike ÷ USD/INR)">
            <select className="oh-weeks" value={String(p.strike_step ?? 0)} onChange={set("strike_step")}>{(STEP_CHOICES[product] || STEP_CHOICES.crude).map(([v, l]) => <option key={v} value={String(v)}>{l}</option>)}</select></Field>
          <Field label="Strike from ATM (min pts)" hint="0 = no limit"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.otm_min} onChange={set("otm_min")} /></Field>
          <Field label="Strike from ATM (max pts)" hint="0 = any strike"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.otm_max} onChange={set("otm_max")} /></Field>
          <Field label="Square off (days before expiry)"><input type="number" min="0" className="oh-weeks bt-num" value={p.exit_days} onChange={set("exit_days")} /></Field>
          <Field label="Stop loss (pts)" hint="Points per barrel, 0 = off"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.stop_loss} onChange={set("stop_loss")} /></Field>
          <Field label="Lot size (bbl)" hint="Barrels per lot, both legs 1:1. ₹ = points × lot size"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.lot_size} onChange={set("lot_size")} /></Field>
          <Field label="Max open trades" hint="0 = no cap"><input type="number" min="0" className="oh-weeks bt-num" value={p.max_positions} onChange={set("max_positions")} /></Field>
          <div className="bt-checks">
            <label className="pt-symtick"><input type="checkbox" checked={!!p.exclude_wide} onChange={set("exclude_wide")} /> Skip wide (undealable) quotes</label>
          </div>
          <div className="bt-actions">
            <button type="button" className="oh-chip" onClick={() => setP(product === "natgas" ? { ...DEFAULTS, ...NG } : { ...DEFAULTS })}>Defaults</button>
            <button type="button" className="btn btn-primary" disabled={busy || !!invalid} title={invalid || ""} onClick={run}>{busy ? "Running…" : "Run backtest"}</button>
          </div>
        </div>
      </div>

      {(err || invalid) && <div className="settings-banner danger">⚠ {err || invalid}</div>}
      {!res && !busy && <div className="oh-note">Set the rules and press <b>Run backtest</b>. It replays every stored half-hourly board (since 19 Aug 2026, growing daily): on each chosen MCX strike (liquid 500-multiples by default), when the MCX and NYMEX implied volatilities differ by the entry gap, the higher-IV option is sold and the other bought at the matching strike; USD/INR and both strikes stay fixed until the gap closes, the square-off day, or the stop.</div>}
      {res && s.trades === 0 && <div className="oh-note"><b>No trade fired.</b> {cov.boards} boards from {dmyt(cov.first)} to {dmyt(cov.last)} never showed an IV gap of {p.entry_diff} points on a dealable strike of the chosen ladder. Lower the entry gap, allow all strikes, or allow wide quotes.</div>}
      {detail && <TradePath t={detail} lot={lot} onClose={() => setDetail(null)} />}
      {res && (
        <>
          <div className="bt-tiles">
            <div className="bt-tile"><span>Net P&L</span><b className={cls(s.pnl_rs)}>{rs(s.pnl_rs)}</b><small>{signed(s.pnl_points)} pts · ₹{lot} a point</small></div>
            <div className="bt-tile"><span>Trades</span><b>{s.trades}</b><small>{s.wins} won · {s.losses} lost{s.flat ? ` · ${s.flat} flat` : ""}</small></div>
            <div className="bt-tile"><span>Win rate</span><b>{s.win_rate == null ? "—" : `${s.win_rate}%`}</b><small>{Object.entries(s.exits || {}).map(([k, v]) => `${v} ${EXIT_LABEL[k] || k}`).join(" · ") || "—"}{s.unpriced_exits ? ` · ${s.unpriced_exits} exits marked by model or one side (no two-way quote)` : ""}</small></div>
            <div className="bt-tile"><span>Average trade</span><b className={cls(s.avg_points)}>{signed(s.avg_points)} pts</b><small>win {signed(s.avg_win)} · loss {signed(s.avg_loss)}</small></div>
            <div className="bt-tile"><span>Best / worst</span><b>{signed(s.best)} / {signed(s.worst)}</b><small>points</small></div>
            <div className="bt-tile"><span>Max drawdown</span><b className="neg">{rs(s.max_drawdown_rs)}</b><small>{signed(s.max_drawdown_points)} pts</small></div>
            <div className="bt-tile"><span>Data</span><b>{cov.days} days</b><small>{cov.boards} boards · {dmy(cov.first?.slice(0, 10))} to {dmy(cov.last?.slice(0, 10))} · avg hold {num(s.avg_hours, 1)} h</small></div>
          </div>
          {res.equity?.length > 1 && (
            <div className="bt-card"><div className="bs-card-h">Cumulative P&L (₹), trade by trade</div><EquityChart curve={res.equity} byDay byTime /></div>
          )}
          <div className="bt-card">
            <div className="bs-card-h bt-head">Trades <span className="bs-muted">click a column to sort · click a trade for its board by board IV gap and P&L</span>
              <button type="button" className="btn btn-primary btn-sm" onClick={downloadCsv}>Download CSV</button></div>
            <div className="bt-tablewrap">
              <table className="nmd-table bt-table">
                <thead><tr>
                  {th("entry_ts", "Entry")}{th("side", "Side")}{th("mcx_strike", "MCX strike")}{th("us_strike", "NYMEX strike")}<th>USD/INR</th>
                  <th>Sell on</th><th>Buy on</th>{th("diff", "IV gap")}{th("exit_ts", "Exit")}<th>Gap at exit</th><th>Exit prices</th>{th("pnl_points", "P&L pts")}{th("pnl_rs", "P&L ₹")}{th("hours", "Hours")}
                </tr></thead>
                <tbody>
                  {shown.map((t, i) => (
                    <tr key={i} className="bt-trow" onClick={() => setDetail(t)} title="Board by board">
                      <td className="nmd-date">{dmyt(t.entry_ts)}</td>
                      <td className={t.side === "CE" ? "pos" : "neg"}>{t.side}</td>
                      <td className="nmd-strike">{fmtNum(t.mcx_strike, 0)}</td>
                      <td>{num(t.us_strike, 1)}</td>
                      <td>{num(t.usdinr, 2)}</td>
                      <td>{t.sell_exch} @ {num(t.sell_px)}<small className="bt-sub">{t.sell_exch === "NYMEX" ? `$${num(t.sell_px_native)} · IV ${num(t.us_iv, 1)}` : `IV ${num(t.mcx_iv, 1)}`}</small></td>
                      <td>{t.buy_exch} @ {num(t.buy_px)}<small className="bt-sub">{t.buy_exch === "NYMEX" ? `$${num(t.buy_px_native)} · IV ${num(t.us_iv, 1)}` : `IV ${num(t.mcx_iv, 1)}`}</small></td>
                      <td>{signed(t.diff, 2)}</td>
                      <td>{dmyt(t.exit_ts)}<small className="bt-sub">{EXIT_LABEL[t.exit_reason] || t.exit_reason}{t.approx ? " · approx (model / one-sided)" : ""}</small></td>
                      <td>{t.exit_diff == null ? "—" : signed(t.exit_diff, 2)}</td>
                      <td>{num(t.sell_exit)} / {num(t.buy_exit)}</td>
                      <td className={cls(t.pnl_points)}>{signed(t.pnl_points)}</td>
                      <td className={cls(t.pnl_rs)}>{rs(t.pnl_rs)}</td>
                      <td>{num(t.hours, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="bsc-foot">
                <span className="bsc-foot-txt">{trades.length} trades · {PAGE} per page · prices in ₹ per barrel, NYMEX at the trade's fixed USD/INR · 1 lot each side</span>
                <span className="bsc-pager">
                  <button type="button" className="oh-chip" disabled={safe <= 1} onClick={() => setPage(1)}>«</button>
                  <button type="button" className="oh-chip" disabled={safe <= 1} onClick={() => setPage(safe - 1)}>‹</button>
                  <b>{safe} / {pages}</b>
                  <button type="button" className="oh-chip" disabled={safe >= pages} onClick={() => setPage(safe + 1)}>›</button>
                  <button type="button" className="oh-chip" disabled={safe >= pages} onClick={() => setPage(pages)}>»</button>
                </span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
