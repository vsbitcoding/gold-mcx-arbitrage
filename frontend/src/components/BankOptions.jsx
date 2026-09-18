import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useConfirm } from "./ConfirmDialog.jsx";
import { useToast } from "./Toast.jsx";
import "./BankOptions.css";

const INDICES = ["BANKEX", "BANKNIFTY"];
const STRIKE_OFFSETS = Array.from({ length: 15 }, (_, index) => (index - 7) * 500);
const DEFAULTS = {
  side: "both", range_points: 3500, liquidity: "all", min_volume: 1,
  max_spread_pct: 10, bankex_lots: 1, banknifty_lots: 1, metric: "points", divisor: 30,
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
    <div className={`bo-index-card bo-index-${name.toLowerCase()}`}>
      <div className="bo-card-top">
        <h3>{name}</h3>
        <span className={`bo-badge ${buyIndex === name ? "bo-buy" : sellIndex === name ? "bo-sell" : ""}`}>{action}</span>
        <span className="bo-index-updated">{age(value?.age_seconds)}</span>
      </div>
      <div className="bo-index-body">
        <strong className="bo-spot" title={`Spot index · ${age(value?.age_seconds)}`}>{number(value?.spot)}</strong>
        <strong className="bo-spot bo-expiry" title="Monthly expiry">{date(value?.expiry)}</strong>
        <dl className="bo-index-details">
          <div><dt>ATM</dt><dd>{number(value?.atm, 0)}</dd></div>
          <div><dt>Lot size</dt><dd>{number(value?.lot_size, 0)}</dd></div>
        </dl>
      </div>
    </div>
  );
}

function QuoteCells({ row, side, strikePair, metric, canAdd, pending, onAdd, onDetails }) {
  const buy = row?.[row.buy_index?.toLowerCase()];
  const sell = row?.[row.sell_index?.toLowerCase()];
  const hasContracts = !!row?.bankex?.security_id && !!row?.banknifty?.security_id;
  const quoted = numeric(buy?.bid) && Number(buy.bid) > 0 && numeric(buy?.ask) && Number(buy.ask) > 0
    && numeric(sell?.bid) && Number(sell.bid) > 0 && numeric(sell?.ask) && Number(sell.ask) > 0;
  const fresh = quoted && buy?.fresh && sell?.fresh;
  const quality = !row ? "Waiting for quotes" : !hasContracts ? "Not listed" : !quoted ? "Awaiting quotes" : !fresh ? "Stale quotes"
    : row?.liquid === false ? "Low liquidity" : "Liquid";
  const reason = row?.reason || row?.liquidity_reason || (!row ? "Waiting for this option pair." : quality);
  const label = `${side} at BANKEX ${number(strikePair.bankex, 0)} / BANKNIFTY ${number(strikePair.banknifty, 0)}`;
  const quoteTitle = (index, option) => `${index || "Awaiting expiry"} · Bid ${number(option?.bid)} / Ask ${number(option?.ask)} · ${age(option?.age_seconds)}`;
  return (
    <>
      <td className={`bo-quote-cell bo-group-start bo-${side.toLowerCase()}-cell`} title={quoteTitle(row?.buy_index, buy)}>
        <span className="bo-mobile-pair">{number(strikePair.bankex, 0)} / {number(strikePair.banknifty, 0)}</span>
        <strong>{number(row?.buy_price)}</strong><span className={`bo-freshness-dot ${buy?.fresh ? "is-fresh" : ""}`} role="img" aria-label={`Buy quote: ${age(buy?.age_seconds)}`} />
      </td>
      <td className={`bo-quote-cell bo-${side.toLowerCase()}-cell`} title={quoteTitle(row?.sell_index, sell)}>
        <strong>{number(row?.sell_price)}</strong><span className={`bo-freshness-dot ${sell?.fresh ? "is-fresh" : ""}`} role="img" aria-label={`Sell quote: ${age(sell?.age_seconds)}`} />
      </td>
      <td className={`bo-value-col bo-${side.toLowerCase()}-value ${tone(row?.display_value)}`}>
        <strong>{metric === "rupees" ? money(row?.display_value) : number(row?.display_value, metric === "divided" ? 4 : 2)}</strong>
        {metric !== "points" && <span className="bo-raw-points" title="Sell Bid − Buy Ask, before division or quantities">({number(row?.difference_points)} pts)</span>}
      </td>
      <td className="bo-entry-cell">
        <div className="bo-entry-actions">
          <button type="button" className="bo-button" aria-label={`Add ${label} paper position`} disabled={!canAdd || !hasContracts || !row?.tradable || !!pending} onClick={() => onAdd(row)}>{pending === `open:${row?.id}` ? "Saving…" : `Add ${side}`}</button>
          <button type="button" className={`bo-info-button ${fresh && row?.liquid !== false ? "bo-quality-good" : "bo-quality-warning"}`} aria-label={`Quote details for ${label}: ${quality}`} title={`${quality} · ${reason}`} onClick={() => onDetails(row || { side, reason, bankex: { strike: strikePair.bankex }, banknifty: { strike: strikePair.banknifty } })}><span aria-hidden="true">i</span></button>
        </div>
      </td>
    </>
  );
}

function QuoteDetails({ row, unavailable, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog ref={dialog} className="bo-quote-dialog" aria-labelledby="bo-quote-title" onClose={() => { if (!dialog.current?.open) onClose(); }} onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    }}>
      <div className="bo-dialog-head"><h3 id="bo-quote-title">{row.side} quote details</h3><button type="button" className="bo-button" onClick={onClose}>Close</button></div>
      <div className="bo-detail-grid">{INDICES.map((name) => {
        const leg = row[name.toLowerCase()];
        const action = row.buy_index === name ? "Buy at Ask" : row.sell_index === name ? "Sell at Bid" : "Awaiting expiry";
        return <section key={name} className="bo-detail-leg">
          <h4>{name} <span>{action}</span></h4><strong>{number(leg?.strike, 0)} {row.side}</strong>
          <p>{date(leg?.expiry)} · {leg?.trading_symbol || "Contract unavailable"}</p>
          <dl><div><dt>Bid</dt><dd>{number(leg?.bid)}</dd></div><div><dt>Ask</dt><dd>{number(leg?.ask)}</dd></div><div><dt>LTP</dt><dd>{number(leg?.ltp)}</dd></div><div><dt>Volume</dt><dd>{number(leg?.volume, 0)}</dd></div><div><dt>Open interest</dt><dd>{number(leg?.oi, 0)}</dd></div><div><dt>Updated</dt><dd>{unavailable ? "Unavailable" : age(leg?.age_seconds)}</dd></div></dl>
        </section>;
      })}</div>
      <p className="bo-detail-status">{unavailable ? "Live updates are unavailable. These are the last received quotes and must not be treated as current prices." : row.reason || row.liquidity_reason || (row.liquid === false ? "BANKEX does not meet the selected liquidity thresholds. This strike remains visible." : "Both legs have current quotes. Entry uses Buy Ask and Sell Bid.")}</p>
    </dialog>
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
  const [positionFilter, setPositionFilter] = useState("open");
  const [quoteDetails, setQuoteDetails] = useState(null);
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
  const pairs = board?.rows || [];
  const groupedRows = STRIKE_OFFSETS.map((offset) => {
    const ce = pairs.find((row) => row.side === "CE" && Number(row.offset_points) === offset);
    const pe = pairs.find((row) => row.side === "PE" && Number(row.offset_points) === offset);
    const bankexAtm = board?.indices?.BANKEX?.atm;
    // The BANKNIFTY strike comes from the server: the same points from its
    // spot as the BANKEX strike is from BANKEX's spot, on the 100-point ladder.
    return { offset, CE: ce, PE: pe,
      bankex: ce?.bankex?.strike ?? pe?.bankex?.strike ?? (numeric(bankexAtm) ? Number(bankexAtm) + offset : null),
      banknifty: ce?.banknifty?.strike ?? pe?.banknifty?.strike ?? null };
  });
  const showCalls = settings.side !== "PE";
  const showPuts = settings.side !== "CE";
  const selectedDetails = quoteDetails?.id ? pairs.find((row) => row.id === quoteDetails.id) : quoteDetails;
  useEffect(() => {
    if (quoteDetails?.id && board && !board.rows?.some((row) => row.id === quoteDetails.id)) setQuoteDetails(null);
  }, [board, quoteDetails?.id]);
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
    if (actionBusy.current || !canAdd || !row?.tradable || !row.bankex?.security_id || !row.banknifty?.security_id) return;
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
        <div className="bo-title-block"><h2 id="bo-title">BANKEX / BANKNIFTY</h2><p>Monthly options · BANKNIFTY strike matched by points from spot</p></div>
        <div className="bo-head-actions">
          {view === "live" && <span className={`bo-status ${board?.market_open && board?.status?.ready && !live.error && !live.refreshing ? "is-live" : ""}`}><span className="bo-status-dot" />{live.error ? "Connection issue" : !board || live.refreshing ? "Loading quotes" : !board.market_open ? "Market closed" : board.status?.ready ? "Live quotes" : "Awaiting quotes"}</span>}
          <div className="bo-tabs" role="tablist" aria-label="Bank options view" onKeyDown={onViewKey}>
            <button type="button" id="bo-live-tab" role="tab" tabIndex={view === "live" ? 0 : -1} aria-selected={view === "live"} aria-controls="bo-live-panel" className={view === "live" ? "active" : ""} onClick={() => setView("live")}>Live</button>
            <button type="button" id="bo-position-tab" role="tab" tabIndex={view === "positions" ? 0 : -1} aria-selected={view === "positions"} aria-controls="bo-position-panel" className={view === "positions" ? "active" : ""} onClick={() => setView("positions")}>Position <span className="bo-paper-label">Paper</span></button>
          </div>
        </div>
      </header>

      {error && <div className="bo-alert bo-error" role="alert">{error} Quotes shown may be out of date; actions are paused.</div>}
      {actionError && <div className="bo-alert bo-error" role="alert">{actionError}<button type="button" className="bo-dismiss" aria-label="Dismiss error" onClick={() => setActionError(null)}>×</button></div>}

      {view === "live" ? (
        <div id="bo-live-panel" className="bo-panel" role="tabpanel" aria-labelledby="bo-live-tab">
          <div className="bo-workbench">
            <div className="bo-workbench-main">
              <div className="bo-index-grid">
                {INDICES.map((name) => <IndexCard key={name} name={name} value={board?.indices?.[name]} buyIndex={board?.buy_index} sellIndex={board?.sell_index} />)}
              </div>
              <div className="bo-controls" role="group" aria-label="Live comparison settings">
                <Field label="Option side"><select value={settings.side} onChange={(event) => update("side", event.target.value)}><option value="both">CE + PE</option><option value="CE">CE · Calls</option><option value="PE">PE · Puts</option></select></Field>
                <Field label="Calculation"><select value={settings.metric} onChange={(event) => update("metric", event.target.value)}><option value="points">Difference in points</option><option value="rupees">Net premium in ₹</option></select></Field>
                <Field label="BANKEX lots"><input type="number" min="1" max="100" step="1" value={settings.bankex_lots} onChange={(event) => update("bankex_lots", event.target.value)} /></Field>
                <Field label="BANKNIFTY lots"><input type="number" min="1" max="100" step="1" value={settings.banknifty_lots} onChange={(event) => update("banknifty_lots", event.target.value)} /></Field>
              </div>
            </div>
            <div className="bo-context-bar">
              <div className="bo-calculation"><strong>{formula}</strong>{settings.metric === "rupees" && <span>Before charges</span>}</div>
              <span className="bo-direction-rule">Earlier expiry <strong>Sell at Bid</strong><span aria-hidden="true"> → </span>Later expiry <strong>Buy at Ask</strong></span>
              <details className="bo-liquidity-settings">
                <summary>Quote quality <span>Min volume {number(settings.min_volume, 0)} · Max spread {number(settings.max_spread_pct, 1)}%</span></summary>
                <div className="bo-liquidity-fields">
                  <Field label="Minimum traded volume"><input type="number" min="0" max="1000000000" step="1" value={settings.min_volume} onChange={(event) => update("min_volume", event.target.value)} /></Field>
                  <Field label="Maximum bid/ask spread (%)"><input type="number" min="0.01" max="200" step="any" value={settings.max_spread_pct} onChange={(event) => update("max_spread_pct", event.target.value)} /></Field>
                  <p>These limits label BANKEX liquidity. All 15 strikes remain visible. Both legs need fresh Bid/Ask quotes for a paper entry.</p>
                </div>
              </details>
            </div>
          </div>
          {invalid && <div className="bo-alert" role="alert">{invalid}</div>}
          <div className="bo-table-meta"><span className="bo-strike-guide"><strong>15 strikes</strong><span>7 below · ATM · 7 above</span><span>500-point steps</span>{board?.status?.message && <span className={`bo-status-note ${board.status.ready ? "" : "is-warning"}`}>{board.status.message}</span>}</span><span><span className="bo-freshness-dot is-fresh" /> Fresh <span className="bo-freshness-dot" /> Awaiting / stale <span className="bo-quality-key" aria-hidden="true">i</span> Quote details</span></div>
          <div className="bo-table-wrap" role="region" aria-label="Live matched options" tabIndex={0}>
            <table className={`bo-table bo-chain-table bo-comparison-table ${showCalls && showPuts ? "bo-both-sides" : "bo-single-side"}`}>
              <thead>
                <tr className="bo-group-heading">
                  {showCalls && <th scope="colgroup" colSpan={4} className="bo-ce-heading"><span className="bo-side-tag">CE</span> Calls</th>}
                  <th scope="colgroup" colSpan={3} className="bo-strike-heading">Matched strikes <span>Same points from spot</span></th>
                  {showPuts && <th scope="colgroup" colSpan={4} className="bo-pe-heading"><span className="bo-side-tag">PE</span> Puts</th>}
                </tr>
                <tr className="bo-column-heading">
                  {showCalls && <><th scope="col">Buy Ask<span className="bo-th-sub">{board?.buy_index || "—"}</span></th><th scope="col">Sell Bid<span className="bo-th-sub">{board?.sell_index || "—"}</span></th><th scope="col">{valueLabel}</th><th scope="col">Paper position</th></>}
                  <th scope="col" className="bo-strike-column bo-group-start">BANKEX</th><th scope="col" className="bo-strike-column">ATM distance</th><th scope="col" className="bo-strike-column">BANKNIFTY</th>
                  {showPuts && <><th scope="col" className="bo-group-start">Buy Ask<span className="bo-th-sub">{board?.buy_index || "—"}</span></th><th scope="col">Sell Bid<span className="bo-th-sub">{board?.sell_index || "—"}</span></th><th scope="col">{valueLabel}</th><th scope="col">Paper position</th></>}
                </tr>
              </thead>
              <tbody>{groupedRows.map((group) => (
                <tr key={group.offset} data-offset={group.offset} className={group.offset === 0 ? "bo-atm-row" : ""}>
                  {showCalls && <QuoteCells row={group.CE} side="CE" strikePair={group} metric={settings.metric} canAdd={canAdd} pending={pending} onAdd={addPosition} onDetails={setQuoteDetails} />}
                  <td className="bo-strike-column bo-group-start"><strong>{number(group.bankex, 0)}</strong></td>
                  <td className="bo-strike-column bo-distance-cell" title={group.offset === 0 ? "At the money" : group.offset < 0 ? "Below ATM" : "Above ATM"}><strong className={group.offset === 0 ? "bo-atm-badge" : ""}>{group.offset === 0 ? "ATM" : `${group.offset > 0 ? "+" : "−"}${number(Math.abs(group.offset), 0)}`}</strong></td>
                  <td className="bo-strike-column"><strong>{number(group.banknifty, 0)}</strong></td>
                  {showPuts && <QuoteCells row={group.PE} side="PE" strikePair={group} metric={settings.metric} canAdd={canAdd} pending={pending} onAdd={addPosition} onDetails={setQuoteDetails} />}
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="bo-footnote">BANKEX ATM follows the nearest 500-point strike. BANKNIFTY strike = BANKNIFTY spot + (BANKEX strike − BANKEX spot), rounded to 100. Earlier expiry sold at Bid, later expiry bought at Ask. Paper P&amp;L uses each leg’s quantity.</p>
        </div>
      ) : (
        <div id="bo-position-panel" className="bo-panel" role="tabpanel" aria-labelledby="bo-position-tab">
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
      {selectedDetails && <QuoteDetails row={selectedDetails} unavailable={!!live.error || live.refreshing || !!invalid} onClose={() => setQuoteDetails(null)} />}
    </section>
  );
}
