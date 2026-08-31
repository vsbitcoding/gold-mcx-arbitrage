import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useConfirm } from "./ConfirmDialog.jsx";
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
  { key: "accounts", label: "Accounts" },
];

// A small overlay for the two editors. The app has no modal primitive beyond
// the confirm dialog, and these forms are too big for it.
function Overlay({ title, onClose, children }) {
  return (
    <div className="pt-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pt-modal" role="dialog" aria-label={title}>
        <div className="pt-modal-head">
          <b>{title}</b>
          <button type="button" className="pt-modal-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// The Manual Signal form: for the day TradingView shows "delivery failed" and
// the book has drifted from the strategy. It fires the webhook's exact path -
// same flip rules, same account fan-out, same live price - and the client
// asked for a confirm before the final send.
function ManualSignal({ symbols, tfs, onClose, onSent, confirm }) {
  const [sym, setSym] = useState(symbols[0] || "");
  const [side, setSide] = useState("buy");
  const [lot, setLot] = useState("1");
  const [tf, setTf] = useState(tfs[0] || "5m");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [fail, setFail] = useState(null);

  async function send() {
    const ok = await confirm({
      title: `Send ${side.toUpperCase()} ${sym}${tf ? " " + tf : ""}?`,
      message: `This fires a ${side} signal for ${lot || 1} lot at the current market price - exactly as if TradingView sent it. Every account holding ${sym} will act on it.`,
      confirmText: `Send ${side}`,
      danger: true,
    });
    if (!ok) return;
    setBusy(true); setFail(null);
    try {
      const r = await api.paperManualSignal({
        type: side, symbol: sym, lot: Number(lot) || 1,
        timeframe: (tf || "").trim() || undefined,
      });
      setResult(r);
      if (r.status === "rejected") setFail(r.reason || "rejected");
      else onSent();
    } catch (e) { setFail(e.message); }
    finally { setBusy(false); }
  }

  return (
    <Overlay title="Manual signal" onClose={onClose}>
      <div className="pt-form">
        <p className="pt-form-hint">
          For a missed webhook: fires the same signal TradingView would have,
          at the current live price. It follows every normal rule - flip,
          duplicate-ignore, account routing - and the Log will say it was manual.
        </p>
        <div className="pt-form-row">
          <label><span>Symbol</span>
            <select className="oh-weeks pt-form-select" value={sym}
              onChange={(e) => setSym(e.target.value)}>
              {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
          <label><span>Type</span>
            <div className="oh-group">
              {["buy", "sell"].map((s) => (
                <button key={s} type="button"
                  className={`oh-chip ${side === s ? "on" : ""}`}
                  onClick={() => setSide(s)}>{s.toUpperCase()}</button>
              ))}
            </div></label>
        </div>
        <div className="pt-form-row">
          <label><span>Lot</span>
            <input type="number" min="0.5" step="0.5" value={lot}
              onChange={(e) => setLot(e.target.value)} /></label>
          <label><span>Timeframe</span>
            <input value={tf} list="pt-tf-list" placeholder="5m"
              onChange={(e) => setTf(e.target.value.toLowerCase())} />
            <datalist id="pt-tf-list">
              {tfs.map((x) => <option key={x} value={x} />)}
            </datalist></label>
        </div>
        {fail && <div className="settings-banner danger">⚠ {fail}</div>}
        {result && result.status !== "rejected" && (
          <div className="pt-sent">
            {(result.accounts || []).map((a) => (
              <span key={a.account}><b>{a.account}</b>: {a.status}</span>
            ))}
          </div>
        )}
        <div className="pt-form-foot">
          <button type="button" className="oh-chip" onClick={onClose}>
            {result && result.status !== "rejected" ? "Done" : "Cancel"}
          </button>
          <button type="button" className="oh-chip on" disabled={busy || !sym}
            onClick={send}>{busy ? "…" : "Send signal"}</button>
        </div>
      </div>
    </Overlay>
  );
}

// The account form. Angel fields are stored-only placeholders today (client,
// 24-Aug: fake details now, real accounts someday) - so they are optional,
// masked on read, and an empty field on save means "keep what is stored".
function AccountEditor({ initial, symbols, onSave, onClose }) {
  const [name, setName] = useState(initial?.name || "");
  const [cid, setCid] = useState(initial?.angel_client_id || "");
  const [mpin, setMpin] = useState("");
  const [totp, setTotp] = useState("");
  const [picked, setPicked] = useState(() => new Set(initial?.symbols || []));
  const toggle = (s) => setPicked((old) => {
    const n = new Set(old);
    if (n.has(s)) n.delete(s); else n.add(s);
    return n;
  });
  return (
    <Overlay title={initial?.id ? `Edit account · ${initial.name}` : "Add account"} onClose={onClose}>
      <div className="pt-form">
        <label><span>Account name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="bhavesh" /></label>
        <label><span>Angel One client ID <em>optional, stored only</em></span>
          <input value={cid} onChange={(e) => setCid(e.target.value)} placeholder="A123456" /></label>
        <div className="pt-form-row">
          <label><span>MPIN <em>optional</em></span>
            <input value={mpin} onChange={(e) => setMpin(e.target.value)}
              placeholder={initial?.angel_mpin ? "saved - leave blank to keep" : ""} /></label>
          <label><span>TOTP secret <em>optional</em></span>
            <input value={totp} onChange={(e) => setTotp(e.target.value)}
              placeholder={initial?.angel_totp ? "saved - leave blank to keep" : ""} /></label>
        </div>
        <div className="pt-form-syms">
          <span>Symbols this account trades</span>
          <div className="pt-symgrid">
            {symbols.map((s) => (
              <label key={s} className={`pt-symtick ${picked.has(s) ? "on" : ""}`}>
                <input type="checkbox" checked={picked.has(s)} onChange={() => toggle(s)} />
                {s}
              </label>
            ))}
          </div>
          {symbols.length === 0 && <i>No symbols yet - add them in Manage Symbols first.</i>}
        </div>
        <div className="pt-form-foot">
          <button type="button" className="oh-chip" onClick={onClose}>Cancel</button>
          <button type="button" className="oh-chip on" disabled={!name.trim()}
            onClick={() => onSave({ name: name.trim(), angel_client_id: cid.trim(),
                                    angel_mpin: mpin.trim(), angel_totp: totp.trim(),
                                    symbols: [...picked] })}>
            {initial?.id ? "Save changes" : "Add account"}
          </button>
        </div>
      </div>
    </Overlay>
  );
}

// Master symbol list: add (resolved against the exchange master, typos are
// refused with the reason), rename, delete. Deletes confirm upstream.
function SymbolManager({ symbols, onAdd, onRename, onDelete, onClose, error }) {
  const [draft, setDraft] = useState("");
  const [renaming, setRenaming] = useState(null);   // symbol being renamed
  const [renameTo, setRenameTo] = useState("");
  return (
    <Overlay title="Manage symbols" onClose={onClose}>
      <div className="pt-form">
        <div className="pt-symadd">
          <input value={draft} placeholder="Official MCX name, e.g. CRUDEOIL"
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
            onKeyDown={(e) => { if (e.key === "Enter" && draft.trim()) { onAdd(draft.trim()); setDraft(""); } }} />
          <button type="button" className="oh-chip on" disabled={!draft.trim()}
            onClick={() => { onAdd(draft.trim()); setDraft(""); }}>Add</button>
        </div>
        {error && <div className="settings-banner danger">⚠ {error}</div>}
        <div className="pt-symlist">
          {symbols.map((s) => (
            <div className="pt-symrow" key={s}>
              {renaming === s ? (
                <>
                  <input autoFocus value={renameTo}
                    onChange={(e) => setRenameTo(e.target.value.toUpperCase())} />
                  <button type="button" className="oh-chip on" disabled={!renameTo.trim()}
                    onClick={() => { onRename(s, renameTo.trim()); setRenaming(null); }}>Save</button>
                  <button type="button" className="oh-chip"
                    onClick={() => setRenaming(null)}>Cancel</button>
                </>
              ) : (
                <>
                  <b>{s}</b>
                  <button type="button" className="oh-chip"
                    onClick={() => { setRenaming(s); setRenameTo(s); }}>Edit</button>
                  <button type="button" className="oh-chip pt-danger"
                    onClick={() => onDelete(s)}>Delete</button>
                </>
              )}
            </div>
          ))}
          {symbols.length === 0 && <i>Empty - add the first symbol above.</i>}
        </div>
      </div>
    </Overlay>
  );
}

export default function AutoTrades() {
  const [view, setView] = useState(() => {
    try { return localStorage.getItem("arbi_pt_view") || "live"; } catch { return "live"; }
  });
  const confirm = useConfirm();
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [tf, setTf] = useState("");
  const [symbols, setSymbols] = useState([]);
  const [tfs, setTfs] = useState([]);
  const [busyState, setBusyState] = useState(false);

  const [account, setAccount] = useState("");      // filter: account name
  const [editAcc, setEditAcc] = useState(null);    // null | {} (new) | account obj
  const [symModal, setSymModal] = useState(false);
  const [sigModal, setSigModal] = useState(false);
  const [live, setLive] = useState(null);
  const [hist, setHist] = useState(null);
  const [logs, setLogs] = useState(null);
  const [histPage, setHistPage] = useState(1);
  const [logPage, setLogPage] = useState(1);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => { try { localStorage.setItem("arbi_pt_view", view); } catch {} }, [view]);
  // Filters reset their pagination - page 3 of a different filter is nonsense.
  useEffect(() => { setHistPage(1); setLogPage(1); }, [symbol, side, tf, account]);

  // Live polls; the other two tabs are event-shaped data and fetch on demand.
  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.paperPositions();
        if (alive) {
          setLive(r); setSymbols(r.symbols || []);
          setTfs(r.timeframes || []); setErr(null);
        }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
  }, []);

  useEffect(() => {
    if (view !== "history") return undefined;
    let alive = true;
    api.paperTrades({ symbol, side, timeframe: tf, account_id: accId, page: histPage })
      .then((r) => { if (alive) { setHist(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [view, symbol, side, tf, account, histPage]);

  useEffect(() => {
    if (view !== "log") return undefined;
    let alive = true;
    // History filters speak long/short; the log speaks buy/sell. One dropdown
    // serves both, translated here.
    const logSide = side === "long" ? "buy" : side === "short" ? "sell" : "";
    api.paperSignals({ symbol, side: logSide, timeframe: tf, account, page: logPage })
      .then((r) => { if (alive) { setLogs(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [view, symbol, side, tf, account, logPage]);

  const positions = useMemo(() => {
    let p = live?.positions || [];
    if (symbol) p = p.filter((x) => x.symbol === symbol);
    if (side) p = p.filter((x) => x.side === side);
    if (tf) p = p.filter((x) => (x.timeframe || "") === tf);
    if (account) p = p.filter((x) => x.account === account);
    return p;
  }, [live, symbol, side, tf, account]);

  const runningPnl = useMemo(
    () => positions.reduce((a, x) => a + (x.pnl || 0), 0), [positions]);

  // The Live strip shows booked totals too, so the summary must exist before
  // anyone visits History - one light fetch, refreshed when a position closes
  // (the open-position count dropping is the only way one ever does).
  useEffect(() => {
    let alive = true;
    api.paperTrades({ symbol, side, timeframe: tf, account_id: accId, page: 1, page_size: 5 })
      .then((r) => { if (alive) setHist((h) => (view === "history" ? h : r)); })
      .catch(() => {});
    return () => { alive = false; };
  }, [symbol, side, tf, account, live?.positions?.length]);

  // One clock for every card's "since entry" - ticking once a second beats
  // 3-second jumps, and one interval beats one per card.
  const [nowMs, setNowMs] = useState(Date.now());
  useEffect(() => {
    if (view !== "live") return undefined;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [view]);

  const sum = hist?.summary;
  const sysOn = live?.state ? !!live.state.enabled : true;
  const accounts = live?.accounts || [];
  const accId = (accounts.find((a) => a.name === account) || {}).id || null;

  // Manual close of one card. Same double-confirm ritual the app uses for
  // every destructive act - Stop, logout - because a booked exit cannot be
  // un-booked (client, 24-Aug: "same like generally aapde delete par karta").
  async function closeTrade(p) {
    const up = (p.pnl ?? 0) >= 0;
    const ok = await confirm({
      title: `Close ${p.symbol}${p.timeframe ? " " + p.timeframe : ""}?`,
      message: `This books the ${p.side} position at the current price - running P/L ${up ? "+" : "−"}₹${fmtNum(Math.abs(p.pnl ?? 0), 2)} becomes final and goes to History. This cannot be undone.`,
      confirmText: "Close trade",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.paperCloseTrade(p.id);
      const r = await api.paperPositions();
      setLive(r); setSymbols(r.symbols || []); setTfs(r.timeframes || []);
    } catch (e) { setErr(e.message); }
  }

  async function refreshLive() {
    try {
      const r = await api.paperPositions();
      setLive(r); setSymbols(r.symbols || []); setTfs(r.timeframes || []);
    } catch (e) { setErr(e.message); }
  }

  async function saveAccount(form) {
    try {
      await api.paperAccountSave(form, editAcc?.id);
      setEditAcc(null);
      await refreshLive();
    } catch (e) { setErr(e.message); }
  }

  async function deleteAccount(a) {
    const ok = await confirm({
      title: `Delete account ${a.name}?`,
      message: "Its closed history stays, but no future webhook will trade for this account. Open trades block the delete.",
      confirmText: "Delete account",
      danger: true,
    });
    if (!ok) return;
    try { await api.paperAccountDelete(a.id); await refreshLive(); }
    catch (e) { setErr(e.message); }
  }

  async function deleteSymbol(s) {
    const ok = await confirm({
      title: `Remove symbol ${s}?`,
      message: "It leaves the master list and every account that ticked it. Open trades on it block the remove.",
      confirmText: "Remove symbol",
      danger: true,
    });
    if (!ok) return;
    try { await api.paperSymbolDelete(s); await refreshLive(); }
    catch (e) { setErr(e.message); }
  }

  async function toggleSystem() {
    if (busyState) return;
    if (sysOn) {
      const openCount = (live?.positions || []).length;
      const ok = await confirm({
        title: "Stop the system?",
        message: openCount
          ? `All ${openCount} open trade${openCount === 1 ? "" : "s"} will be closed at the current price and booked to History. Webhooks will be logged but no trades will fire until you press Start.`
          : "Webhooks will be logged but no trades will fire until you press Start.",
        confirmText: "Stop and close all",
        danger: true,
      });
      if (!ok) return;
    }
    setBusyState(true);
    try {
      await api.paperSetState(!sysOn);
      const r = await api.paperPositions();
      setLive(r); setSymbols(r.symbols || []); setTfs(r.timeframes || []);
    } catch (e) { setErr(e.message); }
    finally { setBusyState(false); }
  }

  return (
    <div className="pt-page">
      <div className="nm-head">
        <div className="nm-head-left">
          <h2>Auto Trades</h2>
          <span className="intl-status on" title="Dummy trades fired by webhook, monitored on the live MCX feed. No real orders anywhere.">
            ● Paper only
          </span>
          <button type="button" className="oh-chip pt-manualsig"
            title="Fire a signal by hand - for when TradingView shows delivery failed"
            onClick={() => setSigModal(true)}>+ Manual Signal</button>
          <button type="button" disabled={busyState}
            className={`pt-power ${sysOn ? "running" : "stopped"}`}
            title={sysOn
              ? "Stop: closes every open trade at the current price, then webhooks fire nothing until Start."
              : "Start: webhooks fire trades again from now on."}
            onClick={toggleSystem}>
            {busyState ? "…" : sysOn ? "■ Stop" : "▶ Start"}
          </button>
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
          <select className="oh-weeks" value={account} onChange={(e) => setAccount(e.target.value)}
            aria-label="Account filter">
            <option value="">All accounts</option>
            {accounts.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}
          </select>
          <select className="oh-weeks" value={tf} onChange={(e) => setTf(e.target.value)}
            aria-label="Timeframe filter">
            <option value="">All timeframes</option>
            {tfs.map((x) => <option key={x} value={x}>{x}</option>)}
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

      {!sysOn && (
        <div className="pt-stopped">
          <b>System stopped</b>
          {live?.state?.changed_by ? ` by ${live.state.changed_by}` : ""}
          {live?.state?.changed_at ? ` · ${when(live.state.changed_at)}` : ""}.
          Incoming webhooks are being logged with the reason, but no trade will
          open or close until Start is pressed.
        </div>
      )}

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
                        <span className="pt-acct">{p.account}</span>
                      </div>
                      <span className="pt-card-meta" title={p.contract || ""}>
                        {num(p.lots, 0)} lot{p.lots === 1 ? "" : "s"}
                        {p.timeframe ? ` · ${p.timeframe}` : ""}
                      </span>
                      <button type="button" className="pt-close"
                        title="Close this trade now at the current price (asks first)"
                        onClick={() => closeTrade(p)}>Close</button>
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
                  <th>#</th><th>Account</th><th>Symbol</th><th>Side</th><th>Lots</th><th>TF</th>
                  <th>Entry</th><th>Entry ₹</th><th>Exit</th><th>Exit ₹</th>
                  <th>Points</th><th>P/L ₹</th><th>Closed by</th><th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {(hist?.rows || []).map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td className="pt-acct-cell">{r.account}</td>
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
                    <td>
                      <span className={`pt-act ${
                          r.exit_reason === "stop" ? "pt-act-flipped"
                          : r.exit_reason === "manual" ? "pt-act-manual"
                          : r.exit_reason === "roll" ? "pt-act-flipped"
                          : "pt-act-ignored"}`}
                        title={r.exit_reason === "stop"
                          ? "Closed by the Stop button, at that moment's price."
                          : r.exit_reason === "manual"
                            ? "Closed by hand from the position card."
                            : r.exit_reason === "roll"
                              ? "Contract changed (expiry roll) - booked at the old contract's last price."
                              : "Closed by the opposite webhook signal."}>
                        {r.exit_reason === "stop" ? "stop"
                          : r.exit_reason === "manual" ? "manual"
                          : r.exit_reason === "roll" ? "roll" : "webhook"}
                      </span>
                    </td>
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
                  <th>Received</th><th>Account</th><th>Symbol</th><th>Side</th><th>Lots</th><th>TF</th>
                  <th>LTP used</th><th>Action</th><th>Reason</th><th>ms</th>
                </tr>
              </thead>
              <tbody>
                {(logs?.rows || []).map((r) => (
                  <tr key={r.id} className={`pt-act-${r.action}`}>
                    <td className="pt-time">{when(r.received_at)}</td>
                    <td className="pt-acct-cell">{r.account || "—"}</td>
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

      {view === "accounts" && (
        <section className="nmg-card pt-accpanel">
          <div className="nmg-rhd">
            <b>ACCOUNTS</b>
            <span className="pt-accbtns">
              <button type="button" className="oh-chip" onClick={() => setSymModal(true)}>
                Manage symbols
              </button>
              <button type="button" className="oh-chip on" onClick={() => setEditAcc({})}>
                + Add account
              </button>
            </span>
          </div>
          {accounts.length === 0 ? (
            <div className="nmg-empty">
              <b>No accounts yet</b>
              <span>A webhook only trades in accounts whose symbol list carries its
                symbol - add the first account to route signals.</span>
            </div>
          ) : (
            <div className="pt-acclist">
              {accounts.map((a) => (
                <div className="pt-accrow" key={a.id}>
                  <div className="pt-accmain">
                    <b>{a.name}</b>
                    <span className="pt-accsyms">
                      {a.symbols.length
                        ? a.symbols.map((s) => <i key={s}>{s}</i>)
                        : <em>no symbols - webhooks will not trade here</em>}
                    </span>
                  </div>
                  <div className="pt-accmeta">
                    {a.angel_client_id ? <span title="Angel One client id">{a.angel_client_id}</span> : null}
                    {a.angel_mpin ? <span title="MPIN stored">MPIN ✓</span> : null}
                    {a.angel_totp ? <span title="TOTP stored">TOTP ✓</span> : null}
                  </div>
                  <div className="pt-accact">
                    <button type="button" className="oh-chip" onClick={() => setEditAcc(a)}>Edit</button>
                    <button type="button" className="oh-chip pt-danger" onClick={() => deleteAccount(a)}>Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {editAcc !== null && (
        <AccountEditor initial={editAcc.id ? editAcc : null} symbols={symbols}
          onSave={saveAccount} onClose={() => setEditAcc(null)} />
      )}
      {sigModal && (
        <ManualSignal symbols={symbols} tfs={tfs} confirm={confirm}
          onClose={() => setSigModal(false)} onSent={refreshLive} />
      )}
      {symModal && (
        <SymbolManager symbols={symbols} error={err}
          onAdd={async (s) => { try { await api.paperSymbolAdd(s); setErr(null); await refreshLive(); } catch (e) { setErr(e.message); } }}
          onRename={async (o, n) => { try { await api.paperSymbolAdd(n, o); setErr(null); await refreshLive(); } catch (e) { setErr(e.message); } }}
          onDelete={deleteSymbol}
          onClose={() => { setSymModal(false); setErr(null); }} />
      )}
    </div>
  );
}
