import React, { useEffect, useState } from "react";
import { fmtNum } from "../utils/format.js";

// Client "Making Charge" premium tab. Live from MCX bid rates (Dhan), computed
// per the client's formula. Factor + making charges are editable (saved locally).
//   Gold pairs : Gold Mini Bid × factor + (making charge × multiplier)
//   Silver     : Silver Bid + making charge   (no factor, no multiplier)
const LS_KEY = "arbi_making_v1";

const DEFAULTS = {
  factor: 0.00402, // gold factor (Gold Mini Bid × factor)
  charges: { petal: 325, guinea: 1000, ten: 1400, silvermicro: 3500 },
};

// base = price-table `short`; mult = making-charge multiplier; factored = uses the gold factor.
const PAIRS = [
  { key: "petal",       label: "Mini → Petal",   base: "mini",   baseLabel: "Gold Mini", mult: 10,   factored: true },
  { key: "guinea",      label: "Mini → Guinea",  base: "mini",   baseLabel: "Gold Mini", mult: 1.25, factored: true },
  { key: "ten",         label: "Mini → Ten",     base: "mini",   baseLabel: "Gold Mini", mult: 1,    factored: true },
  { key: "silvermicro", label: "Silver → Micro", base: "silver", baseLabel: "Silver",    mult: 1,    factored: false },
];

function load() {
  try { const r = localStorage.getItem(LS_KEY); return r ? JSON.parse(r) : null; } catch { return null; }
}
function save(c) { try { localStorage.setItem(LS_KEY, JSON.stringify(c)); } catch {} }

function nearContract(priceData, short) {
  const g = priceData?.groups?.find((x) => x.short === short);
  return g?.contracts?.[0] || null; // contracts are near-first
}

export default function MakingPrice({ priceData }) {
  const [cfg, setCfg] = useState(() => {
    const s = load() || {};
    return { factor: s.factor ?? DEFAULTS.factor, charges: { ...DEFAULTS.charges, ...(s.charges || {}) } };
  });
  useEffect(() => { save(cfg); }, [cfg]);

  const factor = Number(cfg.factor) || 0;
  const setCharge = (key, v) => setCfg((c) => ({ ...c, charges: { ...c.charges, [key]: v } }));

  return (
    <div className="mp-page">
      <div className="mp-head">
        <h2>Making Price</h2>
        <p className="mp-sub">
          Live making-charge premium from MCX bid rates. The gold <b>factor</b> and all
          <b> making charges</b> are editable — your changes auto-save in this browser.
        </p>
        <div className="mp-factor">
          <label htmlFor="mp-factor-in">Gold factor</label>
          <input
            id="mp-factor-in"
            type="number"
            step="0.00001"
            value={cfg.factor}
            onChange={(e) => setCfg((c) => ({ ...c, factor: e.target.value }))}
          />
          <span className="mp-factor-note">Gold Mini Bid × factor — used for Petal / Guinea / Ten</span>
        </div>
      </div>

      <div className="mp-grid">
        {PAIRS.map((p) => {
          const c = nearContract(priceData, p.base);
          const bid = c?.buyer ?? null;
          const charge = Number(cfg.charges[p.key]) || 0;
          const value = bid == null ? null : (p.factored ? bid * factor + charge * p.mult : bid + charge);
          const isSilver = p.base === "silver";
          return (
            <div className={`mp-card ${isSilver ? "mp-silver" : "mp-gold"}`} key={p.key}>
              <div className="mp-card-head">
                <span className="mp-pair">{p.label}</span>
                {c?.contract && <span className="mp-exp">{c.contract}</span>}
              </div>

              <div className="mp-formula">
                {p.factored
                  ? <code>{p.baseLabel} Bid × {cfg.factor} + {fmtNum(charge, 0)} × {p.mult}</code>
                  : <code>{p.baseLabel} Bid + {fmtNum(charge, 0)}</code>}
              </div>

              <div className="mp-rows">
                <div className="mp-row">
                  <span className="mp-label">{p.baseLabel} Bid</span>
                  <span className={`mp-live ${bid == null ? "stale" : ""}`}>
                    {bid == null ? "waiting for tick…" : <>{fmtNum(bid, 2)} <span className="live-dot" title="Live" /></>}
                  </span>
                </div>
                <div className="mp-row">
                  <span className="mp-label">Making charge</span>
                  <input
                    type="number"
                    step="1"
                    className="mp-input"
                    value={cfg.charges[p.key]}
                    onChange={(e) => setCharge(p.key, e.target.value)}
                  />
                </div>
              </div>

              <div className="mp-result">
                <span className="mp-result-label">Value</span>
                <span className="mp-result-value">{value == null ? "—" : fmtNum(value, 2)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
