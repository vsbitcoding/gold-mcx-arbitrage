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
  const seeded = useRef(false);
  const [page, setPage] = useState(1);

  const crossRows = useMemo(() => rows.filter((r) => r.type === "cross"), [rows]);
  const calendarRows = useMemo(() => rows.filter((r) => r.type === "calendar"), [rows]);
  const signalRows = useMemo(() => rows.filter((r) => r.signal), [rows]);

  // In-app alert: toast ONLY when a genuinely new signal appears. The baseline
  // is set once the live data has first loaded, so existing signals never
  // re-notify on a page refresh / reconnect.
  useEffect(() => {
    if (!rows.length) return;                       // wait for the first live snapshot
    const cur = new Map(signalRows.map((r) => [r.name, r.signal.direction]));
    if (!seeded.current) {                          // first loaded snapshot → baseline only
      seeded.current = true;
      sigSeen.current = cur;
      return;
    }
    for (const [name, dir] of cur) {
      if (sigSeen.current.get(name) !== dir) {
        const r = signalRows.find((x) => x.name === name);
        if (r) toast.info(`⚡ ${r.label} ${r.expiry_label}: ${dir === "narrow" ? "NARROW ▼" : "WIDEN ▲"} → target ${r.signal.target}`);
      }
    }
    sigSeen.current = cur;
  }, [rows, signalRows, toast]);

  const isSpread = tab === "cross" || tab === "calendar";
  const tabRows = tab === "cross" ? crossRows : calendarRows;

  const groupedRows = useMemo(() => {
    const map = new Map();
    for (const r of tabRows) {
      const k = r.group_label || r.label;
      if (!map.has(k)) map.set(k, { label: k, rows: [] });
      map.get(k).rows.push(r);
    }
    return Array.from(map.values());
  }, [tabRows]);

  const totalPages = Math.max(1, Math.ceil(groupedRows.length / PAIR_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PAIR_PAGE_SIZE;
  const sliceGroups = groupedRows.slice(start, start + PAIR_PAGE_SIZE);
  useEffect(() => { setPage(1); }, [tab]);

  return (
    <div className="sessions-container">
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
