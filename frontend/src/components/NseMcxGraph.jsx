import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// One strike's - or the future's - difference over time (client, 18-Aug).
//
// TWO lines against a zero baseline, because the sign IS the story: above it the
// pair pays you to open, below it costs you.
//
//   deal  `MCX bid - NSE ask`   what he actually nets, buying NSE selling MCX
//   mid   `MCX mid - NSE mid`   the plain gap, before either spread is paid
//
// The distance between them is what the two spreads cost, which is why the
// client asked for both: on crude 7,400 CE the mid line runs +51 to +59 while
// the deal line runs +21 to +39, so roughly 22 rupees never reaches him.
//
// Gold solid is the deal, blue dashed is the mid. Two hues, not one hue faded -
// the faded version was indistinguishable at a glance (client, 18-Aug). Gold vs
// blue is also the colourblind-safe pair; green and red were unavailable, they
// already mean positive and negative on the dots.
//
// An earlier version drew three lines, one per capture time, and the client
// rejected it: three lines saying the SAME thing at different hours. Two lines
// saying two different things is the case that survived.
const PAD = { t: 22, r: 74, b: 34, l: 66 };
const H = 300;
const SIDES = [{ key: "ce", label: "Call" }, { key: "pe", label: "Put" }];

// One trading day occupies three slots - 10, 12 and 3 - but only the DATE is
// printed, sitting under that day's first dot; the hour is on hover (client,
// 18-Aug). Labelling all three crowded the axis to say something the tooltip
// already says on demand.
const PAD_B2 = 38;
// The picker's first entry. Sent to the API verbatim in place of a strike, so
// one endpoint and one screen serve both the future and every option.
const FUT = "future";

// Nine capture slots now (client, 18-Aug), so the hour is spelled the Indian
// way rather than left as 24-hour text the client has asked us not to use.
const slotShort = (s) => {
  const [h, m] = String(s || "").split(":");
  const hh = Number(h);
  if (!Number.isFinite(hh)) return s;
  const ampm = hh < 12 ? "AM" : "PM";
  const h12 = hh % 12 === 0 ? 12 : hh % 12;
  return m === "00" ? `${h12} ${ampm}` : `${h12}:${m} ${ampm}`;
};
const dayShort = (iso) => {
  const [, m, d] = (iso || "").split("-");
  return d ? `${d}/${m}` : iso;
};
const sign = (v, d) => (v == null ? "—" : (v >= 0 ? "+" : "−") + fmtNum(Math.abs(v), d));

// Axis ticks a person can read: -100, 0, 100 - never 39.4 or -267.3. Steps climb
// through 1/2/2.5/5 x a power of ten, and bracket the data so the plot fills its
// box instead of floating inside it.
function niceTicks(lo, hi, count = 4) {
  const raw = (hi - lo || 1) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + 1e-9; v += step) {
    out.push(Math.abs(v) < 1e-9 ? 0 : Math.round(v * 1e6) / 1e6);
  }
  return out;
}

function Chart({ points, dec }) {
  const [hover, setHover] = useState(null);
  const [w, setW] = useState(900);
  const wrap = useRef(null);

  // Measured, not letterboxed. A fixed viewBox scaled to fit left the chart
  // floating in the middle of a wide screen with dead space either side.
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.max(360, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pts = points.map((p, i) => ({ ...p, i }));
  const vals = pts.filter((p) => p.diff != null);
  const mids = pts.filter((p) => p.mid_diff != null);

  // The scale always includes zero: this chart is about which side of it a
  // number sits on, so cropping the baseline would hide the whole point. Both
  // lines share it - two scales would let them cross where they do not.
  const ys = [...vals.map((p) => p.diff), ...mids.map((p) => p.mid_diff)];
  let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  const pad = (hi - lo || 1) * 0.14;
  const ticks = niceTicks(lo - pad, hi + pad);
  lo = ticks[0];
  hi = ticks[ticks.length - 1];

  const x = (i) => PAD.l + (i * (w - PAD.l - PAD.r)) / Math.max(1, pts.length - 1);
  const y = (v) => PAD.t + ((hi - v) * (H - PAD.t - PAD_B2)) / (hi - lo || 1);
  // The future's deal line is empty before 18-Aug; anchor the tooltip to the
  // mid line there instead of to a NaN.
  const tipY = (p) => y(p.diff != null ? p.diff : p.mid_diff);

  // Break the path where a reading is missing, so a gap reads as a gap. The
  // future's deal line is empty before 18-Aug - MCX future bid/ask only started
  // being stored that day - and a gap says so where a joined line would lie.
  const runs = (key) => {
    const out = [];
    let cur = [];
    for (const p of pts) {
      if (p[key] == null) { if (cur.length > 1) out.push(cur); cur = []; }
      else cur.push(p);
    }
    if (cur.length > 1) out.push(cur);
    return out;
  };
  const segs = runs("diff");
  const midSegs = runs("mid_diff");

  // Each day's run of readings, for the date row and the divider between days.
  const groups = [];
  pts.forEach((p, i) => {
    const g = groups[groups.length - 1];
    if (g && g.date === p.date) g.end = i;
    else groups.push({ date: p.date, start: i, end: i });
  });

  // With no deal readings the mid line is not "context" any more, it is the
  // whole chart - drawing it faint and dashed on its own read as broken rather
  // than as secondary (client, 18-Aug).
  const midLead = vals.length === 0;
  const last = vals[vals.length - 1] || null;
  const lastMid = mids[mids.length - 1] || null;
  const yBase = H - PAD_B2;

  function onMove(e) {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    const px = e.clientX - box.left;
    let best = null;
    for (const p of (vals.length ? vals : mids)) {
      const d = Math.abs(x(p.i) - px);
      if (!best || d < best.d) best = { d, p };
    }
    setHover(best && best.d < 70 ? best.p : null);
  }

  return (
    <div className="nmg-wrap" ref={wrap}
      onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${w} ${H}`} width="100%" height={H} className="nmg-svg" role="img"
        aria-label="MCX bid minus NSE ask, by date and time">
        {ticks.map((v) => (
          <g key={v}>
            <line className={v === 0 ? "nmg-zero" : "nmg-grid"}
              x1={PAD.l} x2={w - PAD.r} y1={y(v)} y2={y(v)} />
            <text className={`nmg-tick ${v === 0 ? "nmg-zero-tick" : ""}`}
              x={PAD.l - 10} y={y(v) + 4} textAnchor="end">{fmtNum(v, 0)}</text>
          </g>
        ))}

        {/* The date sits under its day's FIRST dot, so the axis reads
            "14/08, then its three readings, then the next date". A faint rule
            between days keeps the grouping visible without labelling the hours,
            which the tooltip gives on demand. */}
        {groups.map((g, k) => {
          const a = x(g.start);
          const edge = k ? (x(groups[k - 1].end) + a) / 2 : null;
          return (
            <g key={g.date}>
              {edge != null && (
                <line className="nmg-daysplit" x1={edge} x2={edge} y1={PAD.t} y2={yBase + 8} />
              )}
              <text className="nmg-day" x={a} y={yBase + 22} textAnchor="middle">
                {dayShort(g.date)}
              </text>
            </g>
          );
        })}

        {/* the mid gap sits behind, thinner and dashed - it is context for the
            solid line, not the number he trades */}
        {midSegs.map((seg, k) => (
          <path key={`m${k}`} className={`nmg-line ${midLead ? "midlead" : "mid"}`} fill="none"
            d={seg.map((p, i) => `${i ? "L" : "M"}${x(p.i)},${y(p.mid_diff)}`).join(" ")} />
        ))}
        {mids.map((p) => (
          <circle key={`md${p.i}`} className="nmg-dot mid"
            cx={x(p.i)} cy={y(p.mid_diff)} r={midLead ? 4 : 2.5} />
        ))}

        {segs.map((seg, k) => (
          <path key={k} className="nmg-line" fill="none"
            d={seg.map((p, i) => `${i ? "L" : "M"}${x(p.i)},${y(p.diff)}`).join(" ")} />
        ))}

        {vals.map((p) => (
          <circle key={p.i}
            className={`nmg-dot ${p.diff >= 0 ? "pos" : "neg"} ${p.wide ? "wide" : ""}`}
            cx={x(p.i)} cy={y(p.diff)} r={p.wide ? 5 : 4}>
            {p.wide && <title>One side was quoted very wide here.</title>}
          </circle>
        ))}

        {last && (
          <>
            <circle className={`nmg-dot ${last.diff >= 0 ? "pos" : "neg"}`}
              cx={x(last.i)} cy={y(last.diff)} r={5.5} />
            <text className={`nmg-lastval ${last.diff >= 0 ? "pos" : "neg"}`}
              x={Math.min(x(last.i) + 12, w - 8)} y={y(last.diff) + 4}>{sign(last.diff, dec)}</text>
          </>
        )}
        {lastMid && (
          <text className="nmg-lastval mid"
            x={Math.min(x(lastMid.i) + 12, w - 8)} y={y(lastMid.mid_diff) + 4}>
            {sign(lastMid.mid_diff, dec)}
          </text>
        )}

        {hover && (
          <>
            <line className="nmg-cross" x1={x(hover.i)} x2={x(hover.i)} y1={PAD.t} y2={yBase} />
            {hover.diff != null && (
              <circle className="nmg-hoverdot" cx={x(hover.i)} cy={y(hover.diff)} r={7} />
            )}
            {hover.mid_diff != null && (
              <circle className="nmg-hoverdot mid" cx={x(hover.i)} cy={y(hover.mid_diff)} r={6} />
            )}
          </>
        )}
      </svg>

      {hover && (
        <div className={`nmg-tip ${tipY(hover) > (H - PAD_B2) / 2 ? "above" : "below"}`}
          style={{ left: Math.min(Math.max(x(hover.i), 100), w - 100),
                   top: tipY(hover) + (tipY(hover) > (H - PAD_B2) / 2 ? -12 : 12) }}>
          <em>{dayShort(hover.date)} · {slotShort(hover.slot)}</em>
          <b className={hover.diff >= 0 ? "nmg-pos" : "nmg-neg"}>{sign(hover.diff, dec)}</b>
          <span>NSE ask <i>{fmtNum(hover.nse_ask, dec)}</i></span>
          <span>MCX bid <i>{fmtNum(hover.mcx_bid, dec)}</i></span>
          <span className="mid">mid gap <i>{sign(hover.mid_diff, dec)}</i></span>
          <span>MCX future <i>{fmtNum(hover.mcx_future, dec)}</i></span>
          {hover.wide && <u>one side quoted very wide</u>}
        </div>
      )}
    </div>
  );
}

export default function NseMcxGraph({ product, month, cfg }) {
  const [side, setSide] = useState(() => {
    try { return localStorage.getItem("arbi_nsemcx_side") === "pe" ? "pe" : "ce"; }
    catch { return "ce"; }
  });
  const [strike, setStrike] = useState(null);
  const [opts, setOpts] = useState([]);
  // On by default. A reading taken off a 90% spread is not a price anyone could
  // have traded, and one of them drags the axis so far that every honest point
  // flattens onto the zero line - which is exactly what the page was doing.
  const [hideWide, setHideWide] = useState(true);
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => { try { localStorage.setItem("arbi_nsemcx_side", side); } catch {} }, [side]);

  // The strike list is fetched ONCE per commodity/month. Folding it into the
  // series call meant every switch fired twice - once to learn the strikes,
  // once to use them - and the chart blanked in between.
  useEffect(() => {
    let alive = true;
    api.nseMcxGraph({ commodity: product, month, days: 30 })
      .then((r) => {
        if (!alive) return;
        const list = r.strike_options || [];
        setOpts(list);
        setStrike((cur) => {
          if (cur != null && list.some((o) => o.strike === cur)) return cur;
          // the best-covered strike, not the middle of the list - the middle
          // landed on one with nothing to draw and an empty page
          return list.slice().sort((a, b) => b.readings - a.readings)[0]?.strike ?? null;
        });
      })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [product, month]);

  // The old chart stays on screen, dimmed, while the new one loads. Blanking it
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
  const sDec = cfg.strikeDec ?? 0;
  const isFut = strike === FUT;
  // Drives the legend: naming a line that is not drawn is worse than no legend.
  const hasDeal = (d?.points || []).some((p) => p.diff != null);
  // A point counts if EITHER line has a reading. The future's deal line is
  // empty before 18-Aug, and dropping those points would throw away the mid
  // line that does exist for them.
  const all = useMemo(
    () => (d?.points || []).filter((p) => p.diff != null || p.mid_diff != null), [d]);
  const wide = useMemo(() => all.filter((p) => p.wide), [all]);
  const shown = hideWide ? all.filter((p) => !p.wide) : all;
  const stats = useMemo(() => {
    const clean = all.filter((p) => !p.wide && p.diff != null);
    if (!clean.length) return null;
    const v = clean.map((p) => p.diff);
    const at = (t) => clean.find((p) => p.diff === t);
    return {
      last: clean[clean.length - 1], n: clean.length,
      avg: v.reduce((a, b) => a + b, 0) / v.length,
      max: Math.max(...v), min: Math.min(...v),
      atMax: at(Math.max(...v)), atMin: at(Math.min(...v)),
    };
  }, [all]);

  const title = isFut
    ? `${cfg.label} Future`
    : `${cfg.label} ${fmtNum(strike, sDec)} ${side === "ce" ? "Call" : "Put"}`;

  const toolbar = (
    <div className="nmg-bar">
      {/* a future has no call and no put, so the switch goes away rather than
          sitting there doing nothing */}
      {!isFut && (
        <div className="oh-group" role="tablist" aria-label="Option side">
          {SIDES.map((s) => (
            <button key={s.key} type="button" role="tab" aria-selected={side === s.key}
              className={`oh-chip ${side === s.key ? "on" : ""}`}
              onClick={() => setSide(s.key)}>{s.label}</button>
          ))}
        </div>
      )}
      <label className="nmg-pick">
        <span>CONTRACT</span>
        <select className="oh-weeks" value={strike ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            setStrike(v === FUT ? FUT : Number(v));
          }}>
          {opts.map((o) => (
            <option key={o.strike} value={o.strike}>
              {o.strike === FUT ? "Future" : fmtNum(o.strike, sDec)}
              {" · "}{o.readings} reading{o.readings === 1 ? "" : "s"}
            </option>
          ))}
        </select>
      </label>
      {wide.length > 0 && (
        <label className="nmg-toggle" title="A reading taken off a very wide quote is not a price anyone could have dealt at, and one of them flattens the whole line.">
          <input type="checkbox" checked={hideWide}
            onChange={(e) => setHideWide(e.target.checked)} />
          hide unusable
        </label>
      )}
      {/* two series, so identity can no longer rest on the heading alone */}
      <span className="nmg-legend">
        {hasDeal && <><i className="deal" /> MCX bid − NSE ask</>}
        {/* always the mid swatch - it was borrowing the gold "deal" style when
            it stood alone, so the legend showed a solid gold line beside a
            dashed blue one and named it the same thing (client, 18-Aug) */}
        <i className="mid" /> MCX mid − NSE mid
      </span>
    </div>
  );

  return (
    <div className={`nmg-page ${busy ? "nmg-busy" : ""}`}>
      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {!d && !err && <div className="empty-state">Loading…</div>}

      {d && (
        <div className="nmg-grid-2">
          <section className="nmg-card">
            {toolbar}
            <div className="nmg-body">
              {/* No heading and no prose above the chart (client, 18-Aug). The
                  page header already names the commodity, the picker names the
                  contract, and the legend names both lines - three sentences
                  restating that just pushed the plot down the screen. `title`
                  survives for the empty state, which does need to say what is
                  empty. */}
              {stats && shown.length >= 2 && (
                <div className="nmg-stats">
                  <div><em>LATEST DEAL</em>
                    <b className={stats.last.diff >= 0 ? "nmg-pos" : "nmg-neg"}>
                      {sign(stats.last.diff, dec)}</b>
                    <i>{dayShort(stats.last.date)} · {slotShort(stats.last.slot)}</i></div>
                  <div><em>AVERAGE</em><b>{sign(stats.avg, dec)}</b>
                    <i>{stats.n} reading{stats.n === 1 ? "" : "s"}</i></div>
                  <div><em>BEST</em><b className="nmg-pos">{sign(stats.max, dec)}</b>
                    <i>{dayShort(stats.atMax.date)} · {slotShort(stats.atMax.slot)}</i></div>
                  <div><em>WORST</em>
                    <b className={stats.min >= 0 ? "nmg-pos" : "nmg-neg"}>{sign(stats.min, dec)}</b>
                    <i>{dayShort(stats.atMin.date)} · {slotShort(stats.atMin.slot)}</i></div>
                </div>
              )}

              {shown.length >= 2
                ? <Chart points={shown} dec={dec} />
                : (
                  <div className="nmg-empty">
                    <b>Not enough readings yet for {title}</b>
                    <span>
                      A line needs two. Readings are saved nine times a trading day,
                      from 10 AM to 11:15 PM, and only when both exchanges are quoting
                      it.
                    </span>
                  </div>
                )}
            </div>
          </section>

          {/* the numbers behind the line - few enough to just show, and a chart
              alone is not readable by everyone */}
          <section className="nmg-card nmg-tablecard">
            <div className="nmg-rhd">
              <b>READINGS</b>
              <span>{all.length}{wide.length ? ` · ${wide.length} unusable` : ""}</span>
            </div>
            {all.length === 0 ? (
              <div className="nmg-empty"><span>Nothing to list yet.</span></div>
            ) : (
              <>
                <div className="nmg-tablescroll">
                <table className="cru-table nmg-table">
                  <thead>
                    <tr><th>Date</th><th>Time</th><th>NSE ask</th><th>MCX bid</th>
                      <th>Mid</th><th>Future</th><th>Diff</th></tr>
                  </thead>
                  <tbody>
                    {all.slice().reverse().map((p) => (
                      <tr key={p.date + p.slot} className={p.wide ? "nmg-widerow" : ""}>
                        <td>{dayShort(p.date)}</td>
                        <td>{slotShort(p.slot)}</td>
                        <td>{fmtNum(p.nse_ask, dec)}</td>
                        <td>{fmtNum(p.mcx_bid, dec)}</td>
                        <td className="nmg-midcell">{sign(p.mid_diff, dec)}</td>
                        {/* where the underlying stood, so a +30 can be read
                            against the level it was earned at (client, 18-Aug) */}
                        <td className="nmg-futcell">{fmtNum(p.mcx_future, dec)}</td>
                        <td className={p.diff >= 0 ? "nmg-pos" : "nmg-neg"}
                          title={p.wide ? "One side was quoted very wide here." : ""}>
                          {sign(p.diff, dec)}{p.wide && " ?"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                {wide.length > 0 && (
                  <p className="nmg-widenote">
                    A <b>?</b> means one exchange was quoting that leg very wide at the
                    time, so the difference beside it is arithmetic rather than a price
                    anyone could have dealt at. Those stay out of the average, best and
                    worst{hideWide ? ", and off the line" : ""}.
                  </p>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
