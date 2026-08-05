import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import OptionsBoard from "./OptionsBoard.jsx";

// History for the Nifty/Sensex PE board — renders each stored 10:00/15:00/15:25 IST
// snapshot EXACTLY like the Live board (cards + full 3-week matrix), stacked
// newest-first. Filters: weekday + time + how many past days. Boards are
// fetched ON DEMAND only (control changes) — no polling, no load.
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

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata", weekday: "long", day: "2-digit", month: "short", year: "numeric",
  });
}

const SLOTS = [
  { key: "10:00", label: "10:00 AM" },
  { key: "15:00", label: "3:00 PM" },
  { key: "15:25", label: "3:25 PM" },
];

function slotLabel(slot) {
  return SLOTS.find((s) => s.key === slot)?.label || slot;
}

export default function OptionsHistory({ side }) {
  const [weekday, setWeekday] = useState(() => {
    try { const w = localStorage.getItem("arbi_opthist_wd"); return WEEKDAYS.some((x) => x.key === w) ? w : todayWeekday(); }
    catch { return todayWeekday(); }
  });
  const [slot, setSlot] = useState(() => {
    try {
      const s = localStorage.getItem("arbi_opthist_slot");
      return SLOTS.some((x) => x.key === s) ? s : "10:00";
    } catch { return "10:00"; }
  });
  const [weeks, setWeeks] = useState(7);
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
          {SLOTS.map((s) => (
            <button key={s.key} type="button" className={`oh-chip ${slot === s.key ? "on" : ""}`}
              onClick={() => setSlot(s.key)}>{s.label}</button>
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
          No snapshots yet for this filter. Boards are saved automatically at <b>10:00</b>, <b>3:00</b> and
          <b> 3:25</b> IST every trading day — history builds up from today onward.
        </div>
      )}

      {snaps.length > 0 && (
        <>
          {snaps.length < weeks && (
            <div className="oh-note oh-slim">{snaps.length} of last {weeks} {WEEKDAYS.find((w) => w.key === weekday)?.label}s found (holidays have no snapshot).</div>
          )}
          {snaps.map((s) => (
            <section key={s.snap_date + s.slot} className="oh-board">
              <div className="oh-board-head">
                <span className="oh-board-date">{fmtDate(s.snap_date)}</span>
                <span className="oh-board-dot">•</span>
                <span className="oh-board-slot">{slotLabel(s.slot)}</span>
              </div>
              <OptionsBoard
                side={side}
                live={false}
                data={{
                  ...s,
                  // Expected = Nifty day-change × 3.2 (same as the live board)
                  sensex_expected_change:
                    s.nifty_day_change != null ? s.nifty_day_change * 3.2 : null,
                }}
              />
            </section>
          ))}
        </>
      )}
    </div>
  );
}
