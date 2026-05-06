import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";

const ACTION_META = {
  ladder_created: { label: "Created", cls: "act-create" },
  ladder_updated: { label: "Updated", cls: "act-update" },
  ladder_deleted: { label: "Deleted", cls: "act-delete" },
  fire: { label: "Fire", cls: "act-fire" },
  exit: { label: "Exit", cls: "act-exit" },
  history_deleted: { label: "History Del", cls: "act-delete" },
  history_purged: { label: "Auto-Purge", cls: "act-system" },
  daily_clear: { label: "Daily Clear", cls: "act-system" },
};

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true,
  });
}

export default function Activity() {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [days, setDays] = useState(7);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    async function load() {
      try {
        const params = { days, limit: 500 };
        if (filter !== "all") params.action = filter;
        const r = await api.activity(params);
        if (!alive) return;
        setEvents(r.events || []);
        setTotal(r.total || 0);
      } catch {}
      finally { if (alive) setLoading(false); }
    }
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [days, filter]);

  const counts = useMemo(() => {
    const c = { all: events.length };
    for (const e of events) c[e.action] = (c[e.action] || 0) + 1;
    return c;
  }, [events]);

  return (
    <div className="sessions-container activity-page">
      <div className="sessions-header">
        <h2>Activity Log</h2>
        <div className="header-controls">
          <select className="expiry-filter" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Last 24 h</option>
            <option value={3}>Last 3 days</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
          </select>
          <div className="filter-tabs">
            <button className={`filter-tab ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
              All <span className="count">{counts.all || 0}</span>
            </button>
            <button className={`filter-tab ${filter === "fire" ? "active" : ""}`} onClick={() => setFilter("fire")}>
              Fires <span className="count">{counts.fire || 0}</span>
            </button>
            <button className={`filter-tab ${filter === "exit" ? "active" : ""}`} onClick={() => setFilter("exit")}>
              Exits <span className="count">{counts.exit || 0}</span>
            </button>
            <button className={`filter-tab ${filter === "ladder_created" ? "active" : ""}`} onClick={() => setFilter("ladder_created")}>
              Created <span className="count">{counts.ladder_created || 0}</span>
            </button>
            <button className={`filter-tab ${filter === "ladder_updated" ? "active" : ""}`} onClick={() => setFilter("ladder_updated")}>
              Updated <span className="count">{counts.ladder_updated || 0}</span>
            </button>
            <button className={`filter-tab ${filter === "ladder_deleted" ? "active" : ""}`} onClick={() => setFilter("ladder_deleted")}>
              Deleted <span className="count">{counts.ladder_deleted || 0}</span>
            </button>
          </div>
        </div>
      </div>

      <div className="info-table-wrap activity-table-wrap">
        <table className="info-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Action</th>
              <th>Pair</th>
              <th>Side</th>
              <th>Detail</th>
              <th>By</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr><td colSpan={6} className="empty-state">{loading ? "Loading…" : "No activity in this window."}</td></tr>
            ) : events.map((e) => {
              const meta = ACTION_META[e.action] || { label: e.action, cls: "" };
              return (
                <tr key={e.id}>
                  <td className="num time-cell">{fmtTime(e.timestamp)}</td>
                  <td><span className={`badge ${meta.cls}`}>{meta.label}</span></td>
                  <td className="num">{e.pair_name || "—"}</td>
                  <td>{e.side ? <span className={`badge ${e.side === "decrease" ? "badge-decrease" : "badge-increase"}`}>{e.side}</span> : "—"}</td>
                  <td style={{ textAlign: "left", whiteSpace: "normal" }}>{e.summary || "—"}</td>
                  <td><span className={`badge actor-${e.actor || "user"}`}>{e.actor || "user"}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {total > events.length && (
        <div className="pagination-controls">
          <div>Showing latest {events.length} of {total}</div>
        </div>
      )}
    </div>
  );
}
