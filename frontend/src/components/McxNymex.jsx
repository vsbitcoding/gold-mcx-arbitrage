import React, { useEffect, useState } from "react";
import CrudeOil from "./CrudeOil.jsx";

// One "MCX vs NYMEX" tab (the client's menu note, 03-Sep-2026) holding the
// two former tabs as a switch:
//   INR vs Dollar - MCX in rupees against NYMEX in dollars (was "Crude / Gas")
//   INR vs INR    - NYMEX restated in rupees at the USD/INR future
//                   (was "Crude / Gas INR")
// Each side keeps its own crude / natural gas choice, month and view, exactly
// as before - CrudeOil already keys its memory by currency.
const MODES = [
  { key: "usd", label: "INR vs Dollar" },
  { key: "inr", label: "INR vs INR" },
];

export default function McxNymex() {
  const [mode, setMode] = useState(() => {
    try { return localStorage.getItem("arbi_mcxnymex_mode") === "inr" ? "inr" : "usd"; }
    catch { return "usd"; }
  });
  useEffect(() => { try { localStorage.setItem("arbi_mcxnymex_mode", mode); } catch {} }, [mode]);

  return (
    <div className="mn-wrap">
      <div className="mn-switch" role="tablist" aria-label="Currency basis">
        {MODES.map((m) => (
          <button key={m.key} type="button" role="tab" aria-selected={mode === m.key}
            className={`oh-chip ${mode === m.key ? "on" : ""}`}
            onClick={() => setMode(m.key)}>{m.label}</button>
        ))}
        <span className="mn-hint">
          {mode === "usd" ? "MCX in rupees, NYMEX in dollars" : "both sides in rupees at the live USD/INR future"}
        </span>
      </div>
      {/* keyed so the switch remounts the screen with its own remembered state */}
      <CrudeOil key={mode} currency={mode} />
    </div>
  );
}
