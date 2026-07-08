import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live gold premium (client's Excel formula), grouped calculator layout.
//   Premium = ((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) / 100 − MCX Bid
//   999 (conv 32.12) / 995 (conv 31.99). Plus two manual rate calculators off Gold Ask.
const LS_KEY = "arbi_premium_v1";
const DEFAULTS = { cost: 5, duty: 1854062, convBank: 32.12, convAdani: 31.99, fxAdj: 0.01, onlyPrem: "", prmGst: "" };
// onlyPrem -> "Only Premium": (Gold Ask + onlyPrem) × 1.03  [=(+D9+F15)*1.03]
// prmGst   -> "Premium with GST":  Gold Ask + prmGst        [=G15+D9]

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
  const goldAsk = d?.mcx_gold?.ask;
  const cost = Number(cfg.cost) || 0;
  const duty = Number(cfg.duty) || 0;
  const ready = spot != null && inr != null && mcx != null;
  const premium = (conv) => (ready ? (((spot + cost) * (Number(conv) || 0) * inr + duty) / 100) - mcx : null);
  const p999 = premium(cfg.convBank);
  const p995 = premium(cfg.convAdani);
  const onlyPremIn = cfg.onlyPrem === "" || cfg.onlyPrem == null ? null : Number(cfg.onlyPrem);
  const onlyPremRate = goldAsk != null && onlyPremIn != null ? (goldAsk + onlyPremIn) * 1.03 : null;
  const prmGstIn = cfg.prmGst === "" || cfg.prmGst == null ? null : Number(cfg.prmGst);
  const rateWithGst = goldAsk != null && prmGstIn != null ? goldAsk + prmGstIn : null;
  const setF = (k, v) => setCfg((c) => ({ ...c, [k]: v }));
  const num = (v, dp = 2) => (v == null ? "—" : fmtNum(v, dp));
  const sign = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");

  return (
    <div className="pv-page">
      <div className="pv-head">
        <h2>Forex <span className="pv-x">Premium</span></h2>
        <p className="pv-sub">((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) ÷ 100 − MCX Bid</p>
      </div>
      {err && <div className="settings-banner danger">⚠ Couldn't reach the live feed.</div>}

      <div className="pv-card">
        {/* Live market */}
        <div className="pv-grp">
          <div className="pv-grp-h">Live Market</div>
          <div className="pv-row">
            <span className="pv-param">Spot XAU/USD</span>
            <span className="pv-val">{num(spot)}<span className="pv-u">USD</span>{d?.deriv_connected && <i className="pv-dot" title="Deriv live" />}</span>
          </div>
          <div className="pv-row">
            <span className="pv-param">USD/INR <span className="pv-mut">+{cfg.fxAdj}</span></span>
            <span className="pv-val">{num(inr, 4)}</span>
          </div>
          <div className="pv-row">
            <span className="pv-param">MCX Gold <span className="pv-tag">Bid</span></span>
            <span className="pv-val">{mcx == null ? "—" : `₹${num(mcx, 0)}`}{mcx != null && <i className="pv-dot" title="Dhan live" />}</span>
          </div>
        </div>

        {/* Parameters (editable) */}
        <div className="pv-grp">
          <div className="pv-grp-h">Parameters <span className="pv-grp-hint">auto-save</span></div>
          <div className="pv-row">
            <span className="pv-param">Cost <span className="pv-mut">USD</span></span>
            <input className="pv-input" type="number" step="0.01" value={cfg.cost} onChange={(e) => setF("cost", e.target.value)} />
          </div>
          <div className="pv-row">
            <span className="pv-param">C. Duty</span>
            <input className="pv-input" type="number" step="1" value={cfg.duty} onChange={(e) => setF("duty", e.target.value)} />
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
            <span className="pv-param">USD/INR spread</span>
            <input className="pv-input" type="number" step="0.01" value={cfg.fxAdj} onChange={(e) => setF("fxAdj", e.target.value)} />
          </div>
        </div>

        {/* Premium results */}
        <div className="pv-results">
          <div className="pv-res">
            <span className="pv-res-top"><span className="pv-res-lbl">Premium</span><span className="pv-badge">999</span></span>
            <span className={`pv-res-val ${sign(p999)}`}>{num(p999)}</span>
          </div>
          <div className="pv-res">
            <span className="pv-res-top"><span className="pv-res-lbl">Premium</span><span className="pv-badge alt">995</span></span>
            <span className={`pv-res-val ${sign(p995)}`}>{num(p995)}</span>
          </div>
        </div>

        {/* Calculator: Only Premium */}
        <div className="pv-calc">
          <div className="pv-calc-h">Only Premium <span className="pv-calc-f">(Ask + Premium) × 1.03</span></div>
          <div className="pv-calc-body">
            <label className="pv-calc-in">
              <span>Premium</span>
              <input className="pv-input" type="number" step="0.01" placeholder="type here" value={cfg.onlyPrem} onChange={(e) => setF("onlyPrem", e.target.value)} />
            </label>
            <span className="pv-calc-eq">=</span>
            <div className="pv-calc-out">
              <span>Rate{goldAsk != null && <em> Ask {num(goldAsk, 0)}</em>}</span>
              <b className={onlyPremRate == null ? "muted" : ""}>{onlyPremRate == null ? "—" : `₹${num(onlyPremRate, 0)}`}</b>
            </div>
          </div>
        </div>

        {/* Calculator: Premium with GST */}
        <div className="pv-calc">
          <div className="pv-calc-h">Premium with GST <span className="pv-calc-f">Ask + PRM GST</span></div>
          <div className="pv-calc-body">
            <label className="pv-calc-in">
              <span>Premium with GST</span>
              <input className="pv-input" type="number" step="0.01" placeholder="type here" value={cfg.prmGst} onChange={(e) => setF("prmGst", e.target.value)} />
            </label>
            <span className="pv-calc-eq">=</span>
            <div className="pv-calc-out">
              <span>Rate{goldAsk != null && <em> Ask {num(goldAsk, 0)}</em>}</span>
              <b className={rateWithGst == null ? "muted" : ""}>{rateWithGst == null ? "—" : `₹${num(rateWithGst, 0)}`}</b>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
