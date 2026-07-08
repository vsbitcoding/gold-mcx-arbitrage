import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live gold premium (client's Excel formula), vertical layout like the sheet.
//   Premium = ((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) / 100 − MCX Bid
//   Two variants: 999 (conversion 32.12) and 995 (conversion 31.99).
const LS_KEY = "arbi_premium_v1";
const DEFAULTS = { cost: 5, duty: 1854062, convBank: 32.12, convAdani: 31.99, fxAdj: 0.01 };
// convBank -> "999" (32.12) ; convAdani -> "995" (31.99)

function loadCfg() {
  try { const r = localStorage.getItem(LS_KEY); return r ? { ...DEFAULTS, ...JSON.parse(r) } : { ...DEFAULTS }; }
  catch { return { ...DEFAULTS }; }
}

export default function PremiumInputs() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);
  const [cfg, setCfg] = useState(loadCfg);

  useEffect(() => { try { localStorage.setItem(LS_KEY, JSON.stringify(cfg)); } catch {} }, [cfg]);
  useEffect(() => {
    let alive = true;
    async function load() {
      try { const r = await api.premiumInputs(); if (alive) { setD(r); setErr(false); } }
      catch { if (alive) setErr(true); }
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const spot = d?.xauusd;
  const inrLive = d?.usdinr;
  const inr = inrLive == null ? null : inrLive + (Number(cfg.fxAdj) || 0);
  const mcx = d?.mcx_gold?.bid ?? d?.mcx_gold?.ltp;
  const cost = Number(cfg.cost) || 0;
  const duty = Number(cfg.duty) || 0;
  const ready = spot != null && inr != null && mcx != null;
  const premium = (conv) => (ready ? (((spot + cost) * (Number(conv) || 0) * inr + duty) / 100) - mcx : null);
  const p999 = premium(cfg.convBank);
  const p995 = premium(cfg.convAdani);
  const setF = (k, v) => setCfg((c) => ({ ...c, [k]: v }));
  const num = (v, dp = 2) => (v == null ? "—" : fmtNum(v, dp));

  return (
    <div className="pv-page">
      <div className="pv-head">
        <h2>Forex <span className="pv-x">Premium</span></h2>
        <p className="pv-sub">
          ((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) ÷ 100 − MCX Bid. Editable fields auto-save.
        </p>
      </div>
      {err && <div className="settings-banner danger">⚠ Couldn't reach the live feed.</div>}

      <div className="pv-table">
        <div className="pv-hrow"><span>Parameter</span><span>Value</span><span>Source</span></div>

        <div className="pv-row">
          <span className="pv-param">Spot XAU/USD</span>
          <span className="pv-val">{num(spot)}</span>
          <span className="pv-note">{d?.deriv_connected ? <><span className="live-dot" /> Deriv live</> : "connecting…"}</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">Cost (USD)</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.cost} onChange={(e) => setF("cost", e.target.value)} />
          <span className="pv-note">manual</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">C. Duty</span>
          <input className="pv-input" type="number" step="1" value={cfg.duty} onChange={(e) => setF("duty", e.target.value)} />
          <span className="pv-note">manual</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">USD/INR <span className="pv-mut">(+{cfg.fxAdj})</span></span>
          <span className="pv-val">{num(inr, 4)}</span>
          <span className="pv-note">TwelveData{inrLive != null && ` · spot ${num(inrLive, 4)}`}</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">Conversion — 999</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.convBank} onChange={(e) => setF("convBank", e.target.value)} />
          <span className="pv-note">manual</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">Conversion — 995</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.convAdani} onChange={(e) => setF("convAdani", e.target.value)} />
          <span className="pv-note">manual</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">USD/INR + spread</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.fxAdj} onChange={(e) => setF("fxAdj", e.target.value)} />
          <span className="pv-note">manual</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">MCX Gold <span className="pv-tag">Bid</span></span>
          <span className="pv-val">{num(mcx, 0)}</span>
          <span className="pv-note">Dhan live{d?.mcx_gold?.expiry ? ` · ${d.mcx_gold.expiry}` : ""}</span>
        </div>

        <div className="pv-row pv-prem">
          <span className="pv-param">Premium — 999</span>
          <span className={`pv-pval ${p999 == null ? "" : p999 >= 0 ? "pos" : "neg"}`}>{num(p999)}</span>
          <span className="pv-note">conv {cfg.convBank}</span>
        </div>
        <div className="pv-row pv-prem">
          <span className="pv-param">Premium — 995</span>
          <span className={`pv-pval ${p995 == null ? "" : p995 >= 0 ? "pos" : "neg"}`}>{num(p995)}</span>
          <span className="pv-note">conv {cfg.convAdani}</span>
        </div>
      </div>
    </div>
  );
}
