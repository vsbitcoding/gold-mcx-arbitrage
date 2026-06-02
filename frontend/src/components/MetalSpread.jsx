import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

function signCls(v) {
  if (v == null) return "neutral";
  return v >= 0 ? "pos" : "neg";
}

function fmtSigned(v, decimals) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), decimals);
}

export default function MetalSpread({ data: dataProp, embedded = false }) {
  const controlled = dataProp !== undefined;   // parent supplies data when embedded
  const [dataState, setDataState] = useState(null);
  const [err, setErr] = useState(null);
  const data = controlled ? dataProp : dataState;

  useEffect(() => {
    if (controlled) return;   // parent owns the fetch loop
    let alive = true;
    let timer = null;
    async function load() {
      try {
        const r = await api.metalsSpread();
        if (alive) { setDataState(r); setErr(null); }
      } catch (e) { if (alive) setErr(e.message); }
    }
    function start() { if (!timer) timer = setInterval(load, 2000); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function onVis() {
      if (document.hidden) stop();
      else { load(); start(); }
    }
    load();
    start();
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; stop(); document.removeEventListener("visibilitychange", onVis); };
  }, [controlled]);

  // Mark the first row of each metal group so we can draw a separator + label once.
  const rows = useMemo(() => {
    const rs = data?.rows || [];
    let last = null;
    return rs.map((r) => {
      const firstOfGroup = r.metal !== last;
      last = r.metal;
      return { ...r, firstOfGroup };
    });
  }, [data]);

  return (
    <div className={`metal-page${embedded ? " metal-embedded" : ""}`}>
      {!embedded && (
        <div className="metal-head">
          <h2>Metal — Calendar Spreads</h2>
        </div>
      )}
      <p className="metal-sub">
        Watch-only. <strong>Difference</strong> = far-month Buy − near-month Sell.{" "}
        <strong>% Spread</strong> = Difference ÷ near Sell × 100.
      </p>

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      {!rows.length ? (
        <div className="empty-state">Loading metal data…</div>
      ) : (
        <div className="metal-wrap">
          <table className="metal-table">
            <thead>
              <tr>
                <th className="ml-metal">Metal</th>
                <th className="ml-month">Month</th>
                <th className="ml-diff">Difference</th>
                <th className="ml-pct">% Spread</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={r.firstOfGroup ? "metal-group-start" : ""}>
                  <td className="ml-metal">{r.firstOfGroup ? r.metal : ""}</td>
                  <td className="ml-month">{r.month}</td>
                  <td className="ml-diff">
                    <div className={`ml-diff-val ${signCls(r.difference)}`}>
                      {fmtSigned(r.difference, 2)}
                    </div>
                    {r.far_price != null && r.near_price != null && (
                      <div className="ml-diff-calc">
                        {fmtNum(r.far_price, 2)} − {fmtNum(r.near_price, 2)}
                      </div>
                    )}
                  </td>
                  <td className={`ml-pct ${signCls(r.pct)}`}>
                    {r.pct == null ? "—" : fmtSigned(r.pct, 2) + "%"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
