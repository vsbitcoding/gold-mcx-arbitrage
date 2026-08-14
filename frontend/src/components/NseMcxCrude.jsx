import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

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

function DiffCell({ nse, mcx }) {
  const qn = quality(nse), qm = quality(mcx);
  if (!qn.ok || !qm.ok) {
    return <td className="nm-diff nm-dead" title="one side has no two-way quote, so no honest comparison">—</td>;
  }
  const r = Math.round((qn.mid - qm.mid) * 100) / 100;
  const p = qm.mid ? (r / qm.mid) * 100 : null;
  const shaky = qn.wide || qm.wide;
  return (
    <td className={`nm-diff ${r >= 0 ? "pos" : "neg"} ${shaky ? "nm-shaky" : ""}`}
        title={shaky ? "One side is quoted very wide, so treat this difference with caution." : ""}>
      <span className="nm-diff-rs">{signed(r)}{shaky && " ?"}</span>
      <em>{pct(p)}</em>
    </td>
  );
}

function Leg({ leg }) {
  const q = quality(leg);
  if (!q.ok) {
    return (
      <td className="nm-dead" title="no two-way quote - nothing tradeable here">
        —{leg?.bid != null || leg?.ask != null
          ? <em className="nm-oneside">{num(leg.bid)} / {num(leg.ask)}</em> : null}
      </td>
    );
  }
  return (
    <td className={`nm-px ${q.wide ? "nm-shaky" : ""}`}>
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
      <div className="nm-chip">
        <div className="nm-chip-id">
          <span className="nm-chip-name">MCX FUTURE</span>
          <span className="nm-chip-exp">{fmtDate(f?.mcx?.expiry)}</span>
        </div>
        <b>{num(f?.mcx?.mid, cfg.futDec)}</b>
        <i className="nm-chip-sym">{f?.mcx?.symbol || ""}</i>
      </div>
    </div>
  );
}

function ChainTable({ o, cfg }) {
  const all = o?.rows || [];
  const rows = cfg.step
    ? all.filter((r) => r.atm || r.strike % cfg.step === 0)
    : all;
  if (!rows.length) return <div className="oh-note oh-slim">No chain rows.</div>;
  return (
    <div className="cru-table-wrap">
      <table className="cru-table nm-table">
        <colgroup>
          <col className="nm-c-px" /><col className="nm-c-px" /><col className="nm-c-diff" />
          <col className="nm-c-strike" />
          <col className="nm-c-diff" /><col className="nm-c-px" /><col className="nm-c-px" />
        </colgroup>
        <thead>
          <tr>
            <th colSpan={3} className="intl-call">CALL</th>
            <th className="cru-strike">STRIKE</th>
            <th colSpan={3} className="intl-put">PUT</th>
          </tr>
          <tr className="intl-chain-sub">
            {/* the expiry sits on the column it belongs to, so the header row
                above the table could go and more strikes fit on screen */}
            <th className="intl-call">NSE<em>{fmtDate(o.nse_expiry)}</em></th>
            <th className="intl-call">MCX<em>{fmtDate(o.mcx_expiry)}</em></th>
            <th className="intl-call" title={o.same_expiry ? "" : "Expiries differ, so part of each difference is time value, not a market gap."}>
              Diff{!o.same_expiry && <em className="nm-tv">incl. time value</em>}
            </th>
            <th className="cru-strike" />
            <th className="intl-put" title={o.same_expiry ? "" : "Expiries differ, so part of each difference is time value, not a market gap."}>
              Diff{!o.same_expiry && <em className="nm-tv">incl. time value</em>}
            </th>
            <th className="intl-put">MCX<em>{fmtDate(o.mcx_expiry)}</em></th>
            <th className="intl-put">NSE<em>{fmtDate(o.nse_expiry)}</em></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.strike} className={r.atm ? "cru-atm" : ""}>
              <Leg leg={r.ce?.nse} />
              <Leg leg={r.ce?.mcx} />
              <DiffCell nse={r.ce?.nse} mcx={r.ce?.mcx} />
              <td className="cru-strike">
                {num(r.strike, cfg.strikeDec)}
                {r.atm && <span className="atm-badge">ATM</span>}
              </td>
              <DiffCell nse={r.pe?.nse} mcx={r.pe?.mcx} />
              <Leg leg={r.pe?.mcx} />
              <Leg leg={r.pe?.nse} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const slotLabel = (s) => (SLOTS.find((x) => x.key === s) || {}).label || s;

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

export default function NseMcxCrude() {
  const [product, setProduct] = useState(() => {
    try {
      const p = localStorage.getItem("arbi_nsemcx_product");
      return PRODUCTS.some((x) => x.key === p) ? p : "crude";
    } catch { return "crude"; }
  });
  const [view, setView] = useState("live");
  const [slot, setSlot] = useState("all");
  const [days, setDays] = useState(7);
  const [d, setD] = useState(null);
  const [hist, setHist] = useState(null);
  const [loadingHist, setLoadingHist] = useState(false);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => { try { localStorage.setItem("arbi_nsemcx_product", product); } catch {} }, [product]);

  // Switching commodity is a different market, so the old table must go.
  // Switching Live/History is not - the futures above are the same either way
  // and blanking them made the whole page jump. Only `product` clears state.
  useEffect(() => { setD(null); setHist(null); }, [product]);

  // The live poll keeps running in History too. It costs one 10 KB in-memory
  // read every three seconds, and it means the futures in the header stay live
  // and Live paints instantly on the way back instead of flashing "Loading".
  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.nseMcx(product);
        if (alive) { setD(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
  }, [product]);

  // History rows never change once written, so this fetches on a control change
  // and never polls. The old boards stay on screen while the new ones load.
  useEffect(() => {
    if (view !== "history") return undefined;
    let alive = true;
    setLoadingHist(true);
    (async () => {
      try {
        const r = await api.nseMcxHistory({ commodity: product, slot, days });
        if (alive) { setHist(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
      finally { if (alive) setLoadingHist(false); }
    })();
    return () => { alive = false; };
  }, [view, product, slot, days]);

  const cfg = PRODUCTS.find((p) => p.key === product) || PRODUCTS[0];
  const live = d?.nse?.ok && d?.mcx?.ok;

  const head = (
    <div className="nm-head">
      <h2>{cfg.title}</h2>

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
        <div className="oh-group" role="tablist" aria-label="View">
          {[["live", "Live"], ["history", "History"]].map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={view === k}
              className={`oh-chip ${view === k ? "on" : ""}`}
              onClick={() => setView(k)}>{l}</button>
          ))}
        </div>
        {/* Always present, so the row never changes width when the tab changes. */}
        <span className={`intl-status ${live ? "on" : "off"}`}
          title={live ? "" : [d?.nse?.error, d?.mcx?.error].filter(Boolean).join(" · ")}>
          {live ? "● Live" : "○ Feed issue"}
        </span>
      </div>
    </div>
  );

  if (err) return <div className="cru-page">{head}<div className="settings-banner danger">⚠ {err}</div></div>;

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
            <ChainTable o={s.board?.options} cfg={cfg} />
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
      <ChainTable o={d.options} cfg={cfg} />
    </div>
  );
}
