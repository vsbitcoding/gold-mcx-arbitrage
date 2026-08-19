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
                    <td className="cru-side"><span className={`cru-tag ${side.toLowerCase()}`}>{side}</span></td>
                    {i === 0 ? (
                      <td className="cru-strike" rowSpan={legs.length}>
                        {num(r.strike, strikeDecimals)}
                        {r.atm && <span className="atm-badge">ATM</span>}
                      </td>
                    ) : null}
                    <td>{num(leg?.bid, priceDecimals)}</td>
                    <td>{num(leg?.ask, priceDecimals)}</td>
                    <td className="cru-iv-col">{iv(leg?.iv)}</td>
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
export default function CrudeOil({ currency = "usd" }) {
  const inr = currency === "inr";
  const [product, setProduct] = useState(() => {
    try {
      // Separate key per tab, or picking gas on one silently moves the other.
      const p = localStorage.getItem(`arbi_crude_product_${currency}`);
      return PRODUCTS.some((x) => x.key === p) ? p : "crude";
    } catch { return "crude"; }
  });
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    try { localStorage.setItem(`arbi_crude_product_${currency}`, product); } catch {}
  }, [product, currency]);

  useEffect(() => {
    let alive = true;
    setD(null);
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.crudeIv(product, currency);
        if (alive) { setD(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
  }, [product, currency]);

  const cfg = PRODUCTS.find((p) => p.key === product) || PRODUCTS[0];

  const switcher = (
    <div className="oh-group cru-switch" role="tablist" aria-label="Commodity">
      {PRODUCTS.map((p) => (
        <button key={p.key} type="button" role="tab" aria-selected={product === p.key}
          className={`oh-chip ${product === p.key ? "on" : ""}`}
          onClick={() => setProduct(p.key)}>{p.label}</button>
      ))}
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
    <div className="cru-page">
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
