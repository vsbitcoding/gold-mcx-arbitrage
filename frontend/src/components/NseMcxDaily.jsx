import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { fmtNum } from "../utils/format.js";

// NSE vs MCX option premiums, day by day since April 2024 (client, 08-Sep).
// Closing figures from both exchanges: an NSE expiry against the MCX expiry
// nearest to it, strikes on the client's ladder (round hundreds on crude),
// call and put side by side with the difference. Filters: expiry, dates,
// call/put, one strike or all. One strike also draws its difference over time.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dmy = (iso) => (iso ? `${iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}` : "");
const num = (v, d = 2) => (v == null ? "—" : fmtNum(v, d));
const signed = (v, d = 2) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmtNum(Math.abs(v), d));
const PAGE = 20;
// A leg counts as traded when both exchanges printed volume that day. Deep
// wings settle at 0.10 without a trade, and a % against 0.10 is not a number
// anyone should read - so the % needs both premiums to be at least 1.
const traded = (leg) => leg && leg.nse_vol > 0 && leg.mcx_vol > 0;
const pctOf = (leg) => (leg && leg.nse != null && leg.mcx != null && leg.nse >= 1 && leg.mcx >= 1 ? leg.diff_pct : null);

function DiffChart({ rows, strike }) {
  const box = useRef(null);
  const [W, setW] = useState(900);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setW(Math.max(320, el.clientWidth)));
    ro.observe(el); setW(Math.max(320, el.clientWidth));
    return () => ro.disconnect();
  }, []);
  const pts = useMemo(() => rows.slice().reverse(), [rows]);   // oldest first
  const H = 220, padL = 56, padR = 16, padT = 12, padB = 26;
  const geo = useMemo(() => {
    const vals = [];
    pts.forEach((r) => { if (r.ce.diff != null) vals.push(r.ce.diff); if (r.pe.diff != null) vals.push(r.pe.diff); });
    if (pts.length < 2 || !vals.length) return null;
    let lo = Math.min(...vals, 0), hi = Math.max(...vals, 0);
    if (hi === lo) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const x = (i) => padL + (i / (pts.length - 1)) * (W - padL - padR);
    const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
    const path = (side) => {
      let s = "", started = false;
      pts.forEach((r, i) => { const v = r[side].diff; if (v == null) { started = false; return; } s += `${started ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; started = true; });
      return s;
    };
    const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
    const xt = []; let last = "";
    pts.forEach((r, i) => { const m = r.date.slice(0, 7); if (m !== last) { last = m; xt.push({ x: x(i), label: `${MONTHS[+r.date.slice(5, 7) - 1]} ${r.date.slice(2, 4)}` }); } });
    return { x, y, ce: path("ce"), pe: path("pe"), ticks, xt, zero: y(0) };
  }, [pts, W]);
  if (!geo) return null;
  return (
    <div className="nmd-chart" ref={box}>
      <div className="bs-legend bsc-legend">
        <span><i className="bsc-sw" style={{ background: "var(--green)" }} /> Call difference (NSE − MCX)</span>
        <span><i className="bsc-sw" style={{ background: "var(--red)" }} /> Put difference (NSE − MCX)</span>
        <span className="bs-muted">strike {fmtNum(strike, 0)}, closing premiums, day wise</span>
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="bsc-svg nmd-svg" role="img" aria-label="Premium difference over time">
        {geo.ticks.map((v, i) => <g key={i}><line x1={padL} x2={W - padR} y1={geo.y(v)} y2={geo.y(v)} className="bsc-grid" /><text x={padL - 8} y={geo.y(v) + 4} className="bsc-ax bsc-ax-l">{fmtNum(v, 0)}</text></g>)}
        <line x1={padL} x2={W - padR} y1={geo.zero} y2={geo.zero} className="nmd-zero" />
        {geo.xt.map((t, i) => <text key={i} x={t.x} y={H - 8} className="bsc-ax bsc-ax-x">{t.label}</text>)}
        <path d={geo.ce} className="bsc-line" style={{ stroke: "var(--green)" }} />
        <path d={geo.pe} className="bsc-line" style={{ stroke: "var(--red)" }} />
      </svg>
    </div>
  );
}

function Leg({ leg, dec }) {
  const dim = !traded(leg);
  const pct = pctOf(leg);
  return (
    <>
      <td className={dim ? "nmd-dim" : ""} title={dim ? "not traded on both exchanges that day" : ""}>{num(leg.nse, dec)}</td>
      <td className={dim ? "nmd-dim" : ""}>{num(leg.mcx, dec)}</td>
      <td className={`${dim ? "nmd-dim " : ""}${leg.diff > 0 ? "pos" : leg.diff < 0 ? "neg" : ""}`}>{signed(leg.diff, dec)}</td>
      <td className={`${dim ? "nmd-dim " : ""}${pct > 0 ? "pos" : pct < 0 ? "neg" : ""}`}>{pct == null ? "—" : signed(pct, 2) + "%"}</td>
    </>
  );
}

export default function NseMcxDaily({ product, cfg }) {
  const [exps, setExps] = useState(null);
  const [expiry, setExpiry] = useState("");
  const [type, setType] = useState("");         // "" = both
  const [strike, setStrike] = useState("");     // "" = all
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [page, setPage] = useState(1);
  const [tradedOnly, setTradedOnly] = useState(true);
  const dec = cfg?.decimals ?? 2;
  const quick = (days) => { const d = new Date(); d.setDate(d.getDate() - Number(days)); return d.toISOString().slice(0, 10); };

  useEffect(() => {
    let alive = true;
    setExps(null); setExpiry(""); setData(null); setStrike("");
    api.nseMcxDailyExpiries(product).then((r) => {
      if (!alive) return;
      setExps(r);
      // Open on the front month: the nearest expiry still ahead, else the latest.
      const today = new Date().toISOString().slice(0, 10);
      const ahead = (r.expiries || []).filter((e) => e.nse >= today);
      const pick = ahead.length ? ahead[ahead.length - 1] : (r.expiries || [])[0];
      setExpiry(pick?.nse || "");
    }).catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [product]);

  useEffect(() => {
    if (!expiry) return undefined;
    let alive = true;
    setLoading(true);
    // The strike is filtered here, not on the server, so the strike list
    // stays complete after one is chosen (choosing 4,200 used to leave the
    // dropdown with only 4,200 in it).
    api.nseMcxDaily({ commodity: product, expiry, start: start || null, end: end || null, type: type || null })
      .then((r) => { if (alive) { setData(r); setErr(null); setPage(1); } })
      .catch((e) => { if (alive) setErr(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [product, expiry, start, end, type]);
  useEffect(() => { setPage(1); }, [strike]);

  const pair = exps?.expiries?.find((e) => e.nse === expiry);
  const allRows = useMemo(() => (data?.rows || []).filter((r) => !strike || r.strike === Number(strike)), [data, strike]);
  // Traded only: keep a row when at least one shown side traded on both exchanges.
  const rows = useMemo(() => (tradedOnly
    ? allRows.filter((r) => (type !== "PE" && traded(r.ce)) || (type !== "CE" && traded(r.pe)))
    : allRows), [allRows, tradedOnly, type]);
  useEffect(() => { setPage(1); }, [tradedOnly]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const safe = Math.min(page, pages);
  const shown = rows.slice((safe - 1) * PAGE, safe * PAGE);
  const strikes = data?.strikes || [];
  const showCE = type !== "PE", showPE = type !== "CE";

  function downloadCsv() {
    const head = ["Date", "NSE expiry", "MCX expiry", "NSE future", "MCX future", "Future diff", "Strike", "NSE call", "MCX call", "Call diff", "Call diff %", "NSE put", "MCX put", "Put diff", "Put diff %"];
    const lines = [head.join(",")];
    rows.forEach((r) => lines.push([r.date, data.nse_expiry, data.mcx_expiry, r.fut?.nse ?? "", r.fut?.mcx ?? "", r.fut?.diff ?? "", r.strike, r.ce.nse ?? "", r.ce.mcx ?? "", r.ce.diff ?? "", pctOf(r.ce) ?? "", r.pe.nse ?? "", r.pe.mcx ?? "", r.pe.diff ?? "", pctOf(r.pe) ?? ""].join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `nse-mcx-${product}-${expiry}${strike ? "-" + strike : ""}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  return (
    <div className={`nmd ${loading && data ? "nm-busy" : ""}`}>
      <div className="nmd-controls">
        <label className="nmd-f nmd-w-exp"><span>NSE expiry</span>
          <select className="oh-weeks" value={expiry} onChange={(e) => { setExpiry(e.target.value); setStrike(""); setStart(""); setEnd(""); }}>
            {(exps?.expiries || []).map((e) => <option key={e.nse} value={e.nse}>{dmy(e.nse)}</option>)}
          </select></label>
        <div className="nmd-f nmd-w-mcx"><span>MCX expiry</span><div className="nmd-static"><b>{pair?.mcx ? dmy(pair.mcx) : "—"}</b><small>{pair?.gap_days != null ? `${pair.gap_days} days apart` : ""}</small></div></div>
        <div className="nmd-f"><span>Period</span>
          <div className="oh-group" role="tablist">
            {[["all", "Whole contract"], ["30", "Last 30 days"], ["7", "Last 7 days"]].map(([k, l]) => {
              const on = k === "all" ? (!start && !end) : (start === quick(k) && !end);
              return <button key={k} type="button" role="tab" aria-selected={on} className={`oh-chip ${on ? "on" : ""}`}
                onClick={() => { if (k === "all") { setStart(""); setEnd(""); } else { setStart(quick(k)); setEnd(""); } }}>{l}</button>;
            })}
          </div></div>
        <label className="nmd-f nmd-w-date"><span>From</span><input type="date" className="oh-weeks" value={start} min={data?.from || ""} max={data?.to || ""} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="nmd-f nmd-w-date"><span>To</span><input type="date" className="oh-weeks" value={end} min={data?.from || ""} max={data?.to || ""} onChange={(e) => setEnd(e.target.value)} /></label>
        <div className="nmd-f"><span>Show</span>
          <div className="oh-group" role="tablist">
            {[["", "Call + Put"], ["CE", "Call"], ["PE", "Put"]].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={type === k} className={`oh-chip ${type === k ? "on" : ""}`} onClick={() => setType(k)}>{l}</button>
            ))}
          </div></div>
        <label className="nmd-f nmd-w-strike"><span>Strike</span>
          <select className="oh-weeks" value={strike} onChange={(e) => setStrike(e.target.value)}>
            <option value="">All strikes</option>
            {strikes.map((s) => <option key={s} value={s}>{fmtNum(s, 0)}</option>)}
          </select></label>
        <div className="nmd-f nmd-actions"><span>&nbsp;</span>
          <div className="nmd-actbtns">
            <button type="button" aria-pressed={tradedOnly} className={`oh-chip ${tradedOnly ? "on" : ""}`}
              title="Only days and strikes where BOTH exchanges traded; untraded wings settle at 0.10 and mean nothing"
              onClick={() => setTradedOnly((v) => !v)}>Traded only</button>
            <button type="button" className="oh-chip" title="Clear every filter" onClick={() => { setType(""); setStrike(""); setStart(""); setEnd(""); setTradedOnly(true); }}>Reset</button>
            <button type="button" className="btn btn-primary btn-sm nmd-csv" disabled={!rows.length} onClick={downloadCsv}>Download CSV</button>
          </div></div>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {exps && !exps.expiries?.length && (
        <div className="oh-note">No daily data yet{exps.status?.running ? " - the backfill is running, check back in a few minutes." : "."}</div>
      )}
      {!data && loading && <div className="empty-state">Loading daily data…</div>}
      {data && (
        <>
          <div className="nmd-sub">
            <b>{cfg?.label || product}</b> · options NSE {dmy(data.nse_expiry)} vs MCX {dmy(data.mcx_expiry)} · futures NSE {dmy(data.nse_future_expiry)} vs MCX {dmy(data.mcx_future_expiry)} · {data.days} trading days {data.from ? `(${dmy(data.from)} to ${dmy(data.to)})` : ""} · closing prices, difference = NSE − MCX{tradedOnly ? " · traded on both exchanges only" : ""}
          </div>
          {strike && rows.length > 1 && <DiffChart rows={rows} strike={Number(strike)} />}
          {rows.length === 0 ? (
            <div className="oh-note">
              {tradedOnly && allRows.length
                ? <>No day where BOTH exchanges traded this contract on the ladder yet. <button type="button" className="nmd-link" onClick={() => setTradedOnly(false)}>Show untraded strikes too</button>.</>
                : "No days where both exchanges have this contract."}
            </div>
          ) : (
            <div className="nmd-tablewrap">
              <table className="nmd-table">
                <thead>
                  <tr>
                    <th rowSpan={2}>Date</th>
                    <th colSpan={3} className="nmd-futh">Future (close)</th>
                    <th rowSpan={2}>Strike</th>
                    {showCE && <th colSpan={4} className="nmd-call">Call</th>}
                    {showPE && <th colSpan={4} className="nmd-put">Put</th>}
                  </tr>
                  <tr>
                    <th>NSE</th><th>MCX</th><th>Diff</th>
                    {showCE && <><th>NSE</th><th>MCX</th><th>Diff</th><th>Diff %</th></>}
                    {showPE && <><th>NSE</th><th>MCX</th><th>Diff</th><th>Diff %</th></>}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r, i) => (
                    <tr key={r.date + r.strike} className={i > 0 && shown[i - 1].date !== r.date ? "nmd-daystart" : ""}>
                      <td className="nmd-date">{i === 0 || shown[i - 1].date !== r.date ? dmy(r.date) : ""}</td>
                      {(i === 0 || shown[i - 1].date !== r.date) ? (
                        <><td className="nmd-fut">{num(r.fut?.nse, dec)}</td><td className="nmd-fut">{num(r.fut?.mcx, dec)}</td>
                          <td className={`nmd-fut ${r.fut?.diff > 0 ? "pos" : r.fut?.diff < 0 ? "neg" : ""}`}>{signed(r.fut?.diff, dec)}</td></>
                      ) : <><td /><td /><td /></>}
                      <td className="nmd-strike">{fmtNum(r.strike, 0)}</td>
                      {showCE && <Leg leg={r.ce} dec={dec} />}
                      {showPE && <Leg leg={r.pe} dec={dec} />}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="bsc-foot">
                <span className="bsc-foot-txt">{rows.length} rows · {PAGE} per page</span>
                <span className="bsc-pager">
                  <button type="button" className="oh-chip" disabled={safe <= 1} onClick={() => setPage(1)}>«</button>
                  <button type="button" className="oh-chip" disabled={safe <= 1} onClick={() => setPage(safe - 1)}>‹</button>
                  <b>{safe} / {pages}</b>
                  <button type="button" className="oh-chip" disabled={safe >= pages} onClick={() => setPage(safe + 1)}>›</button>
                  <button type="button" className="oh-chip" disabled={safe >= pages} onClick={() => setPage(pages)}>»</button>
                </span>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
