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

// Compact stat tile — label on top, value under it, so nothing is stretched
// across half the screen the way a label→value row is on a wide monitor.
function Stat({ label, hint, value, decimals = 2, plain }) {
  return (
    <div className="intl-stat">
      <div className="intl-stat-label">{label}<em>{hint}</em></div>
      <div className={`intl-stat-value ${plain ? "" : value == null ? "" : value >= 0 ? "pos" : "neg"}`}>
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
        {/* A competing IBKR login blanks every price while the socket stays up,
            so "Live real-time" over six empty cards is the one thing this pill
            must never say (13-Aug: two hours of it). */}
        <span className={`intl-status ${ib.competing_session ? "warn" : ib.connected ? (ib.delayed ? "warn" : "on") : "off"}`}
          title={ib.competing_session
            ? "IBKR gives market data to one session at a time. Log out of the IBKR website and mobile app; prices come back within about three minutes."
            : ""}>
          {ib.competing_session ? "◷ Blocked — logged in elsewhere"
            : ib.connected ? (ib.delayed ? "◷ Delayed data" : "● Live real-time") : "○ Disconnected"}
        </span>
      </div>

      {ib.competing_session && (
        <div className="settings-banner warn intl-competing">
          Prices are paused because this IBKR account is logged in somewhere else —
          IBKR serves market data to one session at a time. Log out of the IBKR
          website and mobile app; the feed re-subscribes on its own within about
          three minutes.
        </div>
      )}

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

      {/* Everything below is derived from the six feeds above — nothing else. */}
      <div className="intl-stats">
        <Stat label="Gold basis" hint="future − spot" value={goldBasis} />
        <Stat label="Silver basis" hint="future − spot" value={silverBasis} decimals={3} />
        <Stat label="Gold / Silver" hint="spot ratio" value={spotRatio} plain />
        <Stat label="Gold / Silver" hint="future ratio" value={futRatio} plain />
        <Stat label="Crude ATM" hint="nearest strike" value={atmStrike} plain />
        <Stat label="ATM straddle" hint="call + put" value={straddle} plain />
      </div>

      <div className="intl-section-title">
        <span className="intl-num">6</span> CRUDE OPTIONS
        <em>
          NYMEX{expiry ? ` · expiry ${expiry}` : ""}
          {clMid != null ? ` · underlying CL ${num(clMid)}` : ""}
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
                <th colSpan={3} className="intl-call">CALL <em>buy right</em></th>
                <th className="intl-strike-col">
                  STRIKE
                  {clMid != null && <em>CL {num(clMid)}</em>}
                </th>
                <th colSpan={3} className="intl-put">PUT <em>sell right</em></th>
              </tr>
              <tr className="intl-chain-sub">
                <th className="intl-call">Bid</th>
                <th className="intl-call">Ask</th>
                <th className="intl-call">Mid</th>
                <th className="intl-strike-col" />
                <th className="intl-put">Mid</th>
                <th className="intl-put">Bid</th>
                <th className="intl-put">Ask</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const atm = r.strike === atmStrike;
                const cItm = clMid != null && r.strike < clMid;   // call in-the-money
                const pItm = clMid != null && r.strike > clMid;   // put in-the-money
                const cM = mid(r.call), pM = mid(r.put);
                return (
                  <tr key={r.strike} className={atm ? "atm-row" : ""}>
                    <td className={`intl-call ${cItm ? "itm" : ""}`}>{num(r.call?.bid)}</td>
                    <td className={`intl-call ${cItm ? "itm" : ""}`}>{num(r.call?.ask)}</td>
                    <td className={`intl-call strong ${cItm ? "itm" : ""}`}>{num(cM)}</td>
                    <td className="intl-strike-col">
                      <span className="intl-strike">
                        <span className="intl-strike-n">{num(r.strike)}</span>
                        {atm && <span className="atm-badge">ATM</span>}
                      </span>
                    </td>
                    <td className={`intl-put strong ${pItm ? "itm" : ""}`}>{num(pM)}</td>
                    <td className={`intl-put ${pItm ? "itm" : ""}`}>{num(r.put?.bid)}</td>
                    <td className={`intl-put ${pItm ? "itm" : ""}`}>{num(r.put?.ask)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="intl-chain-legend">
            <span><i className="sw call" /> Call side</span>
            <span><i className="sw put" /> Put side</span>
            <span><i className="sw itm" /> Shaded = in the money</span>
            <span><i className="sw atm" /> ATM = strike nearest the crude price</span>
          </div>
        </div>
      )}
    </div>
  );
}
