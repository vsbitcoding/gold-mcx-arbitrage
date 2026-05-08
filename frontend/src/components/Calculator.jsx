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
};

function GoldCard({ etfLive, mcxLive, mcxExpiry, mcxSymbol, cfg, onCfgChange }) {
  const etfPrice = cfg.overrideEtfPrice && cfg.manualEtfPrice !== ""
    ? Number(cfg.manualEtfPrice)
    : etfLive ?? null;

  const mult = Number(cfg.multiplier) || 0;
  const manual = Number(cfg.manual) || 0;
  const div = Number(cfg.divisor) || 1;

  const value1 = etfPrice !== null ? etfPrice * mult : null;
  const value2 = value1 !== null ? value1 + manual : null;
  const finalVal = value2 !== null && div !== 0 ? value2 / div : null;
  // diff = MCX − Calculator (per client spec). Positive = MCX above synthetic.
  const diff = finalVal !== null && mcxLive !== null && mcxLive !== undefined
    ? mcxLive - finalVal
    : null;

  function patch(field, value) {
    onCfgChange({ ...cfg, [field]: value });
  }

  return (
    <div className="calc-card">
      <div className="calc-head">
        <div className="calc-title">
          <span className="calc-metal">GOLD</span>
          <span className="calc-sub">GOLDBEES → Full Gold MCX</span>
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
          <label className="calc-label">GOLDBEES Price</label>
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
            MCX Full Gold {mcxSymbol ? `(${mcxSymbol})` : ""}
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
              ? "MCX higher → opportunity to buy ETF, sell MCX"
              : diff < 0
              ? "MCX lower → opportunity to sell ETF, buy MCX"
              : "Aligned — no edge right now"}
          </div>
        )}
      </div>
    </div>
  );
}

function SilverCard() {
  return (
    <div className="calc-card calc-card-placeholder">
      <div className="calc-head">
        <div className="calc-title">
          <span className="calc-metal silver">SILVER</span>
          <span className="calc-sub">SILVERBEES → MCX Silver</span>
        </div>
        <span className="calc-pending-chip">⌛ Awaiting client formula</span>
      </div>
      <div className="calc-placeholder-body">
        Silver calculator will appear here once the client shares the
        <strong> multiplier</strong>, <strong>divisor</strong> and target
        <strong> MCX Silver contract</strong>. The structure mirrors the Gold card.
      </div>
    </div>
  );
}

export default function Calculator() {
  const [data, setData] = useState({ gold: null, silver: null });
  const [cfg, setCfg] = useState(() => ({ ...DEFAULTS, ...(loadConfig() || {}) }));

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

  const goldEtfLive = data.gold?.etf?.ltp ?? null;
  const goldMcxLive = data.gold?.mcx_full?.ltp ?? null;
  const goldMcxExpiry = data.gold?.mcx_full?.expiry ?? null;
  const goldMcxSymbol = data.gold?.mcx_full?.trading_symbol ?? null;

  return (
    <div className="calc-page">
      <div className="calc-page-head">
        <h2>Spot vs MCX Calculator</h2>
        <p className="calc-page-sub">
          Live ETF price → formula → compare with MCX. Multiplier, manual value, and divisor are editable;
          your settings auto-save in this browser.
        </p>
      </div>

      <div className="calc-grid">
        <GoldCard
          etfLive={goldEtfLive}
          mcxLive={goldMcxLive}
          mcxExpiry={goldMcxExpiry}
          mcxSymbol={goldMcxSymbol}
          cfg={cfg.gold}
          onCfgChange={(g) => setCfg((c) => ({ ...c, gold: g }))}
        />
        <SilverCard />
      </div>
    </div>
  );
}
