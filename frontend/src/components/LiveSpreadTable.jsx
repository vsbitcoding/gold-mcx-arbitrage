import React, { useEffect, useMemo, useState, memo, useRef } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { useConfirm } from "./ConfirmDialog.jsx";

const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };
const STATUS_CLASS = { idle: "badge-idle", armed: "badge-armed", in_position: "badge-position" };
const PER_PAGE = 5;

function fmtSpread(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(2);
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

function ladderStatus(ladder) {
  if (!ladder.enabled) return { label: "Paused", cls: "ldr-paused" };
  if (ladder.open_count > 0) {
    const eff = ladder.effective_max_weight || 1;
    if (ladder.open_weight_grams >= eff) return { label: "Full", cls: "ldr-full" };
    return { label: `${ladder.open_count} Open`, cls: "ldr-running" };
  }
  if (ladder.entry === null || ladder.entry === undefined) return { label: "Not set", cls: "ldr-idle" };
  return { label: "Armed", cls: "ldr-armed" };
}

// ===== Table row for one ladder (inline-edit) =====
function LadderTableRow({ ladder, idx, defaultMaxWeight, maxAllowed, side, onChange }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [draft, setDraft] = useState({
    entry: ladder.entry ?? "",
    exit: ladder.exit ?? "",
    max_weight_grams: ladder.max_weight_grams ?? "",
  });
  const [saving, setSaving] = useState(false);
  const lastServerRef = useRef({
    entry: ladder.entry ?? "",
    exit: ladder.exit ?? "",
    max_weight_grams: ladder.max_weight_grams ?? "",
  });

  useEffect(() => {
    const sE = ladder.entry ?? "", sX = ladder.exit ?? "", sM = ladder.max_weight_grams ?? "";
    setDraft((d) => {
      const wasDirty =
        String(d.entry) !== String(lastServerRef.current.entry) ||
        String(d.exit) !== String(lastServerRef.current.exit) ||
        String(d.max_weight_grams) !== String(lastServerRef.current.max_weight_grams);
      lastServerRef.current = { entry: sE, exit: sX, max_weight_grams: sM };
      if (wasDirty) return d;
      return { entry: sE, exit: sX, max_weight_grams: sM };
    });
  }, [ladder.entry, ladder.exit, ladder.max_weight_grams]);

  const dirty =
    String(draft.entry) !== String(ladder.entry ?? "") ||
    String(draft.exit) !== String(ladder.exit ?? "") ||
    String(draft.max_weight_grams) !== String(ladder.max_weight_grams ?? "");

  const status = ladderStatus(ladder);
  const eff = ladder.effective_max_weight || defaultMaxWeight;
  const usedPct = eff > 0 ? Math.min(100, ((ladder.open_weight_grams || 0) / eff) * 100) : 0;
  const fillCls = usedPct >= 100 ? "full" : usedPct >= 80 ? "high" : usedPct >= 50 ? "mid" : "low";

  function update(field, value) { setDraft((d) => ({ ...d, [field]: value })); }
  function onWeightChange(v) {
    if (v !== "" && Number(v) > maxAllowed) update("max_weight_grams", String(maxAllowed));
    else update("max_weight_grams", v);
  }
  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      await api.updateLadder(ladder.id, {
        entry: draft.entry === "" ? null : Number(draft.entry),
        exit: draft.exit === "" ? null : Number(draft.exit),
        max_weight_grams: draft.max_weight_grams === "" ? null : Number(draft.max_weight_grams),
      });
      toast.success("Saved");
      onChange?.();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  }
  async function togglePause() {
    try {
      await api.updateLadder(ladder.id, {
        entry: ladder.entry, exit: ladder.exit, max_weight_grams: ladder.max_weight_grams,
        enabled: !ladder.enabled,
      });
      toast.success(ladder.enabled ? "Paused" : "Resumed");
      onChange?.();
    } catch (e) { toast.error(e.message); }
  }
  async function remove() {
    if (ladder.open_count > 0) { toast.error("Cannot delete — open trades for this ladder"); return; }
    const ok = await confirm({
      title: "Delete this ladder?",
      message: `Remove ${cap(side)} ladder #${idx + 1} (entry=${ladder.entry ?? "—"})?`,
      confirmText: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteLadder(ladder.id);
      toast.success("Deleted");
      onChange?.();
    } catch (e) { toast.error(e.message); }
  }

  return (
    <tr className={`ldr-table-row ${!ladder.enabled ? "paused" : ""}`}>
      <td className="ldr-num">{idx + 1}</td>
      <td>
        <span className={`ladder-status ${status.cls}`}><span className="dot" />{status.label}</span>
      </td>
      <td>
        <input className={`cell ${draft.entry !== String(ladder.entry ?? "") ? "dirty" : ""}`}
          type="number" step="0.01" placeholder="Entry"
          value={draft.entry ?? ""} onChange={(e) => update("entry", e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()} />
      </td>
      <td>
        <input className={`cell ${draft.exit !== String(ladder.exit ?? "") ? "dirty" : ""}`}
          type="number" step="0.01" placeholder="Exit"
          value={draft.exit ?? ""} onChange={(e) => update("exit", e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()} />
      </td>
      <td>
        <input className={`cell ${draft.max_weight_grams !== String(ladder.max_weight_grams ?? "") ? "dirty" : ""}`}
          type="number" min="0" max={maxAllowed} step="1"
          placeholder={String(defaultMaxWeight)}
          value={draft.max_weight_grams ?? ""}
          onChange={(e) => onWeightChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()} />
      </td>
      <td className="ldr-used">
        <div className="ldr-used-bar">
          <div className={`fill ${fillCls}`} style={{ width: `${usedPct}%` }} />
        </div>
        <div className="ldr-used-text">
          <strong>{ladder.open_weight_grams || 0}</strong>/{eff}g
        </div>
        {ladder.has_pending_cap && (
          <div className="ldr-pending-mini" title="Cap change pending — applies after square-off">
            ⏳ {ladder.pending_max_weight_grams ?? "default"}g
          </div>
        )}
      </td>
      <td className="ldr-actions">
        {dirty && (
          <button className="btn btn-primary btn-sm save-btn" onClick={save} disabled={saving}>
            {saving ? "…" : "Save"}
          </button>
        )}
        <button className="ldr-icon" onClick={togglePause} title={ladder.enabled ? "Pause" : "Resume"}>
          {ladder.enabled ? "⏸" : "▶"}
        </button>
        <button className="ldr-icon danger" onClick={remove} title="Delete">×</button>
      </td>
    </tr>
  );
}

function AddLadderInline({ pairName, side, defaultMaxWeight, maxAllowed, onCreated }) {
  const toast = useToast();
  const [entry, setEntry] = useState("");
  const [exit, setExit] = useState("");
  const [weight, setWeight] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (entry === "") { toast.error("Entry is required"); return; }
    setSubmitting(true);
    try {
      await api.createLadder({
        pair_name: pairName, side,
        entry: Number(entry),
        exit: exit === "" ? null : Number(exit),
        max_weight_grams: weight === "" ? null : Number(weight),
      });
      setEntry(""); setExit(""); setWeight("");
      toast.success(`${cap(side)} ladder added`);
      onCreated?.();
    } catch (e) { toast.error(e.message); }
    finally { setSubmitting(false); }
  }

  return (
    <form className={`add-ladder-row ${side}-add`} onSubmit={submit}>
      <input type="number" step="0.01" placeholder="Entry (required)"
        value={entry} onChange={(e) => setEntry(e.target.value)} className="cell" />
      <input type="number" step="0.01" placeholder="Exit"
        value={exit} onChange={(e) => setExit(e.target.value)} className="cell" />
      <input type="number" min="0" max={maxAllowed} step="1"
        placeholder={`Max (${defaultMaxWeight})`}
        value={weight}
        onChange={(e) => {
          const v = e.target.value;
          if (v !== "" && Number(v) > maxAllowed) setWeight(String(maxAllowed));
          else setWeight(v);
        }}
        className="cell" />
      <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>
        + Add
      </button>
    </form>
  );
}

function LadderTable({ pairName, side, ladders, defaultMaxWeight, maxAllowed, onChange }) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(ladders.length / PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PER_PAGE;
  const slice = ladders.slice(start, start + PER_PAGE);

  return (
    <div className={`ladder-side-table ${side}-side`}>
      <div className="ladder-side-head">
        <span className="side-arrow">{side === "decrease" ? "▼" : "▲"}</span>
        {cap(side)} Ladders
        <span className="side-count">{ladders.length}</span>
      </div>

      <div className="add-ladder-section">
        <AddLadderInline
          pairName={pairName} side={side}
          defaultMaxWeight={defaultMaxWeight}
          maxAllowed={maxAllowed}
          onCreated={() => { onChange(); setPage(totalPages); }}
        />
      </div>

      {ladders.length === 0 ? (
        <div className="empty-state ladder-empty">No ladders yet — add one above.</div>
      ) : (
        <>
          <div className="ladder-table-wrap">
            <table className="ladder-table">
              <thead>
                <tr>
                  <th style={{ width: 32 }}>#</th>
                  <th>Status</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Max (g)</th>
                  <th>Weight Used</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((l, i) => (
                  <LadderTableRow
                    key={l.id} ladder={l} idx={start + i}
                    defaultMaxWeight={defaultMaxWeight}
                    maxAllowed={maxAllowed}
                    side={side}
                    onChange={onChange}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className={`ladder-pager ${totalPages > 1 ? "" : "invisible"}`}>
            <span>Page {safePage} / {totalPages}</span>
            <div className="pager-buttons">
              <button onClick={() => setPage(1)} disabled={safePage === 1}>«</button>
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage === 1}>‹</button>
              <span className="pager-cur">{safePage}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}>›</button>
              <button onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ===== Per-pair Positions tab =====
function PairPositionsTab({ pairName }) {
  const [data, setData] = useState({ positions: [], summaries: [] });
  const [page, setPage] = useState(1);
  const PER = 5;

  useEffect(() => {
    let alive = true;
    async function load() {
      const r = await api.positions(pairName).catch(() => null);
      if (alive && r) setData(r);
    }
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, [pairName]);

  const total = data.positions.length;
  const totalPages = Math.max(1, Math.ceil(total / PER));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PER;
  const slice = data.positions.slice(start, start + PER);

  return (
    <div className="modal-tab-pane">
      {data.summaries.length > 0 && (
        <div className="summary-block compact">
          <div className="summary-title">Aggregate (weighted by gram)</div>
          <table className="summary-table">
            <thead>
              <tr>
                <th>Mode</th><th>Trades</th><th>Total Wt</th><th>Avg Entry</th><th>Cover</th><th>Live PnL</th>
              </tr>
            </thead>
            <tbody>
              {data.summaries.map((s) => (
                <tr key={s.mode}>
                  <td>
                    <span className={`badge ${s.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{s.mode}</span>
                  </td>
                  <td>{s.count}</td>
                  <td>{s.total_weight_grams}g</td>
                  <td className="spread-num">{s.avg_entry_spread === null ? "—" : Number(s.avg_entry_spread).toFixed(2)}</td>
                  <td className="spread-num">{s.cover_spread === null ? "—" : Number(s.cover_spread).toFixed(2)}</td>
                  <td className={s.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                    {s.live_pnl >= 0 ? "+" : ""}{s.live_pnl}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total === 0 ? (
        <div className="empty-state">No active positions for this pair.</div>
      ) : (
        <>
          <table className="ladder-table">
            <thead>
              <tr>
                <th>Mode</th><th>Entry</th><th>Cover</th><th>Lots</th><th>Weight</th><th>Time</th><th>Live PnL</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((p) => (
                <tr key={p.id}>
                  <td>
                    <span className={`badge ${p.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{p.mode}</span>
                  </td>
                  <td className="spread-num">{Number(p.entry_spread).toFixed(2)}</td>
                  <td className="spread-num">{p.cover_spread === null ? "—" : Number(p.cover_spread).toFixed(2)}</td>
                  <td>{p.big_lots}/{p.small_lots}</td>
                  <td>{p.weight_grams}g</td>
                  <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{new Date(p.entry_time).toLocaleTimeString()}</td>
                  <td className={p.live_pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                    {p.live_pnl >= 0 ? "+" : ""}{p.live_pnl}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div className="ladder-pager">
              <span>Page {safePage} / {totalPages} · {total} total</span>
              <div className="pager-buttons">
                <button onClick={() => setPage(1)} disabled={safePage === 1}>«</button>
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage === 1}>‹</button>
                <span className="pager-cur">{safePage}</span>
                <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}>›</button>
                <button onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ===== Per-pair History tab =====
function PairHistoryTab({ pairName }) {
  const [data, setData] = useState({ trades: [], summaries: [] });
  const [page, setPage] = useState(1);
  const PER = 5;

  useEffect(() => {
    let alive = true;
    async function load() {
      const r = await api.history(30, pairName).catch(() => null);
      if (alive && r) setData(r);
    }
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [pairName]);

  const total = data.trades.length;
  const totalPages = Math.max(1, Math.ceil(total / PER));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * PER;
  const slice = data.trades.slice(start, start + PER);

  return (
    <div className="modal-tab-pane">
      {data.summaries.length > 0 && (
        <div className="summary-block compact">
          <div className="summary-title">Aggregate (weighted by gram)</div>
          <table className="summary-table">
            <thead>
              <tr>
                <th>Mode</th><th>Trades</th><th>Total Wt</th><th>Avg Entry</th><th>Avg Exit</th><th>Total PnL</th>
              </tr>
            </thead>
            <tbody>
              {data.summaries.map((s) => (
                <tr key={s.mode}>
                  <td>
                    <span className={`badge ${s.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{s.mode}</span>
                  </td>
                  <td>{s.count}</td>
                  <td>{s.total_weight_grams}g</td>
                  <td className="spread-num">{s.avg_entry_spread === null ? "—" : Number(s.avg_entry_spread).toFixed(2)}</td>
                  <td className="spread-num">{s.avg_exit_spread === null ? "—" : Number(s.avg_exit_spread).toFixed(2)}</td>
                  <td className={s.total_pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                    {s.total_pnl >= 0 ? "+" : ""}{s.total_pnl}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total === 0 ? (
        <div className="empty-state">No history for this pair.</div>
      ) : (
        <>
          <table className="ladder-table">
            <thead>
              <tr>
                <th>Mode</th><th>Entry</th><th>Exit</th><th>Move</th><th>Weight</th><th>Closed</th><th>PnL</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => {
                const move = r.exit_spread - r.entry_spread;
                return (
                  <tr key={r.id}>
                    <td>
                      <span className={`badge ${r.mode === "decrease" ? "badge-decrease" : "badge-increase"}`}>{r.mode}</span>
                    </td>
                    <td className="spread-num">{Number(r.entry_spread).toFixed(2)}</td>
                    <td className="spread-num">{Number(r.exit_spread).toFixed(2)}</td>
                    <td className={`spread-num ${move >= 0 ? "pnl-positive" : "pnl-negative"}`}>
                      {move >= 0 ? "+" : ""}{move.toFixed(2)}
                    </td>
                    <td>{r.weight_grams}g</td>
                    <td style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {new Date(r.exit_time).toLocaleString("en-IN", { hour12: false })}
                    </td>
                    <td className={r.pnl >= 0 ? "pnl-positive" : "pnl-negative"}>
                      {r.pnl >= 0 ? "+" : ""}{r.pnl}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div className="ladder-pager">
              <span>Page {safePage} / {totalPages} · {total} total</span>
              <div className="pager-buttons">
                <button onClick={() => setPage(1)} disabled={safePage === 1}>«</button>
                <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage === 1}>‹</button>
                <span className="pager-cur">{safePage}</span>
                <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}>›</button>
                <button onClick={() => setPage(totalPages)} disabled={safePage === totalPages}>»</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ===== Modal: ladder editor for a single pair =====
function LadderModal({ row, onClose, onChange }) {
  const [tab, setTab] = useState("decrease");
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  if (!row) return null;
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;

  return (
    <div className="ladder-modal-overlay" onClick={onClose}>
      <div className="ladder-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ladder-modal-head">
          <div className="ladder-modal-title">
            <span className="pair-card-title">{row.name}</span>
            <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
              <span className="blip" />
              {STATUS_LABEL[row.status] || row.status}
            </span>
          </div>
          <div className="ladder-modal-spreads">
            <div className="modal-spread dec">
              <div className="lbl">▼ Decrease</div>
              <div className="val">{fmtSpread(row.decrease_spread)}</div>
            </div>
            <div className="modal-spread inc">
              <div className="lbl">▲ Increase</div>
              <div className="val">{fmtSpread(row.increase_spread)}</div>
            </div>
          </div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>

        <div className="ladder-modal-tabs">
          <button className={`mtab dec ${tab === "decrease" ? "active" : ""}`} onClick={() => setTab("decrease")}>
            ▼ Decrease <span className="mtab-count">{decCount}</span>
          </button>
          <button className={`mtab inc ${tab === "increase" ? "active" : ""}`} onClick={() => setTab("increase")}>
            ▲ Increase <span className="mtab-count">{incCount}</span>
          </button>
        </div>

        <div className="ladder-modal-body">
          <div style={{ display: tab === "decrease" ? "flex" : "none", flex: 1, minHeight: 0, flexDirection: "column" }}>
            <LadderTable
              pairName={row.name} side="decrease"
              ladders={row.decrease_ladders}
              defaultMaxWeight={row.default_max_weight}
              maxAllowed={row.max_allowed_weight}
              onChange={onChange}
            />
          </div>
          <div style={{ display: tab === "increase" ? "flex" : "none", flex: 1, minHeight: 0, flexDirection: "column" }}>
            <LadderTable
              pairName={row.name} side="increase"
              ladders={row.increase_ladders}
              defaultMaxWeight={row.default_max_weight}
              maxAllowed={row.max_allowed_weight}
              onChange={onChange}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

// ===== Standalone Positions modal =====
function PositionsModal({ row, onClose }) {
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);
  if (!row) return null;
  return (
    <div className="ladder-modal-overlay" onClick={onClose}>
      <div className="ladder-modal info-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ladder-modal-head">
          <div className="ladder-modal-title">
            <span className="pair-card-title">{row.name}</span>
            <span className="info-modal-tag">Active Positions</span>
          </div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>
        <div className="ladder-modal-body" style={{ overflow: "auto", padding: "16px 20px" }}>
          <PairPositionsTab pairName={row.name} />
        </div>
      </div>
    </div>
  );
}

// ===== Standalone History modal =====
function HistoryModal({ row, onClose }) {
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);
  if (!row) return null;
  return (
    <div className="ladder-modal-overlay" onClick={onClose}>
      <div className="ladder-modal info-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ladder-modal-head">
          <div className="ladder-modal-title">
            <span className="pair-card-title">{row.name}</span>
            <span className="info-modal-tag">Trade History</span>
          </div>
          <button className="drawer-close" onClick={onClose}>×</button>
        </div>
        <div className="ladder-modal-body" style={{ overflow: "auto", padding: "16px 20px" }}>
          <PairHistoryTab pairName={row.name} />
        </div>
      </div>
    </div>
  );
}

// ===== Front-month row (default visible) =====
// Acts as the primary row for each pair — full data + Manage button.
// Has a "+N more" button to expand the other expiries below.
const FrontRow = memo(function FrontRow({ row, label, hasMore, expanded, onToggle, onManage, onPositions, onHistory }) {
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;

  function handleRowClick(e) {
    // Don't toggle if click came from a button or hasn't more expiries
    if (e.target.closest("button")) return;
    if (!hasMore) return;
    onToggle();
  }

  return (
    <tr
      className={`pair-row status-${row.status} ${expanded ? "open" : ""}`}
      onClick={handleRowClick}
      style={{ cursor: hasMore ? "pointer" : "default" }}
    >
      <td className="pair-name gc-identity">
        <div className="front-row-name">
          {hasMore && <span className="caret">{expanded ? "▾" : "▸"}</span>}
          <span className="group-label">{label}</span>
        </div>
      </td>
      <td className="gc-identity col-end-group">
        <div className="pair-expiry">{row.expiry_label || "—"}</div>
      </td>
      <td className="spread-num dec-tone gc-decrease">{fmtSpread(row.decrease_spread)}</td>
      <td className="spread-num inc-tone gc-increase col-end-group">{fmtSpread(row.increase_spread)}</td>
      <td className="gc-status">
        <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
      </td>
      <td className="gc-status"><span className="ladder-count-pill dec">▼ {decCount}</span></td>
      <td className="gc-status"><span className="ladder-count-pill inc">▲ {incCount}</span></td>
      <td className="gc-status">
        <div className="front-actions">
          <button className="btn btn-primary btn-xs" onClick={(e) => { e.stopPropagation(); onManage(row.name); }}>Manage</button>
          <button className="btn btn-secondary btn-xs" onClick={(e) => { e.stopPropagation(); onPositions(row.name); }}>Positions</button>
          <button className="btn btn-secondary btn-xs" onClick={(e) => { e.stopPropagation(); onHistory(row.name); }}>History</button>
        </div>
      </td>
    </tr>
  );
}, (prev, next) => (
  prev.expanded === next.expanded &&
  prev.hasMore === next.hasMore &&
  prev.row.decrease_spread === next.row.decrease_spread &&
  prev.row.increase_spread === next.row.increase_spread &&
  prev.row.status === next.row.status &&
  prev.row.decrease_ladders === next.row.decrease_ladders &&
  prev.row.increase_ladders === next.row.increase_ladders
));

// ===== Other-month sub-row (shown when expanded) =====
const OtherMonthRow = memo(function OtherMonthRow({ row, onManage, onPositions, onHistory, isLast }) {
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;
  return (
    <tr className={`pair-row sub-row status-${row.status} ${isLast ? "last-sub" : ""}`}>
      <td className="gc-identity sub-name" colSpan={2}>
        <div className="sub-row-label">
          <span className="sub-indent">└</span>
          <span className="sub-expiry-text">{row.expiry_label || "—"}</span>
        </div>
      </td>
      <td className="spread-num dec-tone gc-decrease">{fmtSpread(row.decrease_spread)}</td>
      <td className="spread-num inc-tone gc-increase col-end-group">{fmtSpread(row.increase_spread)}</td>
      <td className="gc-status">
        <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
      </td>
      <td className="gc-status"><span className="ladder-count-pill dec">▼ {decCount}</span></td>
      <td className="gc-status"><span className="ladder-count-pill inc">▲ {incCount}</span></td>
      <td className="gc-status">
        <div className="front-actions">
          <button className="btn btn-primary btn-xs" onClick={() => onManage(row.name)}>Manage</button>
          <button className="btn btn-secondary btn-xs" onClick={() => onPositions(row.name)}>Positions</button>
          <button className="btn btn-secondary btn-xs" onClick={() => onHistory(row.name)}>History</button>
        </div>
      </td>
    </tr>
  );
}, (prev, next) => (
  prev.isLast === next.isLast &&
  prev.row.decrease_spread === next.row.decrease_spread &&
  prev.row.increase_spread === next.row.increase_spread &&
  prev.row.status === next.row.status &&
  prev.row.decrease_ladders === next.row.decrease_ladders &&
  prev.row.increase_ladders === next.row.increase_ladders &&
  prev.row.expiry_label === next.row.expiry_label
));

function SortableTh({ label, field, sort, setSort, ...rest }) {
  const active = sort.field === field;
  const dir = active ? sort.dir : null;
  function toggle() {
    if (!active) setSort({ field, dir: "asc" });
    else if (dir === "asc") setSort({ field, dir: "desc" });
    else setSort({ field: null, dir: "asc" });
  }
  return (
    <th {...rest} onClick={toggle} className={`sortable ${rest.className || ""}`}>
      <span className="th-label">{label}</span>
      <span className="sort-arrow">
        {active ? (dir === "asc" ? "▲" : "▼") : <span className="dim">⇅</span>}
      </span>
    </th>
  );
}

const PAIR_PAGE_SIZE = 12;

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

  // Split by type
  const crossRows = useMemo(() => rows.filter((r) => r.type === "cross"), [rows]);
  const calendarRows = useMemo(() => rows.filter((r) => r.type === "calendar"), [rows]);
  const tabRows = tab === "cross" ? crossRows : calendarRows;

  // Available expiries (for the dropdown filter)
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
        const hit = (r.name || "").toLowerCase().includes(term) ||
                    (r.label || "").toLowerCase().includes(term) ||
                    (r.expiry_label || "").toLowerCase().includes(term);
        if (!hit) return false;
      }
      if (expiryFilter !== "all" && r.expiry_label !== expiryFilter) return false;
      if (filter === "all") return true;
      return r.status === filter;
    });
  }, [tabRows, search, filter, expiryFilter]);

  // Sort
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

  // Group rows by label (PETAL / GUINEA, PETAL / TEN, etc.)
  const groupedRows = useMemo(() => {
    const map = new Map();
    for (const r of sortedRows) {
      const k = r.label;
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
            <col style={{ width: "18%" }} />
            <col style={{ width: "12%" }} />
            <col style={{ width: "11%" }} />
            <col style={{ width: "11%" }} />
            <col style={{ width: "12%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "18%" }} />
          </colgroup>
          <thead>
            <tr className="group-row">
              <th colSpan={2} className="cg-identity col-end-group">Identity</th>
              <th className="cg-decrease">▼ Decrease</th>
              <th className="cg-increase col-end-group">▲ Increase</th>
              <th colSpan={4} className="cg-status">Status &amp; Ladders</th>
            </tr>
            <tr>
              <SortableTh label={tab === "cross" ? "Pair" : "Spread"} field="label" sort={sort} setSort={setSort} className="gc-identity" />
              <SortableTh label="Expiry" field="expiry" sort={sort} setSort={setSort} className="gc-identity col-end-group" />
              <SortableTh label="Spread" field="decrease_spread" sort={sort} setSort={setSort} className="gc-decrease" />
              <SortableTh label="Spread" field="increase_spread" sort={sort} setSort={setSort} className="gc-increase col-end-group" />
              <SortableTh label="Status" field="status" sort={sort} setSort={setSort} className="gc-status" />
              <SortableTh label="Dec ▼" field="decrease_count" sort={sort} setSort={setSort} className="gc-status" />
              <SortableTh label="Inc ▲" field="increase_count" sort={sort} setSort={setSort} className="gc-status" />
              <th className="gc-status">Action</th>
            </tr>
          </thead>
          <tbody>
            {groupedRows.length === 0 ? (
              <tr><td colSpan={8} className="empty-state">No pairs match the filter.</td></tr>
            ) : sliceGroups.flatMap((g) => {
              const isOpen = !!expandedGroups[g.label];
              // Sort by expiry ASC — front month first
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

      {openRow && (
        <LadderModal row={openRow} onClose={() => setOpenPair(null)} onChange={onSaved} />
      )}
      {positionsRow && (
        <PositionsModal row={positionsRow} onClose={() => setOpenPositionsPair(null)} />
      )}
      {historyRow && (
        <HistoryModal row={historyRow} onClose={() => setOpenHistoryPair(null)} />
      )}
    </div>
  );
}
