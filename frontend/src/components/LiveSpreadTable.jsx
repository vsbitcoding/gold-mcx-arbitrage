import React, { useEffect, useMemo, useState } from "react";
import { FrontRow, OtherMonthRow, SortableTh } from "./spread/SpreadRows.jsx";
import { LadderModal, PositionsModal, HistoryModal } from "./spread/Modals.jsx";
import { PAIR_PAGE_SIZE } from "./spread/constants.js";

function SkeletonRows({ count = 6 }) {
  return Array.from({ length: count }).map((_, i) => (
    <tr key={`skel:${i}`} className="skel-row">
      {Array.from({ length: 10 }).map((__, j) => (
        <td key={j}><div className="skel-bar" /></td>
      ))}
    </tr>
  ));
}

export default function LiveSpreadTable({ rows, onSaved }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [expiryFilter, setExpiryFilter] = useState("all");
  const [tab, setTab] = useState("cross");
  const [sort, setSort] = useState({ field: null, dir: "asc" });
  const [page, setPage] = useState(1);
  const [openPair, setOpenPair] = useState(null);
  const [openPositionsPair, setOpenPositionsPair] = useState(null);
  const [openHistoryPair, setOpenHistoryPair] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});

  function toggleGroup(label) {
    setExpandedGroups((g) => ({ ...g, [label]: !g[label] }));
  }

  const crossRows = useMemo(() => rows.filter((r) => r.type === "cross"), [rows]);
  const calendarRows = useMemo(() => rows.filter((r) => r.type === "calendar"), [rows]);
  const tabRows = tab === "cross" ? crossRows : calendarRows;

  const expiryOptions = useMemo(() => {
    const seen = new Set();
    const opts = [];
    tabRows.forEach((r) => {
      const k = r.expiry_label || "";
      if (k && !seen.has(k)) {
        seen.add(k);
        opts.push(k);
      }
    });
    return opts;
  }, [tabRows]);

  const counts = useMemo(() => ({
    all: tabRows.length,
    armed: tabRows.filter((r) => r.status === "armed").length,
    in_position: tabRows.filter((r) => r.status === "in_position").length,
    idle: tabRows.filter((r) => r.status === "idle").length,
  }), [tabRows]);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    return tabRows.filter((r) => {
      if (term) {
        const hit =
          (r.name || "").toLowerCase().includes(term) ||
          (r.label || "").toLowerCase().includes(term) ||
          (r.expiry_label || "").toLowerCase().includes(term);
        if (!hit) return false;
      }
      if (expiryFilter !== "all" && r.expiry_label !== expiryFilter) return false;
      if (filter === "all") return true;
      return r.status === filter;
    });
  }, [tabRows, search, filter, expiryFilter]);

  const sortedRows = useMemo(() => {
    if (!sort.field) return filtered;
    const dir = sort.dir === "asc" ? 1 : -1;
    const field = sort.field;
    function key(r) {
      switch (field) {
        case "label": return (r.label || "").toLowerCase();
        case "expiry": return r.big_expiry || r.expiry_label || "";
        case "decrease_spread": return r.decrease_spread ?? -Infinity;
        case "increase_spread": return r.increase_spread ?? -Infinity;
        case "status": return r.status || "";
        case "decrease_count": return r.decrease_ladders.length;
        case "increase_count": return r.increase_ladders.length;
        default: return 0;
      }
    }
    return [...filtered].sort((a, b) => {
      const ka = key(a), kb = key(b);
      if (ka < kb) return -1 * dir;
      if (ka > kb) return 1 * dir;
      return 0;
    });
  }, [filtered, sort]);

  const groupedRows = useMemo(() => {
    const map = new Map();
    for (const r of sortedRows) {
      const k = r.group_label || r.label;
      if (!map.has(k)) map.set(k, { label: k, rows: [] });
      map.get(k).rows.push(r);
    }
    return Array.from(map.values());
  }, [sortedRows]);

  const totalPages = Math.max(1, Math.ceil(groupedRows.length / PAIR_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PAIR_PAGE_SIZE;
  const sliceGroups = groupedRows.slice(start, start + PAIR_PAGE_SIZE);

  useEffect(() => { setPage(1); }, [tab, filter, search, expiryFilter, sort.field, sort.dir]);

  const openRow = openPair ? rows.find((r) => r.name === openPair) : null;
  const positionsRow = openPositionsPair ? rows.find((r) => r.name === openPositionsPair) : null;
  const historyRow = openHistoryPair ? rows.find((r) => r.name === openHistoryPair) : null;

  function resetFilters() {
    setSearch("");
    setFilter("all");
    setExpiryFilter("all");
    setSort({ field: null, dir: "asc" });
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>Live Spread Monitor</h2>
        <div className="pair-tabs">
          <button className={`pair-tab ${tab === "cross" ? "active" : ""}`} onClick={() => setTab("cross")}>
            Cross Pairs <span className="count">{crossRows.length}</span>
          </button>
          <button className={`pair-tab ${tab === "calendar" ? "active" : ""}`} onClick={() => setTab("calendar")}>
            Calendar Spreads <span className="count">{calendarRows.length}</span>
          </button>
        </div>
        <div className="header-controls">
          <div className="search-container">
            <input placeholder="Search pair / month..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <select className="expiry-filter" value={expiryFilter} onChange={(e) => setExpiryFilter(e.target.value)}>
            <option value="all">All expiries</option>
            {expiryOptions.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
          </select>
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
          {(search || filter !== "all" || expiryFilter !== "all" || sort.field) && (
            <button className="btn btn-secondary btn-sm" onClick={resetFilters} title="Clear filters & sort">Reset</button>
          )}
        </div>
      </div>

      <div className="table-container">
        <table className="pair-table fixed">
          <colgroup>
            <col style={{ width: "13%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "7%" }} />
            <col style={{ width: "7%" }} />
            <col style={{ width: "15%" }} />
          </colgroup>
          <thead>
            <tr className="group-row">
              <th colSpan={2} className="cg-identity col-end-group">Identity</th>
              <th colSpan={2} className="cg-ltp col-end-group">LTP</th>
              <th className="cg-decrease">▼ Decrease</th>
              <th className="cg-increase col-end-group">▲ Increase</th>
              <th colSpan={3} className="cg-status col-end-group">Status</th>
              <th className="cg-action">Action</th>
            </tr>
            <tr>
              <SortableTh label={tab === "cross" ? "Pair" : "Spread"} field="label" sort={sort} setSort={setSort} className="gc-identity" />
              <SortableTh label="Expiry" field="expiry" sort={sort} setSort={setSort} className="gc-identity col-end-group" />
              <th className="gc-ltp">Big</th>
              <th className="gc-ltp col-end-group">Small</th>
              <SortableTh label="Spread" field="decrease_spread" sort={sort} setSort={setSort} className="gc-decrease" />
              <SortableTh label="Spread" field="increase_spread" sort={sort} setSort={setSort} className="gc-increase col-end-group" />
              <SortableTh label="Status" field="status" sort={sort} setSort={setSort} className="gc-status" />
              <SortableTh label="Dec ▼" field="decrease_count" sort={sort} setSort={setSort} className="gc-status" />
              <SortableTh label="Inc ▲" field="increase_count" sort={sort} setSort={setSort} className="gc-status col-end-group" />
              <th className="gc-action">&nbsp;</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <SkeletonRows />
            ) : groupedRows.length === 0 ? (
              <tr><td colSpan={10} className="empty-state">No pairs match the filter.</td></tr>
            ) : sliceGroups.flatMap((g) => {
              const isOpen = !!expandedGroups[g.label];
              const sortedByExpiry = [...g.rows].sort((a, b) =>
                (a.big_expiry || "") < (b.big_expiry || "") ? -1 : 1
              );
              const front = sortedByExpiry[0];
              const others = sortedByExpiry.slice(1);
              return [
                <FrontRow
                  key={`f:${g.label}`}
                  row={front}
                  label={g.label}
                  hasMore={others.length > 0}
                  expanded={isOpen}
                  onToggle={() => toggleGroup(g.label)}
                  onManage={(n) => setOpenPair(n)}
                  onPositions={(n) => setOpenPositionsPair(n)}
                  onHistory={(n) => setOpenHistoryPair(n)}
                />,
                ...(isOpen ? others.map((r, idx) => (
                  <OtherMonthRow
                    key={r.name}
                    row={r}
                    isLast={idx === others.length - 1}
                    onManage={(n) => setOpenPair(n)}
                    onPositions={(n) => setOpenPositionsPair(n)}
                    onHistory={(n) => setOpenHistoryPair(n)}
                  />
                )) : []),
              ];
            })}
          </tbody>
        </table>
      </div>

      {groupedRows.length > PAIR_PAGE_SIZE && (
        <div className="pagination-controls">
          <div>Showing {start + 1}-{Math.min(start + PAIR_PAGE_SIZE, groupedRows.length)} of {groupedRows.length} groups</div>
          <div className="pager">
            <button onClick={() => setPage(1)} disabled={safePage === 1}>«</button>
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage === 1}>‹</button>
            <button className="active">{safePage}</button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}>›</button>
            <button onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</button>
          </div>
        </div>
      )}

      {openRow && <LadderModal row={openRow} onClose={() => setOpenPair(null)} onChange={onSaved} />}
      {positionsRow && <PositionsModal row={positionsRow} onClose={() => setOpenPositionsPair(null)} />}
      {historyRow && <HistoryModal row={historyRow} onClose={() => setOpenHistoryPair(null)} />}
    </div>
  );
}
