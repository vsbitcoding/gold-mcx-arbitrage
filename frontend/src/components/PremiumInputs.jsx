import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live premium (client's Excel formula) for Gold AND Silver.
//   Premium = ((Spot + Cost) × Conversion × (USD/INR + spread) + Duty) / 100 − MCX Bid
//   + 3 rate calculators off the metal's BIG Ask (Only Premium / Premium with GST / Premium from Rate).
// Layout: the two parameter tables sit side by side; each metal's 3 calculators are a full-width
// 3-across row below. Gold = XAU/USD + MCX Gold; Silver = XAG/USD + MCX Silver (big). Each metal keeps
// its own editable numbers (separate localStorage); silver conv/cost/duty start blank -> 999/995 show "—".
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

function computeMetal(metal, d, cfg) {
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
  const onlyPremRate = ask != null && numOr(cfg.onlyPrem) != null ? (ask + numOr(cfg.onlyPrem)) * 1.03 : null;
  const rateWithGst = ask != null && numOr(cfg.prmGst) != null ? ask + numOr(cfg.prmGst) : null;
  const gstPrem = rateWithGst != null && ask != null ? rateWithGst / 1.03 - ask : null;
  const manPrem = ask != null && numOr(cfg.manRate) != null ? numOr(cfg.manRate) / 1.03 - ask : null;
  return {
    spot, spotLabel, mcx, ask, mcxLabel, inr,
    p999: premium(cfg.convBank), p995: premium(cfg.convAdani),
    onlyPremRate, rateWithGst, gstPrem, manPrem, deriv: d?.deriv_connected,
  };
}

const pcls = (v) => `pv-pval ${v == null ? "" : v >= 0 ? "pos" : "neg"}`;

function MainTable({ v, cfg, setF }) {
  return (
    <div className="pv-table">
      <div className="pv-hrow"><span>Parameter</span><span>Value</span></div>
      <div className="pv-row">
        <span className="pv-param">{v.spotLabel}</span>
        <span className="pv-val">{num(v.spot)} {v.deriv && <span className="live-dot" title="Deriv live" />}</span>
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
        <span className="pv-val">{num(v.inr, 4)}</span>
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
        <span className="pv-param">{v.mcxLabel} <span className="pv-tag">Bid</span></span>
        <span className="pv-val">{num(v.mcx, 0)} {v.mcx != null && <span className="live-dot" title="Dhan live" />}</span>
      </div>
      <div className="pv-row pv-prem">
        <span className="pv-param">Premium — 999</span>
        <span className={pcls(v.p999)}>{num(v.p999)}</span>
      </div>
      <div className="pv-row pv-prem">
        <span className="pv-param">Premium — 995</span>
        <span className={pcls(v.p995)}>{num(v.p995)}</span>
      </div>
    </div>
  );
}

function Calcs({ v, cfg, setF }) {
  const askTag = v.ask != null ? `Ask ${num(v.ask, 0)}` : "";
  return (
    <div className="pv-two">
      <div className="pv-table">
        <div className="pv-hrow"><span>Only Premium</span><span className="pv-ask">{askTag}</span></div>
        <div className="pv-row">
          <span className="pv-param">Premium</span>
          <input className="pv-input" type="number" step="0.01" placeholder="—" value={cfg.onlyPrem} onChange={(e) => setF("onlyPrem", e.target.value)} />
        </div>
        <div className="pv-row pv-prem">
          <span className="pv-param">Price</span>
          <span className="pv-pval">{num(v.onlyPremRate, 0)}</span>
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
          <span className="pv-val">{num(v.rateWithGst, 0)}</span>
        </div>
        <div className="pv-row pv-prem">
          <span className="pv-param">Premium</span>
          <span className={pcls(v.gstPrem)}>{num(v.gstPrem, 0)}</span>
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
          <span className={pcls(v.manPrem)}>{num(v.manPrem, 0)}</span>
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
  const vg = computeMetal("gold", d, cfgGold);
  const vs = computeMetal("silver", d, cfgSilver);

  return (
    <div className="pv-page">
      <div className="pv-head"><h2><span className="pv-x">Premium</span></h2></div>
      {err && <div className="settings-banner danger">⚠ Couldn't reach the live feed.</div>}

      {/* Gold | Silver side by side; each column = its table + its 3 calculators below */}
      <div className="pv-cols">
        <div className="pv-metalcol gold">
          <div className="pv-metalhead gold">Gold</div>
          <MainTable v={vg} cfg={cfgGold} setF={setGold} />
          <Calcs v={vg} cfg={cfgGold} setF={setGold} />
        </div>
        <div className="pv-metalcol silver">
          <div className="pv-metalhead silver">Silver</div>
          <MainTable v={vs} cfg={cfgSilver} setF={setSilver} />
          <Calcs v={vs} cfg={cfgSilver} setF={setSilver} />
        </div>
      </div>
    </div>
  );
}
