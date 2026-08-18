import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// One strike's TRADEABLE difference over time (client, 18-Aug).
//
// He buys on NSE and sells on MCX, so the line is `MCX bid - NSE ask` - what he
// actually nets. Not mid against mid: a mid is the middle of a spread nobody
// fills at, and on a thin NSE strike the two spreads are most of the number.
//
// Form: one line against a zero baseline, because the sign IS the story -
// above the line the pair pays you to open it, below it costs you. One series,
// so no legend; the heading names it and the last point carries its value.
// Gaps stay gaps: a strike with no quote on one side draws nothing rather than
// dropping to zero, which would read as "no edge" instead of "no market".
const PAD = { t: 18, r: 58, b: 30, l: 56 };

const SIDES = [{ key: "ce", label: "Call" }, { key: "pe", label: "Put" }];

const slotShort = (s) => ({ "10:00": "10 AM", "12:00": "12 PM", "15:00": "3 PM" }[s] || s);
const dayShort = (iso) => {
  const [, m, d] = (iso || "").split("-");
  return d ? `${d}/${m}` : iso;
};

function Chart({ points, dec }) {
  const [hover, setHover] = useState(null);
  const wrap = useRef(null);
  const W = 900, H = 300;

  const pts = points.map((p, i) => ({ ...p, i }));
  const vals = pts.filter((p) => p.diff != null);
  if (vals.length < 2) {
    return (
      <div className="oh-note oh-slim">
        Only {vals.length} reading so far. The line needs at least two, and one is
        saved at 10:00, 12:00 and 3:00 each trading day.
      </div>
    );
  }

  // The scale always includes zero: this chart is about which side of it the
  // number sits on, so cropping the baseline out would hide the whole point.
  let lo = Math.min(0, ...vals.map((p) => p.diff));
  let hi = Math.max(0, ...vals.map((p) => p.diff));
  const padY = (hi - lo || 1) * 0.12;
  lo -= padY; hi += padY;

  const x = (i) => PAD.l + (i * (W - PAD.l - PAD.r)) / Math.max(1, pts.length - 1);
  const y = (v) => PAD.t + ((hi - v) * (H - PAD.t - PAD.b)) / (hi - lo);

  // Break the path wherever a reading is missing, so a gap reads as a gap.
  const segs = [];
  let cur = [];
  for (const p of pts) {
    if (p.diff == null) { if (cur.length) segs.push(cur); cur = []; }
    else cur.push(p);
  }
  if (cur.length) segs.push(cur);

  const last = vals[vals.length - 1];
  const ticks = [lo + padY, (lo + hi) / 2, hi - padY];

  function onMove(e) {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    const px = ((e.clientX - box.left) / box.width) * W;
    let best = null;
    for (const p of vals) {
      const d = Math.abs(x(p.i) - px);
      if (!best || d < best.d) best = { d, p };
    }
    setHover(best && best.d < 90 ? best.p : null);
  }

  return (
    <div className="nmg-wrap" ref={wrap}
      onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="nmg-svg" role="img"
        aria-label="Difference between MCX bid and NSE ask over time">
        {ticks.map((v, k) => (
          <g key={k}>
            <line className="nmg-grid" x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} />
            <text className="nmg-tick" x={PAD.l - 8} y={y(v) + 4} textAnchor="end">
              {fmtNum(v, dec)}
            </text>
          </g>
        ))}

        {/* zero is the decision line, so it is drawn heavier than the grid */}
        <line className="nmg-zero" x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} />
        <text className="nmg-tick nmg-zero-tick" x={W - PAD.r + 6} y={y(0) + 4}>0</text>

        {pts.map((p, i) =>
          (i === 0 || p.date !== pts[i - 1].date) && (
            <text key={"d" + i} className="nmg-day" x={x(i)} y={H - 8} textAnchor="middle">
              {dayShort(p.date)}
            </text>
          ))}

        {segs.map((seg, k) => (
          <path key={k} className="nmg-line" fill="none"
            d={seg.map((p, i) => `${i ? "L" : "M"}${x(p.i)},${y(p.diff)}`).join(" ")} />
        ))}

        {vals.map((p) => (
          <circle key={p.i} className={`nmg-dot ${p.diff >= 0 ? "pos" : "neg"}`}
            cx={x(p.i)} cy={y(p.diff)} r={4} />
        ))}

        {/* the latest reading is the one anyone looks for, so it is labelled */}
        <circle className={`nmg-dot nmg-last ${last.diff >= 0 ? "pos" : "neg"}`}
          cx={x(last.i)} cy={y(last.diff)} r={5.5} />
        <text className={`nmg-lastval ${last.diff >= 0 ? "pos" : "neg"}`}
          x={Math.min(x(last.i) + 10, W - PAD.r + 4)} y={y(last.diff) + 4}>
          {(last.diff >= 0 ? "+" : "−") + fmtNum(Math.abs(last.diff), dec)}
        </text>

        {hover && (
          <>
            <line className="nmg-cross" x1={x(hover.i)} x2={x(hover.i)} y1={PAD.t} y2={H - PAD.b} />
            <circle className="nmg-hoverdot" cx={x(hover.i)} cy={y(hover.diff)} r={6} />
          </>
        )}
      </svg>

      {hover && (
        <div className="nmg-tip" style={{ left: `${(x(hover.i) / W) * 100}%` }}>
          <b>{(hover.diff >= 0 ? "+" : "−") + fmtNum(Math.abs(hover.diff), dec)}</b>
          <em>{dayShort(hover.date)} · {slotShort(hover.slot)}</em>
          <span>MCX bid {fmtNum(hover.mcx_bid, dec)}</span>
          <span>NSE ask {fmtNum(hover.nse_ask, dec)}</span>
        </div>
      )}
    </div>
  );
}

export default function NseMcxGraph({ product, month, cfg }) {
  const [side, setSide] = useState("ce");
  const [strike, setStrike] = useState(null);
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  // One call lists every strike in the window, so the picker fills itself.
  useEffect(() => {
    let alive = true;
    setD(null);
    api.nseMcxGraph({ commodity: product, month, side, strike, days: 30 })
      .then((r) => {
        if (!alive) return;
        setD(r); setErr(null);
        if (strike == null && r.strikes?.length) {
          setStrike(r.strikes[Math.floor(r.strikes.length / 2)]);
        }
      })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [product, month, side, strike]);

  const strikes = d?.strikes || [];
  const dec = cfg.futDec ?? 2;
  const withValues = useMemo(
    () => (d?.points || []).filter((p) => p.diff != null), [d]);

  return (
    <div className="nmg-page">
      <div className="oh-controls nmg-controls">
        <div className="oh-group" role="tablist" aria-label="Option side">
          {SIDES.map((s) => (
            <button key={s.key} type="button" role="tab" aria-selected={side === s.key}
              className={`oh-chip ${side === s.key ? "on" : ""}`}
              onClick={() => setSide(s.key)}>{s.label}</button>
          ))}
        </div>
        <label className="nmg-pick">
          <span>Strike</span>
          <select className="oh-weeks" value={strike ?? ""}
            onChange={(e) => setStrike(Number(e.target.value))}>
            {strikes.map((s) => (
              <option key={s} value={s}>{fmtNum(s, cfg.strikeDec ?? 0)}</option>
            ))}
          </select>
        </label>
        <span className="nmg-formula">MCX bid − NSE ask</span>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {!d && !err && <div className="empty-state">Loading…</div>}

      {d && (
        <>
          <div className="nmg-head">
            <h3>
              {cfg.label} {fmtNum(strike, cfg.strikeDec ?? 0)}{" "}
              {side === "ce" ? "Call" : "Put"}
            </h3>
            <span className="nmg-sub">
              Buy on NSE at the ask, sell on MCX at the bid. Above zero the pair
              pays you to open it.
            </span>
          </div>

          <Chart points={d.points || []} dec={dec} />

          {/* the numbers behind the line, because a chart alone is not readable
              by everyone and there are few enough points to just show them */}
          {withValues.length > 0 && (
            <div className="cru-table-wrap nmg-tablewrap">
              <table className="cru-table nmg-table">
                <thead>
                  <tr>
                    <th>Date</th><th>Time</th>
                    <th>NSE ask</th><th>MCX bid</th><th>Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {withValues.slice().reverse().map((p) => (
                    <tr key={p.date + p.slot}>
                      <td>{dayShort(p.date)}</td>
                      <td>{slotShort(p.slot)}</td>
                      <td>{fmtNum(p.nse_ask, dec)}</td>
                      <td>{fmtNum(p.mcx_bid, dec)}</td>
                      <td className={p.diff >= 0 ? "nmg-pos" : "nmg-neg"}>
                        {(p.diff >= 0 ? "+" : "−") + fmtNum(Math.abs(p.diff), dec)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
