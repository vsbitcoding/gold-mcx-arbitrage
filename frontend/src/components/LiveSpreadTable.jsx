import React, { useEffect, useMemo, useRef, useState } from "react";
import SpreadCards from "./spread/SpreadCards.jsx";
import { PAIR_PAGE_SIZE } from "./spread/constants.js";
import MetalSpread, { otherCommColorKey } from "./MetalSpread.jsx";
import PriceTable from "./PriceTable.jsx";
import SignalsPanel from "./SignalsPanel.jsx";
import { useToast } from "./Toast.jsx";

// `tab` is driven by the top nav bar (App). This component just renders the
// active tab's content (signals / cross / calendar / metals / price / othercomm).
export default function LiveSpreadTable({ rows, tab, metalData, otherCommData, priceData }) {
  const toast = useToast();
  const sigSeen = useRef(null);
  const [search, setSearch] = useState("");
  const [expiryFilter, setExpiryFilter] = useState("all");
  const [page, setPage] = useState(1);

  const crossRows = useMemo(() => rows.filter((r) => r.type === "cross"), [rows]);
  const calendarRows = useMemo(() => rows.filter((r) => r.type === "calendar"), [rows]);
  const signalRows = useMemo(() => rows.filter((r) => r.signal), [rows]);

  // In-app alert: toast when a NEW signal appears (skip the first load).
  useEffect(() => {
    const cur = new Map(signalRows.map((r) => [r.name, r.signal.direction]));
    if (sigSeen.current === null) { sigSeen.current = cur; return; }
    for (const [name, dir] of cur) {
      if (sigSeen.current.get(name) !== dir) {
        const r = signalRows.find((x) => x.name === name);
        if (r) toast.info(`⚡ ${r.label} ${r.expiry_label}: ${dir === "narrow" ? "NARROW ▼" : "WIDEN ▲"} → target ${r.signal.target}`);
      }
    }
    sigSeen.current = cur;
  }, [signalRows, toast]);

  const isSpread = tab === "cross" || tab === "calendar";
  const tabRows = tab === "cross" ? crossRows : calendarRows;

  const expiryOptions = useMemo(() => {
    const seen = new Set(); const opts = [];
    tabRows.forEach((r) => {
      const k = r.expiry_label || "";
      if (k && !seen.has(k)) { seen.add(k); opts.push(k); }
    });
    return opts;
  }, [tabRows]);

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
      return true;
    });
  }, [tabRows, search, expiryFilter]);

  const groupedRows = useMemo(() => {
    const map = new Map();
    for (const r of filtered) {
      const k = r.group_label || r.label;
      if (!map.has(k)) map.set(k, { label: k, rows: [] });
      map.get(k).rows.push(r);
    }
    return Array.from(map.values());
  }, [filtered]);

  const totalPages = Math.max(1, Math.ceil(groupedRows.length / PAIR_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PAIR_PAGE_SIZE;
  const sliceGroups = groupedRows.slice(start, start + PAIR_PAGE_SIZE);
  useEffect(() => { setPage(1); }, [tab, search, expiryFilter]);

  return (
    <div className="sessions-container">
      {isSpread && (
        <div className="sessions-header">
          <div className="header-controls">
            <div className="search-container">
              <input placeholder="Search pair / month..." value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <select className="expiry-filter" value={expiryFilter} onChange={(e) => setExpiryFilter(e.target.value)}>
              <option value="all">All expiries</option>
              {expiryOptions.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
            </select>
            {(search || expiryFilter !== "all") && (
              <button className="btn btn-secondary btn-sm" onClick={() => { setSearch(""); setExpiryFilter("all"); }} title="Clear filters">Reset</button>
            )}
          </div>
        </div>
      )}

      {tab === "signals" && <SignalsPanel signals={signalRows} />}
      {tab === "metals" && <MetalSpread data={metalData} embedded />}
      {tab === "price" && <PriceTable data={priceData} embedded />}
      {tab === "othercomm" && (
        <MetalSpread data={otherCommData} embedded showPct={false} colorFn={otherCommColorKey} loadingText="Loading other-commodity data…" />
      )}

      {isSpread && (
        rows.length === 0 ? (
          <div className="empty-state" style={{ padding: "24px 16px" }}>Loading…</div>
        ) : (
          <>
            <SpreadCards groups={sliceGroups} />
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
          </>
        )
      )}
    </div>
  );
}
