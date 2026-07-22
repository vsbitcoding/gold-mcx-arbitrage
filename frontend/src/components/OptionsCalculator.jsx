import React, { useEffect, useState } from "react";
import { fmtNum } from "../utils/format.js";

// Nifty/Sensex option-premium calculator — POPUP (client sketch, 22-Jul):
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

export default function OptionsCalculator({ open, onClose }) {
  const [cfg, setCfg] = useState(load);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

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
    <div className="confirm-overlay" onClick={onClose}>
      <div className="ocalc-card" onClick={(e) => e.stopPropagation()}>
        <div className="ocalc-head">
          <h3>⌸ Premium Calculator</h3>
          <button type="button" className="ocalc-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="ocalc-grid">
          <span className="ocalc-ghead">Option</span>
          <span className="ocalc-ghead ocalc-right">Price</span>
          <span className="ocalc-ghead" />
          <span className="ocalc-ghead ocalc-right">Qty</span>
          <span className="ocalc-ghead ocalc-right">Value</span>

          <span className="ocalc-name">Nifty <em>PUT</em></span>
          <input className="pv-input ocalc-price" type="number" step="0.05" placeholder="0.00"
            autoFocus value={cfg.np} onChange={(e) => setF("np", e.target.value)} />
          <span className="ocalc-x">×</span>
          <input className="pv-input ocalc-mult" type="number" step="1"
            value={cfg.nm} onChange={(e) => setF("nm", e.target.value)} />
          <span className="ocalc-val">{nVal == null ? "—" : fmtNum(nVal, 2)}</span>

          <span className="ocalc-name">Sensex <em>PUT</em></span>
          <input className="pv-input ocalc-price" type="number" step="0.05" placeholder="0.00"
            value={cfg.sp} onChange={(e) => setF("sp", e.target.value)} />
          <span className="ocalc-x">×</span>
          <input className="pv-input ocalc-mult" type="number" step="1"
            value={cfg.sm} onChange={(e) => setF("sm", e.target.value)} />
          <span className="ocalc-val">{sVal == null ? "—" : fmtNum(sVal, 2)}</span>
        </div>

        <div className="ocalc-answer">
          <span className="ocalc-answer-lbl">Premium <em>Nifty − Sensex</em></span>
          <span className={`ocalc-result ${premium == null ? "" : premium >= 0 ? "pos" : "neg"}`}>
            {premium == null ? "—" : (premium >= 0 ? "+" : "−") + fmtNum(Math.abs(premium), 2)}
          </span>
        </div>
      </div>
    </div>
  );
}
