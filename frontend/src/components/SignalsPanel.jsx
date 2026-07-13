import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

const r0 = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-IN"));
const dshort = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  } catch { return "—"; }
};
// date + time in IST. Server timestamps are naive UTC → treat as UTC, show Asia/Kolkata.
const dtIST = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(/[Z+]/.test(iso) ? iso : iso + "Z");
    return d.toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
      hour: "numeric", minute: "2-digit", hour12: true,
    });
  } catch { return "—"; }
};
// human-readable duration from minutes, e.g. 75 → "1h 15m", 1500 → "1d 1h"
function fmtMin(mins) {
  if (mins == null || mins < 0) return "—";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60), m = mins % 60;
  if (h < 24) return m ? `${h}h ${m}m` : `${h}h`;
  const d = Math.floor(h / 24), hh = h % 24;
  return hh ? `${d}d ${hh}h` : `${d}d`;
}
function fmtDur(fromISO, toISO) {
  if (!fromISO || !toISO) return "—";
  const ms = new Date(toISO) - new Date(fromISO);
  return ms >= 0 ? fmtMin(Math.floor(ms / 60000)) : "—";
}

// Client's signal-study sequence (order the open signals are listed in).
const SIGNAL_ORDER = [
  "GUINEA / TEN", "GUINEA / MINI", "PETAL / GUINEA", "PETAL / TEN", "PETAL / MINI",
  "SILVER MIC / SILVER MINI", "MINI / GOLD", "SILVER MINI / SILVER", "TEN / MINI",
  "SILVER 100 / SILVER MIC", "SILVER 100 / SILVER MINI",
];
function sigRank(label) {
  const i = SIGNAL_ORDER.indexOf(String(label || "").toUpperCase().trim());
  return i === -1 ? 999 : i;
}

// Exact buy/sell legs from "BIG / SMALL" + direction.
// WIDEN = buy the spread → BUY big, SELL small ;  NARROW = sell the spread → SELL big, BUY small.
export function tradeLegs(label, direction) {
  const p = String(label || "").split("/").map((x) => x.trim());
  if (p.length !== 2 || !p[0] || !p[1]) return null;
  const [big, small] = p;
  return direction === "widen" ? { buy: big, sell: small } : { buy: small, sell: big };
}

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
            <span className="sig-acc-sub">{acc.right} hit · {acc.wrong} stopped{acc.timeout ? ` · ${acc.timeout} timed-out` : ""} · {acc.open} open</span>
          </div>
        )}
      </div>

      {view === "open" ? (
        signals.length === 0 ? (
          <div className="empty-state" style={{ padding: "24px 16px", lineHeight: 1.6 }}>
            No open signals right now.<br />
            A signal fires automatically when a cross-spread holds at an extreme
            (±1.5σ on the 4H % band) <b>and</b> the warehouse-stock direction confirms it.
          </div>
        ) : (
          <div className="signal-list">
            {[...signals].sort((a, b) => sigRank(a.label) - sigRank(b.label)).map((r) => {
              const s = r.signal;
              const narrow = s.direction === "narrow";
              const tl = tradeLegs(r.label, s.direction);
              // gauge: stop (0%) ── entry tick ── target (100%); entry isn't centered (1:3 → ~75%)
              const okG = s.stop != null && s.target != null && s.stop !== s.target && s.entry != null;
              const fr = (v) => Math.max(0, Math.min(1, (v - s.stop) / (s.target - s.stop)));
              const entryFrac = okG ? fr(s.entry) : 0.5;
              const markFrac = okG && s.current != null ? fr(s.current) : entryFrac;
              const entryPos = entryFrac * 100;
              const pos = Math.max(2, Math.min(98, markFrac * 100));   // NOW marker
              const toTgt = markFrac >= entryFrac;                     // moving toward target?
              const scalePct = Math.round(toTgt
                ? (entryFrac < 1 ? (markFrac - entryFrac) / (1 - entryFrac) * 100 : 0)
                : (entryFrac > 0 ? -((entryFrac - markFrac) / entryFrac) * 100 : 0));  // 0 entry · +100 target · −100 stop
              return (
                <div className={`signal-card sig-${s.direction}`} key={r.name}>
                  <div className="sig-top">
                    <span className="sig-pair">{r.label}</span>
                    <span className={`sig-dir sig-dir-${s.direction}`}>{narrow ? "▼ NARROW" : "▲ WIDEN"}</span>
                  </div>
                  <div className="sig-exp2">{r.expiry_label}</div>
                  {tl && (
                    <div className="sig-trade">
                      <span className="sig-trade-buy">BUY {tl.buy}</span>
                      <span className="sig-trade-sell">SELL {tl.sell}</span>
                    </div>
                  )}
                  <div className="sig-nowline">
                    <span className="sig-nowlbl">NOW</span>
                    <b className="sig-nowval">{r0(s.current)}</b>
                    <span className={`sig-scalepct ${toTgt ? "pos" : "neg"}`}>{toTgt ? "+" : ""}{scalePct}%</span>
                  </div>
                  <div className="sig-gauge">
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
                  <div className="sig-foot sig-hist-foot">
                    <span className="sig-fire">⚡ fired @ <b>{r0(s.entry)}</b><br />🕐 {s.fired_at}</span>
                    <span className="sig-meta">running {fmtMin(s.age_min)}</span>
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
              const oLabel = h.outcome === "right" ? "✓ RIGHT" : h.outcome === "wrong" ? "✗ STOPPED" : "⏱ TIMED-OUT";
              return (
                <div className={`signal-card hist-${h.outcome}`} key={h.id}>
                  <div className="sig-top">
                    <span className="sig-pair">{h.label}</span>
                    <span className={`sig-out sig-out-${h.outcome}`}>{oLabel}</span>
                  </div>
                  <div className="sig-exp2">{h.expiry_label} · {narrow ? "▼ NARROW" : "▲ WIDEN"}</div>
                  <div className="sig-flow">
                    <span><span className="sig-lbl">entry</span><b>{r0(h.entry)}</b></span>
                    <span className="sig-flow-arrow">→</span>
                    <span><span className="sig-lbl">exit</span><b>{r0(h.exit)}</b></span>
                  </div>
                  <div className="sig-foot sig-hist-foot">
                    <span>⚡ fired {dtIST(h.fired_at)}<br />🏁 closed {dtIST(h.resolved_at)}</span>
                    <span className="sig-meta">ran {fmtDur(h.fired_at, h.resolved_at)}</span>
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
