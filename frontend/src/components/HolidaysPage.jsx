import React, { useEffect, useState } from "react";
import { api, getRole } from "../api/client.js";
import { useConfirm } from "./ConfirmDialog.jsx";
import { useToast } from "./Toast.jsx";

// Market Holidays (client, 14-Sep-2026): the exchange calendar the whole app
// keeps time by - the LIVE / HOLIDAY badge, the feed watchdog and the paper
// engine all read it. Pulled from NSE once a year, editable here.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dmy = (iso) => (iso ? `${iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}` : "—");
const EMPTY = { date: "", exchange: "MCX", name: "", morning_closed: true, evening_closed: false };

function Form({ initial, onClose, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState(initial || EMPTY);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  async function save() {
    if (!f.date) { toast.error("Pick a date."); return; }
    setBusy(true);
    try {
      const body = { ...f, evening_closed: f.exchange === "NSE" ? true : f.evening_closed, morning_closed: f.exchange === "NSE" ? true : f.morning_closed };
      await api.marketHolidaySave(body); toast.success("Saved."); onSaved();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="pt-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pt-modal" role="dialog" aria-label="Holiday">
        <div className="pt-modal-head"><b>{initial?.id ? "Edit holiday" : "Add holiday"}</b><button type="button" className="pt-modal-x" onClick={onClose} aria-label="Close">×</button></div>
        <div className="hp-form">
          <label className="bt-f"><span>Date</span><input type="date" className="oh-weeks" value={f.date} onChange={set("date")} disabled={!!initial?.id} /></label>
          <label className="bt-f"><span>Exchange</span>
            <select className="oh-weeks" value={f.exchange} onChange={set("exchange")} disabled={!!initial?.id}><option value="MCX">MCX (commodity)</option><option value="NSE">NSE (equity, F&O)</option></select></label>
          <label className="bt-f"><span>Occasion</span><input type="text" className="oh-weeks hp-name" value={f.name} onChange={set("name")} placeholder="Diwali" /></label>
          {f.exchange === "MCX" ? (
            <div className="bt-checks hp-checks">
              <label className="pt-symtick"><input type="checkbox" checked={!!f.morning_closed} onChange={set("morning_closed")} /> Morning session closed (09:00 to 17:00)</label>
              <label className="pt-symtick"><input type="checkbox" checked={!!f.evening_closed} onChange={set("evening_closed")} /> Evening session closed (17:00 to 23:30)</label>
            </div>
          ) : <div className="oh-note">NSE is closed for the whole day on a listed holiday.</div>}
          <div className="bt-actions"><button type="button" className="oh-chip" onClick={onClose}>Cancel</button><button type="button" className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button></div>
        </div>
      </div>
    </div>
  );
}

export default function HolidaysPage() {
  const toast = useToast();
  const confirm = useConfirm();
  const admin = getRole() === "admin";
  const [year, setYear] = useState(new Date().getFullYear());
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  async function load(y = year) {
    try { setData(await api.marketHolidays(y)); setErr(null); } catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(year); }, [year]);
  async function refresh() {
    if (!(await confirm({ title: "Refresh from NSE", message: `Pull the ${year} calendar from NSE's holiday master? Days you added or edited by hand are kept.`, confirmText: "Refresh" }))) return;
    setBusy(true);
    try { const r = await api.marketHolidayRefresh(year); toast.success(`NSE ${r.nse} days, MCX ${r.mcx} days${r.kept_manual ? `, ${r.kept_manual} manual kept` : ""}.`); await load(); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }
  async function remove(h) {
    if (!(await confirm({ title: "Delete holiday", message: `Remove ${dmy(h.date)} (${h.exchange}, ${h.name})?`, confirmText: "Delete", danger: true }))) return;
    try { await api.marketHolidayDelete(h.id); toast.success("Deleted."); await load(); } catch (e) { toast.error(e.message); }
  }
  const rows = data?.rows || [];
  const byDate = {};
  rows.forEach((r) => { (byDate[r.date] = byDate[r.date] || {})[r.exchange] = r; });
  const dates = Object.keys(byDate).sort();
  const today = new Date().toISOString().slice(0, 10);
  const mcxNow = data?.now?.mcx; const nseNow = data?.now?.nse;
  const cell = (r, which) => {
    if (!r) return <span className="pos">open</span>;
    const closed = which === "nse" ? true : which === "am" ? r.morning_closed : r.evening_closed;
    return closed ? <span className="neg">closed</span> : <span className="pos">open</span>;
  };
  return (
    <div className="um-page hp-page">
      <div className="um-head">
        <div>
          <h2>Market Holidays</h2>
          <p className="bs-muted">The exchange calendar the dashboard keeps time by: the LIVE / HOLIDAY badge, the feed watchdog and paper trading all read it. Pulled from NSE once a year; edit a day here if an exchange changes it.</p>
        </div>
        <div className="hp-actions">
          <select className="oh-weeks" value={year} onChange={(e) => setYear(+e.target.value)}>{(data?.years || [year]).map((y) => <option key={y} value={y}>{y}</option>)}{!(data?.years || []).includes(year + 1) && <option value={year + 1}>{year + 1}</option>}</select>
          {admin && <button type="button" className="oh-chip" disabled={busy} onClick={refresh}>{busy ? "Refreshing…" : "Refresh from NSE"}</button>}
          {admin && <button type="button" className="btn btn-primary" onClick={() => setForm({ ...EMPTY })}>Add holiday</button>}
        </div>
      </div>
      {err && <div className="settings-banner danger">⚠ {err}</div>}
      {mcxNow && (
        <div className="pp-bar hp-now">
          <span className={`pp-pill ${mcxNow.open ? "on" : ""}`}>MCX: {mcxNow.label}{mcxNow.reason ? ` · ${mcxNow.reason}` : ""}</span>
          <span className={`pp-pill ${nseNow?.open ? "on" : ""}`}>NSE: {nseNow?.label}{nseNow?.reason ? ` · ${nseNow.reason}` : ""}</span>
          {!mcxNow.open && mcxNow.next_open && <span className="pp-info">MCX opens next {dmy(mcxNow.next_open.slice(0, 10))} {mcxNow.next_open.slice(11, 16)}</span>}
        </div>
      )}
      <div className="bt-card">
        <div className="bt-tablewrap">
          <table className="nmd-table bt-table hp-table">
            <thead><tr><th>Date</th><th>Day</th><th>Occasion</th><th>NSE (equity, F&O)</th><th>MCX morning 09:00 to 17:00</th><th>MCX evening 17:00 to 23:30</th><th>Source</th>{admin && <th></th>}</tr></thead>
            <tbody>
              {dates.length === 0 && <tr><td colSpan={admin ? 8 : 7} className="bs-muted">{data ? `No holidays stored for ${year}. ${admin ? "Press Refresh from NSE." : ""}` : "Loading…"}</td></tr>}
              {dates.map((d) => { const n = byDate[d].NSE, m = byDate[d].MCX; const r = m || n; const past = d < today; return (
                <tr key={d} className={d === today ? "hp-today" : past ? "nmd-dim" : ""}>
                  <td className="nmd-date">{dmy(d)}{d === today ? " (today)" : ""}</td>
                  <td>{r.weekday}</td>
                  <td>{r.name}{n && m && n.name !== m.name ? ` / ${n.name}` : ""}</td>
                  <td>{cell(n, "nse")}</td>
                  <td>{cell(m, "am")}</td>
                  <td>{cell(m, "pm")}</td>
                  <td className="bs-muted">{[n, m].filter(Boolean).some((x) => x.source === "manual") ? "edited" : "NSE list"}</td>
                  {admin && <td className="hp-rowact">
                    {m && <button type="button" className="oh-chip" onClick={() => setForm(m)}>MCX</button>}
                    {n && <button type="button" className="oh-chip" onClick={() => setForm(n)}>NSE</button>}
                    {[m, n].filter(Boolean).map((x) => <button key={x.id} type="button" className="oh-chip hp-del" title={`Delete ${x.exchange} row`} onClick={() => remove(x)}>× {x.exchange}</button>)}
                  </td>}
                </tr>); })}
            </tbody>
          </table>
        </div>
      </div>
      {form && <Form initial={form} onClose={() => setForm(null)} onSaved={() => { setForm(null); load(); }} />}
    </div>
  );
}
