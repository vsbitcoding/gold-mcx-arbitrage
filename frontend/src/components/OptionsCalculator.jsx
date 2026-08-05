import React, { useEffect, useState } from "react";
import { fmtNum } from "../utils/format.js";

// Nifty/Sensex option-premium calculator — POPUP (client sketch, 22-Jul):
//   Nifty option price  (manual PUT price) × 325
//   Sensex option price (manual PUT price) × 100
//   Premium = Nifty value − Sensex value
// Quantities are contract lot sizes, so they are shown as fixed labels rather
// than inputs. Prices are deliberately NOT remembered - the client wants to
// type a fresh pair every time he opens it, never yesterday's numbers.
const NIFTY_QTY = 325;
const SENSEX_QTY = 100;

const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

export default function OptionsCalculator({ open, onClose }) {
  const [np, setNp] = useState("");
  const [sp, setSp] = useState("");

  // Blank both prices on every open AND every close, so the popup can never
  // show a stale number.
  useEffect(() => {
    setNp("");
    setSp("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const n = num(np), s = num(sp);
  const nVal = n != null ? n * NIFTY_QTY : null;
  const sVal = s != null ? s * SENSEX_QTY : null;
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
            autoFocus value={np} onChange={(e) => setNp(e.target.value)} />
          <span className="ocalc-x">×</span>
          <span className="ocalc-qty">{NIFTY_QTY}</span>
          <span className="ocalc-val">{nVal == null ? "—" : fmtNum(nVal, 2)}</span>

          <span className="ocalc-name">Sensex <em>PUT</em></span>
          <input className="pv-input ocalc-price" type="number" step="0.05" placeholder="0.00"
            value={sp} onChange={(e) => setSp(e.target.value)} />
          <span className="ocalc-x">×</span>
          <span className="ocalc-qty">{SENSEX_QTY}</span>
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
