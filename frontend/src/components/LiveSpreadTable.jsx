import React, { useEffect, useMemo, useState, memo } from "react";
import { api } from "../api/client.js";

const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };
const STATUS_CLASS = { idle: "badge-idle", armed: "badge-armed", in_position: "badge-position" };

const MULTIPLIERS = { petal: 10, guinea: 1.25, ten: 1, mini: 1 };

function fmtSpread(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(4);
}
function fmtPx(v) {
  return v === null || v === undefined || v === 0 ? "—" : Number(v).toFixed(2);
}
function cap(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

const PairRow = memo(function PairRow({ row, draft, expanded, onToggle, onChange, onSave, onClear }) {
  const bigMult = MULTIPLIERS[row.big] ?? 1;
  const smallMult = MULTIPLIERS[row.small] ?? 1;
  const decBig = row.big_bid ? row.big_bid * bigMult : null;
  const decSmall = row.small_ask ? row.small_ask * smallMult : null;
  const incBig = row.big_ask ? row.big_ask * bigMult : null;
  const incSmall = row.small_bid ? row.small_bid * smallMult : null;

  return (
    <>
      <tr>
        <td className="gc-identity pair-name col-end-group">
          <button className="row-toggle" onClick={onToggle} title="Show calculation">
            <span className="caret">{expanded ? "▾" : "▸"}</span>
            {row.name}
          </button>
        </td>

        <td className="gc-decrease spread-num dec">{fmtSpread(row.decrease_spread)}</td>
        <td className="gc-decrease">
          <input className="cell" type="number" step="0.01" placeholder="—"
            value={draft.decrease_entry ?? ""}
            onChange={(e) => onChange("decrease_entry", e.target.value)} />
        </td>
        <td className="gc-decrease col-end-group">
          <input className="cell" type="number" step="0.01" placeholder="—"
            value={draft.decrease_exit ?? ""}
            onChange={(e) => onChange("decrease_exit", e.target.value)} />
        </td>

        <td className="gc-increase spread-num inc">{fmtSpread(row.increase_spread)}</td>
        <td className="gc-increase">
          <input className="cell" type="number" step="0.01" placeholder="—"
            value={draft.increase_entry ?? ""}
            onChange={(e) => onChange("increase_entry", e.target.value)} />
        </td>
        <td className="gc-increase col-end-group">
          <input className="cell" type="number" step="0.01" placeholder="—"
            value={draft.increase_exit ?? ""}
            onChange={(e) => onChange("increase_exit", e.target.value)} />
        </td>

        <td className="gc-status">
          <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
            <span className="blip" />
            {STATUS_LABEL[row.status] || row.status}
          </span>
        </td>
        <td className="gc-status">
          <div className="row-actions">
            <button className="btn btn-primary btn-sm" onClick={onSave}>Save</button>
            <button className="btn btn-secondary btn-sm" onClick={onClear}>Clear</button>
          </div>
        </td>
      </tr>

      {expanded && (
        <tr className="calc-row">
          <td colSpan={9}>
            <div className="calc-grid">
              <div className="calc-block dec">
                <div className="calc-title">▼ Decrease Spread = (Big.Bid × {bigMult}) − (Small.Ask × {smallMult})</div>
                <div className="calc-line">
                  <span>{cap(row.big)} Bid:</span>
                  <span className="calc-num">{fmtPx(row.big_bid)} × {bigMult} = <b>{fmtSpread(decBig)}</b></span>
                </div>
                <div className="calc-line">
                  <span>{cap(row.small)} Ask:</span>
                  <span className="calc-num">{fmtPx(row.small_ask)} × {smallMult} = <b>{fmtSpread(decSmall)}</b></span>
                </div>
                <div className="calc-line total">
                  <span>Decrease Spread:</span>
                  <span className="calc-num dec-tone">
                    {fmtSpread(decBig)} − {fmtSpread(decSmall)} = <b>{fmtSpread(row.decrease_spread)}</b>
                  </span>
                </div>
              </div>

              <div className="calc-block inc">
                <div className="calc-title">▲ Increase Spread = (Big.Ask × {bigMult}) − (Small.Bid × {smallMult})</div>
                <div className="calc-line">
                  <span>{cap(row.big)} Ask:</span>
                  <span className="calc-num">{fmtPx(row.big_ask)} × {bigMult} = <b>{fmtSpread(incBig)}</b></span>
                </div>
                <div className="calc-line">
                  <span>{cap(row.small)} Bid:</span>
                  <span className="calc-num">{fmtPx(row.small_bid)} × {smallMult} = <b>{fmtSpread(incSmall)}</b></span>
                </div>
                <div className="calc-line total">
                  <span>Increase Spread:</span>
                  <span className="calc-num inc-tone">
                    {fmtSpread(incBig)} − {fmtSpread(incSmall)} = <b>{fmtSpread(row.increase_spread)}</b>
                  </span>
                </div>
              </div>

              <div className="calc-block info">
                <div className="calc-title">Lot Ratio &amp; Live Quotes</div>
                <div className="calc-line"><span>Lots (Big / Small):</span><span className="calc-num"><b>{row.big_lots} / {row.small_lots}</b></span></div>
                <div className="calc-line"><span>{cap(row.big)} Bid / Ask:</span><span className="calc-num">{fmtPx(row.big_bid)} / {fmtPx(row.big_ask)}</span></div>
                <div className="calc-line"><span>{cap(row.small)} Bid / Ask:</span><span className="calc-num">{fmtPx(row.small_bid)} / {fmtPx(row.small_ask)}</span></div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}, (prev, next) => (
  prev.expanded === next.expanded &&
  prev.row.decrease_spread === next.row.decrease_spread &&
  prev.row.increase_spread === next.row.increase_spread &&
  prev.row.big_bid === next.row.big_bid &&
  prev.row.big_ask === next.row.big_ask &&
  prev.row.small_bid === next.row.small_bid &&
  prev.row.small_ask === next.row.small_ask &&
  prev.row.status === next.row.status &&
  prev.row.decrease_entry === next.row.decrease_entry &&
  prev.row.decrease_exit === next.row.decrease_exit &&
  prev.row.increase_entry === next.row.increase_entry &&
  prev.row.increase_exit === next.row.increase_exit &&
  prev.draft === next.draft
));

export default function LiveSpreadTable({ rows, onSaved }) {
  const [drafts, setDrafts] = useState({});
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState({});

  useEffect(() => {
    setDrafts((prev) => {
      const next = { ...prev };
      rows.forEach((r) => {
        if (!next[r.name]) {
          next[r.name] = {
            decrease_entry: r.decrease_entry ?? "",
            decrease_exit: r.decrease_exit ?? "",
            increase_entry: r.increase_entry ?? "",
            increase_exit: r.increase_exit ?? "",
          };
        }
      });
      return next;
    });
  }, [rows.length]);

  const counts = useMemo(() => ({
    all: rows.length,
    armed: rows.filter((r) => r.status === "armed").length,
    in_position: rows.filter((r) => r.status === "in_position").length,
    idle: rows.filter((r) => r.status === "idle").length,
  }), [rows]);

  const filtered = rows.filter((r) => {
    if (search && !r.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "all") return true;
    return r.status === filter;
  });

  function update(pair, field, value) {
    setDrafts((d) => ({ ...d, [pair]: { ...d[pair], [field]: value } }));
  }

  async function save(pair) {
    const d = drafts[pair] || {};
    const body = {
      decrease_entry: d.decrease_entry === "" ? null : Number(d.decrease_entry),
      decrease_exit: d.decrease_exit === "" ? null : Number(d.decrease_exit),
      increase_entry: d.increase_entry === "" ? null : Number(d.increase_entry),
      increase_exit: d.increase_exit === "" ? null : Number(d.increase_exit),
    };
    try {
      await api.saveRule(pair, body);
      onSaved();
    } catch (e) {
      alert(e.message);
    }
  }

  function clear(pair) {
    setDrafts((d) => ({
      ...d,
      [pair]: { decrease_entry: "", decrease_exit: "", increase_entry: "", increase_exit: "" },
    }));
  }

  function toggle(pair) {
    setExpanded((e) => ({ ...e, [pair]: !e[pair] }));
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>Live Spread Monitor</h2>
        <div className="header-controls">
          <div className="search-container">
            <input placeholder="Search pair..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="filter-tabs">
            <button className={`filter-tab ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
              All <span className="count">{counts.all}</span>
            </button>
            <button className={`filter-tab ${filter === "armed" ? "active" : ""}`} onClick={() => setFilter("armed")}>
              Armed <span className="count">{counts.armed}</span>
            </button>
            <button className={`filter-tab ${filter === "in_position" ? "active" : ""}`} onClick={() => setFilter("in_position")}>
              In Position <span className="count">{counts.in_position}</span>
            </button>
            <button className={`filter-tab ${filter === "idle" ? "active" : ""}`} onClick={() => setFilter("idle")}>
              Idle <span className="count">{counts.idle}</span>
            </button>
          </div>
        </div>
      </div>

      <div className="table-container">
        <table className="fixed">
          <colgroup>
            <col style={{ width: "14%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "12%" }} />
            <col style={{ width: "18%" }} />
          </colgroup>
          <thead>
            <tr>
              <th className="col-group cg-identity" colSpan={1}>Identity</th>
              <th className="col-group cg-decrease" colSpan={3}>▼ Decrease Premium</th>
              <th className="col-group cg-increase" colSpan={3}>▲ Increase Premium</th>
              <th className="col-group cg-status" colSpan={2}>Status</th>
            </tr>
            <tr>
              <th className="gc-identity col-end-group">Pair</th>
              <th className="gc-decrease">Spread</th>
              <th className="gc-decrease">Entry</th>
              <th className="gc-decrease col-end-group">Exit</th>
              <th className="gc-increase">Spread</th>
              <th className="gc-increase">Entry</th>
              <th className="gc-increase col-end-group">Exit</th>
              <th className="gc-status">State</th>
              <th className="gc-status">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={9} className="empty-state">No pairs match the filter.</td></tr>
            ) : filtered.map((r) => (
              <PairRow
                key={r.name}
                row={r}
                draft={drafts[r.name] || {}}
                expanded={!!expanded[r.name]}
                onToggle={() => toggle(r.name)}
                onChange={(field, value) => update(r.name, field, value)}
                onSave={() => save(r.name)}
                onClear={() => clear(r.name)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
