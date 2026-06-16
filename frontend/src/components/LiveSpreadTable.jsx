import React, { useEffect, useMemo, useRef, useState } from "react";
import SpreadCards from "./spread/SpreadCards.jsx";
import { PAIR_PAGE_SIZE } from "./spread/constants.js";
import MetalSpread, { otherCommColorKey } from "./MetalSpread.jsx";
import PriceTable from "./PriceTable.jsx";
import SignalsPanel from "./SignalsPanel.jsx";
import { useToast } from "./Toast.jsx";
import { api } from "../api/client.js";

// Tabs that show their own watch-only cards (no search/filter/pagination).
const WATCH_TABS = ["signals", "metals", "price", "othercomm"];

export default function LiveSpreadTable({ rows }) {
  const toast = useToast();
  const sigSeen = useRef(null);
  const [search, setSearch] = useState("");
  const [expiryFilter, setExpiryFilter] = useState("all");
  const [tab, setTab] = useState(() => {
    const t = localStorage.getItem("arbi_spread_tab");
    return ["signals", "cross", "calendar", "metals", "price", "othercomm"].includes(t) ? t : "cross";
  });
  useEffect(() => { localStorage.setItem("arbi_spread_tab", tab); }, [tab]);
  const [sort, setSort] = useState({ field: null, dir: "asc" });
  const [page, setPage] = useState(1);
  const [metalData, setMetalData] = useState(null);
  const [otherCommData, setOtherCommData] = useState(null);
  const [priceData, setPriceData] = useState(null);

  // Watch-only tab data (Metal / Other Commodity / Price) — fetched here so the
  // tab badges can show counts; all paused together when the page is hidden.
  useEffect(() => {
    let alive = true;
    let timer = null;
    async function load() {
      try {
        const [m, o, p] = await Promise.all([
          api.metalsSpread().catch(() => null),
          api.otherCommSpread().catch(() => null),
          api.priceTable().catch(() => null),
        ]);
        if (!alive) return;
        if (m) setMetalData(m);
        if (o) setOtherCommData(o);
        if (p) setPriceData(p);
      } catch { /* keep last */ }
    }
    function start() { if (!timer) timer = setInterval(load, 2000); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function onVis() { if (document.hidden) stop(); else { load(); start(); } }
    load();
    start();
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; stop(); document.removeEventListener("visibilitychange", onVis); };
  }, []);

  const crossRows = useMemo(() => rows.filter((r) => r.type === "cross"), [rows]);
  const calendarRows = useMemo(() => rows.filter((r) => r.type === "calendar"), [rows]);
  const signalRows = useMemo(() => rows.filter((r) => r.signal), [rows]);
  const tabRows = tab === "cross" ? crossRows : calendarRows;

  // In-app alert: toast when a NEW signal appears (skip the first load).
  useEffect(() => {
    const cur = new Map(signalRows.map((r) => [r.name, r.signal.direction]));
    if (sigSeen.current === null) { sigSeen.current = cur; return; }
    for (const [name, dir] of cur) {
      if (sigSeen.current.get(name) !== dir) {
        const r = signalRows.find((x) => x.name === name);
        if (r) toast.info(`⚡ ${r.label} ${r.expiry_label}: ${dir === "narrow" ? "NARROW ▼" : "WIDEN ▲"} → target ${r.signal.target}${r.signal.probability != null ? ` · ${r.signal.probability}% chance` : ""}`);
      }
    }
    sigSeen.current = cur;
  }, [signalRows, toast]);

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

  useEffect(() => { setPage(1); }, [tab, search, expiryFilter, sort.field, sort.dir]);

  function resetFilters() {
    setSearch("");
    setExpiryFilter("all");
    setSort({ field: null, dir: "asc" });
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>Live Spread Monitor</h2>
        <div className="header-controls" aria-hidden={WATCH_TABS.includes(tab)} style={{ visibility: WATCH_TABS.includes(tab) ? "hidden" : "visible" }}>
            <div className="search-container">
              <input placeholder="Search pair / month..." value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <select className="expiry-filter" value={expiryFilter} onChange={(e) => setExpiryFilter(e.target.value)}>
              <option value="all">All expiries</option>
              {expiryOptions.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
            </select>
            {(search || expiryFilter !== "all" || sort.field) && (
              <button className="btn btn-secondary btn-sm" onClick={resetFilters} title="Clear filters & sort">Reset</button>
            )}
        </div>
        <div className="pair-tabs">
          <button className={`pair-tab pair-tab-signals ${tab === "signals" ? "active" : ""}`} onClick={() => setTab("signals")}>
            ⚡ Signals <span className="count">{signalRows.length}</span>
          </button>
          <button className={`pair-tab ${tab === "cross" ? "active" : ""}`} onClick={() => setTab("cross")}>
            Cross Pairs <span className="count">{crossRows.length}</span>
          </button>
          <button className={`pair-tab ${tab === "calendar" ? "active" : ""}`} onClick={() => setTab("calendar")}>
            Calendar Spreads <span className="count">{calendarRows.length}</span>
          </button>
          <button className={`pair-tab ${tab === "metals" ? "active" : ""}`} onClick={() => setTab("metals")}>
            Metal <span className="count">{metalData?.count ?? 0}</span>
          </button>
          <button className={`pair-tab ${tab === "price" ? "active" : ""}`} onClick={() => setTab("price")}>
            Price <span className="count">{priceData?.count ?? 0}</span>
          </button>
          <button className={`pair-tab ${tab === "othercomm" ? "active" : ""}`} onClick={() => setTab("othercomm")}>
            Other Commodity <span className="count">{otherCommData?.count ?? 0}</span>
          </button>
        </div>
      </div>

      {tab === "signals" && <SignalsPanel signals={signalRows} />}
      {tab === "metals" && <MetalSpread data={metalData} embedded />}
      {tab === "price" && <PriceTable data={priceData} embedded />}
      {tab === "othercomm" && (
        <MetalSpread
          data={otherCommData}
          embedded
          showPct={false}
          colorFn={otherCommColorKey}
          loadingText="Loading other-commodity data…"
        />
      )}

      {!WATCH_TABS.includes(tab) && (
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
