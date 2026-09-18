import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useConfirm } from "./ConfirmDialog.jsx";
import { useToast } from "./Toast.jsx";
import "./BankOptions.css";

const INDICES = ["BANKEX", "BANKNIFTY"];
const DEFAULTS = {
  side: "both", range_points: 2000, liquidity: "liquid", min_volume: 1,
  max_spread_pct: 10, bankex_lots: 1, banknifty_lots: 1, metric: "divided", divisor: 30,
};

function numeric(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}
function number(value, digits = 2) {
  return numeric(value) ? Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }) : "—";
}
function money(value) {
  return numeric(value) ? Number(value).toLocaleString("en-IN", {
    style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2,
  }) : "—";
}
function date(value, withTime = false) {
  if (!value) return "—";
  const parsed = new Date(String(value).length === 10 ? `${value}T00:00:00+05:30` : value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}
function age(seconds) {
  if (!numeric(seconds)) return "Awaiting quote";
  if (Number(seconds) < 2) return "Just updated";
  if (Number(seconds) < 60) return `${Math.floor(Number(seconds))}s ago`;
  return `${Math.floor(Number(seconds) / 60)}m ago`;
}
function tone(value) {
  return numeric(value) && Number(value) !== 0 ? (Number(value) > 0 ? "bo-positive" : "bo-negative") : "";
}
function makeRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const h = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// One request at a time. An old filter's response cannot replace the current
// board, and hidden browser tabs neither poll nor accept incoming snapshots.
function useVisiblePolling(read, enabled, key, revision) {
  const [result, setResult] = useState({ key: null, data: null, error: null, refreshing: true });
  useEffect(() => {
    if (!enabled) return undefined;
    setResult((old) => ({ ...old, refreshing: true }));
    let active = true, busy = false, timer = null, generation = 0, controller = null;
    function stop() { clearTimeout(timer); timer = null; }
    async function load() {
      if (!active || document.hidden || busy) return;
      stop();
      busy = true;
      const current = ++generation;
      controller = new AbortController();
      const requestController = controller;
      const timeout = setTimeout(() => requestController.abort(), 10000);
      try {
        const data = await read(requestController.signal);
        if (active && !document.hidden && current === generation) {
          setResult({ key, data, error: null, refreshing: false });
        }
      } catch (error) {
        if (active && !document.hidden && current === generation) {
          const message = requestController.signal.aborted
            ? "The update timed out. Displayed values may be stale; actions are paused."
            : error.message || "Unable to load quotes.";
          setResult((old) => ({ key, data: old.key === key ? old.data : null, error: message, refreshing: false }));
        }
      } finally {
        clearTimeout(timeout);
        busy = false;
        if (active && !document.hidden) timer = setTimeout(load, 2000);
      }
    }
    function onVisibility() {
      stop();
      generation += 1;
      controller?.abort();
      setResult((old) => ({ ...old, refreshing: true }));
      if (!document.hidden) load();
    }
    load();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false; generation += 1; stop(); controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [read, enabled, key, revision]);
  return result.key === key ? result : { data: null, error: null, refreshing: true };
}

function Field({ label, children }) {
  const id = React.useId();
  return <div className="bo-field"><label htmlFor={id}>{label}</label>{React.cloneElement(children, { id })}</div>;
}

function IndexCard({ name, value, buyIndex, sellIndex }) {
  const action = buyIndex === name ? "Buy · Ask" : sellIndex === name ? "Sell · Bid" : "Awaiting expiry";
  return (
    <div className="bo-index-card">
      <div className="bo-card-top"><h3>{name}</h3><span className={`bo-badge ${buyIndex === name ? "bo-buy" : sellIndex === name ? "bo-sell" : ""}`}>{action}</span></div>
      <div className="bo-spot">{number(value?.spot)}<span>Spot index</span></div>
      <dl className="bo-index-details">
        <div><dt>ATM</dt><dd>{number(value?.atm, 0)}</dd></div>
        <div><dt>Monthly expiry</dt><dd>{date(value?.expiry)}</dd></div>
        <div><dt>Lot size</dt><dd>{number(value?.lot_size, 0)}</dd></div>
      </dl>
      <span className="bo-small bo-muted">{age(value?.age_seconds)}</span>
    </div>
  );
}

function OptionCell({ option, side }) {
  if (!option) return <span className="bo-muted">Contract unavailable</span>;
  return (
    <div className="bo-option-cell">
      <strong>{number(option.strike, 0)} <span className="bo-small">{side}</span></strong>
      <span>Bid {number(option.bid)} <span className="bo-muted">/</span> Ask {number(option.ask)}</span>
      <span className={`bo-small ${option.fresh ? "bo-muted" : "bo-warning-text"}`}>{age(option.age_seconds)}</span>
    </div>
  );
}

function PositionLeg({ name, leg, side, closed }) {
  if (!leg) return <span className="bo-muted">—</span>;
  const action = String(leg.action || "").toLowerCase();
  return (
    <div className="bo-position-leg">
      <div><span className={`bo-badge ${action === "buy" ? "bo-buy" : "bo-sell"}`}>{action || "—"}</span> <strong>{number(leg.strike, 0)} {side}</strong></div>
      <span className="bo-small bo-muted">{date(leg.expiry)} · {leg.lots} lot{Number(leg.lots) === 1 ? "" : "s"} × {leg.lot_size} = {leg.quantity} units</span>
      <span className="bo-small">Entry {number(leg.entry_price)} <span className="bo-muted">→ {closed ? "Exit" : action === "buy" ? "Bid" : "Ask"}</span> {number(closed ? leg.exit_price : leg.current_price)}</span>
      <span className="bo-sr-only">{name}</span>
    </div>
  );
}

export default function BankOptions() {
  const confirm = useConfirm();
  const toast = useToast();
  const [view, setView] = useState("live");
  const [settings, setSettings] = useState(DEFAULTS);
  const [strike, setStrike] = useState("all");
  const [positionFilter, setPositionFilter] = useState("open");
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState(null);
  const [actionError, setActionError] = useState(null);
  const actionBusy = useRef(false);
  const openAttempt = useRef(null);

  const invalid = useMemo(() => {
    for (const key of ["bankex_lots", "banknifty_lots"]) {
      if (!numeric(settings[key]) || !Number.isInteger(Number(settings[key])) || Number(settings[key]) < 1 || Number(settings[key]) > 100) return "Enter whole lot quantities between 1 and 100.";
    }
    if (settings.metric === "divided" && (!numeric(settings.divisor) || Number(settings.divisor) < 0.01 || Number(settings.divisor) > 1000000)) return "Enter a divisor between 0.01 and 1,000,000.";
    if (!numeric(settings.min_volume) || !Number.isInteger(Number(settings.min_volume)) || Number(settings.min_volume) < 0 || Number(settings.min_volume) > 1000000000) return "Minimum volume must be a whole number from 0 to 1,000,000,000.";
    if (!numeric(settings.max_spread_pct) || Number(settings.max_spread_pct) <= 0 || Number(settings.max_spread_pct) > 200) return "Maximum bid/ask spread must be greater than 0% and at most 200%.";
    return null;
  }, [settings]);
  const paramsKey = JSON.stringify({ ...settings, divisor: settings.metric === "divided" ? settings.divisor : DEFAULTS.divisor });
  const readLive = useCallback((signal) => api.bankOptionsLive(JSON.parse(paramsKey), signal), [paramsKey]);
  const readPositions = useCallback((signal) => api.bankOptionsPositions(signal), []);
  const live = useVisiblePolling(readLive, view === "live" && !invalid, paramsKey, revision);
  const positions = useVisiblePolling(readPositions, view === "positions", "positions", revision);
  const board = live.data;
  const rows = (board?.rows || []).filter((row) => strike === "all" || String(row.bankex?.strike) === strike);
  const strikes = [...new Set((board?.bankex_strikes || (board?.rows || []).map((row) => row.bankex?.strike)).filter(numeric).map(Number))].sort((a, b) => a - b);
  const selectedOutsideRange = strike !== "all" && !strikes.includes(Number(strike));
  const positionRows = (positions.data?.positions || []).filter((position) => positionFilter === "all" || String(position.status).toLowerCase() === positionFilter);
  const summary = positions.data?.summary;
  const canAdd = !invalid && !live.error && !live.refreshing && board?.status?.ready;
  const error = view === "live" ? live.error : positions.error;
  const valueLabel = settings.metric === "divided" ? `Difference ÷ ${number(settings.divisor, Number(settings.divisor) % 1 ? 2 : 0)}` : settings.metric === "rupees" ? "Net premium (₹)" : "Difference (pts)";
  const formula = settings.metric === "divided" ? `(Sell Bid − Buy Ask) ÷ ${settings.divisor || "divisor"}` : settings.metric === "rupees" ? "(Sell Bid × sell lot size × sell lots) − (Buy Ask × buy lot size × buy lots)" : "Sell Bid − Buy Ask";

  function update(key, value) { setSettings((previous) => ({ ...previous, [key]: value })); }

  function onViewKey(event) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    const next = event.key === "Home" ? "live" : event.key === "End" ? "positions" : view === "live" ? "positions" : "live";
    setView(next);
    document.getElementById(next === "live" ? "bo-live-tab" : "bo-position-tab")?.focus();
  }

  async function addPosition(row) {
    if (actionBusy.current || !canAdd || !row.tradable) return;
    actionBusy.current = true;
    setPending(`open:${row.id}`);
    setActionError(null);
    const captured = {
      bankex_security_id: row.bankex.security_id, banknifty_security_id: row.banknifty.security_id,
      side: row.side, bankex_lots: Number(settings.bankex_lots), banknifty_lots: Number(settings.banknifty_lots),
    };
    const identity = JSON.stringify(captured);
    const bankexAction = row.buy_index === "BANKEX" ? "Buy" : "Sell";
    try {
      const approved = await confirm({
        title: "Add paper position?",
        message: `${bankexAction} BANKEX ${number(row.bankex.strike, 0)} ${row.side} (${captured.bankex_lots} lots) and ${bankexAction === "Buy" ? "sell" : "buy"} BANKNIFTY ${number(row.banknifty.strike, 0)} ${row.side} (${captured.banknifty_lots} lots). Entry uses the latest available Ask for the buy and Bid for the sell. These strikes and quantities remain fixed.`,
        confirmText: "Add paper position",
      });
      if (!approved) return;
      // Reuse an uncertain POST's key if the same position is retried. A lost
      // response must not turn a retry into a second paper position.
      if (openAttempt.current?.identity !== identity) openAttempt.current = { identity, requestId: makeRequestId() };
      await api.bankOptionsOpen({ ...captured, request_id: openAttempt.current.requestId });
      openAttempt.current = null;
      toast.success("Paper position saved. Track it in Position.");
      setRevision((value) => value + 1);
    } catch (err) {
      setActionError(`${err.message || "Unable to save the position."} Check Position before trying again.`);
    } finally {
      actionBusy.current = false;
      setPending(null);
    }
  }

  async function closePosition(position) {
    if (actionBusy.current || !position.can_close || positions.error || positions.refreshing) return;
    actionBusy.current = true;
    setPending(`close:${position.id}`);
    setActionError(null);
    try {
      const approved = await confirm({
        title: "Close paper position?",
        message: `Close BANKEX ${number(position.bankex?.strike, 0)} ${position.side} / BANKNIFTY ${number(position.banknifty?.strike, 0)} ${position.side}? The bought option is sold at Bid and the sold option is bought at Ask. Final P&L uses the latest available quotes.`,
        confirmText: "Close paper position", danger: true,
      });
      if (!approved) return;
      await api.bankOptionsClose(position.id);
      toast.success("Paper position closed.");
      setRevision((value) => value + 1);
    } catch (err) {
      setActionError(err.message || "Unable to close the paper position.");
    } finally {
      actionBusy.current = false;
      setPending(null);
    }
  }

  return (
    <section className="bo-page" aria-labelledby="bo-title">
      <header className="bo-head">
        <div><h2 id="bo-title">BANKEX / BANKNIFTY</h2><p>Monthly options · Matched distance from ATM</p></div>
        <div className="bo-tabs" role="tablist" aria-label="Bank options view" onKeyDown={onViewKey}>
          <button type="button" id="bo-live-tab" role="tab" tabIndex={view === "live" ? 0 : -1} aria-selected={view === "live"} aria-controls="bo-live-panel" className={view === "live" ? "active" : ""} onClick={() => setView("live")}>Live</button>
          <button type="button" id="bo-position-tab" role="tab" tabIndex={view === "positions" ? 0 : -1} aria-selected={view === "positions"} aria-controls="bo-position-panel" className={view === "positions" ? "active" : ""} onClick={() => setView("positions")}>Position <span className="bo-paper-label">Paper</span></button>
        </div>
      </header>

      {error && <div className="bo-alert bo-error" role="alert">{error} Quotes shown may be out of date; actions are paused.</div>}
      {actionError && <div className="bo-alert bo-error" role="alert">{actionError}<button type="button" className="bo-dismiss" aria-label="Dismiss error" onClick={() => setActionError(null)}>×</button></div>}

      {view === "live" ? (
        <div id="bo-live-panel" role="tabpanel" aria-labelledby="bo-live-tab">
          <div className="bo-index-grid">
            {INDICES.map((name) => <IndexCard key={name} name={name} value={board?.indices?.[name]} buyIndex={board?.buy_index} sellIndex={board?.sell_index} />)}
          </div>
          <div className="bo-direction">
            <span className="bo-direction-rule">Earlier expiry <strong>Buy at Ask</strong><span aria-hidden="true"> → </span>Later expiry <strong>Sell at Bid</strong></span>
            <span className={`bo-status ${board?.market_open && board?.status?.ready && !live.error && !live.refreshing ? "is-live" : ""}`}><span className="bo-status-dot" />{live.error ? "Connection issue" : !board || live.refreshing ? "Loading quotes" : !board.market_open ? "Market closed" : board.status?.ready ? "Live quotes" : "Awaiting quotes"}</span>
          </div>

          <div className="bo-controls">
            <Field label="Option side"><select value={settings.side} onChange={(event) => update("side", event.target.value)}><option value="both">CE + PE</option><option value="CE">CE · Calls</option><option value="PE">PE · Puts</option></select></Field>
            <Field label="BANKEX strike"><select value={strike} onChange={(event) => setStrike(event.target.value)}><option value="all">All strikes</option>{strikes.map((value) => <option key={value} value={String(value)}>{number(value, 0)}</option>)}{selectedOutsideRange && <option value={strike}>{number(strike, 0)} · outside range</option>}</select></Field>
            <Field label="Distance from ATM"><select value={settings.range_points} onChange={(event) => update("range_points", Number(event.target.value))}><option value={1000}>Up to 1,000 points</option><option value={2000}>Up to 2,000 points</option><option value={3000}>Up to 3,000 points</option></select></Field>
            <Field label="BANKEX liquidity"><select value={settings.liquidity} onChange={(event) => update("liquidity", event.target.value)}><option value="liquid">Liquid strikes</option><option value="all">All monitored strikes</option></select></Field>
            <Field label="Calculation"><select value={settings.metric} onChange={(event) => update("metric", event.target.value)}><option value="divided">Difference ÷ divisor</option><option value="points">Difference in points</option><option value="rupees">Net premium in ₹</option></select></Field>
            {settings.metric === "divided" && <Field label="Divide by"><input type="number" min="0.01" max="1000000" step="any" value={settings.divisor} onChange={(event) => update("divisor", event.target.value)} /></Field>}
            <Field label="BANKEX lots"><input type="number" min="1" max="100" step="1" value={settings.bankex_lots} onChange={(event) => update("bankex_lots", event.target.value)} /></Field>
            <Field label="BANKNIFTY lots"><input type="number" min="1" max="100" step="1" value={settings.banknifty_lots} onChange={(event) => update("banknifty_lots", event.target.value)} /></Field>
          </div>
          <div className="bo-calculation"><span>Calculation</span><strong>{formula}</strong>{settings.metric === "rupees" && <span>Net premium, before charges</span>}</div>
          <details className="bo-liquidity-settings">
            <summary>Liquidity settings <span>Min volume {number(settings.min_volume, 0)} · Max spread {number(settings.max_spread_pct, 1)}%</span></summary>
            <div className="bo-liquidity-fields">
              <Field label="Minimum traded volume"><input type="number" min="0" max="1000000000" step="1" value={settings.min_volume} onChange={(event) => update("min_volume", event.target.value)} /></Field>
              <Field label="Maximum bid/ask spread (%)"><input type="number" min="0.01" max="200" step="any" value={settings.max_spread_pct} onChange={(event) => update("max_spread_pct", event.target.value)} /></Field>
              <p>Liquid strikes need fresh BANKEX Bid/Ask quotes and must meet these volume and spread limits. Both legs need fresh quotes to add a paper position.</p>
            </div>
          </details>
          {invalid && <div className="bo-alert" role="alert">{invalid}</div>}
          {board?.status?.message && <div className={`bo-alert ${board.status.ready ? "bo-info" : ""}`}>{board.status.message}</div>}
          <div className="bo-table-meta"><span>{rows.length} pairs{numeric(board?.counts?.filtered) && Number(board.counts.filtered) > 0 ? ` · ${number(board.counts.filtered, 0)} hidden by liquidity filters` : ""}</span><span>ATM follows spot · Prices in premium points</span></div>
          <div className="bo-table-wrap" role="region" aria-label="Live matched options" tabIndex={0}>
            <table className="bo-table">
              <thead><tr><th scope="col">Option</th><th scope="col">ATM distance</th><th scope="col">BANKEX</th><th scope="col">BANKNIFTY</th><th scope="col">Buy Ask</th><th scope="col">Sell Bid</th>{settings.metric !== "points" && <th scope="col">Difference (pts)</th>}<th scope="col" className="bo-value-col">{valueLabel}</th><th scope="col">Paper position</th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className={Number(row.offset_points) === 0 ? "bo-atm-row" : ""}>
                    <td><span className={`bo-side ${row.side === "CE" ? "bo-call" : "bo-put"}`}>{row.side}</span></td>
                    <td><strong>{Number(row.offset_points) === 0 ? "ATM" : `${number(Math.abs(Number(row.offset_points)), 0)} pts`}</strong>{Number(row.offset_points) !== 0 && <span className="bo-cell-sub">{row.side === "CE" ? "Above ATM" : "Below ATM"}</span>}</td>
                    <td><OptionCell option={row.bankex} side={row.side} /></td><td><OptionCell option={row.banknifty} side={row.side} /></td>
                    <td><strong>{number(row.buy_price)}</strong><span className="bo-cell-sub">{row.buy_index || "—"}</span></td>
                    <td><strong>{number(row.sell_price)}</strong><span className="bo-cell-sub">{row.sell_index || "—"}</span></td>
                    {settings.metric !== "points" && <td className={tone(row.difference_points)}>{number(row.difference_points)}</td>}
                    <td className={`bo-value-col ${tone(row.display_value)}`}><strong>{settings.metric === "rupees" ? money(row.display_value) : number(row.display_value, settings.metric === "divided" ? 4 : 2)}</strong></td>
                    <td><button type="button" className="bo-button" disabled={!canAdd || !row.tradable || !!pending} onClick={() => addPosition(row)}>{pending === `open:${row.id}` ? "Saving…" : "Add position"}</button>{row.reason && <span className="bo-row-reason">{row.reason}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <div className="bo-empty"><strong>{invalid ? "Check your settings" : !board ? error ? "Quotes could not be loaded" : "Loading monthly option contracts…" : selectedOutsideRange ? "Selected strike is outside the current ATM range" : strike !== "all" ? "No matching pair for this strike" : "No matching quotes yet"}</strong><p>{invalid || (!board ? "This board refreshes automatically while visible." : settings.liquidity === "liquid" ? "Try All monitored strikes to see contracts awaiting quotes or change the liquidity limits." : "Pairs appear when both monthly contracts and index quotes are available.")}</p>{strike !== "all" && <button type="button" className="bo-button" onClick={() => setStrike("all")}>Show all strikes</button>}</div>}
          </div>
          <p className="bo-footnote">Matching uses the same point distance from each index’s ATM. Divide by changes the displayed difference; paper quantities and P&amp;L use each contract’s lot size.</p>
        </div>
      ) : (
        <div id="bo-position-panel" role="tabpanel" aria-labelledby="bo-position-tab">
          <div className="bo-position-summary">
            <div><span>Open positions</span><strong>{number(summary?.open, 0)}</strong></div>
            <div><span>Open P&amp;L</span><strong className={tone(summary?.open_pnl_rupees)}>{money(summary?.open_pnl_rupees)}</strong></div>
            <div><span>Closed positions</span><strong>{number(summary?.closed, 0)}</strong>{Number(summary?.expired) > 0 && <span className="bo-expired-count">{number(summary.expired, 0)} expired</span>}</div>
            <div><span>Realised P&amp;L</span><strong className={tone(summary?.realised_pnl_rupees)}>{money(summary?.realised_pnl_rupees)}</strong></div>
          </div>
          <div className="bo-position-toolbar"><div><h3>Paper positions</h3><p>Strikes and quantities stay fixed at entry. P&amp;L is in rupees, before charges.</p></div><Field label="Show positions"><select value={positionFilter} onChange={(event) => setPositionFilter(event.target.value)}><option value="open">Open</option><option value="closed">Closed</option><option value="expired">Expired</option><option value="all">All positions</option></select></Field></div>
          <div className="bo-table-wrap" role="region" aria-label="Paper positions" tabIndex={0}>
            <table className="bo-table bo-position-table">
              <thead><tr><th scope="col">Opened (IST)</th><th scope="col">BANKEX</th><th scope="col">BANKNIFTY</th><th scope="col">Entry net premium</th><th scope="col">P&amp;L (₹)</th><th scope="col">Status</th><th scope="col">Action</th></tr></thead>
              <tbody>{positionRows.map((position) => {
                const closed = String(position.status).toLowerCase() === "closed";
                const expired = String(position.status).toLowerCase() === "expired";
                return <tr key={position.id}>
                  <td>{date(position.created_at, true)}{closed && <span className="bo-cell-sub">Closed {date(position.closed_at, true)}</span>}</td>
                  <td><PositionLeg name="BANKEX" leg={position.bankex} side={position.side} closed={closed} /></td>
                  <td><PositionLeg name="BANKNIFTY" leg={position.banknifty} side={position.side} closed={closed} /></td>
                  <td>{money(position.entry_credit_rupees)}</td>
                  <td className={tone(position.pnl_rupees)}><strong>{money(position.pnl_rupees)}</strong><span className="bo-cell-sub">{closed ? "Realised" : expired ? "Expired · no settlement" : position.mark_fresh && !positions.error && !positions.refreshing ? "Live" : "Stale / unavailable"}</span></td>
                  <td><span className={`bo-badge ${closed ? "" : position.mark_fresh && !expired ? "bo-buy" : "bo-warning-text"}`}>{closed ? "Closed" : expired ? "Expired" : "Open"}</span>{position.reason && <span className="bo-row-reason">{position.reason}</span>}</td>
                  <td>{!closed && !expired ? <button type="button" className="bo-button bo-close-button" disabled={!position.can_close || !!positions.error || positions.refreshing || !!pending} onClick={() => closePosition(position)}>{pending === `close:${position.id}` ? "Closing…" : "Close position"}</button> : <span className="bo-muted">—</span>}</td>
                </tr>;
              })}</tbody>
            </table>
            {!positionRows.length && <div className="bo-empty"><strong>{!positions.data ? positions.error ? "Positions could not be loaded" : "Loading paper positions…" : `No ${positionFilter === "all" ? "" : `${positionFilter} `}positions`}</strong><p>{positionFilter === "closed" ? "Closed paper positions and realised P&L will appear here." : "Choose a matched pair in Live and add a paper position to track it here."}</p>{positions.data && positionFilter !== "closed" && <button type="button" className="bo-button" onClick={() => setView("live")}>View live pairs</button>}</div>}
          </div>
          <p className="bo-footnote">Open positions are valued at exit prices: Bid for a bought option and Ask for a sold option. Stale or expired contracts cannot be closed without valid current quotes.</p>
        </div>
      )}
    </section>
  );
}
