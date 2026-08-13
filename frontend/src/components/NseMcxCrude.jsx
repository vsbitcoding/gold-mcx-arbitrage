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

function DiffCell({ diff }) {
  const r = diff?.rupees;
  return (
    <td className={`nm-diff ${r == null ? "" : r >= 0 ? "pos" : "neg"}`}>
      <span className="nm-diff-rs">{signed(r)}</span>
      <em>{pct(diff?.percent)}</em>
    </td>
  );
}

function Leg({ leg }) {
  if (!leg?.traded) return <td className="nm-dead" title="no bid and no ask - not trading">—</td>;
  return (
    <td className="nm-px">
      <span className="nm-mid">{num(leg.mid)}</span>
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
      <div className="intl-head cru-head">
        <div>
          <h2>Crude Oil — NSE vs MCX</h2>
        </div>
        <div />
        <span className={`intl-status ${live ? "on" : "off"}`}>
          {live ? "● Live" : "○ Feed issue"}
        </span>
      </div>

      {/* ── Futures: the clean comparison, same expiry both sides ───────── */}
      <div className="nm-fut">
        <div className="nm-fut-box">
          <div className="nm-fut-label">NSE FUTURE<em>{fmtDate(f.nse?.expiry)}</em></div>
          <div className="nm-fut-value">{num(f.nse?.mid)}</div>
          <div className="nm-fut-sub">{num(f.nse?.bid)} / {num(f.nse?.ask)}</div>
        </div>
        <div className="nm-fut-box">
          <div className="nm-fut-label">MCX FUTURE<em>{fmtDate(f.mcx?.expiry)}</em></div>
          <div className="nm-fut-value">{num(f.mcx?.mid)}</div>
          <div className="nm-fut-sub">{f.mcx?.symbol || ""}</div>
        </div>
        <div className="nm-fut-box nm-fut-diff">
          <div className="nm-fut-label">
            DIFFERENCE<em>{f.same_expiry ? "same expiry" : "different expiry"}</em>
          </div>
          <div className={`nm-fut-value ${f.diff?.rupees == null ? "" : f.diff.rupees >= 0 ? "pos" : "neg"}`}>
            {signed(f.diff?.rupees)}
          </div>
          <div className="nm-fut-sub">{pct(f.diff?.percent)}</div>
        </div>
        <div className="nm-fut-box">
          <div className="nm-fut-label">USD / INR<em>NSE currency, live</em></div>
          <div className="nm-fut-value">{num(d.usdinr?.mid, 3)}</div>
          <div className="nm-fut-sub">{num(d.usdinr?.bid, 3)} / {num(d.usdinr?.ask, 3)}</div>
        </div>
      </div>

      <div className="intl-section-title nm-chain-title">
        OPTION CHAIN
        <em>
          NSE {fmtDate(o.nse_expiry)} vs MCX {fmtDate(o.mcx_expiry)} · {rows.length} strikes
          {!o.same_expiry && (
            <b title="The MCX side carries more time value, so part of each premium difference is time, not a market gap.">
              expiries differ — part of each difference is time value
            </b>
          )}
        </em>
      </div>

      <div className="cru-table-wrap">
        <table className="cru-table nm-table">
          <thead>
            <tr>
              <th colSpan={3} className="intl-call">CALL</th>
              <th className="cru-strike">STRIKE</th>
              <th colSpan={3} className="intl-put">PUT</th>
            </tr>
            <tr className="intl-chain-sub">
              <th className="intl-call">NSE</th>
              <th className="intl-call">MCX</th>
              <th className="intl-call">Diff</th>
              <th className="cru-strike" />
              <th className="intl-put">Diff</th>
              <th className="intl-put">MCX</th>
              <th className="intl-put">NSE</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.strike} className={r.atm ? "cru-atm" : ""}>
                <Leg leg={r.ce?.nse} />
                <Leg leg={r.ce?.mcx} />
                <DiffCell diff={r.ce?.diff} />
                <td className="cru-strike">
                  {num(r.strike, 0)}
                  {r.atm && <span className="atm-badge">ATM</span>}
                </td>
                <DiffCell diff={r.pe?.diff} />
                <Leg leg={r.pe?.mcx} />
                <Leg leg={r.pe?.nse} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="cru-foot">
        Each cell shows the mid price with bid / ask beneath it. A dash means the contract has
        no bid and no ask — not trading, so no comparison is possible.
        NSE data via Angel One, MCX via Dhan.
      </div>
    </div>
  );
}
