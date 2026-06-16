import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

const r0 = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));
const pct = (v) => (v == null ? "—" : `${v}%`);

// Fire-once signals (frozen entry/target/probability) + accuracy track record.
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
          <div className="sig-acc" title="Verified track record of resolved signals">
            <b className="sig-acc-pct">{pct(acc.accuracy_pct)}</b> accurate
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
                  <div className="sig-r1">
                    <span className="sig-pair" title={r.label}>{r.label}</span>
                    <span className="sig-prob" title="Historical chance to reach target">{pct(s.probability)}</span>
                    <span className={`sig-dir sig-dir-${s.direction}`}>{narrow ? "▼ NARROW" : "▲ WIDEN"}</span>
                  </div>
                  <div className="sig-r2">{r.expiry_label}</div>
                  <div className="sig-r3">
                    <span className="sig-kv">now <b>{r0(s.current)}</b></span>
                    <span className="sig-arrow">→</span>
                    <span className="sig-kv">target <b className="sig-tgt">{r0(s.target)}</b></span>
                  </div>
                  <div className="sig-prog"><div className="sig-prog-bar" style={{ width: `${s.progress_pct || 0}%` }} /></div>
                  <div className="sig-r4">
                    <span>{s.progress_pct || 0}% to target</span>
                    <span className="sig-meta">{s.age_min}m{s.expected_days ? ` · ~${s.expected_days}d exp` : ""}</span>
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
          <div className="sig-hist">
            {history.map((h) => (
              <div className={`sig-hrow out-${h.outcome}`} key={h.id}>
                <span className="sig-hpair">{h.label}</span>
                <span className="sig-hexp">{h.expiry_label}</span>
                <span className={`sig-dir sig-dir-${h.direction}`}>{h.direction === "narrow" ? "▼" : "▲"}</span>
                <span className="sig-hpx">{r0(h.entry)} → {r0(h.exit)}</span>
                <span className="sig-hprob">{pct(h.probability)}</span>
                <span className={`sig-out sig-out-${h.outcome}`}>{h.outcome === "right" ? "✓ RIGHT" : "✗ WRONG"}</span>
                <span className="sig-hdays">{h.days_held != null ? `${h.days_held}d` : ""}</span>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
