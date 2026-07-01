import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

const FALLBACK_COMMS = [
  { key: "gold", label: "Gold" },
  { key: "silver", label: "Silver" },
  { key: "crude", label: "Crude Oil" },
  { key: "natgas", label: "Natural Gas" },
];

function fmtExpiry(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
}
function fmtSigned(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), 2);
}
function spCls(v) {
  if (v == null) return "go-flat";
  return v >= 0 ? "go-pos" : "go-neg";
}
function cell(v) {
  return v == null ? "—" : fmtNum(v, 2);
}

export default function GoldOptions() {
  const [commodity, setCommodity] = useState("gold");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [exp, setExp] = useState(0);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await api.goldOptions(commodity);
        if (alive) { setData(r); setErr(null); }
      } catch (e) { if (alive) setErr(e?.message || "Failed to load options"); }
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [commodity]);

  const commodities = data?.commodities?.length ? data.commodities : FALLBACK_COMMS;
  const expiries = data?.expiries || [];
  const cur = expiries[exp] || expiries[0];
  const ref = data?.ref;
  const bigName = data?.big_name || "BIG";
  const miniName = data?.mini_name || "MINI";

  const atmStrike = useMemo(() => {
    if (!cur?.rows?.length || ref == null) return null;
    return cur.rows.reduce((best, r) =>
      (best == null || Math.abs(r.strike - ref) < Math.abs(best - ref)) ? r.strike : best, null);
  }, [cur, ref]);

  const sp1Label = data?.spread1_label || "Spread 1";
  const sp2Label = data?.spread2_label || "Spread 2";

  function pickCommodity(k) {
    if (k === commodity) return;
    setExp(0);
    setData(null);
    setCommodity(k);
  }

  return (
    <div className="go-page">
      {/* Commodity selector */}
      <div className="go-comm-bar" role="tablist" aria-label="Commodity">
        {commodities.map((c) => (
          <button key={c.key} type="button" role="tab" aria-selected={c.key === commodity}
            className={c.key === commodity ? "go-comm-btn active" : "go-comm-btn"} onClick={() => pickCommodity(c.key)}>
            {c.label}
          </button>
        ))}
      </div>

      <div className="go-head">
        <div className="go-title">
          <h2 className="go-title-main">{bigName} <span className="go-title-x">/</span> {miniName}</h2>
          <span className="go-title-sub">
            Options Spread · watch only{ref != null && <> · ATM ref {fmtNum(ref, 0)}</>}
          </span>
        </div>
        {expiries.length > 0 && (
          <div className="go-exp-toggle" role="tablist" aria-label="Expiry">
            {expiries.map((e, i) => (
              <button key={i} type="button" role="tab" aria-selected={i === exp}
                className={i === exp ? "go-exp-btn active" : "go-exp-btn"} onClick={() => setExp(i)}>
                <span className="go-exp-main">{fmtExpiry(e.big_expiry)}</span>
                {e.mini_expiry !== e.big_expiry && <span className="go-exp-mini">/ {fmtExpiry(e.mini_expiry)}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      {/* Top cards */}
      <div className="go-cards">
        <div className="go-card go-card-gold">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">◆</span>
              <span className="go-card-label">{bigName} Future</span>
              {data?.big_price != null && <span className="live-dot go-live" />}
            </div>
            <div className="go-card-value">{data?.big_price == null ? "—" : fmtNum(data.big_price, 0)}</div>
            <div className="go-card-foot">Full contract</div>
          </div>
        </div>

        <div className="go-card go-card-mini">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">◈</span>
              <span className="go-card-label">{miniName} Future</span>
              {data?.mini_price != null && <span className="live-dot go-live" />}
            </div>
            <div className="go-card-value">{data?.mini_price == null ? "—" : fmtNum(data.mini_price, 0)}</div>
            <div className="go-card-foot">Mini contract</div>
          </div>
        </div>

        <div className="go-card go-card-ref">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">⇅</span>
              <span className="go-card-label">Pricing Side</span>
            </div>
            <div className="go-card-value go-card-value-sm">
              <span className="go-side-hi">{data?.higher || "—"}</span>
              <span className="go-side-arrow">→ Ask</span>
            </div>
            <div className="go-card-foot"><span className="go-side-lo">{data?.lower || "—"}</span> → Bid</div>
          </div>
        </div>

        <div className="go-card go-card-exp">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">◷</span>
              <span className="go-card-label">Expiry</span>
            </div>
            <div className="go-card-value go-card-value-sm">{cur ? fmtExpiry(cur.big_expiry) : "—"}</div>
            <div className="go-card-foot">{miniName} {cur ? fmtExpiry(cur.mini_expiry) : "—"}</div>
          </div>
        </div>
      </div>

      {/* Table (desktop/tablet) + stacked cards (mobile) */}
      {!cur ? (
        <div className="empty-state">Loading options…</div>
      ) : (
        <>
          <div className="go-wrap" role="region" aria-label="Options spread table" tabIndex={0}>
            <table className="go-table">
              <colgroup>
                <col className="go-col-strike" />
                <col className="go-col-type" />
                <col className="go-col-contract" />
                <col className="go-col-leg" />
                <col className="go-col-leg" />
                <col className="go-col-sp" />
                <col className="go-col-sp" />
              </colgroup>
              <thead>
                <tr className="go-sub-row">
                  <th className="go-sub go-h-strike">Strike</th>
                  <th className="go-sub go-h-type">Type</th>
                  <th className="go-sub">Contract</th>
                  <th className="go-sub">Bid</th>
                  <th className="go-sub">Ask</th>
                  <th className="go-sub go-sub-sp go-edge-l" title={sp1Label}>{sp1Label}</th>
                  <th className="go-sub go-sub-sp" title={sp2Label}>{sp2Label}</th>
                </tr>
              </thead>
              <tbody>
                {cur.rows.map((r, i) => {
                  const isAtm = r.strike === atmStrike;
                  const cls = (isAtm ? " atm-row" : "") + (i % 2 ? " go-alt" : "");
                  return (
                    <React.Fragment key={r.strike}>
                      <tr className={`go-tr go-pair-top${cls}`}>
                        <th scope="row" rowSpan={2} className="go-strike">
                          <span className="go-strike-n">{fmtNum(r.strike, 0)}</span>
                          {isAtm && <span className="go-atm go-atm-block">ATM</span>}
                        </th>
                        <td rowSpan={2} className="go-td go-type-cell">
                          <span className={`go-type go-type-${(r.type || "").toLowerCase()}`}>{r.type}</span>
                        </td>
                        <td className="go-td go-contract go-c-mini">{miniName}</td>
                        <td className="go-td go-num">{cell(r.mini_bid)}</td>
                        <td className="go-td go-num">{cell(r.mini_ask)}</td>
                        <td rowSpan={2} className={`go-td go-num go-hero go-edge-l ${spCls(r.spread1)}`}>{fmtSigned(r.spread1)}</td>
                        <td rowSpan={2} className={`go-td go-num go-hero ${spCls(r.spread2)}`}>{fmtSigned(r.spread2)}</td>
                      </tr>
                      <tr className={`go-tr go-pair-bot${cls}`}>
                        <td className="go-td go-contract go-c-gold">{bigName}</td>
                        <td className="go-td go-num">{cell(r.big_bid)}</td>
                        <td className="go-td go-num">{cell(r.big_ask)}</td>
                      </tr>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Stacked per-strike cards (<= 640px) */}
          <div className="go-stack">
            {cur.rows.map((r) => {
              const isAtm = r.strike === atmStrike;
              return (
                <div key={`m-${r.strike}`} className={isAtm ? "go-scard atm-row" : "go-scard"}>
                  <div className="go-scard-head">
                    <span className="go-scard-strike">
                      {fmtNum(r.strike, 0)}
                      {isAtm && <span className="go-atm">ATM</span>}
                    </span>
                    <span className={`go-type go-type-${(r.type || "").toLowerCase()}`}>{r.type}</span>
                  </div>
                  <div className="go-scard-spreads">
                    <div className="go-scard-sp">
                      <span className="go-scard-sp-lbl">{sp1Label}</span>
                      <span className={`go-scard-sp-val go-hero ${spCls(r.spread1)}`}>{fmtSigned(r.spread1)}</span>
                    </div>
                    <div className="go-scard-sp">
                      <span className="go-scard-sp-lbl">{sp2Label}</span>
                      <span className={`go-scard-sp-val go-hero ${spCls(r.spread2)}`}>{fmtSigned(r.spread2)}</span>
                    </div>
                  </div>
                  <div className="go-scard-legs">
                    <div className="go-scard-leg go-leg-mini">
                      <span className="go-scard-leg-t">{miniName}</span>
                      <span className="go-scard-leg-r"><em>Bid</em> {cell(r.mini_bid)} <i>·</i> <em>Ask</em> {cell(r.mini_ask)}</span>
                    </div>
                    <div className="go-scard-leg go-leg-gold">
                      <span className="go-scard-leg-t">{bigName}</span>
                      <span className="go-scard-leg-r"><em>Bid</em> {cell(r.big_bid)} <i>·</i> <em>Ask</em> {cell(r.big_ask)}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
