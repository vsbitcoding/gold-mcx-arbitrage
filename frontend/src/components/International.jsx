import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// International market screen — the SIX items the client subscribes to on IBKR
// (COMEX L1 + NYMEX L1), nothing else. Numbered 1-6 exactly as he listed them
// so he can tick each one off against his own terminal.
// Polls one tiny in-memory endpoint every 2s and pauses when the tab is hidden.
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) =>
  v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d);

function Card({ n, title, sub, unit, bid, ask, decimals = 2, accent }) {
  const mid = bid != null && ask != null ? (bid + ask) / 2 : (bid ?? ask);
  const spread = bid != null && ask != null ? ask - bid : null;
  return (
    <div className={`intl-card ${accent || ""} ${mid == null ? "waiting" : ""}`}>
      <div className="intl-card-head">
        <span className="intl-num">{n}</span>
        <span className="intl-card-title">{title}</span>
      </div>
      <div className="intl-card-price">
        {num(mid, decimals)}
        {unit && <i>{unit}</i>}
      </div>
      <div className="intl-card-ba">
        <span className="bidcell">Bid <b>{num(bid, decimals)}</b></span>
        <span className="askcell">Ask <b>{num(ask, decimals)}</b></span>
      </div>
      <div className="intl-card-sub">
        <span>{sub}</span>
        {spread != null && <span className="intl-spread">spread {num(spread, decimals)}</span>}
      </div>
    </div>
  );
}

function CmpRow({ label, hint, value, decimals = 2, plain }) {
  return (
    <div className="intl-cmp-row">
      <div className="intl-cmp-label">
        {label}
        {hint && <em>{hint}</em>}
      </div>
      <div className={`intl-cmp-value ${plain ? "" : value == null ? "" : value >= 0 ? "pos" : "neg"}`}>
        {plain ? num(value, decimals) : signed(value, decimals)}
      </div>
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
  const gf = ib.gold_future || {}, sf = ib.silver_future || {}, cf = ib.crude_future || {};
  const xs = ib.gold_spot || {}, ys = ib.silver_spot || {};
  const opts = ib.crude_options || {};
  const rows = opts.rows || [];

  const mid = (o) => (o?.bid != null && o?.ask != null ? (o.bid + o.ask) / 2 : (o?.bid ?? o?.ask ?? null));
  const gcMid = mid(gf), siMid = mid(sf), clMid = mid(cf);
  const xauMid = mid(xs), xagMid = mid(ys);

  const atmStrike = clMid != null && rows.length
    ? rows.reduce((best, r) => (Math.abs(r.strike - clMid) < Math.abs(best - clMid) ? r.strike : best), rows[0].strike)
    : null;
  const atmRow = atmStrike != null ? rows.find((r) => r.strike === atmStrike) : null;

  // Derived — IBKR data only, nothing from any other feed.
  const goldBasis = gcMid != null && xauMid != null ? gcMid - xauMid : null;
  const silverBasis = siMid != null && xagMid != null ? siMid - xagMid : null;
  const spotRatio = xauMid != null && xagMid ? xauMid / xagMid : null;
  const futRatio = gcMid != null && siMid ? gcMid / siMid : null;
  const callMid = mid(atmRow?.call), putMid = mid(atmRow?.put);
  const straddle = callMid != null && putMid != null ? callMid + putMid : null;

  const expiry = opts.expiry
    ? `${opts.expiry.slice(6, 8)}-${opts.expiry.slice(4, 6)}-${opts.expiry.slice(0, 4)}`
    : null;

  return (
    <div className="intl-page">
      <div className="intl-head">
        <div>
          <h2>International Market</h2>
          <div className="intl-sub">6 live items · Interactive Brokers · COMEX + NYMEX</div>
        </div>
        <span className={`intl-status ${ib.connected ? (ib.delayed ? "warn" : "on") : "off"}`}>
          {ib.connected ? (ib.delayed ? "◷ Delayed data" : "● Live real-time") : "○ Disconnected"}
        </span>
      </div>

      <div className="intl-cards">
        <Card n="1" title="GOLD SPOT" accent="gold" sub="XAU/USD · $/oz"
          bid={xs.bid} ask={xs.ask} />
        <Card n="2" title="SILVER SPOT" accent="silver" sub="XAG/USD · $/oz"
          bid={ys.bid} ask={ys.ask} decimals={3} />
        <Card n="3" title="GOLD FUTURE" accent="gold"
          sub={gf.symbol ? `COMEX · ${gf.symbol}` : "COMEX"}
          bid={gf.bid} ask={gf.ask} />
        <Card n="4" title="SILVER FUTURE" accent="silver"
          sub={sf.symbol ? `COMEX · ${sf.symbol}` : "COMEX"}
          bid={sf.bid} ask={sf.ask} decimals={3} />
        <Card n="5" title="CRUDE FUTURE" accent="crude"
          sub={cf.symbol ? `NYMEX WTI · ${cf.symbol}` : "NYMEX WTI"}
          bid={cf.bid} ask={cf.ask} />
      </div>

      <div className="intl-split">
        <div className="intl-split-main">
          <div className="intl-section-title">
            <span className="intl-num">6</span> CRUDE OPTIONS
            <em>
              NYMEX{expiry ? ` · expiry ${expiry}` : ""}
              {rows.length ? ` · ${rows.length} strikes around the money` : ""}
            </em>
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
        </div>

        <div className="intl-split-side">
          <div className="intl-section-title">AT A GLANCE <em>from these 6 feeds</em></div>

          <div className="intl-cmp-box">
            <div className="intl-cmp-title">Future − Spot <span>premium / discount</span></div>
            <CmpRow label="Gold" hint="future 3 − spot 1" value={goldBasis} />
            <CmpRow label="Silver" hint="future 4 − spot 2" value={silverBasis} decimals={3} />
          </div>

          <div className="intl-cmp-box">
            <div className="intl-cmp-title">Gold / Silver <span>ratio</span></div>
            <CmpRow label="Spot" hint="XAU ÷ XAG" value={spotRatio} plain />
            <CmpRow label="Future" hint="GC ÷ SI" value={futRatio} plain />
          </div>

          <div className="intl-cmp-box">
            <div className="intl-cmp-title">
              Crude ATM <span>{atmStrike != null ? `strike ${num(atmStrike)}` : "loading"}</span>
            </div>
            <CmpRow label="Call" hint="mid" value={callMid} plain />
            <CmpRow label="Put" hint="mid" value={putMid} plain />
            <CmpRow label="Straddle" hint="call + put" value={straddle} plain />
          </div>
        </div>
      </div>
    </div>
  );
}
