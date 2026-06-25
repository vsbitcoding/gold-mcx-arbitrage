import React, { useEffect } from "react";
import { tradeLegs } from "./SignalsPanel.jsx";

const r0 = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));
function fmtMin(mins) {
  if (mins == null || mins < 0) return "—";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60), m = mins % 60;
  if (h < 24) return m ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24), hh = h % 24;
  return hh ? `${d}d ${hh}h` : `${d}d`;
}

// Popup with full signal details (no probability — direction + target focus).
export default function SignalModal({ row, onClose }) {
  const s = row?.signal;
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!s) return null;
  const narrow = s.direction === "narrow";
  // gauge: stop (0%) ── entry tick ── target (100%); entry isn't centered (1:3 → ~75%)
  const okG = s.stop != null && s.target != null && s.stop !== s.target && s.entry != null;
  const fr = (v) => Math.max(0, Math.min(1, (v - s.stop) / (s.target - s.stop)));
  const entryFrac = okG ? fr(s.entry) : 0.5;
  const markFrac = okG && s.current != null ? fr(s.current) : entryFrac;
  const entryPos = entryFrac * 100;
  const pos = Math.max(2, Math.min(98, markFrac * 100));
  const toTgt = markFrac >= entryFrac;
  const scalePct = Math.round(toTgt
    ? (entryFrac < 1 ? (markFrac - entryFrac) / (1 - entryFrac) * 100 : 0)
    : (entryFrac > 0 ? -((entryFrac - markFrac) / entryFrac) * 100 : 0));

  return (
    <div className="sigm-overlay" onClick={onClose}>
      <div className={`sigm sigm-${s.direction}`} onClick={(e) => e.stopPropagation()}>
        <button className="sigm-x" onClick={onClose} aria-label="Close">×</button>
        <div className="sigm-pair">{row.label}</div>
        <div className="sigm-exp">{row.expiry_label}</div>
        <div className={`sigm-dir sigm-dir-${s.direction}`}>
          {narrow ? "▼ NARROW — spread likely to fall" : "▲ WIDEN — spread likely to rise"}
        </div>
        {tradeLegs(row.label, s.direction) && (() => {
          const tl = tradeLegs(row.label, s.direction);
          return (
            <div className="sigm-howto">
              <div className="sigm-howto-title">How to trade</div>
              <div className="sigm-howto-legs">
                <span className="sig-trade-buy">🟢 BUY {tl.buy}</span>
                <span className="sig-trade-sell">🔴 SELL {tl.sell}</span>
              </div>
              <div className="sigm-howto-note">
                <div><b>Enter</b> now at the <b>{narrow ? "▼ DEC (sell)" : "▲ INC (buy)"}</b> price.</div>
                <div><b>Exit</b> — watch the <b>{narrow ? "▲ INC" : "▼ DEC"}</b> column:
                  &nbsp;reaches <b style={{ color: "var(--accent)" }}>{r0(s.target)}</b> = book profit ✓ ·
                  &nbsp;reaches <b style={{ color: "var(--red)" }}>{r0(s.stop)}</b> = stop loss ✗</div>
              </div>
            </div>
          );
        })()}
        <div className="sig-nowline" style={{ justifyContent: "center", gap: 10 }}>
          <span className="sig-nowlbl">NOW</span>
          <b className="sig-nowval">{r0(s.current)}</b>
          <span className={`sig-scalepct ${toTgt ? "pos" : "neg"}`} style={{ marginLeft: 4 }}>{toTgt ? "+" : ""}{scalePct}%</span>
        </div>
        <div className="sig-gauge" style={{ margin: "4px 0 14px" }}>
          <div className="sig-gauge-track">
            <div className={`sig-gauge-fill ${toTgt ? "pos" : "neg"}`}
                 style={{ left: `${Math.min(pos, entryPos)}%`, width: `${Math.abs(pos - entryPos)}%` }} />
            <div className="sig-gauge-mid" style={{ left: `${entryPos}%` }} title="fired here" />
            <div className="sig-gauge-dot" style={{ left: `${pos}%` }} />
          </div>
          <div className="sig-gauge-ends">
            <span className="sig-end stop">✗ stop {r0(s.stop)}</span>
            <span className="sig-end tgt">target {r0(s.target)} ✓</span>
          </div>
        </div>
        <div className="sigm-meta">
          <div><span>Entry (fired at)</span><b>{r0(s.entry)}</b></div>
          <div><span>Target (profit)</span><b className="sigm-tgt">{r0(s.target)}</b></div>
          <div><span>Stop (loss)</span><b style={{ color: "var(--red)" }}>{r0(s.stop)}</b></div>
          <div><span>Risk : Reward</span><b>{s.rr || "1:1"}</b></div>
          <div><span>Fired</span><b>{s.fired_at || "—"}</b></div>
          <div><span>Running</span><b>{fmtMin(s.age_min)}</b></div>
          <div><span>Status</span><b>Open{s.expected_days ? ` · usually hits in ~${s.expected_days}d` : ""}</b></div>
        </div>
      </div>
    </div>
  );
}
