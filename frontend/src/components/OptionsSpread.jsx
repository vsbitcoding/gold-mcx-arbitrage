import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import OptionsHistory from "./OptionsHistory.jsx";
import OptionsBoard from "./OptionsBoard.jsx";
import OptionsCalculator from "./OptionsCalculator.jsx";

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
  // Live board vs stored History (10am/3pm snapshots) — survives refresh.
  const [view, setView] = useState(() => {
    try { return localStorage.getItem("opt_view") === "history" ? "history" : "live"; }
    catch { return "live"; }
  });
  const [calcOpen, setCalcOpen] = useState(false);
  useEffect(() => {
    try { localStorage.setItem("opt_view", view); } catch { /* ignore */ }
  }, [view]);

  useEffect(() => {
    if (view !== "live") return undefined; // History view: static data, no polling
    // A side switch clears the board at once: the headings flip to the exit
    // side immediately, so the entry side's prices must not sit under them
    // while the new request is in flight (review 18-Sep, finding 16).
    setData(null); setErr(null);
    const controller = new AbortController();
    let alive = true, timer = null, inflight = false;
    async function load() {
      if (!alive || inflight || document.hidden) return;
      inflight = true;
      try {
        const r = await api.optionsSpread(side, controller.signal);
        if (alive) { setData({ ...r, side }); setErr(null); }
      } catch (e) { if (alive && !controller.signal.aborted) setErr(e.message); }
      finally { inflight = false; }
    }
    load();
    timer = setInterval(load, 2000);
    const onVis = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; clearInterval(timer); controller.abort(); document.removeEventListener("visibilitychange", onVis); };
  }, [side, view]);

  return (
    <div className="opt-page">
      <div className="opt-head">
        <h2>Nifty / Sensex — PE Options Spread</h2>
        <div className="opt-head-toggles">
          <div className="opt-side-toggle opt-view-toggle" role="tablist" aria-label="View">
            <button className={view === "live" ? "active" : ""} onClick={() => setView("live")}>● Live</button>
            <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}>◷ History</button>
          </div>
          <button type="button" className="ocalc-open-btn" onClick={() => setCalcOpen(true)}>
            ⌸ Calculator
          </button>
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
      </div>

      {view === "history" ? (
        <OptionsHistory side={side} />
      ) : (
        <>
          {err && <div className="settings-banner danger">⚠ {err}</div>}
          <OptionsBoard data={data && data.side === side ? data : null} side={side} live />
        </>
      )}

      <OptionsCalculator open={calcOpen} onClose={() => setCalcOpen(false)} />
    </div>
  );
}
