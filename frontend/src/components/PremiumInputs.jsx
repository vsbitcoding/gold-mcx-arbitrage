import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live premium (client's Excel formula) for Gold AND Silver, shown side by side.
//   Premium = ((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) / 100 − MCX Bid
//   + 3 rate calculators off the metal's BIG Ask (Only Premium / Premium with GST / Premium from Rate).
// Gold = XAU/USD + MCX Gold; Silver = XAG/USD + MCX Silver (big). Each metal keeps its own editable
// numbers (separate localStorage). Silver conv/cost/duty start blank -> 999/995 show "—" until entered;
// the 3 calculators work live for both metals right away.
const CFG_KEY = { gold: "arbi_premium_v1", silver: "arbi_premium_silver_v1" };
const DEFAULTS = {
  gold:   { cost: 5,  duty: 1854062, convBank: 32.12, convAdani: 31.99, fxAdj: 0.01, onlyPrem: "", prmGst: "", manRate: "" },
  silver: { cost: "", duty: "",      convBank: "",    convAdani: "",    fxAdj: 0.01, onlyPrem: "", prmGst: "", manRate: "" },
};

function loadCfg(metal) {
  try { const r = localStorage.getItem(CFG_KEY[metal]); return r ? { ...DEFAULTS[metal], ...JSON.parse(r) } : { ...DEFAULTS[metal] }; }
  catch { return { ...DEFAULTS[metal] }; }
}

const num = (v, dp = 2) => (v == null ? "—" : fmtNum(v, dp));
const numOr = (v) => (v === "" || v == null ? null : Number(v));

function MetalBlock({ metal, d, cfg, setF }) {
  const isGold = metal === "gold";
  const spot = isGold ? d?.xauusd : d?.xagusd;
  const spotLabel = isGold ? "Spot XAU/USD" : "Spot XAG/USD";
  const mcxObj = isGold ? d?.mcx_gold : d?.mcx_silver;
  const mcx = mcxObj?.bid ?? mcxObj?.ltp;
  const ask = mcxObj?.ask;
  const mcxLabel = isGold ? "MCX Gold" : "MCX Silver";

  const inrLive = d?.usdinr;
  const inr = inrLive == null ? null : inrLive + (Number(cfg.fxAdj) || 0);
  const cost = Number(cfg.cost) || 0;
  const duty = Number(cfg.duty) || 0;
  const ready = spot != null && inr != null && mcx != null;
  const hasConv = (c) => c !== "" && c != null && Number(c) > 0;
  const premium = (conv) => (ready && hasConv(conv) ? (((spot + cost) * Number(conv) * inr + duty) / 100) - mcx : null);
  const p999 = premium(cfg.convBank);
  const p995 = premium(cfg.convAdani);

  const onlyPremRate = ask != null && numOr(cfg.onlyPrem) != null ? (ask + numOr(cfg.onlyPrem)) * 1.03 : null;
  const rateWithGst = ask != null && numOr(cfg.prmGst) != null ? ask + numOr(cfg.prmGst) : null;
  const gstPrem = rateWithGst != null && ask != null ? rateWithGst / 1.03 - ask : null;
  const manPrem = ask != null && numOr(cfg.manRate) != null ? numOr(cfg.manRate) / 1.03 - ask : null;
  const askTag = ask != null ? `Ask ${num(ask, 0)}` : "";
  const pcls = (v) => `pv-pval ${v == null ? "" : v >= 0 ? "pos" : "neg"}`;

  return (
    <div className="pv-metalcol">
      <div className={`pv-metalhead ${metal}`}>{isGold ? "Gold" : "Silver"}</div>

      <div className="pv-table">
        <div className="pv-hrow"><span>Parameter</span><span>Value</span></div>
        <div className="pv-row">
          <span className="pv-param">{spotLabel}</span>
          <span className="pv-val">{num(spot)} {d?.deriv_connected && <span className="live-dot" title="Deriv live" />}</span>
        </div>
        <div className="pv-row">
          <span className="pv-param">Cost (USD)</span>
          <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.cost} onChange={(e) => setF("cost", e.target.value)} />
        </div>
        <div className="pv-row">
          <span className="pv-param">C. Duty</span>
          <input className="pv-input" type="number" step="1" placeholder="—" value={cfg.duty} onChange={(e) => setF("duty", e.target.value)} />
        </div>
        <div className="pv-row">
          <span className="pv-param">USD/INR <span className="pv-mut">(+{cfg.fxAdj})</span></span>
          <span className="pv-val">{num(inr, 4)}</span>
        </div>
        <div className="pv-row">
          <span className="pv-param">Conversion — 999</span>
          <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.convBank} onChange={(e) => setF("convBank", e.target.value)} />
        </div>
        <div className="pv-row">
          <span className="pv-param">Conversion — 995</span>
          <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.convAdani} onChange={(e) => setF("convAdani", e.target.value)} />
        </div>
        <div className="pv-row">
          <span className="pv-param">USD/INR + spread</span>
          <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.fxAdj} onChange={(e) => setF("fxAdj", e.target.value)} />
        </div>
        <div className="pv-row">
          <span className="pv-param">{mcxLabel} <span className="pv-tag">Bid</span></span>
          <span className="pv-val">{num(mcx, 0)} {mcx != null && <span className="live-dot" title="Dhan live" />}</span>
        </div>
        <div className="pv-row pv-prem">
          <span className="pv-param">Premium — 999</span>
          <span className={pcls(p999)}>{num(p999)}</span>
        </div>
        <div className="pv-row pv-prem">
          <span className="pv-param">Premium — 995</span>
          <span className={pcls(p995)}>{num(p995)}</span>
        </div>
      </div>

      <div className="pv-two">
        <div className="pv-table">
          <div className="pv-hrow"><span>Only Premium</span><span className="pv-ask">{askTag}</span></div>
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
          <div className="pv-hrow"><span>Premium with GST</span><span className="pv-ask">{askTag}</span></div>
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
            <span className={pcls(gstPrem)}>{num(gstPrem, 0)}</span>
          </div>
        </div>

        <div className="pv-table">
          <div className="pv-hrow"><span>Premium from Rate</span><span className="pv-ask">{askTag}</span></div>
          <div className="pv-row">
            <span className="pv-param">Rate</span>
            <input className="pv-input pv-yin" type="number" step="0.01" placeholder="—" value={cfg.manRate} onChange={(e) => setF("manRate", e.target.value)} />
          </div>
          <div className="pv-row pv-prem">
            <span className="pv-param">Premium</span>
            <span className={pcls(manPrem)}>{num(manPrem, 0)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PremiumInputs() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);
  const [cfgGold, setCfgGold] = useState(() => loadCfg("gold"));
  const [cfgSilver, setCfgSilver] = useState(() => loadCfg("silver"));

  useEffect(() => { try { localStorage.setItem(CFG_KEY.gold, JSON.stringify(cfgGold)); } catch {} }, [cfgGold]);
  useEffect(() => { try { localStorage.setItem(CFG_KEY.silver, JSON.stringify(cfgSilver)); } catch {} }, [cfgSilver]);
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

  const setGold = (k, v) => setCfgGold((c) => ({ ...c, [k]: v }));
  const setSilver = (k, v) => setCfgSilver((c) => ({ ...c, [k]: v }));

  return (
    <div className="pv-page">
      <div className="pv-head"><h2><span className="pv-x">Premium</span></h2></div>
      {err && <div className="settings-banner danger">⚠ Couldn't reach the live feed.</div>}

      <div className="pv-cols">
        <MetalBlock metal="gold" d={d} cfg={cfgGold} setF={setGold} />
        <MetalBlock metal="silver" d={d} cfg={cfgSilver} setF={setSilver} />
      </div>
    </div>
  );
}
