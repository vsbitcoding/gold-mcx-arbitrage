import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };

export default function LiveSpreadTable({ rows, onSaved }) {
  const [drafts, setDrafts] = useState({});

  useEffect(() => {
    const next = {};
    rows.forEach((r) => {
      next[r.name] = {
        decrease_entry: r.decrease_entry ?? "",
        decrease_exit: r.decrease_exit ?? "",
        increase_entry: r.increase_entry ?? "",
        increase_exit: r.increase_exit ?? "",
      };
    });
    setDrafts((prev) => ({ ...next, ...prev }));
  }, [rows.length]);

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
      <h2>Live Spread Monitor</h2>
      <table>
        <thead>
          <tr>
            <th>Pair</th>
            <th>Decrease Spread</th>
            <th>Dec Entry</th>
            <th>Dec Exit</th>
            <th>Increase Spread</th>
            <th>Inc Entry</th>
            <th>Inc Exit</th>
            <th>Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const d = drafts[r.name] || {};
            return (
              <tr key={r.name}>
                <td><strong>{r.name}</strong></td>
                <td className="spread-val">{r.decrease_spread ?? "—"}</td>
                <td className="dec-cell">
                  <input
                    className="cell"
                    type="number"
                    step="0.01"
                    value={d.decrease_entry ?? ""}
                    onChange={(e) => update(r.name, "decrease_entry", e.target.value)}
                  />
                </td>
                <td className="dec-cell">
                  <input
                    className="cell"
                    type="number"
                    step="0.01"
                    value={d.decrease_exit ?? ""}
                    onChange={(e) => update(r.name, "decrease_exit", e.target.value)}
                  />
                </td>
                <td className="spread-val">{r.increase_spread ?? "—"}</td>
                <td className="inc-cell">
                  <input
                    className="cell"
                    type="number"
                    step="0.01"
                    value={d.increase_entry ?? ""}
                    onChange={(e) => update(r.name, "increase_entry", e.target.value)}
                  />
                </td>
                <td className="inc-cell">
                  <input
                    className="cell"
                    type="number"
                    step="0.01"
                    value={d.increase_exit ?? ""}
                    onChange={(e) => update(r.name, "increase_exit", e.target.value)}
                  />
                </td>
                <td>
                  <span className={`status ${r.status}`}>{STATUS_LABEL[r.status] || r.status}</span>
                </td>
                <td>
                  <button className="btn save" onClick={() => save(r.name)}>Save</button>{" "}
                  <button className="btn" onClick={() => clear(r.name)}>Clear</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
