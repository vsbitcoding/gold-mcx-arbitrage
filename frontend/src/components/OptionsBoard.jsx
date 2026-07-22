import React, { useMemo } from "react";
import { fmtNum } from "../utils/format.js";

// The full PE-spread board (spot/day-change/VIX cards + 3-week matrix).
// Shared by the Live view (polling data) and History view (stored snapshots
// rendered exactly like Live, one board per captured day).
export function fmtExpiry(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit", month: "short",
  });
}

export function fmtSigned(v, decimals = 0) {
  if (v == null) return "—";
  const s = v >= 0 ? "+" : "−";
  return s + fmtNum(Math.abs(v), decimals);
}

export function spreadCls(v) {
  if (v == null) return "neutral";
  return v >= 0 ? "pos" : "neg";
}

function itmCls(v) {
  if (v == null) return "neutral";
  if (Math.abs(v) < 25) return "neutral";
  return v >= 0 ? "itm" : "otm";
}

export default function OptionsBoard({ data, side, live = false }) {
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
  const dot = (val) => live && val != null ? <span className="live-dot" /> : null;

  return (
    <>
      <div className="opt-spot-bar">
        <div className="opt-spot-chip">
          <span className="opt-spot-label">{dot(data?.nifty_spot)}NIFTY spot</span>
          <span className="opt-spot-value">
            {data?.nifty_spot == null ? "—" : fmtNum(data.nifty_spot, 2)}
          </span>
          <span className="opt-spot-sub">ATM {data?.nifty_atm ?? "—"}</span>
        </div>
        {/* ONE box (per client): divergence + Nifty/Sensex day-change stacked + Expected */}
        <div
          className="opt-spot-chip opt-day-chip"
          title={"Day move vs previous close.\nExpected = Nifty change × 3.2;\ndivergence = actual Sensex change − expected.\n+ = Sensex stronger than ratio · − = weaker"}
        >
          <span className="opt-spot-label">{dot(data?.day_divergence)}DAY CHANGE</span>
          <div className="opt-day-flex">
            <div className="opt-day-seg">
              <em>Divergence</em>
              <b className={`opt-day-hero ${data?.day_divergence == null ? "" : data.day_divergence >= 0 ? "opt-div-pos" : "opt-div-neg"}`}>
                {data?.day_divergence == null ? "—" : fmtSigned(data.day_divergence, 1)}
              </b>
            </div>
            <div className="opt-nse-left">
              <span className="opt-nse-row">
                <em>Nifty</em>
                <b className={data?.nifty_day_change == null ? "" : data.nifty_day_change >= 0 ? "opt-div-pos" : "opt-div-neg"}>
                  {data?.nifty_day_change == null ? "—" : fmtSigned(data.nifty_day_change, 1)}
                </b>
              </span>
              <span className="opt-nse-row">
                <em>Sensex</em>
                <b className={data?.sensex_day_change == null ? "" : data.sensex_day_change >= 0 ? "opt-div-pos" : "opt-div-neg"}>
                  {data?.sensex_day_change == null ? "—" : fmtSigned(data.sensex_day_change, 1)}
                </b>
              </span>
            </div>
            <div className="opt-day-seg">
              <em>Expected</em>
              <b className={`opt-day-big ${data?.sensex_expected_change == null ? "" : data.sensex_expected_change >= 0 ? "opt-div-pos" : "opt-div-neg"}`}>
                {data?.sensex_expected_change == null ? "—" : fmtSigned(data.sensex_expected_change, 1)}
              </b>
            </div>
          </div>
        </div>
        <div className="opt-spot-chip">
          <span className="opt-spot-label">{dot(data?.sensex_spot)}SENSEX spot</span>
          <span className="opt-spot-value">
            {data?.sensex_spot == null ? "—" : fmtNum(data.sensex_spot, 2)}
          </span>
          <span className="opt-spot-sub">ATM {data?.sensex_atm ?? "—"}</span>
        </div>
        <div className="opt-spot-chip" title="India VIX — NSE volatility index">
          <span className="opt-spot-label">{dot(data?.india_vix)}INDIA VIX</span>
          <span className="opt-spot-value">
            {data?.india_vix == null ? "—" : fmtNum(data.india_vix, 2)}
          </span>
          <span className="opt-spot-sub">volatility</span>
        </div>
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
    </>
  );
}
