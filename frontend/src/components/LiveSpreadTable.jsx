import React, { useEffect, useMemo, useState, memo } from "react";
import { api } from "../api/client.js";
import SpreadCell from "./SpreadCell.jsx";

const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };

const PairRow = memo(function PairRow({ row, draft, onChange, onSave, onClear }) {
  return (
    <tr>
      <td className="pair-name">{row.name}</td>

      <td className="cell-mid sec-dec">
        <SpreadCell value={row.decrease_spread} tone="dec" />
      </td>
      <td className="cell-mid sec-dec">
        <input
          className="cell"
          type="number"
          step="0.01"
          placeholder="—"
          value={draft.decrease_entry ?? ""}
          onChange={(e) => onChange("decrease_entry", e.target.value)}
        />
      </td>
      <td className="cell-mid sec-dec sec-dec-end">
        <input
          className="cell"
          type="number"
          step="0.01"
          placeholder="—"
          value={draft.decrease_exit ?? ""}
          onChange={(e) => onChange("decrease_exit", e.target.value)}
        />
      </td>

      <td className="cell-mid sec-inc">
        <SpreadCell value={row.increase_spread} tone="inc" />
      </td>
      <td className="cell-mid sec-inc">
        <input
          className="cell"
          type="number"
          step="0.01"
          placeholder="—"
          value={draft.increase_entry ?? ""}
          onChange={(e) => onChange("increase_entry", e.target.value)}
        />
      </td>
      <td className="cell-mid sec-inc sec-inc-end">
        <input
          className="cell"
          type="number"
          step="0.01"
          placeholder="—"
          value={draft.increase_exit ?? ""}
          onChange={(e) => onChange("increase_exit", e.target.value)}
        />
      </td>

      <td>
        <span className={`status ${row.status}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
      </td>
      <td>
        <div className="row-actions">
          <button className="btn-sm primary" onClick={onSave}>Save</button>
          <button className="btn-sm" onClick={onClear}>Clear</button>
        </div>
      </td>
    </tr>
  );
}, (prev, next) => {
  // Only re-render if the relevant values changed
  return (
    prev.row.decrease_spread === next.row.decrease_spread &&
    prev.row.increase_spread === next.row.increase_spread &&
    prev.row.status === next.row.status &&
    prev.row.decrease_entry === next.row.decrease_entry &&
    prev.row.decrease_exit === next.row.decrease_exit &&
    prev.row.increase_entry === next.row.increase_entry &&
    prev.row.increase_exit === next.row.increase_exit &&
    prev.draft === next.draft
  );
});

export default function LiveSpreadTable({ rows, onSaved }) {
  const [drafts, setDrafts] = useState({});
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");

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

  return (
    <div className="card">
      <div className="card-head">
        <h2>Live Spread Monitor</h2>
        <div className="toolbar">
          <input
            className="search"
            placeholder="Search pair..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className={`pill ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
            All <span className="count">{counts.all}</span>
          </button>
          <button className={`pill ${filter === "armed" ? "active" : ""}`} onClick={() => setFilter("armed")}>
            Armed <span className="count">{counts.armed}</span>
          </button>
          <button className={`pill ${filter === "in_position" ? "active" : ""}`} onClick={() => setFilter("in_position")}>
            In Position <span className="count">{counts.in_position}</span>
          </button>
          <button className={`pill ${filter === "idle" ? "active" : ""}`} onClick={() => setFilter("idle")}>
            Idle <span className="count">{counts.idle}</span>
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table className="spread-table fixed">
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
          <thead className="grouped">
            <tr className="groups">
              <th className="g-identity">Identity</th>
              <th className="g-dec" colSpan={3}>
                <span className="g-icon">▼</span> Decrease Premium
              </th>
              <th className="g-inc" colSpan={3}>
                <span className="g-icon">▲</span> Increase Premium
              </th>
              <th className="g-status" colSpan={2}>Status</th>
            </tr>
            <tr className="cols">
              <th>Pair</th>
              <th className="sec-dec">Spread</th>
              <th className="sec-dec">Entry</th>
              <th className="sec-dec sec-dec-end">Exit</th>
              <th className="sec-inc">Spread</th>
              <th className="sec-inc">Entry</th>
              <th className="sec-inc sec-inc-end">Exit</th>
              <th>State</th>
              <th style={{ textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={9} className="empty">No pairs match the filter.</td></tr>
            ) : filtered.map((r) => (
              <PairRow
                key={r.name}
                row={r}
                draft={drafts[r.name] || {}}
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
