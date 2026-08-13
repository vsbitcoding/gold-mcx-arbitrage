import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Crude Oil — NSE vs MCX, future and option chain side by side, with the
// difference in rupees AND percent on every leg (client, 13-Aug).
//
// Two honesty rules baked into the display:
//   * Only bid/ask are compared. A dead contract still prints an old LTP, and
//     on NSE that can be months stale, so an untraded leg shows "no market"
//     rather than a number that invites a wrong conclusion.
//   * Both expiry dates are always on screen. The futures share one, so that
//     difference is clean; the options never do, so part of the premium gap is
//     time value and the header says so.
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

function quality(leg) {
  if (!leg || leg.bid == null || leg.ask == null) return { ok: false, wide: false };
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

export default function NseMcxCrude() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      if (document.hidden) return;
      try {
        const r = await api.nseMcxCrude();
        if (alive) { setD(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    timer.current = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer.current); };
  }, []);

  if (err) return <div className="settings-banner danger">⚠ {err}</div>;
  if (!d) return <div className="empty-state">Loading NSE vs MCX crude…</div>;

  const f = d.future || {};
  const o = d.options || {};
  const rows = o.rows || [];
  const live = d.nse?.ok && d.mcx?.ok;

  return (
    <div className="cru-page">
      <div className="nm-head">
        <h2>Crude Oil — NSE vs MCX</h2>
        <div className="nm-head-right">
          <div className="nm-chip">
            <span className="nm-chip-name">NSE FUTURE<em>{fmtDate(f.nse?.expiry)}</em></span>
            <b>{num(f.nse?.mid)}</b>
            <i>{num(f.nse?.bid)} / {num(f.nse?.ask)}</i>
          </div>
          <div className="nm-chip">
            <span className="nm-chip-name">MCX FUTURE<em>{fmtDate(f.mcx?.expiry)}</em></span>
            <b>{num(f.mcx?.mid)}</b>
            <i>{f.mcx?.symbol || ""}</i>
          </div>
        </div>
        <span className={`intl-status nm-head-status ${live ? "on" : "off"}`}>
          {live ? "● Live" : "○ Feed issue"}
        </span>
      </div>

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
                  {num(r.strike, 0)}
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

      <div className="cru-foot">
        Mid price with bid / ask beneath. A dash means there is no two-way quote, so no honest
        comparison exists — a one-sided price is not a market. A “?” marks a difference where one
        side is quoted unusually wide. NSE via Angel One, MCX via Dhan.
      </div>
    </div>
  );
}
