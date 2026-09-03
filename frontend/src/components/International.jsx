import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// "COMEX + NYMEX" screen (the client's name for it, 03-Sep): the FIVE IBKR
// items he subscribes to, numbered as he listed them. The crude option chain,
// ATM strike and straddle that used to sit below were removed on his note.
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

  const mid = (o) => (o?.bid != null && o?.ask != null ? (o.bid + o.ask) / 2 : (o?.bid ?? o?.ask ?? null));
  const gcMid = mid(gf), siMid = mid(sf);
  const xauMid = mid(xs), xagMid = mid(ys);

  // Derived — IBKR data only, nothing from any other feed.
  const goldBasis = gcMid != null && xauMid != null ? gcMid - xauMid : null;
  const silverBasis = siMid != null && xagMid != null ? siMid - xagMid : null;
  const spotRatio = xauMid != null && xagMid ? xauMid / xagMid : null;
  const futRatio = gcMid != null && siMid ? gcMid / siMid : null;

  return (
    <div className="intl-page">
      <div className="intl-head">
        <div>
          <h2>COMEX + NYMEX</h2>
          <div className="intl-sub">5 live items · Interactive Brokers</div>
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

      {/* Everything below is derived from the five feeds above — nothing else. */}
      <div className="intl-stats">
        <Stat label="Gold basis" hint="future − spot" value={goldBasis} />
        <Stat label="Silver basis" hint="future − spot" value={silverBasis} decimals={3} />
        <Stat label="Gold / Silver" hint="spot ratio" value={spotRatio} plain />
        <Stat label="Gold / Silver" hint="future ratio" value={futRatio} plain />
      </div>

    </div>
  );
}
