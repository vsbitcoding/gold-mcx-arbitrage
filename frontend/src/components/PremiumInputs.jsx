import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live COMEX-vs-MCX gold premium (client's sheet formula):
//   Premium = ((Spot + Cost) × Conversion × USD/INR + Duty) / 100 − MCX Gold
// Cost, Duty and the two conversion factors are editable (auto-saved locally).
const LS_KEY = "arbi_premium_v1";
const DEFAULTS = { cost: 4, duty: 1854062, convBank: 32.12, convAdani: 31.99 };

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
  const inr = d?.usdinr;
  const mcx = d?.mcx_gold?.ltp;
  const cost = Number(cfg.cost) || 0;
  const duty = Number(cfg.duty) || 0;
  const ready = spot != null && inr != null && mcx != null;

  // Premium = ((Spot + Cost) × Conversion × USD/INR + Duty) / 100 − MCX Gold
  const premium = (conv) => (ready ? (((spot + cost) * (Number(conv) || 0) * inr + duty) / 100) - mcx : null);
  const bankPrem = premium(cfg.convBank);
  const adaniPrem = premium(cfg.convAdani);

  const setF = (k, v) => setCfg((c) => ({ ...c, [k]: v }));

  return (
    <div className="pi-page">
      <div className="pi-head">
        <h2>Forex <span className="pi-x">Premium</span></h2>
        <p className="pi-sub">
          Live gold premium — <b>((Spot + Cost) × Conversion × USD/INR + Duty) ÷ 100 − MCX Gold</b>.
          Cost, Duty and the conversion factors are editable; your changes auto-save.
        </p>
      </div>

      {err && <div className="settings-banner danger">⚠ Couldn't reach the live feed.</div>}

      {/* Live inputs */}
      <div className="pi-grid">
        <div className="pi-card pi-usd">
          <div className="pi-card-h"><span className="pi-name">Spot XAU/USD</span><span className="pi-src">Deriv · live</span></div>
          <div className="pi-val">{spot == null ? "—" : fmtNum(spot, 2)}</div>
          <div className="pi-foot">{d?.deriv_connected ? <><span className="live-dot" /> streaming</> : "connecting…"}</div>
        </div>
        <div className="pi-card pi-inr">
          <div className="pi-card-h"><span className="pi-name">USD / INR</span><span className="pi-src">TwelveData spot</span></div>
          <div className="pi-val">{inr == null ? "—" : fmtNum(inr, 4)}</div>
          <div className="pi-foot">{inr == null ? "loading…" : "~2 min refresh"}</div>
        </div>
        <div className="pi-card pi-mcx">
          <div className="pi-card-h"><span className="pi-name">MCX Gold</span><span className="pi-src">Dhan · live</span></div>
          <div className="pi-val">{mcx == null ? "—" : fmtNum(mcx, 0)}</div>
          <div className="pi-foot">{d?.mcx_gold?.expiry || "—"}</div>
        </div>
      </div>

      {/* Editable inputs */}
      <div className="pi-settings">
        <div className="pi-field">
          <label>Cost (USD)</label>
          <input type="number" step="0.01" value={cfg.cost} onChange={(e) => setF("cost", e.target.value)} />
        </div>
        <div className="pi-field">
          <label>C. Duty</label>
          <input type="number" step="1" value={cfg.duty} onChange={(e) => setF("duty", e.target.value)} />
        </div>
        <div className="pi-field">
          <label>Conversion — Bank/MMTC</label>
          <input type="number" step="0.01" value={cfg.convBank} onChange={(e) => setF("convBank", e.target.value)} />
        </div>
        <div className="pi-field">
          <label>Conversion — ADANI/995</label>
          <input type="number" step="0.01" value={cfg.convAdani} onChange={(e) => setF("convAdani", e.target.value)} />
        </div>
      </div>

      {/* Premium outputs */}
      <div className="pi-prem-grid">
        <div className="pi-prem">
          <div className="pi-prem-h">Premium — Bank / MMTC <span className="pi-prem-sub">conv {cfg.convBank}</span></div>
          <div className={`pi-prem-val ${bankPrem == null ? "" : bankPrem >= 0 ? "pos" : "neg"}`}>
            {bankPrem == null ? "—" : fmtNum(bankPrem, 2)}
          </div>
        </div>
        <div className="pi-prem">
          <div className="pi-prem-h">Premium — ADANI / 995 <span className="pi-prem-sub">conv {cfg.convAdani}</span></div>
          <div className={`pi-prem-val ${adaniPrem == null ? "" : adaniPrem >= 0 ? "pos" : "neg"}`}>
            {adaniPrem == null ? "—" : fmtNum(adaniPrem, 2)}
          </div>
        </div>
      </div>
    </div>
  );
}
