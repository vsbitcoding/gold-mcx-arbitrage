import React, { useState } from "react";
import { fmtNum } from "../utils/format.js";

// Nifty/Sensex option-premium calculator (client sketch, 22-Jul):
//   Nifty option price  (manual PUT price) × 325
//   Sensex option price (manual PUT price) × 100
//   Premium = Nifty value − Sensex value
// Pure client-side; inputs + multipliers persist in localStorage.
const LS_KEY = "arbi_optcalc_v1";

function load() {
  try {
    const d = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    return { np: d.np ?? "", sp: d.sp ?? "", nm: d.nm ?? 325, sm: d.sm ?? 100 };
  } catch {
    return { np: "", sp: "", nm: 325, sm: 100 };
  }
}

const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

export default function OptionsCalculator() {
  const [cfg, setCfg] = useState(load);
  const setF = (k, v) => {
    setCfg((c) => {
      const next = { ...c, [k]: v };
      try { localStorage.setItem(LS_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  };

  const np = num(cfg.np), sp = num(cfg.sp);
  const nm = num(cfg.nm) ?? 325, sm = num(cfg.sm) ?? 100;
  const nVal = np != null ? np * nm : null;
  const sVal = sp != null ? sp * sm : null;
  const premium = nVal != null && sVal != null ? nVal - sVal : null;

  return (
    <div className="ocalc-wrap">
      <div className="ocalc-card">
        <div className="ocalc-row">
          <span className="ocalc-label">Nifty Option Price</span>
          <input className="pv-input ocalc-price" type="number" step="0.05" placeholder="—"
            value={cfg.np} onChange={(e) => setF("np", e.target.value)} />
          <span className="ocalc-x">×</span>
          <input className="pv-input ocalc-mult" type="number" step="1"
            value={cfg.nm} onChange={(e) => setF("nm", e.target.value)} />
          <span className="ocalc-eq">=</span>
          <span className="ocalc-val">{nVal == null ? "—" : fmtNum(nVal, 2)}</span>
        </div>
        <div className="ocalc-row">
          <span className="ocalc-label">Sensex Option Price</span>
          <input className="pv-input ocalc-price" type="number" step="0.05" placeholder="—"
            value={cfg.sp} onChange={(e) => setF("sp", e.target.value)} />
          <span className="ocalc-x">×</span>
          <input className="pv-input ocalc-mult" type="number" step="1"
            value={cfg.sm} onChange={(e) => setF("sm", e.target.value)} />
          <span className="ocalc-eq">=</span>
          <span className="ocalc-val">{sVal == null ? "—" : fmtNum(sVal, 2)}</span>
        </div>
        <div className="ocalc-row ocalc-answer">
          <span className="ocalc-label">Premium <em>Nifty − Sensex</em></span>
          <span className={`ocalc-result ${premium == null ? "" : premium >= 0 ? "pos" : "neg"}`}>
            {premium == null ? "—" : (premium >= 0 ? "+" : "−") + fmtNum(Math.abs(premium), 2)}
          </span>
        </div>
      </div>
    </div>
  );
}
