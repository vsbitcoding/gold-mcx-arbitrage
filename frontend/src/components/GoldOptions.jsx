import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

function fmtExpiry(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
}
function fmtSigned(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), 2);
}
function spCls(v) {
  if (v == null) return "neutral";
  return v >= 0 ? "pos" : "neg";
}

export default function GoldOptions() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [exp, setExp] = useState(0);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await api.goldOptions();
        if (alive) { setData(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const expiries = data?.expiries || [];
  const cur = expiries[exp] || expiries[0];
  const ref = data?.ref;

  const atmStrike = useMemo(() => {
    if (!cur?.rows?.length || ref == null) return null;
    return cur.rows.reduce((best, r) =>
      (best == null || Math.abs(r.strike - ref) < Math.abs(best - ref)) ? r.strike : best, null);
  }, [cur, ref]);

  const cell = (v) => (v == null ? "—" : fmtNum(v, 2));

  return (
    <div className="go-page">
      <div className="go-head">
        <h2>GOLD / GOLD MINI <span className="go-head-sub">— Options Spread</span></h2>
        {expiries.length > 0 && (
          <div className="go-exp-toggle" role="tablist">
            {expiries.map((e, i) => (
              <button key={i} className={i === exp ? "active" : ""} onClick={() => setExp(i)}>
                {fmtExpiry(e.gold_expiry)}
                {e.goldm_expiry !== e.gold_expiry && <span className="go-exp-sub"> / {fmtExpiry(e.goldm_expiry)}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      <div className="go-bar">
        <div className="go-chip go-chip-g">
          <span className="go-chip-l">{data?.gold_price != null && <span className="live-dot" />}GOLD future</span>
          <span className="go-chip-v">{data?.gold_price == null ? "—" : fmtNum(data.gold_price, 0)}</span>
        </div>
        <div className="go-chip go-chip-m">
          <span className="go-chip-l">{data?.goldm_price != null && <span className="live-dot" />}GOLD MINI future</span>
          <span className="go-chip-v">{data?.goldm_price == null ? "—" : fmtNum(data.goldm_price, 0)}</span>
        </div>
        <div className="go-chip">
          <span className="go-chip-l">Higher → Ask</span>
          <span className="go-chip-v">{data?.higher || "—"}</span>
          <span className="go-chip-s">lower → Bid</span>
        </div>
        {cur && (
          <div className="go-chip">
            <span className="go-chip-l">Expiry</span>
            <span className="go-chip-v">GOLD {fmtExpiry(cur.gold_expiry)}</span>
            <span className="go-chip-s">MINI {fmtExpiry(cur.goldm_expiry)}</span>
          </div>
        )}
      </div>

      {!cur ? (
        <div className="empty-state">Loading gold options…</div>
      ) : (
        <div className="go-wrap">
          <table className="go-table">
            <thead>
              <tr className="go-grp-row">
                <th rowSpan={2} className="go-h-strike">Strike</th>
                <th rowSpan={2} className="go-h-type">Type</th>
                <th colSpan={2} className="go-grp go-grp-m">GOLD MINI</th>
                <th colSpan={2} className="go-grp go-grp-g">GOLD</th>
                <th colSpan={2} className="go-grp go-grp-s">Spread · 1:1</th>
              </tr>
              <tr className="go-sub-row">
                <th className="num go-b-m">Bid</th><th className="num">Ask</th>
                <th className="num go-b-g">Bid</th><th className="num">Ask</th>
                <th className="num go-b-s">{data?.spread1_label || "Spread 1"}</th>
                <th className="num">{data?.spread2_label || "Spread 2"}</th>
              </tr>
            </thead>
            <tbody>
              {cur.rows.map((r) => (
                <tr key={r.strike} className={r.strike === atmStrike ? "atm-row" : ""}>
                  <td className="go-strike">
                    {fmtNum(r.strike, 0)}
                    {r.strike === atmStrike && <span className="atm-badge">ATM</span>}
                  </td>
                  <td><span className={`go-type go-${(r.type || "").toLowerCase()}`}>{r.type}</span></td>
                  <td className="num go-b-m">{cell(r.goldm_bid)}</td>
                  <td className="num">{cell(r.goldm_ask)}</td>
                  <td className="num go-b-g">{cell(r.gold_bid)}</td>
                  <td className="num">{cell(r.gold_ask)}</td>
                  <td className={`num go-b-s go-sp go-sp-main ${spCls(r.spread1)}`}>{fmtSigned(r.spread1)}</td>
                  <td className={`num go-sp ${spCls(r.spread2)}`}>{fmtSigned(r.spread2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
