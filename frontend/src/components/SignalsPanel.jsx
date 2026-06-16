import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

const r0 = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));
const dshort = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  } catch { return "—"; }
};

// Fire-once signals (direction + target) + accuracy track record. No % shown.
export default function SignalsPanel({ signals }) {
  const [view, setView] = useState("open");
  const [history, setHistory] = useState([]);
  const [acc, setAcc] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.signalsAccuracy().then((a) => alive && setAcc(a)).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    if (view !== "history") return;
    let alive = true;
    const load = () => api.signalsHistory(100).then((d) => alive && setHistory(d.history || [])).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [view]);

  return (
    <div className="sig-wrap">
      <div className="sig-bar">
        <div className="sig-toggle">
          <button className={view === "open" ? "active" : ""} onClick={() => setView("open")}>
            Open <span className="count">{signals.length}</span>
          </button>
          <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}>
            History
          </button>
        </div>
        {acc && acc.total > 0 && (
          <div className="sig-acc" title="Track record of resolved signals">
            <b className="sig-acc-pct">{acc.accuracy_pct}%</b> accurate
            <span className="sig-acc-sub">{acc.right}/{acc.total} right · {acc.open} open</span>
          </div>
        )}
      </div>

      {view === "open" ? (
        signals.length === 0 ? (
          <div className="empty-state" style={{ padding: "24px 16px", lineHeight: 1.6 }}>
            No open signals right now.<br />
            A signal fires automatically when a cross-spread holds at an extreme (±1.5σ).
          </div>
        ) : (
          <div className="signal-list">
            {signals.map((r) => {
              const s = r.signal;
              const narrow = s.direction === "narrow";
              return (
                <div className={`signal-card sig-${s.direction}`} key={r.name}>
                  <div className="sig-top">
                    <span className="sig-pair">{r.label}</span>
                    <span className={`sig-dir sig-dir-${s.direction}`}>{narrow ? "▼ NARROW" : "▲ WIDEN"}</span>
                  </div>
                  <div className="sig-exp2">{r.expiry_label}</div>
                  <div className="sig-flow big">
                    <span><span className="sig-lbl">now</span><b>{r0(s.current)}</b></span>
                    <span className="sig-flow-arrow">{narrow ? "↓" : "↑"}</span>
                    <span><span className="sig-lbl">target</span><b className="sig-tgt">{r0(s.target)}</b></span>
                  </div>
                  <div className="sig-prog"><div className="sig-prog-bar" style={{ width: `${s.progress_pct || 0}%` }} /></div>
                  <div className="sig-foot">
                    <span><b>{s.progress_pct || 0}%</b> to target</span>
                    <span className="sig-meta">fired {s.fired_at || "—"}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : (
        history.length === 0 ? (
          <div className="empty-state" style={{ padding: "24px 16px" }}>No resolved signals yet — they'll appear here marked right / wrong.</div>
        ) : (
          <div className="signal-list">
            {history.map((h) => {
              const narrow = h.direction === "narrow";
              return (
                <div className={`signal-card hist-${h.outcome}`} key={h.id}>
                  <div className="sig-top">
                    <span className="sig-pair">{h.label}</span>
                    <span className={`sig-out sig-out-${h.outcome}`}>{h.outcome === "right" ? "✓ RIGHT" : "✗ WRONG"}</span>
                  </div>
                  <div className="sig-exp2">{h.expiry_label} · {narrow ? "▼ NARROW" : "▲ WIDEN"}</div>
                  <div className="sig-flow">
                    <span><span className="sig-lbl">entry</span><b>{r0(h.entry)}</b></span>
                    <span className="sig-flow-arrow">→</span>
                    <span><span className="sig-lbl">exit</span><b>{r0(h.exit)}</b></span>
                  </div>
                  <div className="sig-foot">
                    <span>fired {dshort(h.fired_at)} → closed {dshort(h.resolved_at)}</span>
                    <span className="sig-meta">{h.days_held != null ? `${h.days_held}d` : ""}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}
