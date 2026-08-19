import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Crude Oil / Natural Gas — MCX and US option chains side by side with implied
// volatility. One screen with a commodity switch rather than a tab each: the
// nav is already fourteen wide.
// Layout is the client's own (same as the Commodity Options tab): 10 calls
// above the money, the ATM row carrying both sides, 10 puts below.
// Both chains are read from one tiny in-memory endpoint; polling pauses when
// the tab is hidden.
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const iv = (v) => (v == null || v === 0 ? "—" : fmtNum(v, 2) + "%");

function Chain({ title, sub, badge, data, priceDecimals, strikeDecimals, showOi }) {
  const rows = data?.rows || [];
  return (
    <div className="cru-chain">
      <div className="cru-chain-head">
        <div>
          <span className="cru-chain-title">{title}</span>
          <span className="cru-chain-sub">{sub}</span>
        </div>
        <span className="cru-fut">
          {data?.future_price != null ? num(data.future_price, priceDecimals) : "—"}
          <em>future</em>
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="oh-note oh-slim">{badge || "Loading chain…"}</div>
      ) : (
        <div className="cru-table-wrap">
          <table className="cru-table">
            <thead>
              <tr>
                <th className="cru-side">Type</th>
                <th className="cru-strike">Strike</th>
                <th>Bid</th>
                <th>Ask</th>
                <th className="cru-iv-col">IV</th>
                <th>Delta</th>
                {showOi && <th>OI</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                // PE sits above CE on the ATM row: puts run above the money and
                // calls below, so this keeps each block unbroken (client, 05-Aug).
                const legs = r.atm
                  ? [["PE", r.pe], ["CE", r.ce]]
                  : [[r.side, r.side === "CE" ? r.ce : r.pe]];
                return legs.map(([side, leg], i) => (
                  <tr key={`${r.strike}-${side}`}
                    className={`${r.atm ? "cru-atm" : ""} ${side === "CE" ? "cru-ce" : "cru-pe"}`}>
                    <td className="cru-side">
                      <span className={`cru-tag ${String(side || "").toLowerCase()}`}>{side}</span>
                    </td>
                    {i === 0 ? (
                      <td className="cru-strike" rowSpan={legs.length}>
                        {num(r.strike, strikeDecimals)}
                        {r.atm && <span className="atm-badge">ATM</span>}
                      </td>
                    ) : null}
                    <td>{num(leg?.bid, priceDecimals)}</td>
                    <td>{num(leg?.ask, priceDecimals)}</td>
                    {/* A volatility solved off the mid of 100.1 / 799.9 is
                        arithmetic, not a market reading. The MCX October chain
                        had 12 of 13 legs like that on 19-Aug. Marked rather than
                        blanked - removing them empties the panel, and an empty
                        panel says less than a flagged one. */}
                    <td className={`cru-iv-col ${leg?.wide ? "cru-shaky" : ""}`}
                      title={leg?.wide
                        ? "Bid and ask are more than 25% apart, so this volatility comes from a mid nobody could deal at."
                        : ""}>
                      {iv(leg?.iv)}{leg?.wide && leg?.iv != null ? " ?" : ""}
                    </td>
                    <td>{leg?.delta == null ? "—" : fmtNum(leg.delta, 3)}</td>
                    {showOi && <td>{leg?.oi == null ? "—" : fmtNum(leg.oi, 0)}</td>}
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const PRODUCTS = [
  { key: "crude", label: "Crude Oil", usTitle: "US CRUDE OIL (NYMEX)", usDec: 2, mcxDec: 1 },
  { key: "natgas", label: "Natural Gas", usTitle: "US NATURAL GAS (NYMEX)", usDec: 3, mcxDec: 2 },
];

// `currency="inr"` is the Crude / Gas INR tab: the same screen with the US side
// restated in rupees at the USD/INR future, so both panels read in one currency
// and the premiums can be compared line for line instead of in your head.
// The IV is identical either way and deliberately so.
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Named by the expiry actually loaded. "Next" tells you nothing when the front
// option month is already two months out, which it is on crude.
function monthLabel(d, which) {
  const exp = d?.mcx?.expiry;
  if (!exp) return which === 0 ? "This month" : "Next month";
  const m = Number(String(exp).split("-")[1]) - 1;
  const shown = d?.month ?? 0;
  const i = ((m + (which - shown)) % 12 + 12) % 12;
  return MONTH_NAMES[i] || (which === 0 ? "This month" : "Next month");
}

// Stored boards are flat lists with a cols_ header - the shape that took a
// year of this history from 433 MB to 89 MB. Unpack back into the live shape so
// one <Chain> renders both.
function unpack(chain, cols, rate) {
  if (!chain?.rows) return { rows: [] };
  const at = (row, name) => {
    const i = cols.indexOf(name);
    return i < 0 ? null : row[i];
  };
  // The US side is stored in DOLLARS and converted here, at the rate that
  // applied when the board was captured - which is kept beside it. The History
  // view was labelling the panel "in Rs" and printing dollars: MCX 8,102 next to
  // US 83, the one comparison the rupee tab exists to make (client, 19-Aug).
  // Converting at read time also beats storing both: one fact, one copy, and a
  // six o'clock board is never restated at eight o'clock's rate.
  const r = rate || 1;
  const px = (v, f = 1) => (typeof v === "number" ? v * r * f : v);
  // `side` is not stored - it is derivable, and repeating "CE"/"PE" on every
  // strike of every board would be bytes for nothing. Rebuild it by the same
  // rule get_chain uses: calls above the money, puts below, both on the ATM.
  // Leaving it out is what crashed the History view on its first day: <Chain>
  // switches on it and called .toLowerCase() on undefined.
  const atmStrike = (chain.rows.find((r) => at(r, "atm")) || [])[cols.indexOf("strike")];
  const leg = (row, s) => ({
    bid: px(at(row, `${s}_bid`)), ask: px(at(row, `${s}_ask`)),
    // IV is unchanged by the conversion - scaling forward, strike and price by
    // one rate cannot move it - and delta is dimensionless.
    iv: at(row, `${s}_iv`), delta: at(row, `${s}_delta`),
    wide: !!at(row, `${s}_wide`), oi: at(row, `${s}_oi`),
  });
  return {
    ...chain,
    future_price: px(chain.future),
    rows: chain.rows.map((row) => ({
      strike: px(at(row, "strike")),
      atm: !!at(row, "atm"),
      side: at(row, "atm") ? "ATM"
        : (atmStrike != null && at(row, "strike") > atmStrike ? "CE" : "PE"),
      ce: leg(row, "ce"),
      pe: leg(row, "pe"),
    })),
  };
}

const hhmm = (s) => {
  const [h, m] = String(s || "").split(":");
  const hh = Number(h);
  if (!Number.isFinite(hh)) return s;
  const ap = hh < 12 ? "AM" : "PM";
  const h12 = hh % 12 === 0 ? 12 : hh % 12;
  return `${h12}:${m} ${ap}`;
};
const dmy = (iso) => {
  const [, m, d] = String(iso || "").split("-");
  return d ? `${d}/${m}` : iso;
};

// Every stored board, newest first, each one rendered by the same <Chain> the
// live view uses - so a half hour from last week reads exactly like now.
function HistoryBoards({ h, loading, cfg, inr, mcxDec }) {
  if (loading && !h) return <div className="empty-state">Loading history…</div>;
  const snaps = h?.snapshots || [];
  if (!snaps.length) {
    return (
      <div className="nmg-empty">
        <b>Nothing stored yet</b>
        <span>
          A board is saved every half hour from 9:00 AM to 11:30 PM, and only
          while both exchanges are quoting two-way. Nothing before the first
          capture exists, and no exchange sells it back.
        </span>
      </div>
    );
  }
  return (
    <div className="cru-hist">
      {snaps.map((s) => {
        // MCX is already rupees; only the US side is converted, and only here.
        const m = unpack(s.board?.mcx, s.board?.cols_mcx || []);
        const u = unpack(s.board?.us, s.board?.cols_us || [],
                         inr ? (s.board?.usdinr || s.usdinr) : 1);
        return (
          <section className="cru-hist-board" key={`${s.snap_date}-${s.slot}`}>
            <div className="cru-hist-head">
              <b>{dmy(s.snap_date)}</b>
              <span className="oh-board-dot">•</span>
              <span className="oh-board-slot">{hhmm(s.slot)}</span>
              <em>
                MCX {s.mcx_atm_iv == null ? "—" : `${fmtNum(s.mcx_atm_iv, 2)}%`}
                {" · "}US {s.us_atm_iv == null ? "—" : `${fmtNum(s.us_atm_iv, 2)}%`}
              </em>
              {s.iv_diff != null && (
                <i className={s.iv_diff >= 0 ? "nmg-pos" : "nmg-neg"}>
                  {(s.iv_diff >= 0 ? "+" : "−") + fmtNum(Math.abs(s.iv_diff), 2)}%
                </i>
              )}
              <u>forward {num(s.mcx_forward, 1)} · US {num(s.us_future, 2)}</u>
            </div>
            <div className="cru-split">
              <Chain title={cfg.label.toUpperCase()} sub={`MCX · ${m.expiry || ""}`}
                data={m} priceDecimals={mcxDec ?? cfg.mcxDec} strikeDecimals={0} showOi />
              <Chain title={inr ? `${cfg.usTitle} in ₹` : cfg.usTitle}
                sub={`${u.symbol || ""} · ${u.expiry || ""}`}
                data={u} priceDecimals={inr ? (mcxDec ?? cfg.mcxDec) : cfg.usDec}
                strikeDecimals={inr ? 0 : cfg.usDec} />
            </div>
          </section>
        );
      })}
    </div>
  );
}

export default function CrudeOil({ currency = "usd" }) {
  const inr = currency === "inr";
  const [product, setProduct] = useState(() => {
    try {
      // Separate key per tab, or picking gas on one silently moves the other.
      const p = localStorage.getItem(`arbi_crude_product_${currency}`);
      return PRODUCTS.some((x) => x.key === p) ? p : "crude";
    } catch { return "crude"; }
  });
  // The month and the view both survive a refresh, per tab. The client landed
  // back on Live every time otherwise, which is the complaint that got the same
  // thing fixed on the NSE vs MCX screen.
  const [month, setMonth] = useState(() => {
    try { return localStorage.getItem(`arbi_crude_month_${currency}`) === "1" ? 1 : 0; }
    catch { return 0; }
  });
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(`arbi_crude_view_${currency}`) === "history" ? "history" : "live"; }
    catch { return "live"; }
  });
  const [d, setD] = useState(null);
  const [hist, setHist] = useState(null);
  const [loadingHist, setLoadingHist] = useState(false);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    try { localStorage.setItem(`arbi_crude_product_${currency}`, product); } catch {}
  }, [product, currency]);

  useEffect(() => {
    try {
      localStorage.setItem(`arbi_crude_month_${currency}`, String(month));
      localStorage.setItem(`arbi_crude_view_${currency}`, view);
    } catch {}
  }, [month, view, currency]);

  // History rows never change once written, so this fetches on a control change
  // and never polls. 3 days is 90 boards, which is a lot to scroll already.
  useEffect(() => {
    if (view !== "history") return undefined;
    let alive = true;
    setLoadingHist(true);
    api.crudeIvHistory({ commodity: product, month, days: 3 })
      .then((r) => { if (alive) setHist(r); })
      .catch((e) => { if (alive) setErr(e.message); })
      .finally(() => { if (alive) setLoadingHist(false); });
    return () => { alive = false; };
  }, [view, product, month]);

  // Nothing clears the board any more, commodity switch included. The API
  // answers in about 5 ms, so the replacement is there before the browser
  // repaints and blanking only ever bought a flash of empty page. The board
  // that is briefly still on screen belongs to the previous commodity, so it is
  // dimmed until the right one lands rather than passed off as current.
  const stale = !!d && d.commodity !== product;

  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.crudeIv(product, currency, month);
        if (alive) { setD(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
    // `month` belongs here. Leaving it out is why Aug and Sep showed the same
    // board: the state changed, the fetch did not.
  }, [product, currency, month]);

  const cfg = PRODUCTS.find((p) => p.key === product) || PRODUCTS[0];

  const switcher = (
    <div className="cru-switches">
      <div className="oh-group cru-switch" role="tablist" aria-label="Commodity">
        {PRODUCTS.map((p) => (
          <button key={p.key} type="button" role="tab" aria-selected={product === p.key}
            className={`oh-chip ${product === p.key ? "on" : ""}`}
            onClick={() => setProduct(p.key)}>{p.label}</button>
        ))}
      </div>
      {/* Named by the expiry actually loaded rather than "next" - both months
          land on the same date on MCX and NYMEX, so one label serves both. */}
      <div className="oh-group cru-switch" role="tablist" aria-label="Month">
        {[0, 1].map((k) => (
          <button key={k} type="button" role="tab" aria-selected={month === k}
            className={`oh-chip ${month === k ? "on" : ""}`}
            onClick={() => setMonth(k)}>{monthLabel(d, k)}</button>
        ))}
      </div>
      <div className="oh-group cru-switch" role="tablist" aria-label="View">
        {[["live", "Live"], ["history", "History"]].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={view === k}
            className={`oh-chip ${view === k ? "on" : ""}`}
            onClick={() => setView(k)}>{l}</button>
        ))}
      </div>
    </div>
  );

  if (err) return <div className="settings-banner danger">⚠ {err}</div>;
  if (!d) return (
    <div className="cru-page">
      <div className="cru-switch-solo">{switcher}</div>
      <div className="empty-state">Loading {cfg.label.toLowerCase()} option chains…</div>
    </div>
  );

  const mcx = d.mcx || {}, us = d.us || {};
  const fmtExp = (e) => {
    if (!e) return "";
    if (/^\d{8}$/.test(e)) return `${e.slice(6, 8)}-${e.slice(4, 6)}-${e.slice(0, 4)}`;
    const [y, m, day] = e.split("-");
    return day ? `${day}-${m}-${y}` : e;
  };
  // Headline comparison: ATM implied volatility on each exchange.
  const atmIv = (chain) => {
    const r = (chain.rows || []).find((x) => x.atm);
    const vals = [r?.ce?.iv, r?.pe?.iv].filter((v) => v != null && v !== 0);
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };
  const mIv = atmIv(mcx), uIv = atmIv(us);
  const gap = mIv != null && uIv != null ? mIv - uIv : null;

  return (
    <div className={`cru-page ${stale ? "cru-stale" : ""}`}>
      <div className="intl-head cru-head">
        <div>
          <h2>{cfg.label} — Option Comparison</h2>
          <div className="intl-sub">
            MCX vs US (NYMEX) · implied volatility and greeks on every strike
          </div>
        </div>
        {switcher}
        <span className={`intl-status ${us.connected ? (us.delayed ? "warn" : "on") : "off"}`}>
          {us.connected ? (us.delayed ? "◷ Delayed" : "● Live real-time") : "○ Disconnected"}
        </span>
      </div>

      <div className="cru-stats">
        <div className="intl-stat">
          <div className="intl-stat-label">MCX ATM IV<em>{fmtExp(mcx.expiry) || "—"}</em></div>
          <div className="intl-stat-value">{iv(mIv)}</div>
        </div>
        <div className="intl-stat">
          <div className="intl-stat-label">US ATM IV<em>{fmtExp(us.expiry) || "—"}</em></div>
          <div className="intl-stat-value">{iv(uIv)}</div>
        </div>
        <div className="intl-stat">
          <div className="intl-stat-label">Difference<em>MCX − US</em></div>
          <div className={`intl-stat-value ${gap == null ? "" : gap >= 0 ? "pos" : "neg"}`}>
            {gap == null ? "—" : (gap >= 0 ? "+" : "−") + fmtNum(Math.abs(gap), 2) + "%"}
          </div>
        </div>
        {/* The forward, not the future. They are different contracts and the
            distinction is the whole reason the IV on this screen used to be
            wrong: the printed future is the front month, the chain is the month
            after, and on crude they sit ~60 apart. The front month is still
            shown underneath, because it is what he trades - it is just not what
            prices this chain. */}
        <div className="intl-stat">
          <div className="intl-stat-label">
            MCX forward<em>{mcx.fwd_strikes ? `parity · ${mcx.fwd_strikes} strike${mcx.fwd_strikes === 1 ? "" : "s"}` : "₹"}</em>
          </div>
          <div className="intl-stat-value" title="What the option prices themselves imply, and what the IV beside them was solved against.">
            {num(mcx.forward ?? mcx.future_price, 0)}
            {mcx.forward != null && mcx.future_price != null
              && Math.abs(mcx.future_price - mcx.forward) > 5 && (
              <em className="cru-fwd-gap" title={"The front-month future is " + num(mcx.future_price, 0)
                  + ", which belongs to a different contract. Using it would shift every IV here by several points."}>
                front {num(mcx.future_price, 0)}
              </em>
            )}
          </div>
        </div>
        <div className="intl-stat">
          <div className="intl-stat-label">US future<em>$</em></div>
          <div className="intl-stat-value">{num(us.future_price, cfg.usDec)}</div>
        </div>
        <div className="intl-stat">
          <div className="intl-stat-label">USD / INR<em>{d.usdinr?.source || "live"}</em></div>
          <div className="intl-stat-value">{num(d.usdinr?.price, 3)}</div>
        </div>
      </div>

      {view === "history" ? (
        <HistoryBoards h={hist} loading={loadingHist} cfg={cfg} inr={inr} mcxDec={mcx.decimals} />
      ) : (
      <div className="cru-split">
        <Chain
          title={mcx.label || "MCX"}
          sub={`${mcx.symbol || ""} · exp ${fmtExp(mcx.expiry) || "—"} · ₹`}
          badge={mcx.error ? `Chain unavailable: ${mcx.error}` : "Loading chain…"}
          data={mcx} priceDecimals={mcx.decimals ?? cfg.mcxDec} strikeDecimals={0} showOi
        />
        <Chain
          title={inr ? `${cfg.usTitle} in ₹` : cfg.usTitle}
          sub={`${us.symbol || ""}${us.trading_class ? ` (${us.trading_class})` : ""}`
            + ` · exp ${fmtExp(us.expiry) || "—"} · `
            + (inr ? `₹ at ${num(us.inr_rate, 3)}` : "$")}
          data={us}
          /* rupee prices need the MCX decimals, not the dollar ones - two
             decimals on 415.29 is right, on 4.39 it was necessary */
          priceDecimals={inr ? (mcx.decimals ?? cfg.mcxDec) : cfg.usDec}
          strikeDecimals={inr ? 0 : cfg.usDec}
        />
      </div>
      )}

      <div className="cru-foot">
        MCX refreshes every ~5 s (exchange API limit is one call per 3 s); the US side is live.
        IV is shown as a percentage on both.
        {inr && (
          <>
            {" "}The US strikes, prices and greeks are converted at the USD/INR
            <b> future</b>, live, so both panels read in rupees. The implied
            volatility is the same number as on the dollar tab: multiplying the
            forward, the strike and the price by one rate cannot change it. Delta
            is unchanged too; vega and theta are in rupees and gamma per rupee.
          </>
        )}
      </div>
    </div>
  );
}
