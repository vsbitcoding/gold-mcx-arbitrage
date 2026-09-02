import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";
import NseMcxGraph from "./NseMcxGraph.jsx";

// NSE vs MCX — future and option chain side by side, with the difference in
// rupees AND percent on every leg (client, 13-Aug). Crude oil first, natural
// gas added the same day; those are the only two NSE commodities with a real
// two-way market.
//
// Two honesty rules baked into the display:
//   * Only bid/ask are compared. A dead contract still prints an old LTP, and
//     on NSE that can be months stale, so an untraded leg shows "no market"
//     rather than a number that invites a wrong conclusion.
//   * Both expiry dates are always on screen. The futures share one on both
//     commodities, so that difference is clean; the options never do, so part
//     of the premium gap is time value and the column header says so.
//
// History is the same board, stored whole at 10:00, 12:00 and 15:00 IST — the
// client picked the full table over an ATM-only summary. Nobody sells NSE
// commodity history, so it can only build forward from the first capture.
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) =>
  v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d);
const pct = (v) => (v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), 2) + "%");

// A price is only usable if BOTH sides are quoted. A one-sided quote makes the
// "mid" whatever that single side happens to be, and on a thin NSE strike that
// produced a +321% difference on screen - obvious nonsense that destroys trust
// in the whole column. Wide two-sided markets are shown but marked, because the
// mid between 562 and 1078 is not a price anyone can trade.
const WIDE_SPREAD = 0.25;

const PRODUCTS = [
  // Crude is subscribed in round hundreds at the source now, so this filter only
  // still matters for boards captured on 13-Aug before that change - it keeps
  // History looking like Live instead of suddenly doubling in length.
  { key: "crude", label: "Crude Oil", title: "Crude Oil — NSE vs MCX", futDec: 1, strikeDec: 0, step: 100 },
  { key: "natgas", label: "Natural Gas", title: "Natural Gas — NSE vs MCX", futDec: 2, strikeDec: 0 },
  // Futures-only: NSE lists no electricity options, so this key renders its
  // own slim view (ElecCompare) instead of the chain machinery.
  { key: "electricity", label: "Electricity", title: "Electricity — NSE vs MCX", futDec: 0 },
];
const SLOTS = [
  { key: "all", label: "All" },
  { key: "10:00", label: "10:00 AM" },
  { key: "12:00", label: "12:00 PM" },
  { key: "15:00", label: "3:00 PM" },
];

function quality(leg) {
  // A quoted 0 is not a price, it is an absent side - MCX printed the crude
  // 8300 put as 0.00 / 1289.60 and the old null-check turned that into a
  // confident-looking mid of 644.80. Matches the server, which has always
  // treated 0 as missing.
  if (!leg || !leg.bid || !leg.ask) return { ok: false, wide: false };
  const mid = (leg.bid + leg.ask) / 2;
  if (!mid) return { ok: false, wide: false };
  return { ok: true, wide: (leg.ask - leg.bid) / mid > WIDE_SPREAD, mid };
}

function DiffCell({ nse, mcx, put }) {
  const qn = quality(nse), qm = quality(mcx);
  if (!qn.ok || !qm.ok) {
    return <td className={`nm-diff nm-dead ${put ? "nm-put" : ""}`}
      title="one side has no two-way quote, so no honest comparison">—</td>;
  }
  const r = Math.round((qn.mid - qm.mid) * 100) / 100;
  const p = qm.mid ? (r / qm.mid) * 100 : null;
  const shaky = qn.wide || qm.wide;
  return (
    <td className={`nm-diff ${r >= 0 ? "pos" : "neg"} ${shaky ? "nm-shaky" : ""} ${put ? "nm-put" : ""}`}
        title={shaky ? "One side is quoted very wide, so treat this difference with caution." : ""}>
      <span className="nm-diff-rs">{signed(r)}{shaky && " ?"}</span>
      <em>{pct(p)}</em>
    </td>
  );
}

// ONE implied volatility per leg, off the mid, in its own column - the same
// shape as the Crude/Gas screen, which is what the client pointed at.
//
// He asked for a bid/ask pair on 18-Aug, saw it, and asked for a single figure
// the next day. The pair is still in the payload and sits in the hover, which is
// where the width of the answer belongs on a thin NSE strike quoted
// 712.4 / 721.8: there when wanted, out of the way when not.
function IvCell({ leg, put }) {
  const v = leg?.iv;
  const b = leg?.iv_bid, a = leg?.iv_ask;
  return (
    <td className={`nm-ivcell ${put ? "nm-put" : ""}`}
      title={v != null && b != null && a != null
        ? `${num(v, 2)}% at the mid · ${num(b, 2)}% at the bid · ${num(a, 2)}% at the ask`
        : ""}>
      {v == null ? "—" : `${num(v, 1)}%`}
    </td>
  );
}

function Leg({ leg, put }) {
  const q = quality(leg);
  if (!q.ok) {
    return (
      <td className={`nm-dead ${put ? "nm-put" : ""}`}
        title="no two-way quote - nothing tradeable here">
        —{leg?.bid != null || leg?.ask != null
          ? <em className="nm-oneside">{num(leg.bid)} / {num(leg.ask)}</em> : null}
      </td>
    );
  }
  return (
    <td className={`nm-px ${q.wide ? "nm-shaky" : ""} ${put ? "nm-put" : ""}`}>
      <span className="nm-mid">{num(q.mid)}</span>
      <em>{num(leg.bid)} / {num(leg.ask)}</em>
    </td>
  );
}

const fmtDate = (s) => {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  return d ? `${d}-${m}-${y}` : s;
};

function Futures({ f, cfg }) {
  return (
    <div className="nm-head-right">
      <div className="nm-chip">
        <div className="nm-chip-id">
          <span className="nm-chip-name">NSE FUTURE</span>
          <span className="nm-chip-exp">{fmtDate(f?.nse?.expiry)}</span>
        </div>
        <b>{num(f?.nse?.mid, cfg.futDec)}</b>
        <i>{num(f?.nse?.bid, cfg.futDec)} / {num(f?.nse?.ask, cfg.futDec)}</i>
      </div>
      <div className="nm-chip" title={f?.mcx?.symbol || ""}>
        <div className="nm-chip-id">
          <span className="nm-chip-name">MCX FUTURE</span>
          <span className="nm-chip-exp">{fmtDate(f?.mcx?.expiry)}</span>
        </div>
        <b>{num(f?.mcx?.mid, cfg.futDec)}</b>
        {/* bid/ask, exactly like the NSE card. The contract name used to sit
            here, wrapping onto two lines as "-19Aug2026-" / "FUT" to repeat an
            expiry already printed above it; it is the card's tooltip now. */}
        <i>{num(f?.mcx?.bid, cfg.futDec)} / {num(f?.mcx?.ask, cfg.futDec)}</i>
      </div>
    </div>
  );
}

// Shows its own workings. A vendor's IV was wrong for weeks precisely because
// nothing on screen said which underlying it came from, so this names the
// forward, how many strikes agreed on it, and how many days are left - the three
// inputs that can silently make every number in the table wrong.
function IvBasis({ b, cfg, fut }) {
  if (!b) return null;
  const dec = cfg.futDec ?? 2;
  const side = (k, label, shown) => {
    const s = b[k] || {};
    if (!s.forward) return <span key={k}><b>{label}</b> no forward yet</span>;
    // The gap against the future ON SCREEN is the whole point. That future is
    // the front month; the chain is the month after. On crude they were 60
    // apart, which is a five point IV error.
    const gap = shown ? Math.abs(shown - s.forward) : null;
    return (
      <span key={k}>
        <b>{label}</b> {num(s.forward, dec)}
        <em> from {s.strikes} strike{s.strikes === 1 ? "" : "s"} · {s.days}d</em>
        {gap != null && gap > 5 && (
          <i title={"The future above is the front month; this chain belongs to the month after, "
                  + num(gap, dec) + " away. IV must use the chain's own month or it is wrong."}>
            {" "}({num(gap, dec)} off the future above)
          </i>
        )}
      </span>
    );
  };
  return (
    <div className="oh-note oh-slim nm-ivbasis">
      <span className="nm-ivbasis-lead">IV from the option prices themselves,
        Black-76 with rate and dividend at zero.</span>
      {side("nse", "NSE", fut?.nse?.mid)}
      {side("mcx", "MCX", fut?.mcx?.mid)}
    </div>
  );
}

function ChainTable({ o, cfg, iv }) {
  const all = o?.rows || [];
  const rows = cfg.step
    ? all.filter((r) => r.atm || r.strike % cfg.step === 0)
    : all;
  if (!rows.length) return <div className="oh-note oh-slim">No chain rows.</div>;
  return (
    <div className="cru-table-wrap">
      <table className="cru-table nm-table">
        <colgroup>
          <col className="nm-c-px" />{iv && <col className="nm-c-iv" />}
          <col className="nm-c-px" />{iv && <col className="nm-c-iv" />}
          <col className="nm-c-diff" />
          <col className="nm-c-strike" />
          <col className="nm-c-diff" />
          {iv && <col className="nm-c-iv" />}<col className="nm-c-px" />
          {iv && <col className="nm-c-iv" />}<col className="nm-c-px" />
        </colgroup>
        <thead>
          <tr>
            <th colSpan={iv ? 5 : 3} className="intl-call">CALL</th>
            <th className="cru-strike">STRIKE</th>
            <th colSpan={iv ? 5 : 3} className="intl-put nm-put">PUT</th>
          </tr>
          <tr className="intl-chain-sub">
            {/* the expiry sits on the column it belongs to, so the header row
                above the table could go and more strikes fit on screen */}
            <th className="intl-call">NSE<em>{fmtDate(o.nse_expiry)}</em></th>
            {iv && <th className="intl-call nm-ivhead">IV</th>}
            <th className="intl-call">MCX<em>{fmtDate(o.mcx_expiry)}</em></th>
            {iv && <th className="intl-call nm-ivhead">IV</th>}
            <th className="intl-call" title={o.same_expiry ? "" : "Expiries differ, so part of each difference is time value, not a market gap."}>
              Diff{!o.same_expiry && <em className="nm-tv">incl. time value</em>}
            </th>
            <th className="cru-strike" />
            <th className="intl-put" title={o.same_expiry ? "" : "Expiries differ, so part of each difference is time value, not a market gap."}>
              Diff{!o.same_expiry && <em className="nm-tv">incl. time value</em>}
            </th>
            {/* mirrored, so each IV still sits beside the exchange it belongs to */}
            {iv && <th className="intl-put nm-ivhead nm-put">IV</th>}
            <th className="intl-put nm-put">MCX<em>{fmtDate(o.mcx_expiry)}</em></th>
            {iv && <th className="intl-put nm-ivhead nm-put">IV</th>}
            <th className="intl-put nm-put">NSE<em>{fmtDate(o.nse_expiry)}</em></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.strike} className={r.atm ? "cru-atm" : ""}>
              <Leg leg={r.ce?.nse} />
              {iv && <IvCell leg={r.ce?.nse} />}
              <Leg leg={r.ce?.mcx} />
              {iv && <IvCell leg={r.ce?.mcx} />}
              <DiffCell nse={r.ce?.nse} mcx={r.ce?.mcx} />
              <td className="cru-strike">
                {num(r.strike, cfg.strikeDec)}
                {r.atm && <span className="atm-badge">ATM</span>}
              </td>
              <DiffCell nse={r.pe?.nse} mcx={r.pe?.mcx} put />
              {iv && <IvCell leg={r.pe?.mcx} put />}
              <Leg leg={r.pe?.mcx} put />
              {iv && <IvCell leg={r.pe?.nse} put />}
              <Leg leg={r.pe?.nse} put />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const slotLabel = (s) => (SLOTS.find((x) => x.key === s) || {}).label || s;

// The button says which month it actually is once the board has loaded, so
// nobody has to guess what "next" means - on crude it is October, because NSE
// lists no August option at all.
const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function monthLabel(d, which) {
  const exp = d?.options?.nse_expiry;
  if (!exp) return which === 0 ? "This month" : "Next month";
  const m = Number(exp.split("-")[1]) - 1;
  const shown = d?.month ?? 0;
  // The payload only carries the month on screen, so the other button's name is
  // stepped from it rather than guessed.
  const i = ((m + (which - shown)) % 12 + 12) % 12;
  return MONTH_NAMES[i] || (which === 0 ? "This month" : "Next month");
}

// "4 minutes" reads; "247 s" makes the reader do arithmetic before they can
// judge whether the number above is worth looking at.
function ageWords(sec) {
  if (sec == null) return "not once since the page loaded";
  if (sec < 90) return Math.round(sec) + " seconds old";
  const m = Math.round(sec / 60);
  if (m < 90) return m + (m === 1 ? " minute old" : " minutes old");
  const h = Math.floor(sec / 3600), r = Math.round((sec % 3600) / 60);
  return h + (h === 1 ? " hour " : " hours ") + (r ? r + " min " : "") + "old";
}

// NSE quotes the near month's options fully and the month after not at all -
// 0 of 42 legs on both commodities, checked live on 17-Aug while the near month
// showed all 42. The futures do trade in both months, so the top of the screen
// is a real comparison and only the chain below it is empty. Saying which is
// the difference between an honest screen and a broken-looking one.
function NoNseChain({ d }) {
  const rows = d?.options?.rows || [];
  if (!rows.length) return null;
  const anyNse = rows.some((r) => ["ce", "pe"].some((s) => r[s]?.nse?.traded));
  if (anyNse) return null;
  return (
    <div className="settings-banner warn nm-stale">
      <b>NSE is not quoting these options.</b> Not one strike has a bid or an ask
      on the NSE side for {fmtDate(d?.options?.nse_expiry)}, so there is nothing to
      compare in the table below.
      <div className="nm-stale-why">
        The futures above are real on both exchanges - that comparison holds.
        Only the option chain is empty, and that is NSE's market, not our feed.
      </div>
    </div>
  );
}

// A stale side is the one failure this screen cannot afford to whisper about.
// On 14-Aug the NSE session died at midnight and the page served 00:00 prices
// against a live MCX until 09:40, with nothing but a small red pill to say so.
function StaleNote({ d }) {
  const bad = [];
  if (d?.nse?.stale) bad.push({ who: "NSE", sec: d.nse.stale_seconds, err: d.nse.error });
  if (d?.mcx?.stale) bad.push({ who: "MCX", sec: d.mcx.stale_seconds, err: d.mcx.error });
  if (!bad.length) return null;
  return (
    <div className="settings-banner danger nm-stale">
      {bad.map((b) => (
        <div key={b.who}>
          <b>{b.who} prices are {ageWords(b.sec)}.</b>{" "}
          {b.err ? <span className="nm-stale-err">{b.err}</span> : null}
        </div>
      ))}
      <div className="nm-stale-why">
        The difference column is blank while this lasts — subtracting a live price
        from an old one is not a difference.
      </div>
    </div>
  );
}

// Electricity - futures only, one difference (the client's note, 02-Sep).
// Live: both exchanges' futures side by side with a single MCX-minus-NSE
// number. History: our own hourly record, one row per hour since 02-Sep -
// older hours cannot exist (Angel's historical API has no NCO segment).
function ElecCompare({ d, err, product, setProduct, month, setMonth }) {
  const [view, setView] = useState("live");
  const [days, setDays] = useState(7);
  const [hist, setHist] = useState(null);
  const [histErr, setHistErr] = useState(null);
  useEffect(() => {
    if (view !== "history") return undefined;
    let alive = true;
    setHist(null);
    api.elecHourly(month, days)
      .then((r) => { if (alive) { setHist(r); setHistErr(null); } })
      .catch((e) => { if (alive) setHistErr(e.message); });
    return () => { alive = false; };
  }, [view, month, days]);

  const nse = d?.nse?.future || null;
  const mcx = d?.mcx?.future || null;
  const live = !!d?.fresh;
  const num = (v, dec = 0) => (v == null ? "—" : fmtNum(v, dec));

  const leg = (label, f, age) => (
    <div className="el-leg">
      <em>{label}</em>
      <b>{num(f?.ltp)}</b>
      <span>Buyer {num(f?.bid)} · Seller {num(f?.ask)}</span>
      <i>{f?.symbol || "—"}{age != null ? ` · ${Math.round(age)}s` : ""}</i>
    </div>
  );

  return (
    <div className="cru-page">
      <div className="nm-head">
        <div className="nm-head-left">
          <h2>Electricity — NSE vs MCX</h2>
          <span className={`intl-status ${live ? "on" : "off"}`}>
            {live ? "● Live" : "○ Feed issue"}
          </span>
        </div>
        <div className="nm-head-end">
          <div className="oh-group" role="tablist" aria-label="Commodity">
            {PRODUCTS.map((p) => (
              <button key={p.key} type="button" role="tab" aria-selected={product === p.key}
                className={`oh-chip ${product === p.key ? "on" : ""}`}
                onClick={() => setProduct(p.key)}>{p.label}</button>
            ))}
          </div>
          <div className="oh-group" role="tablist" aria-label="Month">
            {[[0, "Month 1"], [1, "Month 2"]].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={month === k}
                className={`oh-chip ${month === k ? "on" : ""}`}
                onClick={() => setMonth(k)}>{l}</button>
            ))}
          </div>
          <div className="oh-group" role="tablist" aria-label="View">
            {[["live", "Live"], ["history", "1 Hr History"]].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={view === k}
                className={`oh-chip ${view === k ? "on" : ""}`}
                onClick={() => setView(k)}>{l}</button>
            ))}
          </div>
        </div>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      {view === "live" && (
        <div className="el-board">
          {leg("NSE", nse, d?.nse?.age)}
          <div className="el-diff">
            <em>Difference (MCX − NSE)</em>
            <b className={(d?.diff ?? 0) >= 0 ? "pos" : "neg"}>{num(d?.diff)}</b>
            <span>{d?.pct == null ? "—" : `${fmtNum(d.pct, 2)}%`}</span>
          </div>
          {leg("MCX", mcx, d?.mcx?.age)}
        </div>
      )}

      {view === "history" && (
        <section className="nmg-card">
          <div className="nmg-rhd">
            <b>HOURLY DIFFERENCE</b>
            <select className="oh-weeks" value={days}
              onChange={(e) => setDays(Number(e.target.value))}>
              {[2, 7, 30, 90].map((x) => <option key={x} value={x}>{x} days</option>)}
            </select>
          </div>
          {histErr && <div className="settings-banner danger">⚠ {histErr}</div>}
          {!hist && !histErr && <div className="empty-state">Loading…</div>}
          {hist && (
            <div className="pt-tablewrap">
              <table className="pt-table sh-table">
                <thead><tr>
                  <th>Hour</th><th>NSE</th><th>MCX</th><th>Difference</th><th>%</th>
                </tr></thead>
                <tbody>
                  {hist.rows.map((r) => (
                    <tr key={r.hour}>
                      <td>{r.hour}</td>
                      <td>{num(r.nse)}</td><td>{num(r.mcx)}</td>
                      <td className={r.diff >= 0 ? "pos" : "neg"}><b>{num(r.diff)}</b></td>
                      <td>{r.pct == null ? "—" : fmtNum(r.pct, 2)}</td>
                    </tr>
                  ))}
                  {hist.rows.length === 0 && (
                    <tr><td colSpan={5}>
                      Recording started 02-Sep-2026 - rows appear from the next
                      market hour onward. Older hourly data does not exist for
                      the NSE side.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default function NseMcxCrude() {
  const [product, setProduct] = useState(() => {
    try {
      const p = localStorage.getItem("arbi_nsemcx_product");
      return PRODUCTS.some((x) => x.key === p) ? p : "crude";
    } catch { return "crude"; }
  });
  // The tab, the month and the commodity all survive a refresh. Landing back on
  // Live every time meant anyone watching History or the Graph had to click
  // their way back after every reload (client, 18-Aug).
  const [view, setView] = useState(() => {
    try {
      const v = localStorage.getItem("arbi_nsemcx_view");
      return ["live", "history", "graph"].includes(v) ? v : "live";
    } catch { return "live"; }
  });
  // Which contract month. The client asked for one at a time behind a button
  // rather than both stacked, so only the month on screen has to be watched -
  // which is why the feed can keep the near month at full speed and let the
  // far one refresh slowly.
  const [month, setMonth] = useState(() => {
    try { return localStorage.getItem("arbi_nsemcx_month") === "1" ? 1 : 0; }
    catch { return 0; }
  });
  // On by default - the client asked for IV, so it should be there when he
  // opens the page. The toggle exists because it costs a third line in every
  // price cell, which is 21 rows taller on a screen he also reads for prices.
  const [showIv, setShowIv] = useState(() => {
    try { return localStorage.getItem("arbi_nsemcx_iv") !== "0"; } catch { return true; }
  });
  const [slot, setSlot] = useState("all");
  const [days, setDays] = useState(7);
  const [d, setD] = useState(null);
  const [hist, setHist] = useState(null);
  const [loadingHist, setLoadingHist] = useState(false);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => { try { localStorage.setItem("arbi_nsemcx_product", product); } catch {} }, [product]);
  useEffect(() => { try { localStorage.setItem("arbi_nsemcx_view", view); } catch {} }, [view]);
  useEffect(() => { try { localStorage.setItem("arbi_nsemcx_month", String(month)); } catch {} }, [month]);
  useEffect(() => { try { localStorage.setItem("arbi_nsemcx_iv", showIv ? "1" : "0"); } catch {} }, [showIv]);

  // Switching commodity is a different market, so the old table must go.
  // Switching Live/History is not - the futures above are the same either way
  // and blanking them made the whole page jump. Only `product` clears state.
  useEffect(() => { setD(null); setHist(null); }, [product, month]);

  // The live poll keeps running in History too. It costs one 10 KB in-memory
  // read every three seconds, and it means the futures in the header stay live
  // and Live paints instantly on the way back instead of flashing "Loading".
  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.nseMcx(product, month);
        if (alive) { setD(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
  }, [product, month]);

  // History rows never change once written, so this fetches on a control change
  // and never polls. The old boards stay on screen while the new ones load.
  useEffect(() => {
    if (view !== "history" || product === "electricity") return undefined;
    let alive = true;
    setLoadingHist(true);
    (async () => {
      try {
        const r = await api.nseMcxHistory({ commodity: product, slot, days, month });
        if (alive) { setHist(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
      finally { if (alive) setLoadingHist(false); }
    })();
    return () => { alive = false; };
  }, [view, product, slot, days, month]);

  if (product === "electricity") {
    return (
      <ElecCompare d={d} err={err} product={product} setProduct={setProduct}
        month={month} setMonth={setMonth} />
    );
  }

  const cfg = PRODUCTS.find((p) => p.key === product) || PRODUCTS[0];
  const live = d?.nse?.ok && d?.mcx?.ok;

  const head = (
    <div className="nm-head">
      {/* The status belongs beside the name of the thing it describes, not
          alone at the far right where it wrapped onto its own line. */}
      <div className="nm-head-left">
        <h2>{cfg.title}</h2>
        <span className={`intl-status ${live ? "on" : "off"}`}
          title={live ? "" : [d?.nse?.error, d?.mcx?.error].filter(Boolean).join(" · ")}>
          {live ? "● Live" : "○ Feed issue"}
        </span>
      </div>

      {/* Rendered in BOTH views. The futures are the current market whichever
          tab is open, and taking them away on the way to History was most of
          what made switching feel like a different page loading. */}
      <Futures f={d?.future} cfg={cfg} />

      <div className="nm-head-end">
        <div className="oh-group" role="tablist" aria-label="Commodity">
          {PRODUCTS.map((p) => (
            <button key={p.key} type="button" role="tab" aria-selected={product === p.key}
              className={`oh-chip ${product === p.key ? "on" : ""}`}
              onClick={() => setProduct(p.key)}>{p.label}</button>
          ))}
        </div>
        <div className="oh-group" role="tablist" aria-label="Month">
          {[[0, monthLabel(d, 0)], [1, monthLabel(d, 1)]].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={month === k}
              className={`oh-chip ${month === k ? "on" : ""}`}
              onClick={() => setMonth(k)}>{l}</button>
          ))}
        </div>
        {/* IV is computed here, not taken from a vendor - Dhan's MCX figure
            disagrees with itself between the call and the put at one strike,
            and nobody publishes NSE IV at all. */}
        <button type="button" aria-pressed={showIv}
          className={`oh-chip nm-ivchip ${showIv ? "on" : ""}`}
          title="Implied volatility under each price, off the bid and off the ask"
          onClick={() => setShowIv((v) => !v)}>IV</button>
        <div className="oh-group" role="tablist" aria-label="View">
          {[["live", "Live"], ["history", "History"], ["graph", "Graph"]].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={view === k}
              className={`oh-chip ${view === k ? "on" : ""}`}
              onClick={() => setView(k)}>{l}</button>
          ))}
        </div>
      </div>
    </div>
  );

  if (err) return <div className="cru-page">{head}<div className="settings-banner danger">⚠ {err}</div></div>;

  if (view === "graph") {
    return (
      <div className="cru-page">
        {head}
        <NseMcxGraph product={product} month={month} cfg={cfg} />
      </div>
    );
  }

  if (view === "history") {
    const snaps = hist?.snapshots || [];
    return (
      <div className={`cru-page ${loadingHist && hist ? "nm-busy" : ""}`}>
        {head}
        <div className="oh-controls nm-hist-controls">
          <div className="oh-group" role="tablist" aria-label="Time">
            {SLOTS.map((s) => (
              <button key={s.key} type="button" role="tab" aria-selected={slot === s.key}
                className={`oh-chip ${slot === s.key ? "on" : ""}`}
                onClick={() => setSlot(s.key)}>{s.label}</button>
            ))}
          </div>
          <select className="oh-weeks" value={days} title="How many past days"
            onChange={(e) => setDays(Number(e.target.value))}>
            {[3, 7, 14, 30].map((n) => <option key={n} value={n}>Last {n} days</option>)}
          </select>
        </div>

        {/* Only on the very first load. After that the boards already on screen
            stay put while the new ones fetch, so changing a filter does not
            empty the page and fill it again. */}
        {!hist && loadingHist && <div className="empty-state">Loading history…</div>}
        {hist && snaps.length === 0 && !loadingHist && (
          <div className="oh-note">
            No saved boards yet. The full table is stored automatically at <b>10:00 AM</b>,
            <b> 12:00 PM</b> and <b>3:00 PM</b> IST every trading day. No exchange sells NSE
            commodity history, so this builds up from the first capture onward.
          </div>
        )}
        {snaps.map((s, i) => (
          <section key={s.snap_date + s.slot}
            className={`oh-board ${s.snap_date !== snaps[i - 1]?.snap_date ? "oh-day-start" : ""}`}>
            <div className="oh-board-head">
              <span className="oh-board-date">{fmtDate(s.snap_date)}</span>
              <span className="oh-board-dot">•</span>
              <span className="oh-board-slot" data-slot={s.slot}>{slotLabel(s.slot)}</span>
            </div>
            <div className="nm-hist-futs">
              <Futures f={s.board?.future} cfg={cfg} />
            </div>
            <ChainTable o={s.board?.options} cfg={cfg} iv={showIv} />
          </section>
        ))}
      </div>
    );
  }

  if (!d) return <div className="cru-page">{head}<div className="empty-state">Loading {cfg.label.toLowerCase()}…</div></div>;

  return (
    <div className="cru-page">
      {head}
      <StaleNote d={d} />
      <NoNseChain d={d} />
      {showIv && <IvBasis b={d.iv_basis} cfg={cfg} fut={d.future} />}
      <ChainTable o={d.options} cfg={cfg} iv={showIv} />
    </div>
  );
}
