import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Weekday-compare history for the Nifty/Sensex PE board.
// Boards are auto-captured at 10:00 & 15:00 IST (see options_history_service);
// this view fetches ON DEMAND only (control changes) — no polling, no load.
const WEEKDAYS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
];

function todayWeekday() {
  const d = new Date().getDay(); // 0=Sun..6=Sat
  return d >= 1 && d <= 5 ? WEEKDAYS[d - 1].key : "mon";
}

function fmtSigned(v, decimals = 0) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), decimals);
}
function spreadCls(v) {
  if (v == null) return "neutral";
  return v >= 0 ? "pos" : "neg";
}
function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short",
  });
}

export default function OptionsHistory({ side }) {
  const [weekday, setWeekday] = useState(() => {
    try { const w = localStorage.getItem("arbi_opthist_wd"); return WEEKDAYS.some((x) => x.key === w) ? w : todayWeekday(); }
    catch { return todayWeekday(); }
  });
  const [slot, setSlot] = useState(() => {
    try { const s = localStorage.getItem("arbi_opthist_slot"); return s === "15:00" ? "15:00" : "10:00"; }
    catch { return "10:00"; }
  });
  const [weeks, setWeeks] = useState(7);
  const [wk, setWk] = useState(0); // board week (expiry) 0..2
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { try { localStorage.setItem("arbi_opthist_wd", weekday); } catch {} }, [weekday]);
  useEffect(() => { try { localStorage.setItem("arbi_opthist_slot", slot); } catch {} }, [slot]);

  // Fetch on control change only — history is static once written.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.optionsHistory({ weekday, slot, side, weeks })
      .then((r) => { if (alive) { setData(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message || "Failed to load history"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [weekday, slot, side, weeks]);

  const snaps = data?.snapshots || [];

  // Row count = longest board among snapshots (they can differ if config changed).
  const rowCount = useMemo(
    () => Math.max(0, ...snaps.map((s) => s.weeks?.[wk]?.rows?.length || 0)),
    [snaps, wk]
  );

  // Generic row labels: position relative to that day's ATM (strikes differ per date).
  const rowLabel = (idx) => {
    if (idx === 0) return "ATM";
    const step = idx * 50;
    return side === "below" ? `ATM −${step}` : `ATM +${step}`;
  };

  return (
    <div className="oh-wrap">
      <div className="oh-controls">
        <div className="oh-group" role="tablist" aria-label="Weekday">
          {WEEKDAYS.map((w) => (
            <button key={w.key} type="button" role="tab" aria-selected={weekday === w.key}
              className={`oh-chip ${weekday === w.key ? "on" : ""}`} onClick={() => setWeekday(w.key)}>
              {w.label}
            </button>
          ))}
        </div>
        <div className="oh-group" role="tablist" aria-label="Time">
          <button type="button" className={`oh-chip ${slot === "10:00" ? "on" : ""}`} onClick={() => setSlot("10:00")}>10:00 AM</button>
          <button type="button" className={`oh-chip ${slot === "15:00" ? "on" : ""}`} onClick={() => setSlot("15:00")}>3:00 PM</button>
        </div>
        <div className="oh-group" role="tablist" aria-label="Expiry week">
          {[0, 1, 2].map((i) => (
            <button key={i} type="button" className={`oh-chip ${wk === i ? "on" : ""}`} onClick={() => setWk(i)}>Week {i + 1}</button>
          ))}
        </div>
        <select className="oh-weeks" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))} title="How many past days">
          <option value={4}>Last 4</option>
          <option value={7}>Last 7</option>
          <option value={12}>Last 12</option>
        </select>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {loading && !data && <div className="empty-state">Loading history…</div>}

      {!loading && snaps.length === 0 && !err && (
        <div className="oh-note">
          No snapshots yet for this filter. Boards are saved automatically at <b>10:00</b> and <b>3:00</b> IST
          every trading day — history builds up from today onward.
        </div>
      )}

      {snaps.length > 0 && (
        <>
          {snaps.length < weeks && (
            <div className="oh-note oh-slim">{snaps.length} of last {weeks} {WEEKDAYS.find((w) => w.key === weekday)?.label}s found (holidays have no snapshot).</div>
          )}
          <div className="oh-scroll" role="region" aria-label="History comparison" tabIndex={0}>
            <table className="oh-table">
              <thead>
                <tr>
                  <th className="oh-sticky">Strike</th>
                  {snaps.map((s) => (
                    <th key={s.snap_date + s.slot}>
                      <div className="oh-date">{fmtDate(s.snap_date)}</div>
                      <div className="oh-sub">
                        N {s.nifty_spot != null ? fmtNum(s.nifty_spot, 0) : "—"} · S {s.sensex_spot != null ? fmtNum(s.sensex_spot, 0) : "—"}
                        {s.india_vix != null && <> · VIX {fmtNum(s.india_vix, 1)}</>}
                        {s.day_divergence != null && (
                          <> · <span className={s.day_divergence >= 0 ? "oh-div-pos" : "oh-div-neg"} title="Sensex day-move vs Nifty×3.2">Δ {fmtSigned(s.day_divergence, 0)}</span></>
                        )}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: rowCount }, (_, idx) => (
                  <tr key={idx} className={idx === 0 ? "atm-row" : ""}>
                    <td className="oh-sticky oh-rowlbl">{rowLabel(idx)}</td>
                    {snaps.map((s) => {
                      const r = s.weeks?.[wk]?.rows?.[idx];
                      if (!r) return <td key={s.snap_date + s.slot} className="oh-cell neutral">—</td>;
                      const tip = `${s.snap_date} ${s.slot}\nNifty ${r.nifty_strike ?? "—"} / Sensex ${r.sensex_strike ?? "—"}\nN leg ${r.nifty_leg ?? "—"} · S leg ${r.sensex_leg ?? "—"}`;
                      return (
                        <td key={s.snap_date + s.slot} className={`oh-cell ${spreadCls(r.spread)}`} title={tip}>
                          <span className="oh-spread">{fmtSigned(r.spread, 0)}</span>
                          <span className="oh-strikes">{r.nifty_strike ?? "—"}/{r.sensex_strike ?? "—"}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
