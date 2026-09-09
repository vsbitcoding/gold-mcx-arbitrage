import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Backtester for the NSE-vs-MCX premium arbitrage (client's notebook, 09-Sep).
// Every number from the notebook is a field here, so the client can re-run the
// past with his own thresholds. Runs on the daily closes since April 2024.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dmy = (iso) => (iso ? `${iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}` : "—");
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmtNum(Math.abs(v), d));
const rs = (v) => (v == null ? "—" : (v < 0 ? "−₹" : "₹") + fmtNum(Math.abs(v), 0));
const PAGE = 25;
const KEY = "arbi_nsemcx_bt_params";

const DEFAULTS = {
  start: "2024-04-01", end: "", expiry: "", sides: "both",
  threshold_same: 25, threshold_gap: 60, otm_min: 300, otm_max: 800, strike_step: 100,
  mode: "hold", move_points: 500, point_value: 100, multi: false, liquid_only: true, pick: "max",
  entry_days: 30, exit_days: 10, loss_roll: true, roll_days: 1, roll_legs: "both", max_rolls: 0,
};
const EXIT_LABEL = {
  "square off": "squared off before expiry", expiry: "at expiry", adjusted: "closed on adjustment",
  "data end": "still open, at latest close", "last price": "at latest close",
};

function Field({ label, hint, children }) {
  return <label className="bt-f"><span title={hint}>{label}</span>{children}</label>;
}

function EquityChart({ curve }) {
  const box = useRef(null);
  const [W, setW] = useState(900);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setW(Math.max(320, el.clientWidth)));
    ro.observe(el); setW(Math.max(320, el.clientWidth));
    return () => ro.disconnect();
  }, []);
  const H = 200, padL = 70, padR = 16, padT = 12, padB = 26;
  const geo = useMemo(() => {
    if (!curve || curve.length < 2) return null;
    const vals = curve.map((c) => c.cum_rs);
    let lo = Math.min(...vals, 0), hi = Math.max(...vals, 0);
    if (hi === lo) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const x = (i) => padL + (i / (curve.length - 1)) * (W - padL - padR);
    const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
    const path = curve.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(c.cum_rs).toFixed(1)}`).join(" ");
    const area = `M${x(0).toFixed(1)},${y(0).toFixed(1)} ` + curve.map((c, i) => `L${x(i).toFixed(1)},${y(c.cum_rs).toFixed(1)}`).join(" ") + ` L${x(curve.length - 1).toFixed(1)},${y(0).toFixed(1)} Z`;
    const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
    const xt = []; let last = "";
    curve.forEach((c, i) => { const m = (c.date || "").slice(0, 7); if (m && m !== last) { last = m; xt.push({ x: x(i), label: `${MONTHS[+c.date.slice(5, 7) - 1]} ${c.date.slice(2, 4)}` }); } });
    return { x, y, path, area, ticks, xt: xt.filter((_, i) => i % Math.ceil(xt.length / 14) === 0), zero: y(0) };
  }, [curve, W]);
  if (!geo) return null;
  return (
    <div className="bt-chart" ref={box}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="bsc-svg" style={{ height: H }} role="img" aria-label="Cumulative profit">
        {geo.ticks.map((v, i) => <g key={i}><line x1={padL} x2={W - padR} y1={geo.y(v)} y2={geo.y(v)} className="bsc-grid" /><text x={padL - 8} y={geo.y(v) + 4} className="bsc-ax bsc-ax-l">{fmtNum(v, 0)}</text></g>)}
        <line x1={padL} x2={W - padR} y1={geo.zero} y2={geo.zero} className="nmd-zero" />
        {geo.xt.map((t, i) => <text key={i} x={t.x} y={H - 8} className="bsc-ax bsc-ax-x">{t.label}</text>)}
        <path d={geo.area} className="bt-area" />
        <path d={geo.path} className="bsc-line bt-line" />
      </svg>
    </div>
  );
}

export default function NseMcxBacktest({ product, cfg }) {
  const [p, setP] = useState(() => {
    try { return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) || "{}")) }; } catch { return { ...DEFAULTS }; }
  });
  const [exps, setExps] = useState([]);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState("entry_date");
  const [sortDir, setSortDir] = useState(1);
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch {} }, [p]);
  useEffect(() => { api.nseMcxDailyExpiries(product).then((r) => setExps(r.expiries || [])).catch(() => {}); }, [product]);
  const set = (k) => (e) => setP((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function run() {
    setBusy(true); setErr(null);
    try {
      const body = { ...p, commodity: product, end: p.end || null, expiry: p.expiry || null };
      const r = await api.nseMcxBacktest(body);
      setRes(r); setPage(1);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  const trades = useMemo(() => {
    const t = (res?.trades || []).slice();
    t.sort((a, b) => { const x = a[sortKey], y = b[sortKey]; if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
    return t;
  }, [res, sortKey, sortDir]);
  const pages = Math.max(1, Math.ceil(trades.length / PAGE));
  const safe = Math.min(page, pages);
  const shown = trades.slice((safe - 1) * PAGE, safe * PAGE);
  const s = res?.summary;
  const th = (k, l) => <th onClick={() => { if (sortKey === k) setSortDir(-sortDir); else { setSortKey(k); setSortDir(1); } }} className="bt-sort">{l}{sortKey === k ? (sortDir > 0 ? " ▲" : " ▼") : ""}</th>;

  function downloadCsv() {
    const head = ["Entry date", "NSE expiry", "MCX expiry", "Side", "Strike", "Buy on", "Buy premium", "Sell on", "Sell premium", "Diff", "Entry future", "Reason", "Exit date", "Exit reason", "Buy exit", "Sell exit", "Shifts", "Final NSE expiry", "Final MCX expiry", "P&L points", "P&L Rs", "Days"];
    const lines = [head.join(",")];
    trades.forEach((t) => lines.push([t.entry_date, t.nse_expiry, t.mcx_expiry, t.side, t.strike, t.buy_exch, t.buy_px, t.sell_exch, t.sell_px, t.diff, t.entry_future ?? "", t.reason, t.exit_date ?? "", t.exit_reason ?? "", t.buy_exit ?? "", t.sell_exit ?? "", t.rolls, t.exit_nse_expiry, t.exit_mcx_expiry, t.pnl_points ?? "", t.pnl_rs ?? "", t.days ?? ""].join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `backtest-${product}-${p.mode}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  return (
    <div className="bt">
      <div className="bt-panel">
        <div className="bt-row">
          <Field label="From"><input type="date" className="oh-weeks" value={p.start} onChange={set("start")} /></Field>
          <Field label="To" hint="Blank = today"><input type="date" className="oh-weeks" value={p.end} onChange={set("end")} /></Field>
          <Field label="NSE expiry" hint="One contract, or every expiry in the range">
            <select className="oh-weeks" value={p.expiry} onChange={set("expiry")}>
              <option value="">All expiries in range</option>
              {exps.map((e) => <option key={e.nse} value={e.nse}>{dmy(e.nse)} (MCX {dmy(e.mcx)})</option>)}
            </select></Field>
          <Field label="Side"><select className="oh-weeks" value={p.sides} onChange={set("sides")}><option value="both">Call + Put</option><option value="CE">Call only</option><option value="PE">Put only</option></select></Field>
          <Field label="Mode" hint="hold = run to expiry; roll = on a move close the old strike and take the new one; add = keep the old and add the new">
            <select className="oh-weeks" value={p.mode} onChange={set("mode")}><option value="hold">Hold to expiry (a)</option><option value="roll">Adjust: new strike, old closed (b1)</option><option value="add">Adjust: new strike, old kept (b2)</option></select></Field>
          <Field label="Move trigger (pts)" hint="Future move after entry that adjusts the strike (down hurts CE, up hurts PE)"><input type="number" className="oh-weeks bt-num" value={p.move_points} onChange={set("move_points")} disabled={p.mode === "hold"} /></Field>
        </div>
        <div className="bt-row">
          <Field label="Diff, same expiry" hint="Minimum premium difference (points) when both expiries fall on one day"><input type="number" className="oh-weeks bt-num" value={p.threshold_same} onChange={set("threshold_same")} /></Field>
          <Field label="Diff, 7-day gap" hint="Minimum premium difference (points) when the expiries are a week apart"><input type="number" className="oh-weeks bt-num" value={p.threshold_gap} onChange={set("threshold_gap")} /></Field>
          <Field label="OTM from (pts)" hint="Nearest strike considered, points from the day's ATM"><input type="number" className="oh-weeks bt-num" value={p.otm_min} onChange={set("otm_min")} /></Field>
          <Field label="OTM to (pts)"><input type="number" className="oh-weeks bt-num" value={p.otm_max} onChange={set("otm_max")} /></Field>
          <Field label="Strike step" hint="100 = every hundred, 500 = the round ones (5000, 5500...)"><select className="oh-weeks" value={p.strike_step} onChange={set("strike_step")}><option value="100">100</option><option value="500">500</option></select></Field>
          <Field label="₹ per point"><input type="number" className="oh-weeks bt-num" value={p.point_value} onChange={set("point_value")} /></Field>
          <Field label="Pick" hint="Which strike when several qualify"><select className="oh-weeks" value={p.pick} onChange={set("pick")}><option value="max">Widest difference</option><option value="near">Nearest to ATM</option></select></Field>
          <div className="bt-checks">
            <label className="pt-symtick"><input type="checkbox" checked={!!p.liquid_only} onChange={set("liquid_only")} /> Traded on both exchanges</label>
            <label className="pt-symtick"><input type="checkbox" checked={!!p.multi} onChange={set("multi")} /> Several strikes per side</label>
          </div>
        </div>
        <div className="bt-row">
          <Field label="Entry window (days)" hint="Enter only when the first expiry is this many days away or less. 0 = any day"><input type="number" min="0" className="oh-weeks bt-num" value={p.entry_days} onChange={set("entry_days")} /></Field>
          <Field label="Square off (days before)" hint="Square off this many days before the first expiry. 0 = on the expiry day"><input type="number" min="0" className="oh-weeks bt-num" value={p.exit_days} onChange={set("exit_days")} /></Field>
          <div className="bt-checks">
            <label className="pt-symtick"><input type="checkbox" checked={!!p.loss_roll} onChange={set("loss_roll")} /> In loss: shift to next expiry</label>
          </div>
          <Field label="Shift (days before)" hint="A losing leg shifts to its next expiry this many days before its own expiry (NSE leg at NSE expiry, MCX leg at MCX expiry)"><input type="number" min="0" className="oh-weeks bt-num" value={p.roll_days} onChange={set("roll_days")} disabled={!p.loss_roll} /></Field>
          <Field label="Shift legs"><select className="oh-weeks" value={p.roll_legs} onChange={set("roll_legs")} disabled={!p.loss_roll}><option value="both">NSE and MCX</option><option value="NSE">NSE only</option><option value="MCX">MCX only</option></select></Field>
          <Field label="Max shifts" hint="How many times one trade may shift. 0 = no limit"><input type="number" min="0" className="oh-weeks bt-num" value={p.max_rolls} onChange={set("max_rolls")} disabled={!p.loss_roll} /></Field>
          <div className="bt-actions">
            <button type="button" className="oh-chip" onClick={() => setP({ ...DEFAULTS })}>Defaults</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={run}>{busy ? "Running…" : "Run backtest"}</button>
          </div>
        </div>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {!res && !busy && <div className="oh-note">Set the rules above and press <b>Run backtest</b>. It replays every day since April 2024 on closing prices: buy the option where it is cheaper, sell it where it is dearer, square both before the first expiry when in profit, or shift a losing trade to the next expiry.</div>}
      {res && (
        <>
          <div className="bt-tiles">
            <div className="bt-tile"><span>Net P&L</span><b className={s.pnl_rs > 0 ? "pos" : s.pnl_rs < 0 ? "neg" : ""}>{rs(s.pnl_rs)}</b><small>{signed(s.pnl_points)} pts</small></div>
            <div className="bt-tile"><span>Trades</span><b>{s.trades}</b><small>{s.wins} won · {s.losses} lost{s.flat ? ` · ${s.flat} flat` : ""}{s.rolled_trades ? ` · ${s.rolled_trades} shifted` : ""}</small></div>
            <div className="bt-tile"><span>Win rate</span><b>{s.win_rate == null ? "—" : `${s.win_rate}%`}</b><small>{res.summary.expiries} expiries</small></div>
            <div className="bt-tile"><span>Average trade</span><b className={s.avg_points > 0 ? "pos" : s.avg_points < 0 ? "neg" : ""}>{signed(s.avg_points)} pts</b><small>win {signed(s.avg_win)} · loss {signed(s.avg_loss)}</small></div>
            <div className="bt-tile"><span>Best / worst</span><b>{signed(s.best)} / {signed(s.worst)}</b><small>points</small></div>
            <div className="bt-tile"><span>Max drawdown</span><b className="neg">{rs(s.max_drawdown_rs)}</b><small>{signed(s.max_drawdown_points)} pts</small></div>
            <div className="bt-tile"><span>Avg days held</span><b>{num(s.avg_days, 1)}</b><small>entry to exit</small></div>
          </div>
          {res.equity?.length > 1 && (
            <div className="bt-card">
              <div className="bs-card-h">Cumulative P&L (₹), trade by trade</div>
              <EquityChart curve={res.equity} />
            </div>
          )}
          <div className="bt-two">
            <div className="bt-card">
              <div className="bs-card-h">By expiry</div>
              <div className="bt-tablewrap">
                <table className="nmd-table bt-table">
                  <thead><tr><th>NSE expiry</th><th>MCX expiry</th><th>Gap</th><th>Diff rule</th><th>Days</th><th>Trades</th><th>Won</th><th>Shifts</th><th>P&L pts</th><th>P&L ₹</th></tr></thead>
                  <tbody>
                    {res.by_expiry.slice().reverse().map((e) => (
                      <tr key={e.nse_expiry} className={e.trades ? "" : "nmd-dim"}>
                        <td>{dmy(e.nse_expiry)}</td><td>{dmy(e.mcx_expiry)}</td><td>{e.gap_days}d</td><td>≥ {e.threshold}</td><td>{e.days}</td><td>{e.trades}</td><td>{e.wins}</td><td>{e.rolls || "—"}</td>
                        <td className={e.pnl_points > 0 ? "pos" : e.pnl_points < 0 ? "neg" : ""}>{signed(e.pnl_points)}</td>
                        <td className={e.pnl_rs > 0 ? "pos" : e.pnl_rs < 0 ? "neg" : ""}>{rs(e.pnl_rs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div className="bt-card">
            <div className="bs-card-h bt-head">Trades <span className="bs-muted">click a column to sort</span>
              <button type="button" className="btn btn-primary btn-sm" onClick={downloadCsv}>Download CSV</button></div>
            <div className="bt-tablewrap">
              <table className="nmd-table bt-table">
                <thead><tr>
                  {th("entry_date", "Entry")}{th("nse_expiry", "Expiry NSE / MCX")}{th("side", "Side")}{th("strike", "Strike")}
                  <th>Buy on</th><th>Sell on</th>{th("diff", "Diff")}{th("entry_future", "Future")}<th>Why</th>
                  {th("exit_date", "Exit")}<th>Exit prices</th>{th("pnl_points", "P&L pts")}{th("pnl_rs", "P&L ₹")}{th("days", "Days")}
                </tr></thead>
                <tbody>
                  {shown.map((t, i) => (
                    <tr key={i}>
                      <td className="nmd-date">{dmy(t.entry_date)}</td>
                      <td>{dmy(t.nse_expiry)} / {dmy(t.mcx_expiry)}</td>
                      <td className={t.side === "CE" ? "pos" : "neg"}>{t.side}</td>
                      <td className="nmd-strike">{fmtNum(t.strike, 0)}</td>
                      <td>{t.buy_exch} @ {num(t.buy_px)}</td>
                      <td>{t.sell_exch} @ {num(t.sell_px)}</td>
                      <td>{signed(t.diff)}</td>
                      <td>{num(t.entry_future, 0)}</td>
                      <td className="bt-why">{t.reason === "adjust" ? `adjusted from ${t.parent}` : "signal"}
                        {t.rolls > 0 && <small className="bt-sub">{t.roll_log.map((r) => `${r.exch} ${dmy(r.date)} → ${dmy(r.to)}`).join(", ")}</small>}</td>
                      <td>{dmy(t.exit_date)}<small className="bt-sub">{EXIT_LABEL[t.exit_reason] || t.exit_reason}{t.rolls > 0 ? ` · ${t.rolls} shift${t.rolls > 1 ? "s" : ""}` : ""}</small></td>
                      <td>{num(t.buy_exit)} / {num(t.sell_exit)}</td>
                      <td className={t.pnl_points > 0 ? "pos" : t.pnl_points < 0 ? "neg" : ""}>{signed(t.pnl_points)}</td>
                      <td className={t.pnl_rs > 0 ? "pos" : t.pnl_rs < 0 ? "neg" : ""}>{rs(t.pnl_rs)}</td>
                      <td>{t.days ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="bsc-foot">
                <span className="bsc-foot-txt">{trades.length} trades · {PAGE} per page · closing prices, 1 lot each side, ₹{p.point_value} per point</span>
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
