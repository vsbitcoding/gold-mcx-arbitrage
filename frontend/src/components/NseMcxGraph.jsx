import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// One strike's TRADEABLE difference over time (client, 18-Aug).
//
// He buys on NSE and sells on MCX, so the line is `MCX bid - NSE ask` - what he
// actually nets. Not mid against mid: a mid is the middle of a spread nobody
// fills at, and on a thin NSE strike the two spreads are most of the number.
//
// Form: one line against a zero baseline, because the sign IS the story - above
// it the pair pays you to open, below it costs you. One series, so no legend;
// the heading names it and the last point carries its value.
const PAD = { t: 22, r: 66, b: 34, l: 66 };
const H = 320;
const SIDES = [{ key: "ce", label: "Call" }, { key: "pe", label: "Put" }];

const slotShort = (s) => ({ "10:00": "10 AM", "12:00": "12 PM", "15:00": "3 PM" }[s] || s);
const dayShort = (iso) => {
  const [, m, d] = (iso || "").split("-");
  return d ? `${d}/${m}` : iso;
};
const sign = (v, d) => (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d);

// Axis ticks a person can read: 0, 25, 50 - never 39.4 or -113.9. Steps climb
// through 1/2/2.5/5 x a power of ten, which is what makes the labels land on
// numbers the eye already knows.
function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || 1;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  // Bracket the data rather than sit inside it, so the top and bottom
  // gridlines are above and below every point and the plot fills its box.
  const out = [];
  const first = Math.floor(lo / step) * step;
  const stop = Math.ceil(hi / step) * step;
  for (let v = first; v <= stop + 1e-9; v += step) {
    out.push(Math.abs(v) < 1e-9 ? 0 : Math.round(v * 1e6) / 1e6);
  }
  return out;
}

function Chart({ points, dec }) {
  const [hover, setHover] = useState(null);
  const [w, setW] = useState(900);
  const wrap = useRef(null);

  // The SVG is measured, not letterboxed. A fixed viewBox scaled with
  // preserveAspectRatio leaves the chart floating in the middle of a wide
  // screen with dead space either side, which is what it was doing.
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.max(360, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pts = points.map((p, i) => ({ ...p, i }));
  const vals = pts.filter((p) => p.diff != null);
  if (vals.length < 2) {
    return (
      <div className="oh-note oh-slim">
        Only {vals.length} reading so far. The line needs two, and one is saved at
        10:00, 12:00 and 3:00 each trading day.
      </div>
    );
  }

  // The scale always includes zero: this chart is about which side of it a
  // number sits on, so cropping the baseline would hide the whole point.
  const ys = vals.map((p) => p.diff);
  let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const pad = (hi - lo || 1) * 0.14;
  const ticks = niceTicks(lo - pad, hi + pad);
  lo = Math.min(lo - pad, ticks[0]);
  hi = Math.max(hi + pad, ticks[ticks.length - 1]);

  const x = (i) => PAD.l + (i * (w - PAD.l - PAD.r)) / Math.max(1, pts.length - 1);
  const y = (v) => PAD.t + ((hi - v) * (H - PAD.t - PAD.b)) / (hi - lo);

  // Break the path where a reading is missing, so a gap reads as a gap.
  const segs = [];
  let cur = [];
  for (const p of pts) {
    if (p.diff == null) { if (cur.length > 1) segs.push(cur); cur = []; }
    else cur.push(p);
  }
  if (cur.length > 1) segs.push(cur);

  const last = vals[vals.length - 1];

  function onMove(e) {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    const px = e.clientX - box.left;
    let best = null;
    for (const p of vals) {
      const d = Math.abs(x(p.i) - px);
      if (!best || d < best.d) best = { d, p };
    }
    setHover(best && best.d < 80 ? best.p : null);
  }

  const tipLeft = hover ? Math.min(Math.max(x(hover.i), 96), w - 96) : 0;
  const tipAbove = hover ? y(hover.diff) > H / 2 : true;

  return (
    <div className="nmg-wrap" ref={wrap}
      onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${w} ${H}`} width="100%" height={H} className="nmg-svg" role="img"
        aria-label="MCX bid minus NSE ask, over time">
        {ticks.map((v) => (
          <g key={v}>
            <line className={v === 0 ? "nmg-zero" : "nmg-grid"}
              x1={PAD.l} x2={w - PAD.r} y1={y(v)} y2={y(v)} />
            <text className={`nmg-tick ${v === 0 ? "nmg-zero-tick" : ""}`}
              x={PAD.l - 10} y={y(v) + 4} textAnchor="end">{fmtNum(v, 0)}</text>
          </g>
        ))}

        {pts.map((p, i) =>
          (i === 0 || p.date !== pts[i - 1].date) && (
            <text key={"d" + i} className="nmg-day" x={x(i)} y={H - 10} textAnchor="middle">
              {dayShort(p.date)}
            </text>
          ))}

        {segs.map((seg, k) => (
          <path key={k} className="nmg-line" fill="none"
            d={seg.map((p, i) => `${i ? "L" : "M"}${x(p.i)},${y(p.diff)}`).join(" ")} />
        ))}

        {vals.map((p) => (
          <circle key={p.i}
            className={`nmg-dot ${p.diff >= 0 ? "pos" : "neg"} ${p.wide ? "wide" : ""}`}
            cx={x(p.i)} cy={y(p.diff)} r={p.wide ? 5 : 4}>
            {p.wide && <title>One side was quoted very wide here, so treat this reading with caution.</title>}
          </circle>
        ))}

        {/* the latest reading is what anyone looks for first, so it is labelled */}
        <circle className={`nmg-dot nmg-last ${last.diff >= 0 ? "pos" : "neg"}`}
          cx={x(last.i)} cy={y(last.diff)} r={5.5} />
        <text className={`nmg-lastval ${last.diff >= 0 ? "pos" : "neg"}`}
          x={x(last.i) + 12} y={y(last.diff) + 4}>{sign(last.diff, dec)}</text>

        {hover && (
          <>
            <line className="nmg-cross" x1={x(hover.i)} x2={x(hover.i)} y1={PAD.t} y2={H - PAD.b} />
            <circle className="nmg-hoverdot" cx={x(hover.i)} cy={y(hover.diff)} r={7} />
          </>
        )}
      </svg>

      {hover && (
        <div className={`nmg-tip ${tipAbove ? "above" : "below"}`}
          style={{ left: tipLeft, top: tipAbove ? y(hover.diff) - 12 : y(hover.diff) + 12 }}>
          <b className={hover.diff >= 0 ? "nmg-pos" : "nmg-neg"}>{sign(hover.diff, dec)}</b>
          <em>{dayShort(hover.date)} · {slotShort(hover.slot)}</em>
          <span>NSE ask <i>{fmtNum(hover.nse_ask, dec)}</i></span>
          <span>MCX bid <i>{fmtNum(hover.mcx_bid, dec)}</i></span>
          {hover.wide && <u>one side quoted very wide</u>}
        </div>
      )}
    </div>
  );
}

export default function NseMcxGraph({ product, month, cfg }) {
  const [side, setSide] = useState("ce");
  const [strike, setStrike] = useState(null);
  const [strikes, setStrikes] = useState([]);
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // The strike list is fetched ONCE per commodity/month. Folding it into the
  // series call meant every switch fired twice - once without a strike to learn
  // them, once with - and the chart blanked between the two.
  useEffect(() => {
    let alive = true;
    api.nseMcxGraph({ commodity: product, month, days: 30 })
      .then((r) => {
        if (!alive) return;
        const list = r.strikes || [];
        setStrikes(list);
        setStrike((cur) => (cur != null && list.includes(cur)
          ? cur : list[Math.floor(list.length / 2)] ?? null));
      })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [product, month]);

  // The old data stays on screen while the new arrives, dimmed. Blanking it
  // made every strike change flash the whole page.
  useEffect(() => {
    if (strike == null) return undefined;
    let alive = true;
    setBusy(true);
    api.nseMcxGraph({ commodity: product, month, side, strike, days: 30 })
      .then((r) => { if (alive) { setD(r); setErr(null); } })
      .catch((e) => { if (alive) setErr(e.message); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [product, month, side, strike]);

  const dec = cfg.futDec ?? 2;
  const rows = useMemo(
    () => (d?.points || []).filter((p) => p.diff != null).reverse(), [d]);
  const stats = useMemo(() => {
    const v = rows.filter((p) => !p.wide).map((p) => p.diff);
    if (!v.length) return null;
    return { last: rows[0], min: Math.min(...v), max: Math.max(...v),
             avg: v.reduce((a, b) => a + b, 0) / v.length, n: v.length };
  }, [rows]);

  return (
    <div className={`nmg-page ${busy ? "nmg-busy" : ""}`}>
      <div className="nmg-bar">
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
        <div className="nmg-grid-2">
          <section className="nmg-card">
            <div className="nmg-head">
              <h3>{cfg.label} {fmtNum(strike, cfg.strikeDec ?? 0)} {side === "ce" ? "Call" : "Put"}</h3>
              <span className="nmg-sub">
                Buy on NSE at the ask, sell on MCX at the bid. Above zero the pair
                pays you to open it.
              </span>
            </div>

            {stats && (
              <div className="nmg-stats">
                <div><em>Latest</em>
                  <b className={stats.last.diff >= 0 ? "nmg-pos" : "nmg-neg"}>
                    {sign(stats.last.diff, dec)}</b>
                  <i>{dayShort(stats.last.date)} · {slotShort(stats.last.slot)}</i></div>
                <div><em>Average</em><b>{sign(stats.avg, dec)}</b><i>{stats.n} readings</i></div>
                <div><em>Best</em><b className="nmg-pos">{sign(stats.max, dec)}</b></div>
                <div><em>Worst</em><b className={stats.min >= 0 ? "nmg-pos" : "nmg-neg"}>
                  {sign(stats.min, dec)}</b></div>
              </div>
            )}

            <Chart points={d.points || []} dec={dec} />
          </section>

          {/* the numbers behind the line - few enough to just show, and a chart
              alone is not readable by everyone */}
          <section className="nmg-card nmg-tablecard">
            <div className="cru-table-wrap">
              <table className="cru-table nmg-table">
                <thead>
                  <tr><th>Date</th><th>Time</th><th>NSE ask</th><th>MCX bid</th><th>Difference</th></tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.date + p.slot} className={p.wide ? "nmg-widerow" : ""}>
                      <td>{dayShort(p.date)}</td>
                      <td>{slotShort(p.slot)}</td>
                      <td>{fmtNum(p.nse_ask, dec)}</td>
                      <td>{fmtNum(p.mcx_bid, dec)}</td>
                      <td className={p.diff >= 0 ? "nmg-pos" : "nmg-neg"}
                        title={p.wide ? "One side was quoted very wide here." : ""}>
                        {sign(p.diff, dec)}{p.wide && " ?"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.some((p) => p.wide) && (
              <p className="nmg-widenote">
                A <b>?</b> means one exchange was quoting that leg very wide at the
                time, so the difference beside it is arithmetic rather than a price
                anyone could have dealt at. Those readings are left out of the
                average, best and worst.
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
