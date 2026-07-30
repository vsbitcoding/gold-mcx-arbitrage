import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// International market screen — COMEX/NYMEX (IBKR) on top, the free spot feeds
// below. Polls one tiny in-memory endpoint every 2s and pauses when the tab is
// hidden, so an open screen costs the server almost nothing.
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));

function ageTag(a) {
  if (a == null) return null;
  const cls = a < 15 ? "ok" : a < 120 ? "warn" : "bad";
  return <span className={`intl-age ${cls}`}>{a < 60 ? `${a}s` : `${Math.round(a / 60)}m`}</span>;
}

function Card({ title, sub, bid, ask, age, decimals = 2, accent }) {
  const mid = bid != null && ask != null ? (bid + ask) / 2 : (bid ?? ask);
  return (
    <div className={`intl-card ${accent || ""}`}>
      <div className="intl-card-head">
        <span className="intl-card-title">{title}</span>
        {ageTag(age)}
      </div>
      <div className="intl-card-price">{num(mid, decimals)}</div>
      <div className="intl-card-ba">
        <span>bid <b>{num(bid, decimals)}</b></span>
        <span>ask <b>{num(ask, decimals)}</b></span>
      </div>
      {sub && <div className="intl-card-sub">{sub}</div>}
    </div>
  );
}

export default function International() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;           // no polling while the tab is in the background
      try {
        const r = await api.international();
        if (alive) { setD(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 2000);
    return () => { alive = false; clearInterval(timer.current); };
  }, []);

  if (err) return <div className="settings-banner danger">⚠ {err}</div>;
  if (!d) return <div className="empty-state">Loading international data…</div>;

  const ib = d.ibkr || {};
  const sp = d.spot || {};
  const gf = ib.gold_future || {}, sf = ib.silver_future || {}, cf = ib.crude_future || {};
  const opts = ib.crude_options || {};
  const rows = opts.rows || [];
  const clMid = cf.bid != null && cf.ask != null ? (cf.bid + cf.ask) / 2 : null;
  const atmStrike = clMid != null && rows.length
    ? rows.reduce((best, r) => (Math.abs(r.strike - clMid) < Math.abs(best - clMid) ? r.strike : best), rows[0].strike)
    : null;

  return (
    <div className="intl-page">
      <div className="intl-head">
        <h2>International Market</h2>
        <span className={`intl-status ${ib.connected ? "on" : "off"}`}>
          {ib.connected ? (ib.delayed ? "◷ IBKR delayed" : "● IBKR live") : "○ IBKR disconnected"}
        </span>
      </div>

      {/* ── COMEX / NYMEX (paid subscription) ───────────────────────── */}
      <div className="intl-section-title">COMEX / NYMEX <em>real-time</em></div>
      <div className="intl-cards">
        <Card title="GOLD COMEX FUTURE" accent="gold"
          sub={gf.symbol ? `${gf.symbol} · exp ${gf.expiry || ""}` : null}
          bid={gf.bid} ask={gf.ask} age={gf.age} />
        <Card title="SILVER COMEX FUTURE" accent="silver"
          sub={sf.symbol ? `${sf.symbol} · exp ${sf.expiry || ""}` : null}
          bid={sf.bid} ask={sf.ask} age={sf.age} decimals={3} />
        <Card title="CRUDE FUTURE (NYMEX)" accent="crude"
          sub={cf.symbol ? `${cf.symbol} · exp ${cf.expiry || ""}` : null}
          bid={cf.bid} ask={cf.ask} age={cf.age} />
      </div>

      {/* ── Crude option chain ──────────────────────────────────────── */}
      <div className="intl-section-title">
        CRUDE OPTION CHAIN <em>{opts.expiry ? `expiry ${opts.expiry}` : ""}</em>
        {ageTag(opts.age)}
      </div>
      {rows.length === 0 ? (
        <div className="oh-note oh-slim">Option chain loading…</div>
      ) : (
        <div className="intl-chain-wrap">
          <table className="intl-chain">
            <thead>
              <tr>
                <th colSpan={2} className="intl-call">CALL</th>
                <th className="intl-strike-col">
                  STRIKE
                  {clMid != null && <em>CL {num(clMid)}</em>}
                </th>
                <th colSpan={2} className="intl-put">PUT</th>
              </tr>
              <tr className="intl-chain-sub">
                <th className="intl-call">Bid</th><th className="intl-call">Ask</th>
                <th className="intl-strike-col" />
                <th className="intl-put">Bid</th><th className="intl-put">Ask</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const atm = r.strike === atmStrike;
                return (
                  <tr key={r.strike} className={atm ? "atm-row" : ""}>
                    <td className="intl-call">{num(r.call?.bid)}</td>
                    <td className="intl-call">{num(r.call?.ask)}</td>
                    <td className="intl-strike-col">
                      {num(r.strike)}{atm && <span className="atm-badge">ATM</span>}
                    </td>
                    <td className="intl-put">{num(r.put?.bid)}</td>
                    <td className="intl-put">{num(r.put?.ask)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Free feeds ──────────────────────────────────────────────── */}
      <div className="intl-section-title">SPOT &amp; OTHER <em>free feeds</em></div>
      <div className="intl-cards">
        <Card title="GOLD SPOT (XAU/USD)" accent="gold"
          sub={sp.gold?.source} bid={sp.gold?.price} ask={sp.gold?.price} age={sp.gold?.age} />
        <Card title="SILVER SPOT (XAG/USD)" accent="silver"
          sub={sp.silver?.source} bid={sp.silver?.price} ask={sp.silver?.price}
          age={sp.silver?.age} decimals={3} />
        <Card title="CRUDE WTI SPOT" accent="crude"
          sub={sp.wti?.source} bid={sp.wti?.price} ask={sp.wti?.price} age={sp.wti?.age} />
        <Card title="BRENT SPOT" accent="crude"
          sub={sp.brent?.source} bid={sp.brent?.price} ask={sp.brent?.price} age={sp.brent?.age} />
        <Card title="USD / INR" sub={sp.usdinr?.source}
          bid={sp.usdinr?.price} ask={sp.usdinr?.price} age={sp.usdinr?.age} decimals={4} />
        <Card title="MCX GOLD (fut)" accent="gold" sub="Dhan"
          bid={d.mcx?.gold?.bid} ask={d.mcx?.gold?.ask} decimals={0} />
        <Card title="MCX SILVER (fut)" accent="silver" sub="Dhan"
          bid={d.mcx?.silver?.bid} ask={d.mcx?.silver?.ask} decimals={0} />
      </div>
    </div>
  );
}
