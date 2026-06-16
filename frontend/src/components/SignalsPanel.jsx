import React from "react";

const r0 = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));

// Lists the currently-active mean-reversion signals (cross pairs). Watch-only.
export default function SignalsPanel({ signals }) {
  if (!signals.length) {
    return (
      <div className="empty-state" style={{ padding: "28px 16px", lineHeight: 1.6 }}>
        No active signals right now.<br />
        A signal fires automatically when a cross-spread holds at an extreme (±1.5σ of its 20-day average).
      </div>
    );
  }
  return (
    <div className="signal-list">
      {signals.map((r) => {
        const s = r.signal;
        const narrow = s.direction === "narrow";
        return (
          <div className={`signal-card sig-${s.direction}`} key={r.name}>
            <div className="sig-r1">
              <span className="sig-pair" title={r.label}>{r.label}</span>
              <span className={`sig-dir sig-dir-${s.direction}`}>{narrow ? "▼ NARROW" : "▲ WIDEN"}</span>
            </div>
            <div className="sig-r2">{r.expiry_label}</div>
            <div className="sig-r3">
              <span className="sig-kv">now <b>{r0(s.current)}</b></span>
              <span className="sig-arrow">→</span>
              <span className="sig-kv">target <b className="sig-tgt">{r0(s.target)}</b></span>
              <span className="sig-meta">{s.z >= 0 ? "+" : ""}{s.z}σ · {s.age_min}m</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
