import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

const LS_KEY = "arbi_calc_v1";

function loadConfig() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
function saveConfig(c) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(c)); } catch {}
}

const DEFAULTS = {
  gold: {
    multiplier: 120000,
    manual: 0,
    divisor: 103,
    overrideEtfPrice: false,
    manualEtfPrice: "",
  },
  silver: {
    multiplier: 31000,
    manual: 0,
    divisor: 30.9,
    overrideEtfPrice: false,
    manualEtfPrice: "",
  },
};

function MetalCard({
  metal,            // "gold" | "silver"
  etfSymbol,        // "GOLDBEES" | "SILVERBEES"
  mcxLabel,         // "Full Gold MCX" | "Full Silver MCX"
  etfLive,
  mcxLive,
  mcxExpiry,
  mcxSymbol,
  cfg,
  onCfgChange,
}) {
  const etfPrice = cfg.overrideEtfPrice && cfg.manualEtfPrice !== ""
    ? Number(cfg.manualEtfPrice)
    : etfLive ?? null;

  const mult = Number(cfg.multiplier) || 0;
  const manual = Number(cfg.manual) || 0;
  const div = Number(cfg.divisor) || 1;

  const value1 = etfPrice !== null ? etfPrice * mult : null;
  const value2 = value1 !== null ? value1 + manual : null;
  const finalVal = value2 !== null && div !== 0 ? value2 / div : null;
  // diff = Calculator − MCX (per client spec). Positive = synthetic above MCX.
  const diff = finalVal !== null && mcxLive !== null && mcxLive !== undefined
    ? finalVal - mcxLive
    : null;

  function patch(field, value) {
    onCfgChange({ ...cfg, [field]: value });
  }

  const metalCls = metal === "silver" ? "silver" : "";
  return (
    <div className="calc-card">
      <div className="calc-head">
        <div className="calc-title">
          <span className={`calc-metal ${metalCls}`}>{metal.toUpperCase()}</span>
          <span className="calc-sub">{etfSymbol} → {mcxLabel}</span>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-xs"
          onClick={() => patch("overrideEtfPrice", !cfg.overrideEtfPrice)}
          title={cfg.overrideEtfPrice ? "Switch back to live price" : "Type your own ETF price"}
        >
          {cfg.overrideEtfPrice ? "↻ Use live" : "✎ Manual price"}
        </button>
      </div>

      <div className="calc-rows">
        <div className="calc-row">
          <label className="calc-label">{etfSymbol} Price</label>
          {cfg.overrideEtfPrice ? (
            <input
              type="number"
              step="0.01"
              className="calc-input"
              value={cfg.manualEtfPrice}
              onChange={(e) => patch("manualEtfPrice", e.target.value)}
              placeholder="Enter ETF price"
              autoFocus
            />
          ) : (
            <div className={`calc-live ${etfLive === null || etfLive === undefined ? "stale" : ""}`}>
              {etfLive === null || etfLive === undefined
                ? "waiting for live tick…"
                : <>₹ {fmtNum(etfLive, 2)} <span className="live-dot" title="Live"></span></>}
            </div>
          )}
        </div>

        <div className="calc-row two-col">
          <div>
            <label className="calc-label">Multiplier</label>
            <input
              type="number"
              step="1"
              className="calc-input"
              value={cfg.multiplier}
              onChange={(e) => patch("multiplier", e.target.value)}
            />
          </div>
          <div>
            <label className="calc-label">Manual Value</label>
            <input
              type="number"
              step="0.01"
              className="calc-input"
              value={cfg.manual}
              onChange={(e) => patch("manual", e.target.value)}
              placeholder="0"
            />
          </div>
        </div>

        <div className="calc-row">
          <label className="calc-label">Divisor</label>
          <input
            type="number"
            step="0.01"
            className="calc-input"
            value={cfg.divisor}
            onChange={(e) => patch("divisor", e.target.value)}
          />
        </div>
      </div>

      <div className="calc-formula">
        <code>(price × {fmtNum(mult, 0)} + {fmtNum(manual, 2)}) ÷ {fmtNum(div, 2)}</code>
      </div>

      <div className="calc-results">
        <div className="calc-result-row">
          <span className="calc-result-label">Calculated Value</span>
          <span className="calc-result-value">
            {finalVal === null ? "—" : `₹ ${fmtNum(finalVal, 2)}`}
          </span>
        </div>
        <div className="calc-result-row">
          <span className="calc-result-label">
            {mcxLabel} {mcxSymbol ? `(${mcxSymbol})` : ""}
            {mcxExpiry && (
              <span className="calc-mcx-expiry">
                {" · "}{new Date(mcxExpiry).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "2-digit" })}
              </span>
            )}
          </span>
          <span className="calc-result-value">
            {mcxLive === null || mcxLive === undefined ? "—" : `₹ ${fmtNum(mcxLive, 2)}`}
          </span>
        </div>
        <div className={`calc-diff ${diff === null ? "" : diff >= 0 ? "pos" : "neg"}`}>
          <span className="calc-result-label">Difference</span>
          <span className="calc-result-value">
            {diff === null
              ? "—"
              : `${diff >= 0 ? "▲ +" : "▼ "}${fmtNum(diff, 2)}`}
          </span>
        </div>
        {diff !== null && (
          <div className="calc-hint">
            {diff > 0
              ? "Calculator higher → opportunity to sell ETF, buy MCX"
              : diff < 0
              ? "Calculator lower → opportunity to buy ETF, sell MCX"
              : "Aligned — no edge right now"}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Calculator() {
  const [data, setData] = useState({ gold: null, silver: null });
  const [cfg, setCfg] = useState(() => {
    const stored = loadConfig() || {};
    return {
      gold: { ...DEFAULTS.gold, ...(stored.gold || {}) },
      silver: { ...DEFAULTS.silver, ...(stored.silver || {}) },
    };
  });

  useEffect(() => { saveConfig(cfg); }, [cfg]);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await api.calcQuotes();
        if (alive) setData(r);
      } catch {}
    }
    load();
    const t = setInterval(load, 1500);
    return () => { alive = false; clearInterval(t); };
  }, []);

  return (
    <div className="calc-page">
      <div className="calc-page-head">
        <h2>ETF vs MCX</h2>
        <p className="calc-page-sub">
          Live ETF price → formula → compare with MCX. Multiplier, manual value, and divisor are editable;
          your settings auto-save in this browser.
        </p>
      </div>

      <div className="calc-grid">
        <MetalCard
          metal="gold"
          etfSymbol="GOLDBEES"
          mcxLabel="MCX Full Gold"
          etfLive={data.gold?.etf?.ltp ?? null}
          mcxLive={data.gold?.mcx_full?.ltp ?? null}
          mcxExpiry={data.gold?.mcx_full?.expiry ?? null}
          mcxSymbol={data.gold?.mcx_full?.trading_symbol ?? null}
          cfg={cfg.gold}
          onCfgChange={(g) => setCfg((c) => ({ ...c, gold: g }))}
        />
        <MetalCard
          metal="silver"
          etfSymbol="SILVERBEES"
          mcxLabel="MCX Full Silver"
          etfLive={data.silver?.etf?.ltp ?? null}
          mcxLive={data.silver?.mcx_full?.ltp ?? null}
          mcxExpiry={data.silver?.mcx_full?.expiry ?? null}
          mcxSymbol={data.silver?.mcx_full?.trading_symbol ?? null}
          cfg={cfg.silver}
          onCfgChange={(s) => setCfg((c) => ({ ...c, silver: s }))}
        />
      </div>
    </div>
  );
}
