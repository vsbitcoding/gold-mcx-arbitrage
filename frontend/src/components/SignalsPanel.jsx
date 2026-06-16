import React from "react";

// Lists the currently-active mean-reversion signals (cross pairs). Watch-only.
export default function SignalsPanel({ signals }) {
  if (!signals.length) {
    return (
      <div className="empty-state" style={{ padding: "28px 16px", lineHeight: 1.5 }}>
        No active signals right now.<br />
        A signal fires automatically when a cross-spread reaches an extreme (±1.5σ of its 20-day average).
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
            <div className="sig-head">
              <span className="sig-pair">{r.label}</span>
              <span className="sig-exp">{r.expiry_label}</span>
              <span className={`sig-dir sig-dir-${s.direction}`}>
                {narrow ? "▼ NARROW" : "▲ WIDEN"}
              </span>
            </div>
            <div className="sig-body">
              <span className="sig-leg">now <b>{s.current}</b></span>
              <span className="sig-arrow">→</span>
              <span className="sig-leg sig-target">target <b>{s.target}</b></span>
              <span className="sig-meta">{s.z >= 0 ? "+" : ""}{s.z}σ</span>
              <span className="sig-meta sig-age">{s.age_min}m ago</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
