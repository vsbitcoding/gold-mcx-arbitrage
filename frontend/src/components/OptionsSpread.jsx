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

function fmtSpread(v) {
  if (v == null) return "—";
  const s = v >= 0 ? "+" : "−";
  return s + fmtNum(Math.abs(v), 0);
}

function spreadCls(v) {
  if (v == null) return "neutral";
  return v >= 0 ? "pos" : "neg";
}

export default function OptionsSpread() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await api.optionsSpread();
        if (alive) { setData(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // Build the combined matrix: rows = strikes (descending from ATM), columns = weeks.
  const matrix = useMemo(() => {
    if (!data?.weeks?.length) return null;
    // Use week 0's strikes as the canonical strike list (ATM-derived; same in all weeks)
    const baseRows = data.weeks[0].rows;
    return baseRows.map((baseRow, idx) => {
      const cells = data.weeks.map((wk) => {
        const r = wk.rows[idx];
        return r ? { spread: r.spread, niftyPE: r.nifty_pe, sensexPE: r.sensex_pe } : null;
      });
      return {
        index: idx,
        niftyStrike: baseRow.nifty_strike,
        sensexStrike: baseRow.sensex_strike,
        isAtm: idx === 0,
        cells,
      };
    });
  }, [data]);

  const weeks = data?.weeks || [];

  return (
    <div className="opt-page">
      <div className="opt-head">
        <h2>Nifty / Sensex — PE Options Spread</h2>
        <p className="opt-sub">
          Live ATM + 9 OTM puts per weekly expiry.{" "}
          <strong>Spread</strong> = (Nifty PE × 325) − (Sensex PE × 100).{" "}
          Sensex strike = <code>round(Sensex_spot − (Nifty_spot − Strike) × 3.2, 100)</code>.
          ATM follows live spot.
        </p>
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
          <table className="opt-matrix">
            <thead>
              <tr className="opt-matrix-head1">
                <th rowSpan={2} className="opt-strike-col">Strike <span className="opt-th-sub">(Nifty / Sensex)</span></th>
                {weeks.map((w) => (
                  <th key={w.week_index} className="opt-week-col">
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
                {weeks.map((w) => (
                  <th key={w.week_index} className="opt-week-col">Spread</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.map((row) => (
                <tr key={row.index} className={row.isAtm ? "atm-row" : ""}>
                  <td className="opt-strike-col">
                    <div className="opt-strike">
                      <span className="opt-strike-n">{row.niftyStrike ?? "—"}</span>
                      <span className="opt-strike-s">/ {row.sensexStrike ?? "—"}</span>
                    </div>
                    {row.isAtm && <span className="atm-badge">ATM</span>}
                  </td>
                  {row.cells.map((c, i) => (
                    <td
                      key={i}
                      className={`opt-cell ${c ? spreadCls(c.spread) : "neutral"}`}
                      title={
                        c && c.niftyPE != null && c.sensexPE != null
                          ? `Nifty PE: ${fmtNum(c.niftyPE, 2)}\nSensex PE: ${fmtNum(c.sensexPE, 2)}`
                          : "No live quote"
                      }
                    >
                      <span className="opt-spread-num">
                        {c ? fmtSpread(c.spread) : "—"}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
