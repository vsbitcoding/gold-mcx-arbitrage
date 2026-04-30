import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";

const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };

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
        <table>
          <thead className="grouped">
            <tr className="groups">
              <th className="g-identity" colSpan={1}>Identity</th>
              <th className="g-dec" colSpan={3}>Decrease Premium</th>
              <th className="g-inc" colSpan={3}>Increase Premium</th>
              <th className="g-status" colSpan={2}>Status</th>
            </tr>
            <tr className="cols">
              <th>Pair</th>
              <th>Spread</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Spread</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>State</th>
              <th style={{ textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={9} className="empty">No pairs match the filter.</td></tr>
            ) : filtered.map((r) => {
              const d = drafts[r.name] || {};
              return (
                <tr key={r.name}>
                  <td className="pair-name">{r.name}</td>
                  <td className="spread dec-tone">{r.decrease_spread ?? "—"}</td>
                  <td className="dec-cell">
                    <input
                      className="cell"
                      type="number"
                      step="0.01"
                      placeholder="—"
                      value={d.decrease_entry ?? ""}
                      onChange={(e) => update(r.name, "decrease_entry", e.target.value)}
                    />
                  </td>
                  <td className="dec-cell">
                    <input
                      className="cell"
                      type="number"
                      step="0.01"
                      placeholder="—"
                      value={d.decrease_exit ?? ""}
                      onChange={(e) => update(r.name, "decrease_exit", e.target.value)}
                    />
                  </td>
                  <td className="spread inc-tone">{r.increase_spread ?? "—"}</td>
                  <td className="inc-cell">
                    <input
                      className="cell"
                      type="number"
                      step="0.01"
                      placeholder="—"
                      value={d.increase_entry ?? ""}
                      onChange={(e) => update(r.name, "increase_entry", e.target.value)}
                    />
                  </td>
                  <td className="inc-cell">
                    <input
                      className="cell"
                      type="number"
                      step="0.01"
                      placeholder="—"
                      value={d.increase_exit ?? ""}
                      onChange={(e) => update(r.name, "increase_exit", e.target.value)}
                    />
                  </td>
                  <td>
                    <span className={`status ${r.status}`}>
                      <span className="blip" />
                      {STATUS_LABEL[r.status] || r.status}
                    </span>
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="btn-sm primary" onClick={() => save(r.name)}>Save</button>
                      <button className="btn-sm" onClick={() => clear(r.name)}>Clear</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
