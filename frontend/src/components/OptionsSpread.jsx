import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

function fmtExpiry(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit", month: "short", year: "2-digit",
  });
}

function WeekCard({ week }) {
  return (
    <div className="opt-week-card">
      <div className="opt-week-head">
        <div className="opt-week-title">Week {week.week_index + 1}</div>
        <div className="opt-week-expiries">
          <span>Nifty: <strong>{fmtExpiry(week.nifty_expiry)}</strong></span>
          <span>Sensex: <strong>{fmtExpiry(week.sensex_expiry)}</strong></span>
        </div>
      </div>
      <table className="info-table opt-table">
        <thead>
          <tr>
            <th>Strike</th>
            <th className="col-pe">Nifty PE</th>
            <th className="col-pe">Sensex PE</th>
            <th>Spread</th>
          </tr>
        </thead>
        <tbody>
          {week.rows.map((r, i) => (
            <tr key={i} className={i === 0 ? "atm-row" : ""}>
              <td>
                <div className="opt-strike">
                  <span className="opt-strike-n">{r.nifty_strike ?? "—"}</span>
                  <span className="opt-strike-s">/ {r.sensex_strike ?? "—"}</span>
                  {i === 0 && <span className="atm-badge">ATM</span>}
                </div>
              </td>
              <td className="num col-pe">{r.nifty_pe == null ? "—" : fmtNum(r.nifty_pe, 2)}</td>
              <td className="num col-pe">{r.sensex_pe == null ? "—" : fmtNum(r.sensex_pe, 2)}</td>
              <td className={`opt-spread ${r.spread == null ? "" : r.spread >= 0 ? "pnl-positive" : "pnl-negative"}`}>
                {r.spread == null ? "—" : (r.spread >= 0 ? "+" : "") + fmtNum(r.spread, 2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
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

  return (
    <div className="opt-page">
      <div className="opt-head">
        <h2>Nifty / Sensex — PE Options Spread</h2>
        <p className="opt-sub">
          ATM + 9 OTM puts per expiry. <strong>Spread</strong> = (Nifty PE × 325) − (Sensex PE × 100).
          Strike pairing: <code>Sensex = Nifty × 3.2 → round 100</code>. ATM follows live spot.
        </p>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      <div className="opt-spot-bar">
        <div className="opt-spot-chip">
          <span className="opt-spot-label">
            {data?.nifty_spot != null && <span className="live-dot" />}
            NIFTY spot
          </span>
          <span className="opt-spot-value">{data?.nifty_spot == null ? "—" : fmtNum(data.nifty_spot, 2)}</span>
          <span className="opt-spot-sub">ATM {data?.nifty_atm ?? "—"}</span>
        </div>
        <div className="opt-spot-chip">
          <span className="opt-spot-label">
            {data?.sensex_spot != null && <span className="live-dot" />}
            SENSEX spot
          </span>
          <span className="opt-spot-value">{data?.sensex_spot == null ? "—" : fmtNum(data.sensex_spot, 2)}</span>
          <span className="opt-spot-sub">ATM {data?.sensex_atm ?? "—"}</span>
        </div>
        {data?.status?.subscribed_options != null && (
          <div className="opt-spot-chip" title="Total option contracts under live subscription">
            <span className="opt-spot-label">Subscribed</span>
            <span className="opt-spot-value">{data.status.subscribed_options}</span>
            <span className="opt-spot-sub">PE contracts</span>
          </div>
        )}
      </div>

      <div className="opt-grid">
        {(data?.weeks || []).map((w) => (
          <WeekCard key={w.week_index} week={w} />
        ))}
        {(data?.weeks || []).length === 0 && (
          <div className="empty-state">Loading options data…</div>
        )}
      </div>
    </div>
  );
}
