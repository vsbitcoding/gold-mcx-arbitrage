import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

function fmtExpiry(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit", month: "short",
  });
}

function fmtSigned(v, decimals = 0) {
  if (v == null) return "—";
  const s = v >= 0 ? "+" : "−";
  return s + fmtNum(Math.abs(v), decimals);
}

function spreadCls(v) {
  if (v == null) return "neutral";
  return v >= 0 ? "pos" : "neg";
}

function itmCls(v) {
  if (v == null) return "neutral";
  if (Math.abs(v) < 25) return "neutral";
  return v >= 0 ? "itm" : "otm";
}

export default function OptionsSpread() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  // remember the chosen tab across refreshes
  const [side, setSide] = useState(() => {
    try {
      const s = localStorage.getItem("opt_side");
      return ["above", "squareoff", "below"].includes(s) ? s : "below";
    } catch { return "below"; }
  });
  useEffect(() => {
    try { localStorage.setItem("opt_side", side); } catch { /* ignore */ }
  }, [side]);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await api.optionsSpread(side);
        if (alive) { setData(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [side]);

  const matrix = useMemo(() => {
    if (!data?.weeks?.length) return null;
    const baseRows = data.weeks[0].rows;
    const niftySpot = data.nifty_spot;
    const sensexSpot = data.sensex_spot;
    return baseRows.map((baseRow, idx) => {
      const cells = data.weeks.map((wk) => {
        const r = wk.rows[idx];
        return r ? {
          spread: r.spread,
          // leg the backend used for THIS side (below/above: N bid·S ask; squareoff: N ask·S bid)
          niftyLeg: r.nifty_leg ?? r.nifty_bid ?? r.nifty_pe,
          sensexLeg: r.sensex_leg ?? r.sensex_ask ?? r.sensex_pe,
        } : null;
      });
      const niftyItm = (baseRow.nifty_strike != null && niftySpot != null)
        ? baseRow.nifty_strike - niftySpot : null;
      const sensexItm = (baseRow.sensex_strike != null && sensexSpot != null)
        ? baseRow.sensex_strike - sensexSpot : null;
      // Variation = Sensex ITM − (Nifty ITM × 3.2)
      // Quantifies the rounding gap between perfect 3.2× scaling and the
      // actual Sensex strike (which is round-to-100).
      const variation = (niftyItm != null && sensexItm != null)
        ? sensexItm - (niftyItm * 3.2) : null;
      return {
        index: idx,
        niftyStrike: baseRow.nifty_strike,
        sensexStrike: baseRow.sensex_strike,
        isAtm: idx === 0,
        niftyItm,
        sensexItm,
        variation,
        cells,
      };
    });
  }, [data]);

  const weeks = data?.weeks || [];
  // column labels flip for the square-off (exit) side
  const legNLabel = side === "squareoff" ? "N ask" : "N bid";
  const legSLabel = side === "squareoff" ? "S bid" : "S ask";

  return (
    <div className="opt-page">
      <div className="opt-head">
        <h2>Nifty / Sensex — PE Options Spread</h2>
        <div className="opt-side-toggle" role="tablist">
          <button className={side === "below" ? "active" : ""} onClick={() => setSide("below")}>
            ▼ Below ATM <span className="opt-side-sub">10</span>
          </button>
          <button className={side === "above" ? "active" : ""} onClick={() => setSide("above")}>
            ▲ Above ATM <span className="opt-side-sub">15</span>
          </button>
          <button className={side === "squareoff" ? "active" : ""} onClick={() => setSide("squareoff")}>
            ⤢ Square off ITM <span className="opt-side-sub">15</span>
          </button>
        </div>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      <div className="opt-spot-bar">
        <div className="opt-spot-chip">
          <span className="opt-spot-label">
            {data?.nifty_spot != null && <span className="live-dot" />}NIFTY spot
          </span>
          <span className="opt-spot-value">
            {data?.nifty_spot == null ? "—" : fmtNum(data.nifty_spot, 2)}
          </span>
          <span className="opt-spot-sub">ATM {data?.nifty_atm ?? "—"}</span>
        </div>
        <div className="opt-spot-chip">
          <span className="opt-spot-label">
            {data?.sensex_spot != null && <span className="live-dot" />}SENSEX spot
          </span>
          <span className="opt-spot-value">
            {data?.sensex_spot == null ? "—" : fmtNum(data.sensex_spot, 2)}
          </span>
          <span className="opt-spot-sub">ATM {data?.sensex_atm ?? "—"}</span>
        </div>
        {data?.status?.subscribed_options != null && (
          <div className="opt-spot-chip" title="Total option contracts under live subscription">
            <span className="opt-spot-label">SUBSCRIBED</span>
            <span className="opt-spot-value">{data.status.subscribed_options}</span>
            <span className="opt-spot-sub">PE contracts</span>
          </div>
        )}
      </div>

      {!matrix ? (
        <div className="empty-state">Loading options data…</div>
      ) : (
        <div className="opt-matrix-wrap">
          <table className="opt-matrix opt-matrix-pro">
            <thead>
              <tr className="opt-matrix-head1">
                <th rowSpan={2} className="opt-strike-col">
                  Strike <span className="opt-th-sub">Nifty / Sensex</span>
                </th>
                <th rowSpan={2} className="opt-itm-col">
                  ITM <span className="opt-th-sub">N / S (strike − spot)</span>
                </th>
                <th rowSpan={2} className="opt-var-col">
                  Variation <span className="opt-th-sub">S − N×3.2</span>
                </th>
                {weeks.map((w) => (
                  <th key={w.week_index} colSpan={3} className={`opt-week-group opt-wk-${w.week_index + 1}`}>
                    <div className="opt-week-num">Week {w.week_index + 1}</div>
                    <div className="opt-week-dates">
                      <span>N {fmtExpiry(w.nifty_expiry)}</span>
                      <span className="opt-week-sep">·</span>
                      <span>S {fmtExpiry(w.sensex_expiry)}</span>
                    </div>
                  </th>
                ))}
              </tr>
              <tr className="opt-matrix-head2">
                {weeks.map((w) => {
                  const wk = `opt-wk-${w.week_index + 1}`;
                  return (
                    <React.Fragment key={w.week_index}>
                      <th className={`opt-subcol opt-subcol-ask ${wk}`}>{legNLabel}</th>
                      <th className={`opt-subcol opt-subcol-bid ${wk}`}>{legSLabel}</th>
                      <th className={`opt-subcol opt-subcol-spread ${wk}`}>Spread</th>
                    </React.Fragment>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {matrix.map((row) => (
                <tr key={row.index} className={row.isAtm ? "atm-row" : ""}>
                  <td className="opt-strike-col">
                    <div className="opt-strike-inline">
                      <span className="opt-strike-n">{row.niftyStrike ?? "—"}</span>
                      <span className="opt-strike-slash">/</span>
                      <span className="opt-strike-s">{row.sensexStrike ?? "—"}</span>
                    </div>
                    {row.isAtm && <span className="atm-badge">ATM</span>}
                  </td>
                  <td className="opt-itm-col">
                    <div className="opt-itm-pair">
                      <span className={`opt-itm-num opt-itm-${itmCls(row.niftyItm)}`}>
                        {fmtSigned(row.niftyItm, 2)}
                      </span>
                      <span className="opt-itm-slash">/</span>
                      <span className={`opt-itm-num opt-itm-${itmCls(row.sensexItm)}`}>
                        {fmtSigned(row.sensexItm, 2)}
                      </span>
                    </div>
                  </td>
                  <td className="opt-var-col">
                    <span className={`opt-var-num opt-itm-${itmCls(row.variation)}`}>
                      {fmtSigned(row.variation, 2)}
                    </span>
                  </td>
                  {row.cells.map((c, i) => {
                    const wk = `opt-wk-${i + 1}`;
                    return (
                      <React.Fragment key={i}>
                        <td className={`opt-subcol opt-subcol-ask ${wk}`}>
                          <span className="opt-leg-num">
                            {c && c.niftyLeg != null ? fmtNum(c.niftyLeg, 2) : "—"}
                          </span>
                        </td>
                        <td className={`opt-subcol opt-subcol-bid ${wk}`}>
                          <span className="opt-leg-num">
                            {c && c.sensexLeg != null ? fmtNum(c.sensexLeg, 2) : "—"}
                          </span>
                        </td>
                        <td className={`opt-subcol opt-subcol-spread opt-cell ${wk} ${c ? spreadCls(c.spread) : "neutral"}`}>
                          <span className="opt-spread-num">
                            {c ? fmtSigned(c.spread, 0) : "—"}
                          </span>
                        </td>
                      </React.Fragment>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
