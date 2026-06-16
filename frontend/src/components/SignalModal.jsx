import React, { useEffect } from "react";

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

  return (
    <div className="sigm-overlay" onClick={onClose}>
      <div className={`sigm sigm-${s.direction}`} onClick={(e) => e.stopPropagation()}>
        <button className="sigm-x" onClick={onClose} aria-label="Close">×</button>
        <div className="sigm-pair">{row.label}</div>
        <div className="sigm-exp">{row.expiry_label}</div>
        <div className={`sigm-dir sigm-dir-${s.direction}`}>
          {narrow ? "▼ NARROW — spread likely to fall" : "▲ WIDEN — spread likely to rise"}
        </div>
        <div className="sigm-flow">
          <div><span className="sigm-lbl">now</span><b>{r0(s.current)}</b></div>
          <span className="sigm-arrow">{narrow ? "↓" : "↑"}</span>
          <div><span className="sigm-lbl">target</span><b className="sigm-tgt">{r0(s.target)}</b></div>
        </div>
        <div className="sigm-prog"><div className="sigm-prog-bar" style={{ width: `${s.progress_pct || 0}%` }} /></div>
        <div className="sigm-meta">
          <div><span>Progress</span><b>{s.progress_pct || 0}% to target</b></div>
          <div><span>Fired</span><b>{s.fired_at || "—"}</b></div>
          <div><span>Running</span><b>{fmtMin(s.age_min)}</b></div>
          <div><span>Status</span><b>Open{s.expected_days ? ` · ~${s.expected_days}d expected` : ""}</b></div>
        </div>
      </div>
    </div>
  );
}
