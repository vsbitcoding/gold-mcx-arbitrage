import React, { useMemo, useState } from "react";

function fmt(d) {
  return d ? new Date(d).toLocaleString("en-IN", { hour12: false }) : "—";
}
function fmtPx(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(2);
}
function fmtDur(secs) {
  if (!secs) return "—";
  const m = Math.floor(secs / 60);
  if (m < 1) return `${Math.floor(secs)}s`;
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : ""; }

function LegBlock({ action, instrument, lots, entryPx, exitPx }) {
  const cls = action === "BUY" ? "leg-buy" : "leg-sell";
  const d = (entryPx !== null && exitPx !== null) ? Number(exitPx) - Number(entryPx) : null;
  return (
    <div className={`leg-block ${cls}`}>
      <div className="leg-head">
        <span className="leg-action">{action}</span>
        <span className="leg-instrument">{cap(instrument)}</span>
        <span className="leg-lots">{lots} lots</span>
      </div>
      <div className="leg-prices">
        <div>
          <span className="leg-label">Entry @</span>
          <span className="leg-price">{fmtPx(entryPx)}</span>
        </div>
        <div className="leg-arrow">→</div>
        <div>
          <span className="leg-label">Exit @</span>
          <span className="leg-price">{fmtPx(exitPx)}</span>
        </div>
        {d !== null && (
          <div className={`leg-delta ${d >= 0 ? "pos" : "neg"}`}>
            {d >= 0 ? "+" : ""}{d.toFixed(2)}
          </div>
        )}
      </div>
    </div>
  );
}

export default function TradeHistory({ rows }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState({});
  const PER = 10;

  const totals = useMemo(() => {
    const wins = rows.filter((r) => r.pnl > 0);
    const losses = rows.filter((r) => r.pnl <= 0);
    const net = rows.reduce((s, r) => s + (r.pnl || 0), 0);
    return { net, wins: wins.length, losses: losses.length };
  }, [rows]);

  const filtered = rows.filter((r) => {
    if (search && !r.pair_name.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "win") return r.pnl > 0;
    if (filter === "loss") return r.pnl <= 0;
    return true;
  });
  const start = (page - 1) * PER;
  const slice = filtered.slice(start, start + PER);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PER));

  function toggle(id) {
    setExpanded((e) => ({ ...e, [id]: !e[id] }));
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>
          Trade History <span style={{ color: "var(--text-muted)", fontWeight: 500, marginLeft: 6 }}>({rows.length})</span>
          <span style={{ marginLeft: 14, fontSize: 13, fontWeight: 600 }} className={totals.net >= 0 ? "pnl-positive" : "pnl-negative"}>
            Net: {totals.net >= 0 ? "+" : ""}{totals.net.toFixed(2)}
          </span>
        </h2>
        <div className="header-controls">
          <div className="search-container">
            <input placeholder="Search pair..." value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          </div>
          <div className="filter-tabs">
            <button className={`filter-tab ${filter === "all" ? "active" : ""}`} onClick={() => { setFilter("all"); setPage(1); }}>
              All <span className="count">{rows.length}</span>
            </button>
            <button className={`filter-tab ${filter === "win" ? "active" : ""}`} onClick={() => { setFilter("win"); setPage(1); }}>
              Wins <span className="count">{totals.wins}</span>
            </button>
            <button className={`filter-tab ${filter === "loss" ? "active" : ""}`} onClick={() => { setFilter("loss"); setPage(1); }}>
              Losses <span className="count">{totals.losses}</span>
            </button>
          </div>
        </div>
      </div>
      <div className="table-container">
        {filtered.length === 0 ? (
          <div className="empty-state">No trades match the filter.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Pair</th>
                <th>Mode</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Move</th>
                <th>Lots</th>
                <th>Weight</th>
                <th>Duration</th>
                <th>Closed By</th>
                <th>PnL</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => {
                const isOpen = !!expanded[r.id];
                const move = (r.entry_spread != null && r.exit_spread != null)
                  ? Number(r.exit_spread) - Number(r.entry_spread) : null;
                const moveCls = move === null ? "" : (move >= 0 ? "pnl-positive" : "pnl-negative");
                return (
                  <React.Fragment key={r.id}>
                    <tr className={isOpen ? "expanded" : ""}>
                      <td style={{ width: 30 }}>
                        <button className="row-toggle" onClick={() => toggle(r.id)} title="Show details">
                          <span className="caret">{isOpen ? "▾" : "▸"}</span>
                        </button>
                      </td>
                      <td className="pair-name">{r.pair_name}</td>
                      <td>
                        <span className={`badge ${r.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>
                          {cap(r.mode)}
                        </span>
                      </td>
                      <td className="spread-num">{Number(r.entry_spread).toFixed(2)}</td>
                      <td className="spread-num">{Number(r.exit_spread).toFixed(2)}</td>
                      <td className={`spread-num ${moveCls}`}>
                        {move === null ? "—" : (move >= 0 ? "+" : "") + move.toFixed(2)}
                      </td>
                      <td>{r.big_lots}/{r.small_lots}</td>
                      <td>{r.weight_grams ? `${r.weight_grams}g` : "—"}</td>
                      <td>{fmtDur(r.duration_seconds)}</td>
                      <td style={{ textTransform: "capitalize", color: "var(--text-muted)" }}>{r.closed_by}</td>
                      <td className={r.pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                        {r.pnl >= 0 ? "+" : ""}{r.pnl}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="position-detail-row">
                        <td colSpan={11}>
                          <div className="position-detail">
                            <LegBlock
                              action={r.big_action}
                              instrument={r.big_instrument}
                              lots={r.big_lots}
                              entryPx={r.big_entry_price}
                              exitPx={r.big_exit_price}
                            />
                            <LegBlock
                              action={r.small_action}
                              instrument={r.small_instrument}
                              lots={r.small_lots}
                              entryPx={r.small_entry_price}
                              exitPx={r.small_exit_price}
                            />
                            <div className="leg-block info">
                              <div className="leg-head">
                                <span className="leg-instrument">PnL Calculation</span>
                              </div>
                              <div className="leg-prices small">
                                <div>
                                  <span className="leg-label">{r.mode === "decrease" ? "Entry − Exit" : "Exit − Entry"}</span>
                                </div>
                                <div className="leg-arrow"></div>
                                <div>
                                  <span className="leg-price">
                                    {r.mode === "decrease"
                                      ? `${Number(r.entry_spread).toFixed(2)} − ${Number(r.exit_spread).toFixed(2)}`
                                      : `${Number(r.exit_spread).toFixed(2)} − ${Number(r.entry_spread).toFixed(2)}`}
                                  </span>
                                </div>
                                <div className="leg-arrow">×</div>
                                <div>
                                  <span className="leg-price">{r.big_lots} lots</span>
                                </div>
                                <div className="leg-arrow">=</div>
                                <div>
                                  <span className={`leg-price ${r.pnl >= 0 ? "pos" : "neg"}`}>
                                    {r.pnl >= 0 ? "+" : ""}{r.pnl}
                                  </span>
                                </div>
                              </div>
                              <div className="leg-prices small" style={{ marginTop: 8, color: "var(--text-muted)" }}>
                                <div><span className="leg-label">Opened:</span> {fmt(r.entry_time)}</div>
                                <div><span className="leg-label">Closed:</span> {fmt(r.exit_time)}</div>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {filtered.length > 0 && (
        <div className="pagination-controls">
          <div>Showing {start + 1}-{Math.min(start + PER, filtered.length)} of {filtered.length}</div>
          <div className="pager">
            <button onClick={() => setPage(1)} disabled={page === 1}>«</button>
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
            <button className="active">{page}</button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>›</button>
            <button onClick={() => setPage(totalPages)} disabled={page === totalPages}>»</button>
          </div>
        </div>
      )}
    </div>
  );
}
