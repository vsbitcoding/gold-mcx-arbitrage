import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live gold premium (client's Excel formula), vertical Parameter/Value layout.
//   Premium = ((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) / 100 − MCX Bid
//   Two variants: 999 (conversion 32.12) and 995 (conversion 31.99).
const LS_KEY = "arbi_premium_v1";
const DEFAULTS = { cost: 5, duty: 1854062, convBank: 32.12, convAdani: 31.99, fxAdj: 0.01, onlyPrem: "", prmGst: "", manRate: "" };
// convBank -> "999" (32.12) ; convAdani -> "995" (31.99)
// Three calculators (client sheet):
//   onlyPrem -> "Only Premium": type a premium -> Price = (Gold Ask + onlyPrem) × 1.03   [=(+D9+F15)*1.03]
//   prmGst   -> "Premium with GST": type a premium -> Rate = Gold Ask + prmGst, and then
//               Premium = Rate / 1.03 − Gold Ask   [=G15+D9 ; =G16/1.03-D9]  (chained in same box)
//   manRate  -> "Premium from Rate": type a rate (yellow) -> Premium = manRate / 1.03 − Gold Ask  [=F18/1.03-D9]
// Blank -> shows "—".

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
  // Two manual rate sections off Gold big Ask.
  const goldAsk = d?.mcx_gold?.ask;
  const onlyPremIn = cfg.onlyPrem === "" || cfg.onlyPrem == null ? null : Number(cfg.onlyPrem);
  const onlyPremRate = goldAsk != null && onlyPremIn != null ? (goldAsk + onlyPremIn) * 1.03 : null; // box1: (Ask+Prem)×1.03
  const prmGstIn = cfg.prmGst === "" || cfg.prmGst == null ? null : Number(cfg.prmGst);
  const rateWithGst = goldAsk != null && prmGstIn != null ? goldAsk + prmGstIn : null;   // Rate = Ask + PRM GST
  const gstPrem = rateWithGst != null && goldAsk != null ? rateWithGst / 1.03 - goldAsk : null; // Rate÷1.03 − Ask
  const manRateIn = cfg.manRate === "" || cfg.manRate == null ? null : Number(cfg.manRate);
  const manPrem = manRateIn != null && goldAsk != null ? manRateIn / 1.03 - goldAsk : null; // manual Rate÷1.03 − Ask
  const setF = (k, v) => setCfg((c) => ({ ...c, [k]: v }));
  const num = (v, dp = 2) => (v == null ? "—" : fmtNum(v, dp));

  return (
    <div className="pv-page">
      <div className="pv-head">
        <h2>Forex <span className="pv-x">Premium</span></h2>
      </div>
      {err && <div className="settings-banner danger">⚠ Couldn't reach the live feed.</div>}

      <div className="pv-table">
        <div className="pv-hrow"><span>Parameter</span><span>Value</span></div>

        <div className="pv-row">
          <span className="pv-param">Spot XAU/USD {d?.deriv_connected && <span className="live-dot" title="Deriv live" />}</span>
          <span className="pv-val">{num(spot)}</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">Cost (USD)</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.cost} onChange={(e) => setF("cost", e.target.value)} />
        </div>

        <div className="pv-row">
          <span className="pv-param">C. Duty</span>
          <input className="pv-input" type="number" step="1" value={cfg.duty} onChange={(e) => setF("duty", e.target.value)} />
        </div>

        <div className="pv-row">
          <span className="pv-param">USD/INR <span className="pv-mut">(+{cfg.fxAdj})</span></span>
          <span className="pv-val">{num(inr, 4)}</span>
        </div>

        <div className="pv-row">
          <span className="pv-param">Conversion — 999</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.convBank} onChange={(e) => setF("convBank", e.target.value)} />
        </div>

        <div className="pv-row">
          <span className="pv-param">Conversion — 995</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.convAdani} onChange={(e) => setF("convAdani", e.target.value)} />
        </div>

        <div className="pv-row">
          <span className="pv-param">USD/INR + spread</span>
          <input className="pv-input" type="number" step="0.01" value={cfg.fxAdj} onChange={(e) => setF("fxAdj", e.target.value)} />
        </div>

        <div className="pv-row">
          <span className="pv-param">MCX Gold <span className="pv-tag">Bid</span></span>
          <span className="pv-val">{num(mcx, 0)} {mcx != null && <span className="live-dot" title="Dhan live" />}</span>
        </div>

        <div className="pv-row pv-prem">
          <span className="pv-param">Premium — 999</span>
          <span className={`pv-pval ${p999 == null ? "" : p999 >= 0 ? "pos" : "neg"}`}>{num(p999)}</span>
        </div>
        <div className="pv-row pv-prem">
          <span className="pv-param">Premium — 995</span>
          <span className={`pv-pval ${p995 == null ? "" : p995 >= 0 ? "pos" : "neg"}`}>{num(p995)}</span>
        </div>
      </div>

      <div className="pv-two">
        <div className="pv-table">
          <div className="pv-hrow"><span>Only Premium</span><span className="pv-ask">{goldAsk != null ? `Ask ${num(goldAsk, 0)}` : ""}</span></div>
          <div className="pv-row">
            <span className="pv-param">Premium</span>
            <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.onlyPrem} onChange={(e) => setF("onlyPrem", e.target.value)} />
          </div>
          <div className="pv-row pv-prem">
            <span className="pv-param">Price</span>
            <span className="pv-pval">{num(onlyPremRate, 0)}</span>
          </div>
        </div>

        <div className="pv-table">
          <div className="pv-hrow"><span>Premium with GST</span><span className="pv-ask">{goldAsk != null ? `Ask ${num(goldAsk, 0)}` : ""}</span></div>
          <div className="pv-row">
            <span className="pv-param">Premium GST</span>
            <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.prmGst} onChange={(e) => setF("prmGst", e.target.value)} />
          </div>
          <div className="pv-row">
            <span className="pv-param">Rate</span>
            <span className="pv-val">{num(rateWithGst, 0)}</span>
          </div>
          <div className="pv-row pv-prem">
            <span className="pv-param">Premium</span>
            <span className={`pv-pval ${gstPrem == null ? "" : gstPrem >= 0 ? "pos" : "neg"}`}>{num(gstPrem, 0)}</span>
          </div>
        </div>

        <div className="pv-table">
          <div className="pv-hrow"><span>Premium from Rate</span><span className="pv-ask">{goldAsk != null ? `Ask ${num(goldAsk, 0)}` : ""}</span></div>
          <div className="pv-row">
            <span className="pv-param">Rate</span>
            <input className="pv-input pv-yin" type="number" step="0.01" placeholder="—" value={cfg.manRate} onChange={(e) => setF("manRate", e.target.value)} />
          </div>
          <div className="pv-row pv-prem">
            <span className="pv-param">Premium</span>
            <span className={`pv-pval ${manPrem == null ? "" : manPrem >= 0 ? "pos" : "neg"}`}>{num(manPrem, 0)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
