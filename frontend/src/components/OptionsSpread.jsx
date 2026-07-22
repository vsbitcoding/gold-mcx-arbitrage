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
    try {
      const v = localStorage.getItem("opt_view");
      return ["history", "calculator"].includes(v) ? v : "live";
    } catch { return "live"; }
  });
  useEffect(() => {
    try { localStorage.setItem("opt_view", view); } catch { /* ignore */ }
  }, [view]);

  useEffect(() => {
    if (view !== "live") return; // History view: static data, no polling
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
  }, [side, view]);

  return (
    <div className="opt-page">
      <div className="opt-head">
        <h2>Nifty / Sensex — PE Options Spread</h2>
        <div className="opt-head-toggles">
          <div className="opt-side-toggle opt-view-toggle" role="tablist" aria-label="View">
            <button className={view === "live" ? "active" : ""} onClick={() => setView("live")}>● Live</button>
            <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}>◷ History</button>
            <button className={view === "calculator" ? "active" : ""} onClick={() => setView("calculator")}>⌸ Calculator</button>
          </div>
          {view !== "calculator" && (
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
          )}
        </div>
      </div>

      {view === "history" ? (
        <OptionsHistory side={side} />
      ) : view === "calculator" ? (
        <OptionsCalculator />
      ) : (
        <>
          {err && <div className="settings-banner danger">⚠ {err}</div>}
          <OptionsBoard data={data} side={side} live />
        </>
      )}
    </div>
  );
}
