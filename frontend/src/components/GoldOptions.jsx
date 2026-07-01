import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

function fmtExpiry(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
  });
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
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [exp, setExp] = useState(0);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await api.goldOptions();
        if (alive) {
          setData(r);
          setErr(null);
        }
      } catch (e) {
        if (alive) setErr(e?.message || "Failed to load gold options");
      }
    }
    load();
    const t = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const expiries = data?.expiries || [];
  const cur = expiries[exp] || expiries[0];
  const ref = data?.ref;

  const atmStrike = useMemo(() => {
    if (!cur?.rows?.length || ref == null) return null;
    return cur.rows.reduce(
      (best, r) =>
        best == null || Math.abs(r.strike - ref) < Math.abs(best - ref)
          ? r.strike
          : best,
      null
    );
  }, [cur, ref]);

  const sp1Label = data?.spread1_label || "Spread 1";
  const sp2Label = data?.spread2_label || "Spread 2";
  const higher = data?.higher || "—";
  const lower = data?.lower || "—";

  return (
    <div className="go-page">
      {/* ===== Header + expiry toggle ===== */}
      <div className="go-head">
        <div className="go-title">
          <h2 className="go-title-main">
            GOLD <span className="go-title-x">/</span> GOLD MINI
          </h2>
          <span className="go-title-sub">Options Spread · watch only</span>
        </div>
        {expiries.length > 0 && (
          <div className="go-exp-toggle" role="tablist" aria-label="Expiry">
            {expiries.map((e, i) => (
              <button
                key={i}
                type="button"
                role="tab"
                aria-selected={i === exp}
                className={i === exp ? "go-exp-btn active" : "go-exp-btn"}
                onClick={() => setExp(i)}
              >
                <span className="go-exp-main">{fmtExpiry(e.gold_expiry)}</span>
                {e.goldm_expiry !== e.gold_expiry && (
                  <span className="go-exp-mini">/ {fmtExpiry(e.goldm_expiry)}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      {/* ===== Top cards ===== */}
      <div className="go-cards">
        <div className="go-card go-card-gold">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">◆</span>
              <span className="go-card-label">GOLD Future</span>
              {data?.gold_price != null && <span className="live-dot go-live" />}
            </div>
            <div className="go-card-value">
              {data?.gold_price == null ? "—" : fmtNum(data.gold_price, 0)}
            </div>
            <div className="go-card-foot">Full contract</div>
          </div>
        </div>

        <div className="go-card go-card-mini">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">◈</span>
              <span className="go-card-label">GOLD MINI Future</span>
              {data?.goldm_price != null && <span className="live-dot go-live" />}
            </div>
            <div className="go-card-value">
              {data?.goldm_price == null ? "—" : fmtNum(data.goldm_price, 0)}
            </div>
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
              <span className="go-side-hi">{higher}</span>
              <span className="go-side-arrow">→ Ask</span>
            </div>
            <div className="go-card-foot">
              <span className="go-side-lo">{lower}</span> → Bid
            </div>
          </div>
        </div>

        <div className="go-card go-card-exp">
          <span className="go-card-bar" />
          <div className="go-card-body">
            <div className="go-card-top">
              <span className="go-card-ico" aria-hidden="true">◷</span>
              <span className="go-card-label">Expiry</span>
            </div>
            <div className="go-card-value go-card-value-sm">
              {cur ? fmtExpiry(cur.gold_expiry) : "—"}
            </div>
            <div className="go-card-foot">
              MINI {cur ? fmtExpiry(cur.goldm_expiry) : "—"}
            </div>
          </div>
        </div>
      </div>

      {/* ===== Legend ===== */}
      {cur && (
        <div className="go-legend">
          <span className="go-legend-item">
            <span className="go-swatch go-swatch-s1" /> {sp1Label}
          </span>
          <span className="go-legend-item">
            <span className="go-swatch go-swatch-s2" /> {sp2Label}
          </span>
          <span className="go-legend-item go-legend-atm">
            <span className="go-atm">ATM</span> nearest to ref
            {ref != null ? ` (${fmtNum(ref, 0)})` : ""}
          </span>
        </div>
      )}

      {/* ===== Table (desktop/tablet) + stacked cards (mobile) ===== */}
      {!cur ? (
        <div className="empty-state">Loading gold options…</div>
      ) : (
        <>
          <div
            className="go-wrap"
            role="region"
            aria-label="Gold options spread table"
            tabIndex={0}
          >
            <table className="go-table">
              <colgroup>
                <col className="go-col-strike" />
                <col className="go-col-type" />
                <col />
                <col />
                <col />
                <col />
                <col className="go-col-sp" />
                <col className="go-col-sp" />
              </colgroup>
              <thead>
                <tr className="go-grp-row">
                  <th rowSpan={2} className="go-h-strike">
                    Strike
                  </th>
                  <th rowSpan={2} className="go-h-type">
                    Type
                  </th>
                  <th colSpan={2} className="go-grp go-grp-mini">
                    GOLD MINI
                  </th>
                  <th colSpan={2} className="go-grp go-grp-gold">
                    GOLD
                  </th>
                  <th colSpan={2} className="go-grp go-grp-sp">
                    Spread · 1:1
                  </th>
                </tr>
                <tr className="go-sub-row">
                  <th className="go-sub go-edge-l">Bid</th>
                  <th className="go-sub">Ask</th>
                  <th className="go-sub go-edge-l">Bid</th>
                  <th className="go-sub">Ask</th>
                  <th className="go-sub go-sub-sp go-edge-l" title={sp1Label}>
                    {sp1Label}
                  </th>
                  <th className="go-sub go-sub-sp" title={sp2Label}>
                    {sp2Label}
                  </th>
                </tr>
              </thead>
              <tbody>
                {cur.rows.map((r) => {
                  const isAtm = r.strike === atmStrike;
                  return (
                    <tr
                      key={`${r.strike}-${r.type}`}
                      className={isAtm ? "go-tr atm-row" : "go-tr"}
                    >
                      <th scope="row" className="go-strike">
                        <span className="go-strike-n">{fmtNum(r.strike, 0)}</span>
                        {isAtm && <span className="go-atm go-atm-block">ATM</span>}
                      </th>
                      <td className="go-td">
                        <span
                          className={`go-type go-type-${(r.type || "").toLowerCase()}`}
                        >
                          {r.type}
                        </span>
                      </td>
                      <td className="go-td go-num go-edge-l">{cell(r.goldm_bid)}</td>
                      <td className="go-td go-num">{cell(r.goldm_ask)}</td>
                      <td className="go-td go-num go-edge-l">{cell(r.gold_bid)}</td>
                      <td className="go-td go-num">{cell(r.gold_ask)}</td>
                      <td
                        className={`go-td go-num go-edge-l go-hero ${spCls(r.spread1)}`}
                      >
                        {fmtSigned(r.spread1)}
                      </td>
                      <td className={`go-td go-num go-hero ${spCls(r.spread2)}`}>
                        {fmtSigned(r.spread2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ===== Stacked per-strike cards (<= 640px) ===== */}
          <div className="go-stack">
            {cur.rows.map((r) => {
              const isAtm = r.strike === atmStrike;
              return (
                <div
                  key={`m-${r.strike}-${r.type}`}
                  className={isAtm ? "go-scard atm-row" : "go-scard"}
                >
                  <div className="go-scard-head">
                    <span className="go-scard-strike">
                      {fmtNum(r.strike, 0)}
                      {isAtm && <span className="go-atm">ATM</span>}
                    </span>
                    <span
                      className={`go-type go-type-${(r.type || "").toLowerCase()}`}
                    >
                      {r.type}
                    </span>
                  </div>

                  <div className="go-scard-spreads">
                    <div className="go-scard-sp">
                      <span className="go-scard-sp-lbl">{sp1Label}</span>
                      <span
                        className={`go-scard-sp-val go-hero ${spCls(r.spread1)}`}
                      >
                        {fmtSigned(r.spread1)}
                      </span>
                    </div>
                    <div className="go-scard-sp">
                      <span className="go-scard-sp-lbl">{sp2Label}</span>
                      <span
                        className={`go-scard-sp-val go-hero ${spCls(r.spread2)}`}
                      >
                        {fmtSigned(r.spread2)}
                      </span>
                    </div>
                  </div>

                  <div className="go-scard-legs">
                    <div className="go-scard-leg go-leg-mini">
                      <span className="go-scard-leg-t">GOLD MINI</span>
                      <span className="go-scard-leg-r">
                        <em>Bid</em> {cell(r.goldm_bid)} <i>·</i>{" "}
                        <em>Ask</em> {cell(r.goldm_ask)}
                      </span>
                    </div>
                    <div className="go-scard-leg go-leg-gold">
                      <span className="go-scard-leg-t">GOLD</span>
                      <span className="go-scard-leg-r">
                        <em>Bid</em> {cell(r.gold_bid)} <i>·</i>{" "}
                        <em>Ask</em> {cell(r.gold_ask)}
                      </span>
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
