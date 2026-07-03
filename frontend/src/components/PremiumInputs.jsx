import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// Live building blocks for the gold-premium calc. The full premium formula
// slots in here once the client confirms it.
export default function PremiumInputs() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);

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

  const g = d?.mcx_gold;
  const inr = d?.usdinr;
  const usd = d?.xauusd;

  return (
    <div className="pi-page">
      <div className="pi-head">
        <h2>Premium <span className="pi-x">Live Inputs</span></h2>
        <p className="pi-sub">
          Live building blocks for the gold-premium calculation. The full premium formula will
          slot in here once you confirm it from the sheet.
        </p>
      </div>

      {err && <div className="settings-banner danger">⚠ Couldn't reach the premium feed.</div>}

      <div className="pi-grid">
        <div className="pi-card pi-usd">
          <div className="pi-card-h">
            <span className="pi-name">XAU / USD</span>
            <span className="pi-src">Deriv · WebSocket</span>
          </div>
          <div className="pi-val">{usd == null ? "—" : fmtNum(usd, 2)}</div>
          <div className="pi-foot">
            {d?.deriv_connected
              ? <><span className="live-dot" /> live stream{d?.xauusd_age != null && d.xauusd_age < 15 ? "" : d?.xauusd_age != null ? ` · ${Math.round(d.xauusd_age)}s ago` : ""}</>
              : "connecting…"}
          </div>
        </div>

        <div className="pi-card pi-inr">
          <div className="pi-card-h">
            <span className="pi-name">USD / INR</span>
            <span className="pi-src">TwelveData · spot</span>
          </div>
          <div className="pi-val">{inr == null ? "—" : fmtNum(inr, 4)}</div>
          <div className="pi-foot">
            {inr == null ? "loading…" : <>{d?.usdinr_age != null ? `${Math.round(d.usdinr_age)}s ago` : ""} · ~2 min refresh</>}
          </div>
        </div>

        <div className="pi-card pi-mcx">
          <div className="pi-card-h">
            <span className="pi-name">MCX Gold</span>
            <span className="pi-src">Dhan · live</span>
          </div>
          <div className="pi-val">{g?.ltp == null ? "—" : fmtNum(g.ltp, 0)}</div>
          <div className="pi-foot">
            {g?.expiry || "—"}{g?.bid != null && <> · bid {fmtNum(g.bid, 0)}</>}
          </div>
        </div>
      </div>

      <div className="pi-note">
        <b>Next:</b> send the sheet's premium formula (Spot COMEX / conversion / duty / GST) and the
        live <b>Premium</b> value will compute here from these three feeds.
      </div>
    </div>
  );
}
