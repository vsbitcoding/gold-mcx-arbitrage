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

// Real-life metal colour theme per family (minis share their parent's colour).
function metalColorKey(symbol) {
  const s = (symbol || "").toUpperCase();
  if (s.startsWith("COPPER")) return "copper";
  if (s.startsWith("ALUMIN")) return "aluminium";  // ALUMINIUM + ALUMINI
  if (s.startsWith("ZINC")) return "zinc";          // ZINC + ZINCMINI
  if (s.startsWith("NICKEL")) return "nickel";
  if (s.startsWith("LEAD")) return "lead";          // LEAD + LEADMINI
  return "default";
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

  // Group the flat rows into one card per metal (preserves API order).
  const cards = useMemo(() => {
    const rs = data?.rows || [];
    const byMetal = new Map();
    for (const r of rs) {
      if (!byMetal.has(r.metal)) byMetal.set(r.metal, []);
      byMetal.get(r.metal).push(r);
    }
    return Array.from(byMetal, ([metal, rows]) => ({
      metal, rows, color: metalColorKey(rows[0] && rows[0].symbol),
    }));
  }, [data]);

  return (
    <div className={`metal-page${embedded ? " metal-embedded" : ""}`}>
      {!embedded && (
        <div className="metal-head"><h2>Metal — Calendar Spreads</h2></div>
      )}

      {err && <div className="settings-banner danger">⚠ {err}</div>}

      {!cards.length ? (
        <div className="empty-state">Loading metal data…</div>
      ) : (
        <div className="metal-cards">
          {cards.map((c) => (
            <div className={`metal-card mc-${c.color}`} key={c.metal}>
              <div className="metal-card-head">{c.metal}</div>
              <div className="metal-card-body">
                {c.rows.map((r, i) => (
                  <div className="metal-row" key={i}>
                    <div className="mr-month">{r.month}</div>
                    <div className="mr-diff">
                      <span className={`mr-diff-val ${signCls(r.difference)}`}>
                        {fmtSigned(r.difference, 2)}
                      </span>
                      {r.far_price != null && r.near_price != null && (
                        <span className="mr-calc">
                          {fmtNum(r.far_price, 2)}−{fmtNum(r.near_price, 2)}
                        </span>
                      )}
                    </div>
                    <div className={`mr-pct ${signCls(r.pct)}`}>
                      {r.pct == null ? "—" : fmtSigned(r.pct, 2) + "%"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
