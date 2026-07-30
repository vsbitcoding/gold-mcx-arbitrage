import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// International market screen — COMEX/NYMEX (IBKR) + the free spot/MCX feeds,
// with the derived comparisons a bullion desk actually reads (future-vs-spot
// basis, and COMEX converted to ₹ against the live MCX quote).
// Polls one tiny in-memory endpoint every 2s and pauses when the tab is hidden.
const OZ_PER_KG = 32.1507466;          // troy ounces in 1 kg
const GRAMS_PER_OZ = 31.1034768;

const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) =>
  v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d);

function Card({ title, sub, bid, ask, decimals = 2, accent, note }) {
  const mid = bid != null && ask != null ? (bid + ask) / 2 : (bid ?? ask);
  return (
    <div className={`intl-card ${accent || ""}`}>
      <div className="intl-card-head">
        <span className="intl-card-title">{title}</span>
      </div>
      <div className="intl-card-price">{num(mid, decimals)}</div>
      <div className="intl-card-ba">
        <span>bid <b>{num(bid, decimals)}</b></span>
        <span>ask <b>{num(ask, decimals)}</b></span>
      </div>
      {note && <div className="intl-card-note">{note}</div>}
      {sub && <div className="intl-card-sub">{sub}</div>}
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
  const sp = d.spot || {};
  const gf = ib.gold_future || {}, sf = ib.silver_future || {}, cf = ib.crude_future || {};
  const bf = ib.brent_future || {};
  const xs = ib.gold_spot || {}, ys = ib.silver_spot || {};   // XAU/XAG spot — IBKR
  const opts = ib.crude_options || {};
  const rows = opts.rows || [];

  const mid = (o) => (o?.bid != null && o?.ask != null ? (o.bid + o.ask) / 2 : (o?.bid ?? o?.ask ?? null));
  const gcMid = mid(gf), siMid = mid(sf), clMid = mid(cf);
  const xauMid = mid(xs), xagMid = mid(ys);
  const inr = sp.usdinr?.price ?? null;
  const mcxGold = mid(d.mcx?.gold), mcxSilver = mid(d.mcx?.silver);

  const atmStrike = clMid != null && rows.length
    ? rows.reduce((best, r) => (Math.abs(r.strike - clMid) < Math.abs(best - clMid) ? r.strike : best), rows[0].strike)
    : null;
  const atmRow = atmStrike != null ? rows.find((r) => r.strike === atmStrike) : null;

  // Derived: future − spot basis, and COMEX converted to the MCX quoting basis.
  const goldBasis = gcMid != null && xauMid != null ? gcMid - xauMid : null;
  const silverBasis = siMid != null && xagMid != null ? siMid - xagMid : null;
  const crudeBasis = clMid != null && mid(bf) != null ? mid(bf) - clMid : null;
  // COMEX gold $/oz → ₹ per 10 g   |   COMEX silver $/oz → ₹ per kg
  const gcInr = gcMid != null && inr != null ? (gcMid * inr / GRAMS_PER_OZ) * 10 : null;
  const siInr = siMid != null && inr != null ? siMid * inr * OZ_PER_KG : null;
  const goldGap = mcxGold != null && gcInr != null ? mcxGold - gcInr : null;
  const silverGap = mcxSilver != null && siInr != null ? mcxSilver - siInr : null;

  return (
    <div className="intl-page">
      <div className="intl-head">
        <h2>International Market</h2>
        <span className={`intl-status ${ib.connected ? "on" : "off"}`}>
          {ib.connected ? (ib.delayed ? "◷ IBKR delayed" : "● IBKR live") : "○ IBKR disconnected"}
        </span>
      </div>

      {/* ── The 6 items the client buys from IBKR ────────────────────── */}
      <div className="intl-section-title">
        IBKR REAL-TIME <em>the 6 international items</em>
      </div>
      <div className="intl-cards">
        <Card title="1 · GOLD SPOT (XAU/USD)" accent="gold" sub="IBKR · CMDTY spot"
          bid={xs.bid} ask={xs.ask} />
        <Card title="2 · SILVER SPOT (XAG/USD)" accent="silver" sub="IBKR · CMDTY spot"
          bid={ys.bid} ask={ys.ask} decimals={3} />
        <Card title="3 · GOLD COMEX FUTURE" accent="gold"
          sub={gf.symbol ? `${gf.symbol} · ${gf.expiry || ""}` : "COMEX"}
          bid={gf.bid} ask={gf.ask} />
        <Card title="4 · SILVER COMEX FUTURE" accent="silver"
          sub={sf.symbol ? `${sf.symbol} · ${sf.expiry || ""}` : "COMEX"}
          bid={sf.bid} ask={sf.ask} decimals={3} />
        <Card title="5 · CRUDE FUTURE (WTI)" accent="crude"
          sub={cf.symbol ? `${cf.symbol} · ${cf.expiry || ""}` : "NYMEX"}
          bid={cf.bid} ask={cf.ask} />
        <Card title="6 · CRUDE OPTIONS" accent="crude"
          sub={`NYMEX · ${rows.length} strikes live${opts.expiry ? ` · ${opts.expiry}` : ""}`}
          bid={atmRow?.call?.bid} ask={atmRow?.call?.ask}
          note={atmStrike != null ? `ATM ${num(atmStrike)} call` : "loading…"} />
      </div>

      {/* ── Everything else we already stream, for comparison ────────── */}
      <div className="intl-section-title">OTHER LIVE FEEDS <em>for comparison</em></div>
      <div className="intl-cards">
        <Card title="BRENT FUTURE" accent="crude"
          sub={bf.symbol ? `IBKR · ${bf.symbol}` : "IBKR · NYMEX"}
          bid={bf.bid} ask={bf.ask} />
        <Card title="USD / INR" sub={sp.usdinr?.source}
          bid={sp.usdinr?.price} ask={sp.usdinr?.price} decimals={4} />
        <Card title="MCX GOLD (fut)" accent="gold" sub="Dhan · ₹/10g"
          bid={d.mcx?.gold?.bid} ask={d.mcx?.gold?.ask} decimals={0} />
        <Card title="MCX SILVER (fut)" accent="silver" sub="Dhan · ₹/kg"
          bid={d.mcx?.silver?.bid} ask={d.mcx?.silver?.ask} decimals={0} />
      </div>

      {/* ── Chain (left) + derived comparison (right) ────────────────── */}
      <div className="intl-split">
        <div className="intl-split-main">
          <div className="intl-section-title">
            CRUDE OPTION CHAIN <em>{opts.expiry ? `expiry ${opts.expiry}` : ""}</em>
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
          <div className="intl-section-title">COMPARISON <em>live</em></div>

          <div className="intl-cmp-box">
            <div className="intl-cmp-title">Future − Spot <span>basis</span></div>
            <CmpRow label="Gold" hint="GC − XAU" value={goldBasis} />
            <CmpRow label="Silver" hint="SI − XAG" value={silverBasis} decimals={3} />
            <CmpRow label="Crude" hint="BZ − CL" value={crudeBasis} />
          </div>

          <div className="intl-cmp-box">
            <div className="intl-cmp-title">COMEX in ₹ <span>at {num(inr, 3)}</span></div>
            <CmpRow label="Gold" hint="₹ / 10 g" value={gcInr} decimals={0} plain />
            <CmpRow label="Silver" hint="₹ / kg" value={siInr} decimals={0} plain />
          </div>

          <div className="intl-cmp-box">
            <div className="intl-cmp-title">MCX − COMEX <span>premium</span></div>
            <CmpRow label="Gold" hint="₹ / 10 g" value={goldGap} decimals={0} />
            <CmpRow label="Silver" hint="₹ / kg" value={silverGap} decimals={0} />
          </div>
        </div>
      </div>
    </div>
  );
}
