import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.js";

const fmt = (v) => (v == null ? "—" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

const BLANK = {
  name: "", code: "", ref_type: "feed", ref_key: "gold_spot",
  buy_parity: 0, sell_parity: 0, buy_manual: null, sell_manual: null,
  visible: true, allow_trade: false, template: "gurukrupa",
};

function Toggle({ on, onClick }) {
  return <button type="button" className={`tgl${on ? " on" : ""}`} onClick={onClick} aria-pressed={on}><span /></button>;
}

export default function ScripMaster() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState(null); // scrip object or BLANK (add) or null
  const [busy, setBusy] = useState(false);
  const prevRates = useRef({}); // id -> {buy, sell} for flash
  const modalOpen = editing !== null;

  async function load() {
    try { const d = await api.listScrips(); setData(d); setErr(""); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (modalOpen) return;               // pause live poll while editing
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [modalOpen]);

  const refLabel = useMemo(() => {
    const m = {};
    (data?.references || []).forEach((r) => { m[r.key] = r.label; });
    return m;
  }, [data]);
  const scripName = useMemo(() => {
    const m = {};
    (data?.scrip_refs || []).forEach((s) => { m[String(s.id)] = s.name; });
    return m;
  }, [data]);

  const rows = (data?.scrips || []).filter((s) => s.name.toLowerCase().includes(q.toLowerCase()));

  function flashCls(s, side) {
    const p = prevRates.current[s.id];
    const cur = side === "buy" ? s.buy_rate : s.sell_rate;
    const was = p ? (side === "buy" ? p.buy : p.sell) : null;
    if (was == null || cur == null || was === cur) return "";
    return cur > was ? "up" : "down";
  }
  useEffect(() => {
    const m = {};
    (data?.scrips || []).forEach((s) => { m[s.id] = { buy: s.buy_rate, sell: s.sell_rate }; });
    prevRates.current = m;
  }, [data]);

  async function toggle(s, field) {
    const body = { ...s, [field]: !s[field] };
    setData((d) => ({ ...d, scrips: d.scrips.map((x) => (x.id === s.id ? body : x)) })); // optimistic
    try { await api.updateScrip(s.id, body); } catch (e) { setErr(e.message); load(); }
  }
  async function move(s, dir) {
    const ids = rows.map((x) => x.id);
    const i = ids.indexOf(s.id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try { await api.reorder(ids); await load(); } catch (e) { setErr(e.message); }
  }
  async function del(s) {
    if (!window.confirm(`Delete "${s.name}"?`)) return;
    try { await api.deleteScrip(s.id); await load(); } catch (e) { setErr(e.message); }
  }
  async function save() {
    setBusy(true); setErr("");
    const body = { ...editing };
    ["buy_parity", "sell_parity", "buy_manual", "sell_manual"].forEach((k) => {
      body[k] = body[k] === "" || body[k] == null ? (k.includes("parity") ? 0 : null) : Number(body[k]);
    });
    try {
      if (editing.id) await api.updateScrip(editing.id, body);
      else await api.createScrip(body);
      setEditing(null); await load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  async function seed() { setBusy(true); try { await api.seed(); await load(); } finally { setBusy(false); } }

  const empty = data && rows.length === 0 && !q;

  return (
    <div className="sm">
      <div className="sm-bar">
        <div className="sm-title">
          Scrip Master <span className="sm-live"><i className="dot" /> live</span>
        </div>
        <input className="sm-search" placeholder="Search scrip…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="grow" />
        <button className="btn btn-gold" onClick={() => setEditing({ ...BLANK })}>＋ Add Scrip</button>
      </div>

      {err && <div className="sm-err">⚠ {err}</div>}

      {empty ? (
        <div className="soon-panel">
          <div className="soon-ic">▤</div>
          <h2>No scrips yet</h2>
          <p>Load the current 12 products to preview the panel with live rates.</p>
          <button className="btn btn-gold" onClick={seed} disabled={busy}>{busy ? "Loading…" : "Load demo data"}</button>
        </div>
      ) : (
        <div className="sm-scroll">
          <table className="sm-table">
            <thead>
              <tr>
                <th className="c-ord"></th>
                <th className="c-name">Scrip Name</th>
                <th>Reference</th>
                <th className="c-num">Buy Parity</th>
                <th className="c-rate">Buy Rate</th>
                <th className="c-num">Sell Parity</th>
                <th className="c-rate">Sell Rate</th>
                <th className="c-tg">Visible</th>
                <th className="c-tg">Trade</th>
                <th className="c-code">Code</th>
                <th className="c-act"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td className="c-ord">
                    <button className="mini" onClick={() => move(s, -1)} title="Up">↑</button>
                    <button className="mini" onClick={() => move(s, 1)} title="Down">↓</button>
                  </td>
                  <td className="c-name">{s.name}</td>
                  <td className="c-ref">
                    {s.ref_type === "scrip"
                      ? <span className="ref-pill scrip">↳ {scripName[String(s.ref_key)] || "scrip"}</span>
                      : s.ref_type === "manual"
                        ? <span className="ref-pill manual">manual</span>
                        : <span className="ref-pill">{refLabel[s.ref_key] || s.ref_key}</span>}
                  </td>
                  <td className="c-num">{s.buy_parity ?? 0}</td>
                  <td className={`c-rate buy ${flashCls(s, "buy")}`}>{fmt(s.buy_rate)}</td>
                  <td className="c-num">{s.sell_parity ?? 0}</td>
                  <td className={`c-rate sell ${flashCls(s, "sell")}`}>{fmt(s.sell_rate)}</td>
                  <td className="c-tg"><Toggle on={s.visible} onClick={() => toggle(s, "visible")} /></td>
                  <td className="c-tg"><Toggle on={s.allow_trade} onClick={() => toggle(s, "allow_trade")} /></td>
                  <td className="c-code">{s.code || "—"}</td>
                  <td className="c-act">
                    <button className="mini" onClick={() => setEditing({ ...s })} title="Edit">✎</button>
                    <button className="mini danger" onClick={() => del(s)} title="Delete">🗑</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && (
        <div className="modal-ov" onClick={(e) => { if (e.target.classList.contains("modal-ov")) setEditing(null); }}>
          <div className="modal">
            <div className="modal-h">{editing.id ? "Edit Scrip" : "Add Scrip"}</div>
            <div className="modal-b">
              <div className="fld"><label>Scrip Name</label>
                <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} autoFocus /></div>
              <div className="fld"><label>Code</label>
                <input value={editing.code || ""} onChange={(e) => setEditing({ ...editing, code: e.target.value })} /></div>
              <div className="fld"><label>Reference type</label>
                <select value={editing.ref_type} onChange={(e) => setEditing({ ...editing, ref_type: e.target.value, ref_key: e.target.value === "feed" ? "gold_spot" : "" })}>
                  <option value="feed">Market feed</option>
                  <option value="scrip">Another scrip</option>
                  <option value="manual">Manual (type rate)</option>
                </select></div>
              {editing.ref_type === "feed" && (
                <div className="fld"><label>Feed</label>
                  <select value={editing.ref_key || ""} onChange={(e) => setEditing({ ...editing, ref_key: e.target.value })}>
                    {(data?.references || []).map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
                  </select></div>
              )}
              {editing.ref_type === "scrip" && (
                <div className="fld"><label>Based on scrip</label>
                  <select value={editing.ref_key || ""} onChange={(e) => setEditing({ ...editing, ref_key: e.target.value })}>
                    <option value="">— select —</option>
                    {(data?.scrip_refs || []).filter((x) => x.id !== editing.id).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                  </select></div>
              )}
              {editing.ref_type !== "manual" ? (
                <div className="fld2">
                  <div className="fld"><label>Buy Parity</label>
                    <input type="number" value={editing.buy_parity ?? 0} onChange={(e) => setEditing({ ...editing, buy_parity: e.target.value })} /></div>
                  <div className="fld"><label>Sell Parity</label>
                    <input type="number" value={editing.sell_parity ?? 0} onChange={(e) => setEditing({ ...editing, sell_parity: e.target.value })} /></div>
                </div>
              ) : (
                <div className="fld2">
                  <div className="fld"><label>Buy Rate</label>
                    <input type="number" value={editing.buy_manual ?? ""} onChange={(e) => setEditing({ ...editing, buy_manual: e.target.value })} /></div>
                  <div className="fld"><label>Sell Rate</label>
                    <input type="number" value={editing.sell_manual ?? ""} onChange={(e) => setEditing({ ...editing, sell_manual: e.target.value })} /></div>
                </div>
              )}
              <div className="fld-row">
                <label className="chk"><Toggle on={editing.visible} onClick={() => setEditing({ ...editing, visible: !editing.visible })} /> Visible on board</label>
                <label className="chk"><Toggle on={editing.allow_trade} onClick={() => setEditing({ ...editing, allow_trade: !editing.allow_trade })} /> Allow trade</label>
              </div>
            </div>
            <div className="modal-f">
              <button className="btn btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button className="btn btn-gold" onClick={save} disabled={busy || !editing.name.trim()}>{busy ? "Saving…" : "Save"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
