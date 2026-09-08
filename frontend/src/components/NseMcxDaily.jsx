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
  const dec = cfg?.decimals ?? 2;

  useEffect(() => {
    let alive = true;
    setExps(null); setExpiry(""); setData(null); setStrike("");
    api.nseMcxDailyExpiries(product).then((r) => {
      if (!alive) return;
      setExps(r);
      const first = r.expiries?.[0]?.nse || "";
      setExpiry(first);
    }).catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [product]);

  useEffect(() => {
    if (!expiry) return undefined;
    let alive = true;
    setLoading(true);
    api.nseMcxDaily({ commodity: product, expiry, start: start || null, end: end || null, type: type || null, strike: strike || null })
      .then((r) => { if (alive) { setData(r); setErr(null); setPage(1); } })
      .catch((e) => { if (alive) setErr(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [product, expiry, start, end, type, strike]);

  const pair = exps?.expiries?.find((e) => e.nse === expiry);
  const rows = data?.rows || [];
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const safe = Math.min(page, pages);
  const shown = rows.slice((safe - 1) * PAGE, safe * PAGE);
  const strikes = data?.strikes || [];
  const showCE = type !== "PE", showPE = type !== "CE";

  function downloadCsv() {
    const head = ["Date", "NSE expiry", "MCX expiry", "Strike", "NSE call", "MCX call", "Call diff", "Call diff %", "NSE put", "MCX put", "Put diff", "Put diff %"];
    const lines = [head.join(",")];
    rows.forEach((r) => lines.push([r.date, data.nse_expiry, data.mcx_expiry, r.strike, r.ce.nse ?? "", r.ce.mcx ?? "", r.ce.diff ?? "", r.ce.diff_pct ?? "", r.pe.nse ?? "", r.pe.mcx ?? "", r.pe.diff ?? "", r.pe.diff_pct ?? ""].join(",")));
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `nse-mcx-${product}-${expiry}${strike ? "-" + strike : ""}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  return (
    <div className={`nmd ${loading && data ? "nm-busy" : ""}`}>
      <div className="oh-controls nmd-controls">
        <label className="nmd-f"><span>NSE expiry</span>
          <select className="oh-weeks" value={expiry} onChange={(e) => { setExpiry(e.target.value); setStrike(""); setStart(""); setEnd(""); }}>
            {(exps?.expiries || []).map((e) => <option key={e.nse} value={e.nse}>{dmy(e.nse)}</option>)}
          </select></label>
        <div className="nmd-f nmd-pair"><span>Compared with MCX</span><b>{pair?.mcx ? dmy(pair.mcx) : "—"}</b><small>{pair?.gap_days != null ? `${pair.gap_days} days apart` : ""}</small></div>
        <label className="nmd-f"><span>From</span><input type="date" className="oh-weeks" value={start} min={data?.from || ""} max={data?.to || ""} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="nmd-f"><span>To</span><input type="date" className="oh-weeks" value={end} min={data?.from || ""} max={data?.to || ""} onChange={(e) => setEnd(e.target.value)} /></label>
        <div className="nmd-f"><span>Side</span>
          <div className="oh-group" role="tablist">
            {[["", "Call + Put"], ["CE", "Call"], ["PE", "Put"]].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={type === k} className={`oh-chip ${type === k ? "on" : ""}`} onClick={() => setType(k)}>{l}</button>
            ))}
          </div></div>
        <label className="nmd-f"><span>Strike</span>
          <select className="oh-weeks" value={strike} onChange={(e) => setStrike(e.target.value)}>
            <option value="">All strikes</option>
            {strikes.map((s) => <option key={s} value={s}>{fmtNum(s, 0)}</option>)}
          </select></label>
        <button type="button" className="oh-chip nmd-dl" disabled={!rows.length} onClick={downloadCsv}>⬇ CSV</button>
      </div>

      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {exps && !exps.expiries?.length && (
        <div className="oh-note">No daily data yet{exps.status?.running ? " - the backfill is running, check back in a few minutes." : "."}</div>
      )}
      {!data && loading && <div className="empty-state">Loading daily data…</div>}
      {data && (
        <>
          <div className="nmd-sub">
            <b>{cfg?.label || product}</b> · NSE {dmy(data.nse_expiry)} vs MCX {dmy(data.mcx_expiry)} · {data.days} trading days {data.from ? `(${dmy(data.from)} to ${dmy(data.to)})` : ""} · {strikes.length} strikes on the ladder · closing premiums, difference = NSE − MCX
          </div>
          {strike && rows.length > 1 && <DiffChart rows={rows} strike={Number(strike)} />}
          {rows.length === 0 ? (
            <div className="oh-note">No days where both exchanges have this contract.</div>
          ) : (
            <div className="nmd-tablewrap">
              <table className="nmd-table">
                <thead>
                  <tr>
                    <th rowSpan={2}>Date</th><th rowSpan={2}>Strike</th>
                    {showCE && <th colSpan={4} className="nmd-call">Call</th>}
                    {showPE && <th colSpan={4} className="nmd-put">Put</th>}
                  </tr>
                  <tr>
                    {showCE && <><th>NSE</th><th>MCX</th><th>Diff</th><th>Diff %</th></>}
                    {showPE && <><th>NSE</th><th>MCX</th><th>Diff</th><th>Diff %</th></>}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r, i) => (
                    <tr key={r.date + r.strike} className={i > 0 && shown[i - 1].date !== r.date ? "nmd-daystart" : ""}>
                      <td className="nmd-date">{i === 0 || shown[i - 1].date !== r.date ? dmy(r.date) : ""}</td>
                      <td className="nmd-strike">{fmtNum(r.strike, 0)}</td>
                      {showCE && <><td>{num(r.ce.nse, dec)}</td><td>{num(r.ce.mcx, dec)}</td><td className={r.ce.diff > 0 ? "pos" : r.ce.diff < 0 ? "neg" : ""}>{signed(r.ce.diff, dec)}</td><td className={r.ce.diff_pct > 0 ? "pos" : r.ce.diff_pct < 0 ? "neg" : ""}>{r.ce.diff_pct == null ? "—" : signed(r.ce.diff_pct, 2) + "%"}</td></>}
                      {showPE && <><td>{num(r.pe.nse, dec)}</td><td>{num(r.pe.mcx, dec)}</td><td className={r.pe.diff > 0 ? "pos" : r.pe.diff < 0 ? "neg" : ""}>{signed(r.pe.diff, dec)}</td><td className={r.pe.diff_pct > 0 ? "pos" : r.pe.diff_pct < 0 ? "neg" : ""}>{r.pe.diff_pct == null ? "—" : signed(r.pe.diff_pct, 2) + "%"}</td></>}
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
