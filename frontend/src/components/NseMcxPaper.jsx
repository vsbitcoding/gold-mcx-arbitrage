import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, getRole } from "../api/client.js";
import { fmtNum } from "../utils/format.js";
import { TradeDetail, EXIT_LABEL, dmy } from "./NseMcxBacktest.jsx";

// Live PAPER trading of the NSE-vs-MCX premium arbitrage (client, 10-Sep):
// the backtest's rules on the live quotes of both exchanges. Never a real
// order. The engine runs on the server; this screen shows what it sees, what
// it holds and what it did, and lets the admin set the rules and start / stop.

const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmtNum(Math.abs(v), d));
const rs = (v) => (v == null ? "—" : (v < 0 ? "−₹" : "₹") + fmtNum(Math.abs(v), 0));
const hm = (iso) => (iso ? `${dmy(iso.slice(0, 10))} ${iso.slice(11, 16)}` : "—");
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const STEPS = { crude: [100, 500], natgas: [5, 10] };
const LABEL = { signal: "signal", "add lot": "add lot", adjust: "adjusted", manual: "closed by hand", carry: "carried", shift: "shifted", exit: "exit", start: "started", stop: "stopped", settings: "rules changed", clear: "cleared" };

function Field({ label, hint, children }) {
  return <label className="bt-f"><span title={hint}>{label}</span>{children}</label>;
}

function Rules({ product, params, admin, onSave }) {
  const [p, setP] = useState(params);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!dirty) setP(params); }, [params, dirty]);
  const set = (k) => (e) => { setDirty(true); setP((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value })); };
  async function save() {
    setBusy(true);
    try { await onSave(p); setDirty(false); } finally { setBusy(false); }
  }
  const dis = !admin;
  return (
    <div className="bt-panel pp-rules">
      <div className="bt-row">
        <Field label="Side"><select className="oh-weeks" value={p.sides} onChange={set("sides")} disabled={dis}><option value="both">Call + Put</option><option value="CE">Call only</option><option value="PE">Put only</option></select></Field>
        <Field label="Mode" hint="hold = no strike change; roll = on a move close the old strike and take the new one; add = keep the old and add the new">
          <select className="oh-weeks" value={p.mode} onChange={set("mode")} disabled={dis}><option value="hold">Hold to expiry (a)</option><option value="roll">Adjust: new strike, old closed (b1)</option><option value="add">Adjust: new strike, old kept (b2)</option></select></Field>
        <Field label="Move trigger (pts)"><input type="number" step="any" className="oh-weeks bt-num" value={p.move_points} onChange={set("move_points")} disabled={dis || p.mode === "hold"} /></Field>
        <Field label="Diff, same expiry" hint="Minimum difference (sell side ask minus buy side bid) when both expiries fall on one day"><input type="number" step="any" className="oh-weeks bt-num" value={p.threshold_same} onChange={set("threshold_same")} disabled={dis} /></Field>
        <Field label="Diff, different expiry"><input type="number" step="any" className="oh-weeks bt-num" value={p.threshold_gap} onChange={set("threshold_gap")} disabled={dis} /></Field>
        <Field label="OTM from (pts)"><input type="number" step="any" className="oh-weeks bt-num" value={p.otm_min} onChange={set("otm_min")} disabled={dis} /></Field>
        <Field label="OTM to (pts)"><input type="number" step="any" className="oh-weeks bt-num" value={p.otm_max} onChange={set("otm_max")} disabled={dis} /></Field>
        <Field label="Strike step"><select className="oh-weeks" value={p.strike_step} onChange={set("strike_step")} disabled={dis}>{(STEPS[product] || STEPS.crude).map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
        <Field label="₹ per point"><input type="number" step="any" className="oh-weeks bt-num" value={p.point_value} onChange={set("point_value")} disabled={dis} /></Field>
        <Field label="Pick"><select className="oh-weeks" value={p.pick} onChange={set("pick")} disabled={dis}><option value="max">Widest difference</option><option value="near">Nearest to ATM</option></select></Field>
      </div>
      <div className="bt-row">
        <Field label="Entry window (days)" hint="Enter only when the first expiry is this many days away or less. 0 = any day"><input type="number" min="0" className="oh-weeks bt-num" value={p.entry_days} onChange={set("entry_days")} disabled={dis} /></Field>
        <Field label="Take profit (pts)" hint="Close a lot the moment its open profit reaches this. 0 = off"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.take_profit} onChange={set("take_profit")} disabled={dis} /></Field>
        <Field label="Square off (days before)" hint="From this many days before the first expiry a profitable lot closes; a losing one is carried when shifting is on"><input type="number" min="0" className="oh-weeks bt-num" value={p.exit_days} onChange={set("exit_days")} disabled={dis} /></Field>
        <Field label="Add lot every (pts)" hint="While the strike is still OTM, one more lot each time the difference widens by this much. 0 = off"><input type="number" step="any" min="0" className="oh-weeks bt-num" value={p.add_step} onChange={set("add_step")} disabled={dis} /></Field>
        <Field label="Max lots" hint="Lots per strike including the first. 0 = no cap"><input type="number" min="0" className="oh-weeks bt-num" value={p.max_lots} onChange={set("max_lots")} disabled={dis} /></Field>
        <div className="bt-checks">
          <label className="pt-symtick"><input type="checkbox" checked={!!p.loss_roll} onChange={set("loss_roll")} disabled={dis} /> In loss: shift to next expiry</label>
          <label className="pt-symtick"><input type="checkbox" checked={!!p.multi} onChange={set("multi")} disabled={dis} /> Several strikes per side</label>
        </div>
        <Field label="Shift (days before)"><input type="number" min="0" className="oh-weeks bt-num" value={p.roll_days} onChange={set("roll_days")} disabled={dis || !p.loss_roll} /></Field>
        <Field label="Shift legs"><select className="oh-weeks" value={p.roll_legs} onChange={set("roll_legs")} disabled={dis || !p.loss_roll}><option value="both">NSE and MCX</option><option value="NSE">NSE only</option><option value="MCX">MCX only</option></select></Field>
        <Field label="Max shifts" hint="0 = never shift (a loss squares off too)"><input type="number" min="0" className="oh-weeks bt-num" value={p.max_rolls} onChange={set("max_rolls")} disabled={dis || !p.loss_roll} /></Field>
        {admin && (
          <div className="bt-actions">
            {dirty && <button type="button" className="oh-chip" onClick={() => { setP(params); setDirty(false); }}>Discard</button>}
            <button type="button" className="btn btn-primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save rules"}</button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function NseMcxPaper({ product }) {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState(null);
  const [detail, setDetail] = useState(null);
  const [flash, setFlash] = useState(null);
  const lastEvent = useRef(null);
  const admin = getRole() === "admin";

  useEffect(() => {
    let alive = true, timer = null;
    lastEvent.current = null; setSt(null);
    async function load() {
      try {
        const r = await api.nseMcxPaper(product);
        if (!alive) return;
        setSt(r); setErr(null);
        const ev = r.events?.[r.events.length - 1];
        if (ev && lastEvent.current != null && ev.id !== lastEvent.current && ["signal", "add lot", "adjust", "exit", "shift"].includes(ev.kind)) {
          setFlash(ev); setTimeout(() => setFlash((f) => (f === ev ? null : f)), 12000);
        }
        if (ev) lastEvent.current = ev.id;
      } catch (e) { if (alive) setErr(e.message); }
    }
    const start = () => { if (!timer) timer = setInterval(load, 5000); };
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
    const onVis = () => { if (document.hidden) stop(); else { load(); start(); } };
    load(); start();
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; stop(); document.removeEventListener("visibilitychange", onVis); };
  }, [product]);

  async function act(fn, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    try { await fn(); const r = await api.nseMcxPaper(product); setSt(r); setErr(null); }
    catch (e) { setErr(e.message); }
  }

  const s = st?.summary;
  const pv = st?.params?.point_value || 100;
  const openRows = useMemo(() => (st?.open || []).slice().sort((a, b) => (a.entry_time < b.entry_time ? 1 : -1)), [st]);
  const closedRows = st?.closed || [];
  const pv_ = st?.preview;

  function downloadCsv() {
    const head = ["Entry", "Side", "Strike", "Reason", "Buy on", "Buy price", "Sell on", "Sell price", "Diff", "Shifts", "Exit", "Exit reason", "Buy exit", "Sell exit", "P&L points", "P&L Rs"];
    const lines = [head.join(",")];
    closedRows.forEach((t) => lines.push([t.entry_time, t.side, t.strike, t.reason, t.buy_exch, t.buy_px, t.sell_exch, t.sell_px, t.diff, t.rolls, t.exit_time || "", t.exit_reason || "", t.buy_exit ?? "", t.sell_exit ?? "", t.pnl_points ?? "", t.pnl_rs ?? ""].join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `paper-${product}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  if (!st && !err) return <div className="oh-note">Loading paper trading…</div>;

  return (
    <div className="bt pp">
      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {flash && <div className="pp-flash"><b>{LABEL[flash.kind] || flash.kind}</b> · {flash.text} <small>{flash.time.slice(11, 16)}</small></div>}
      {st && (
        <>
          <div className="pp-bar">
            <span className={`pp-pill ${st.enabled ? "on" : ""}`}>{st.enabled ? "● Running" : "○ Stopped"}</span>
            <span className={`pp-pill ${st.market_open ? "on" : ""}`}>{st.market_open ? "Market open" : "Market closed"}</span>
            {st.book?.nse_expiry && <span className="pp-info">NSE {dmy(st.book.nse_expiry)} · MCX {dmy(st.book.mcx_expiry)} · future {num(st.book.future, 1)} · ATM {num(st.book.atm, 0)}{st.book.fresh === false ? " · quotes stale" : ""}</span>}
            <span className="pp-info">last check {st.last_check ? st.last_check.slice(11, 19) : "—"} · every {st.poll_seconds}s{st.last_error ? ` · ${st.last_error}` : ""}</span>
            {admin && (
              <span className="pp-actions">
                <button type="button" className={`btn btn-sm ${st.enabled ? "" : "btn-primary"}`} onClick={() => act(() => api.nseMcxPaperEnable(product, !st.enabled), st.enabled ? "Stop paper trading? Open lots stay open and are not marked until you start again." : null)}>{st.enabled ? "Stop" : "Start paper trading"}</button>
                <button type="button" className="oh-chip" disabled={!openRows.length} onClick={() => act(() => api.nseMcxPaperCloseAll(product), "Close every open lot at the current prices?")}>Close all</button>
                <button type="button" className="oh-chip" onClick={() => act(() => api.nseMcxPaperClear(product), "Delete the whole paper history of this commodity? This cannot be undone.")}>Clear history</button>
              </span>
            )}
          </div>

          <Rules product={product} params={st.params} admin={admin} onSave={(p) => act(() => api.nseMcxPaperSettings(product, p))} />

          <div className="bt-tiles pp-tiles">
            <div className="bt-tile"><span>Open lots</span><b>{s.open_lots}</b><small>live on both exchanges</small></div>
            <div className="bt-tile"><span>Open P&L</span><b className={cls(s.open_rs)}>{rs(s.open_rs)}</b><small>{signed(s.open_points)} pts</small></div>
            <div className="bt-tile"><span>Closed trades</span><b>{s.closed}</b><small>{s.wins} won · win rate {s.win_rate == null ? "—" : `${s.win_rate}%`}</small></div>
            <div className="bt-tile"><span>Closed P&L</span><b className={cls(s.closed_rs)}>{rs(s.closed_rs)}</b><small>{signed(s.closed_points)} pts</small></div>
            <div className="bt-tile"><span>Total</span><b className={cls(s.total_rs)}>{rs(s.total_rs)}</b><small>{signed(s.total_points)} pts · ₹{pv} a point</small></div>
            <div className="bt-tile"><span>Engine sees now</span>
              {pv_ && pv_.sides ? (
                <b className="pp-see">{["CE", "PE"].map((sd) => { const b = pv_.sides[sd]?.best; return <span key={sd} className={pv_.sides[sd]?.fires ? "pos" : ""}>{sd} {b ? `${fmtNum(b.strike, 0)} diff ${num(b.diff)}` : "no strike"}</span>; })}</b>
              ) : <b>—</b>}
              <small>{pv_?.threshold != null ? `rule ≥ ${pv_.threshold} · ${pv_.in_window ? "entry window open" : "outside entry window"} · square off ${dmy(pv_.square_off_day)}` : "market closed"}</small></div>
          </div>

          <div className="bt-card">
            <div className="bs-card-h bt-head">Open lots <span className="bs-muted">marked live: bought leg at bid, sold leg at ask</span></div>
            <div className="bt-tablewrap">
              <table className="nmd-table bt-table">
                <thead><tr><th>Entered</th><th>Side</th><th>Strike</th><th>Why</th><th>Buy on</th><th>Sell on</th><th>Diff</th><th>Now buy / sell</th><th>Expiry NSE / MCX</th><th>Shifts</th><th>P&L pts</th><th>P&L ₹</th>{admin && <th></th>}</tr></thead>
                <tbody>
                  {openRows.length === 0 && <tr><td colSpan={admin ? 13 : 12} className="bs-muted">No open lot. {st.enabled ? "The engine enters the moment a strike meets the rules." : "Press Start paper trading to begin."}</td></tr>}
                  {openRows.map((t) => (
                    <tr key={t.id} className="bt-trow" onClick={() => setDetail(t)} title="Day by day P&L">
                      <td className="nmd-date">{hm(t.entry_time)}</td>
                      <td className={t.side === "CE" ? "pos" : "neg"}>{t.side}</td>
                      <td className="nmd-strike">{fmtNum(t.strike, 0)}</td>
                      <td className="bt-why">{t.reason === "add lot" ? `add lot on #${t.parent}` : t.reason === "adjust" ? `adjusted from #${t.parent}` : "signal"}<small className="bt-sub">#{t.id}</small></td>
                      <td>{t.buy_exch} @ {num(t.buy_px)}</td>
                      <td>{t.sell_exch} @ {num(t.sell_px)}</td>
                      <td>{num(t.diff)}</td>
                      <td>{num(t.mark_prices?.[t.buy_exch])} / {num(t.mark_prices?.[t.sell_exch])}<small className="bt-sub">{t.mark_time ? t.mark_time.slice(11, 19) : ""}</small></td>
                      <td>{dmy(t.legs?.NSE?.exp)} / {dmy(t.legs?.MCX?.exp)}</td>
                      <td>{t.rolls || "—"}</td>
                      <td className={cls(t.mark)}>{signed(t.mark)}</td>
                      <td className={cls(t.mark_rs)}>{rs(t.mark_rs)}</td>
                      {admin && <td><button type="button" className="oh-chip" onClick={(e) => { e.stopPropagation(); act(() => api.nseMcxPaperClose(product, t.id), `Close ${t.side} ${t.strike} at the current prices?`); }}>Close</button></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bt-two pp-two">
            <div className="bt-card">
              <div className="bs-card-h bt-head">Closed trades <span className="bs-muted">click a trade for its day by day P&L</span>
                <button type="button" className="btn btn-primary btn-sm" disabled={!closedRows.length} onClick={downloadCsv}>Download CSV</button></div>
              <div className="bt-tablewrap">
                <table className="nmd-table bt-table">
                  <thead><tr><th>Entered</th><th>Side</th><th>Strike</th><th>Why</th><th>Buy on</th><th>Sell on</th><th>Diff</th><th>Exit</th><th>Exit prices</th><th>Shifts</th><th>P&L pts</th><th>P&L ₹</th></tr></thead>
                  <tbody>
                    {closedRows.length === 0 && <tr><td colSpan={12} className="bs-muted">Nothing closed yet.</td></tr>}
                    {closedRows.map((t) => (
                      <tr key={t.id} className="bt-trow" onClick={() => setDetail(t)}>
                        <td className="nmd-date">{hm(t.entry_time)}</td>
                        <td className={t.side === "CE" ? "pos" : "neg"}>{t.side}</td>
                        <td className="nmd-strike">{fmtNum(t.strike, 0)}</td>
                        <td className="bt-why">{t.reason === "add lot" ? `add lot on #${t.parent}` : t.reason === "adjust" ? `adjusted from #${t.parent}` : "signal"}<small className="bt-sub">#{t.id}</small></td>
                        <td>{t.buy_exch} @ {num(t.buy_px)}</td>
                        <td>{t.sell_exch} @ {num(t.sell_px)}</td>
                        <td>{num(t.diff)}</td>
                        <td>{hm(t.exit_time)}<small className="bt-sub">{EXIT_LABEL[t.exit_reason] || LABEL[t.exit_reason] || t.exit_reason}</small></td>
                        <td>{num(t.buy_exit)} / {num(t.sell_exit)}</td>
                        <td>{t.rolls || "—"}</td>
                        <td className={cls(t.pnl_points)}>{signed(t.pnl_points)}</td>
                        <td className={cls(t.pnl_rs)}>{rs(t.pnl_rs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="bt-card pp-events">
              <div className="bs-card-h">What the engine did</div>
              <ul className="pp-evlist">
                {(st.events || []).slice().reverse().map((e) => (
                  <li key={e.id} className={`pp-ev pp-ev-${e.kind.replace(" ", "-")}`}><span className="pp-evtime">{hm(e.time)}</span><b>{LABEL[e.kind] || e.kind}</b> {e.text}</li>
                ))}
                {!(st.events || []).length && <li className="bs-muted">Nothing yet.</li>}
              </ul>
            </div>
          </div>
        </>
      )}
      {detail && <TradeDetail t={{ ...detail, entry_date: (detail.entry_time || "").slice(0, 10), exit_date: (detail.exit_time || "").slice(0, 10) || null, nse_expiry: detail.nse_expiry, mcx_expiry: detail.mcx_expiry, pnl_points: detail.status === "open" ? detail.mark : detail.pnl_points, pnl_rs: detail.status === "open" ? detail.mark_rs : detail.pnl_rs, exit_reason: detail.status === "open" ? "open" : detail.exit_reason }} pointValue={pv} onClose={() => setDetail(null)} />}
    </div>
  );
}
