import React, { useEffect, useMemo, useState, memo } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { useConfirm } from "./ConfirmDialog.jsx";


const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };
const STATUS_CLASS = { idle: "badge-idle", armed: "badge-armed", in_position: "badge-position" };
const MULTIPLIERS = { petal: 10, guinea: 1.25, ten: 1, mini: 1 };

function fmtSpread(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(4);
}
function fmtPx(v) {
  return v === null || v === undefined || v === 0 ? "—" : Number(v).toFixed(2);
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }
function eqOrEmpty(a, b) {
  // normalize: empty string == null
  const na = a === "" || a === undefined || a === null ? null : Number(a);
  const nb = a === "" || b === undefined || b === null ? null : Number(b);
  if (na === null && nb === null) return true;
  return na === nb;
}

const PairRow = memo(function PairRow({ row, draft, dirty, expanded, onToggle, onChange, onSave, onClear }) {
  const bigMult = MULTIPLIERS[row.big] ?? 1;
  const smallMult = MULTIPLIERS[row.small] ?? 1;
  const decBig = row.big_bid ? row.big_bid * bigMult : null;
  const decSmall = row.small_ask ? row.small_ask * smallMult : null;
  const incBig = row.big_ask ? row.big_ask * bigMult : null;
  const incSmall = row.small_bid ? row.small_bid * smallMult : null;

  const cls = (key) => `cell ${dirty[key] ? "dirty" : ""}`;

  return (
    <>
      <tr>
        <td className="gc-identity pair-name col-end-group">
          <button className="row-toggle" onClick={onToggle} title="Show calculation">
            <span className="caret">{expanded ? "▾" : "▸"}</span>
            {row.name}
          </button>
        </td>

        <td className="gc-decrease spread-num dec">
          {fmtSpread(row.decrease_spread)}
          {row.decrease_open && <span className="side-pill open" title="Decrease trade open">●</span>}
        </td>
        <td className="gc-decrease">
          <input className={cls("decrease_entry")} type="number" step="0.01" placeholder="—"
            value={draft.decrease_entry ?? ""}
            onChange={(e) => onChange("decrease_entry", e.target.value)} />
        </td>
        <td className="gc-decrease col-end-group">
          <input className={cls("decrease_exit")} type="number" step="0.01" placeholder="—"
            value={draft.decrease_exit ?? ""}
            onChange={(e) => onChange("decrease_exit", e.target.value)} />
        </td>

        <td className="gc-increase spread-num inc">
          {fmtSpread(row.increase_spread)}
          {row.increase_open && <span className="side-pill open" title="Increase trade open">●</span>}
        </td>
        <td className="gc-increase">
          <input className={cls("increase_entry")} type="number" step="0.01" placeholder="—"
            value={draft.increase_entry ?? ""}
            onChange={(e) => onChange("increase_entry", e.target.value)} />
        </td>
        <td className="gc-increase col-end-group">
          <input className={cls("increase_exit")} type="number" step="0.01" placeholder="—"
            value={draft.increase_exit ?? ""}
            onChange={(e) => onChange("increase_exit", e.target.value)} />
        </td>

        <td className="gc-status">
          <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
            <span className="blip" />
            {STATUS_LABEL[row.status] || row.status}
          </span>
        </td>
        <td className="gc-weight">
          <input
            className={cls("max_weight_grams")}
            type="number"
            min="0"
            max={row.max_allowed_weight ?? 1000}
            step="1"
            placeholder={String(row.default_max_weight ?? 1000)}
            value={draft.max_weight_grams ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              const limit = row.max_allowed_weight ?? 1000;
              if (v !== "" && Number(v) > limit) {
                onChange("max_weight_grams", String(limit));
              } else {
                onChange("max_weight_grams", v);
              }
            }}
            title={`Default ${row.default_max_weight ?? 1000}g if blank · Max ${row.max_allowed_weight ?? 1000}g`}
          />
          {row.has_pending_cap && (
            <div
              className="pending-cap"
              title="Cap changed mid-round. New value will apply after current trades close."
            >
              ⏳ Pending: {row.pending_max_weight_grams ?? "default"}g
            </div>
          )}
        </td>
        <td className="gc-status">
          <div className="row-actions">
            <button
              className={`btn btn-primary btn-sm ${dirty.any ? "dirty" : ""}`}
              onClick={onSave}
              title={dirty.any ? "Unsaved changes — click to save" : "Save (no changes)"}
            >
              {dirty.any ? "Save *" : "Save"}
            </button>
            <button className="btn btn-secondary btn-sm" onClick={onClear}>Clear</button>
          </div>
        </td>
      </tr>

      {expanded && (
        <tr className="calc-row">
          <td colSpan={10}>
            <div className="calc-grid">
              <div className="calc-block dec">
                <div className="calc-title">▼ Decrease Spread = (Big.Bid × {bigMult}) − (Small.Ask × {smallMult})</div>
                <div className="calc-line">
                  <span>{cap(row.big)} Bid:</span>
                  <span className="calc-num">{fmtPx(row.big_bid)} × {bigMult} = <b>{fmtSpread(decBig)}</b></span>
                </div>
                <div className="calc-line">
                  <span>{cap(row.small)} Ask:</span>
                  <span className="calc-num">{fmtPx(row.small_ask)} × {smallMult} = <b>{fmtSpread(decSmall)}</b></span>
                </div>
                <div className="calc-line total">
                  <span>Decrease Spread:</span>
                  <span className="calc-num dec-tone">
                    {fmtSpread(decBig)} − {fmtSpread(decSmall)} = <b>{fmtSpread(row.decrease_spread)}</b>
                  </span>
                </div>
              </div>

              <div className="calc-block inc">
                <div className="calc-title">▲ Increase Spread = (Big.Ask × {bigMult}) − (Small.Bid × {smallMult})</div>
                <div className="calc-line">
                  <span>{cap(row.big)} Ask:</span>
                  <span className="calc-num">{fmtPx(row.big_ask)} × {bigMult} = <b>{fmtSpread(incBig)}</b></span>
                </div>
                <div className="calc-line">
                  <span>{cap(row.small)} Bid:</span>
                  <span className="calc-num">{fmtPx(row.small_bid)} × {smallMult} = <b>{fmtSpread(incSmall)}</b></span>
                </div>
                <div className="calc-line total">
                  <span>Increase Spread:</span>
                  <span className="calc-num inc-tone">
                    {fmtSpread(incBig)} − {fmtSpread(incSmall)} = <b>{fmtSpread(row.increase_spread)}</b>
                  </span>
                </div>
              </div>

              <div className="calc-block info">
                <div className="calc-title">Lot Ratio &amp; Live Quotes</div>
                <div className="calc-line"><span>Lots (Big / Small):</span><span className="calc-num"><b>{row.big_lots} / {row.small_lots}</b></span></div>
                <div className="calc-line"><span>{cap(row.big)} Bid / Ask:</span><span className="calc-num">{fmtPx(row.big_bid)} / {fmtPx(row.big_ask)}</span></div>
                <div className="calc-line"><span>{cap(row.small)} Bid / Ask:</span><span className="calc-num">{fmtPx(row.small_bid)} / {fmtPx(row.small_ask)}</span></div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}, (prev, next) => (
  prev.expanded === next.expanded &&
  prev.dirty === next.dirty &&
  prev.row.decrease_spread === next.row.decrease_spread &&
  prev.row.increase_spread === next.row.increase_spread &&
  prev.row.big_bid === next.row.big_bid &&
  prev.row.big_ask === next.row.big_ask &&
  prev.row.small_bid === next.row.small_bid &&
  prev.row.small_ask === next.row.small_ask &&
  prev.row.status === next.row.status &&
  prev.row.decrease_open === next.row.decrease_open &&
  prev.row.increase_open === next.row.increase_open &&
  prev.row.decrease_entry === next.row.decrease_entry &&
  prev.row.decrease_exit === next.row.decrease_exit &&
  prev.row.increase_entry === next.row.increase_entry &&
  prev.row.increase_exit === next.row.increase_exit &&
  prev.row.max_weight_grams === next.row.max_weight_grams &&
  prev.row.effective_max_weight === next.row.effective_max_weight &&
  prev.row.open_weight_grams === next.row.open_weight_grams &&
  prev.row.has_pending_cap === next.row.has_pending_cap &&
  prev.row.pending_max_weight_grams === next.row.pending_max_weight_grams &&
  prev.draft === next.draft
));

function normalizeServerVal(v) {
  return v === null || v === undefined ? "" : String(v);
}

function buildDirtyMap(row, draft) {
  if (!row || !draft) return { any: false };
  const fields = ["decrease_entry", "decrease_exit", "increase_entry", "increase_exit", "max_weight_grams"];
  const out = { any: false };
  for (const f of fields) {
    const server = normalizeServerVal(row[f]);
    const local = draft[f] ?? "";
    if (String(server) !== String(local)) {
      out[f] = true;
      out.any = true;
    }
  }
  return out;
}

export default function LiveSpreadTable({ rows, onSaved }) {
  const toast = useToast();
  const confirm = useConfirm();

  const [drafts, setDrafts] = useState({});
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState({});

  // Initialize drafts from server (only for pairs not yet in drafts).
  // Keep user's in-progress edits if dirty.
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
            max_weight_grams: r.max_weight_grams ?? "",
          };
        }
      });
      return next;
    });
  }, [rows.length]);

  const dirtyMaps = useMemo(() => {
    const m = {};
    rows.forEach((r) => { m[r.name] = buildDirtyMap(r, drafts[r.name]); });
    return m;
  }, [rows, drafts]);

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
    const row = rows.find((r) => r.name === pair);
    const d = drafts[pair] || {};
    const dirty = dirtyMaps[pair] || { any: false };
    if (!dirty.any) {
      toast.info("No changes to save.");
      return;
    }

    // Warn when changing exit while that side has an open trade
    if (row?.decrease_open && dirty.decrease_exit) {
      const ok = await confirm({
        title: "Update Decrease Exit?",
        message: `Decrease trade is currently OPEN for ${pair}. Updating Exit will affect the live trade — auto square-off will use the new value on the next tick. Continue?`,
        confirmText: "Update Exit",
        danger: true,
      });
      if (!ok) return;
    }
    if (row?.increase_open && dirty.increase_exit) {
      const ok = await confirm({
        title: "Update Increase Exit?",
        message: `Increase trade is currently OPEN for ${pair}. Updating Exit will affect the live trade — auto square-off will use the new value on the next tick. Continue?`,
        confirmText: "Update Exit",
        danger: true,
      });
      if (!ok) return;
    }

    const limit = row?.max_allowed_weight ?? 1000;
    if (d.max_weight_grams !== "" && d.max_weight_grams != null && Number(d.max_weight_grams) > limit) {
      toast.error(`Max weight cannot exceed ${limit}g`);
      return;
    }

    const body = {
      decrease_entry: d.decrease_entry === "" ? null : Number(d.decrease_entry),
      decrease_exit: d.decrease_exit === "" ? null : Number(d.decrease_exit),
      increase_entry: d.increase_entry === "" ? null : Number(d.increase_entry),
      increase_exit: d.increase_exit === "" ? null : Number(d.increase_exit),
      max_weight_grams: d.max_weight_grams === "" ? null : Number(d.max_weight_grams),
    };
    try {
      await api.saveRule(pair, body);
      toast.success(`${pair} saved — bot updated.`);
      onSaved();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function clear(pair) {
    const row = rows.find((r) => r.name === pair);
    if (row?.decrease_open || row?.increase_open) {
      const sides = [];
      if (row.decrease_open) sides.push("Decrease");
      if (row.increase_open) sides.push("Increase");
      const ok = await confirm({
        title: "Trade is still open",
        message: `${sides.join(" and ")} trade${sides.length > 1 ? "s are" : " is"} currently open for ${pair}. Clearing values will NOT close the trade — it only stops re-arming after this trade closes. To close the trade now, use "Square Off" in Active Positions.`,
        confirmText: "Clear values anyway",
        danger: true,
      });
      if (!ok) return;
    }
    setDrafts((d) => ({
      ...d,
      [pair]: { decrease_entry: "", decrease_exit: "", increase_entry: "", increase_exit: "", max_weight_grams: "" },
    }));
    // Auto-save the cleared values
    try {
      await api.saveRule(pair, {
        decrease_entry: null, decrease_exit: null,
        increase_entry: null, increase_exit: null,
        max_weight_grams: null,
      });
      toast.success(`${pair} cleared.`);
      onSaved();
    } catch (e) {
      toast.error(e.message);
    }
  }

  function toggle(pair) {
    setExpanded((e) => ({ ...e, [pair]: !e[pair] }));
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>Live Spread Monitor</h2>
        <div className="header-controls">
          <div className="search-container">
            <input placeholder="Search pair..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
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
        </div>
      </div>

      {/* MOBILE CARD VIEW */}
      <div className="mobile-cards">
        {filtered.length === 0 ? (
          <div className="empty-state">No pairs match the filter.</div>
        ) : filtered.map((r) => {
          const d = drafts[r.name] || {};
          const dirty = dirtyMaps[r.name] || { any: false };
          const isOpen = !!expanded[r.name];
          return (
            <div key={r.name} className={`pair-card status-${r.status}`}>
              <div className="pair-card-head">
                <div className="pair-card-title">{r.name}</div>
                <span className={`badge ${STATUS_CLASS[r.status] || "badge-idle"}`}>
                  <span className="blip" />
                  {STATUS_LABEL[r.status] || r.status}
                </span>
              </div>

              <div className="pair-card-section dec-section">
                <div className="pair-card-section-head">
                  <span className="section-arrow">▼</span> Decrease
                  <span className="section-spread">{fmtSpread(r.decrease_spread)}</span>
                  {r.decrease_open && <span className="side-pill open">●</span>}
                </div>
                <div className="pair-card-inputs">
                  <label>Entry
                    <input className={`cell ${dirty.decrease_entry ? "dirty" : ""}`} type="number" step="0.01" placeholder="—"
                      value={d.decrease_entry ?? ""}
                      onChange={(e) => update(r.name, "decrease_entry", e.target.value)} />
                  </label>
                  <label>Exit
                    <input className={`cell ${dirty.decrease_exit ? "dirty" : ""}`} type="number" step="0.01" placeholder="—"
                      value={d.decrease_exit ?? ""}
                      onChange={(e) => update(r.name, "decrease_exit", e.target.value)} />
                  </label>
                </div>
              </div>

              <div className="pair-card-section inc-section">
                <div className="pair-card-section-head">
                  <span className="section-arrow">▲</span> Increase
                  <span className="section-spread">{fmtSpread(r.increase_spread)}</span>
                  {r.increase_open && <span className="side-pill open">●</span>}
                </div>
                <div className="pair-card-inputs">
                  <label>Entry
                    <input className={`cell ${dirty.increase_entry ? "dirty" : ""}`} type="number" step="0.01" placeholder="—"
                      value={d.increase_entry ?? ""}
                      onChange={(e) => update(r.name, "increase_entry", e.target.value)} />
                  </label>
                  <label>Exit
                    <input className={`cell ${dirty.increase_exit ? "dirty" : ""}`} type="number" step="0.01" placeholder="—"
                      value={d.increase_exit ?? ""}
                      onChange={(e) => update(r.name, "increase_exit", e.target.value)} />
                  </label>
                </div>
              </div>

              <div className="pair-card-footer">
                <label className="weight-label">Max (g)
                  <input
                    className={`cell ${dirty.max_weight_grams ? "dirty" : ""}`}
                    type="number" min="0" max={r.max_allowed_weight ?? 1000} step="1"
                    placeholder={String(r.default_max_weight ?? 1000)}
                    value={d.max_weight_grams ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      const limit = r.max_allowed_weight ?? 1000;
                      if (v !== "" && Number(v) > limit) update(r.name, "max_weight_grams", String(limit));
                      else update(r.name, "max_weight_grams", v);
                    }}
                  />
                </label>
                <div className="pair-card-actions">
                  <button className={`btn btn-primary btn-sm ${dirty.any ? "dirty" : ""}`} onClick={() => save(r.name)}>
                    {dirty.any ? "Save *" : "Save"}
                  </button>
                  <button className="btn btn-secondary btn-sm" onClick={() => clear(r.name)}>Clear</button>
                </div>
              </div>
              {r.has_pending_cap && (
                <div className="pending-cap-mobile">⏳ Pending cap: {r.pending_max_weight_grams ?? "default"}g</div>
              )}
            </div>
          );
        })}
      </div>

      {/* DESKTOP TABLE VIEW */}
      <div className="table-container desktop-only">
        <table className="fixed">
          <colgroup>
            <col style={{ width: "12%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "8%" }} />
            <col style={{ width: "8%" }} />
            <col style={{ width: "9%" }} />
            <col style={{ width: "8%" }} />
            <col style={{ width: "8%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "18%" }} />
          </colgroup>
          <thead>
            <tr>
              <th className="col-group cg-identity" colSpan={1}>Identity</th>
              <th className="col-group cg-decrease" colSpan={3}>▼ Decrease Premium</th>
              <th className="col-group cg-increase" colSpan={3}>▲ Increase Premium</th>
              <th className="col-group cg-status" colSpan={3}>Status &amp; Cap</th>
            </tr>
            <tr>
              <th className="gc-identity col-end-group">Pair</th>
              <th className="gc-decrease">Spread</th>
              <th className="gc-decrease">Entry</th>
              <th className="gc-decrease col-end-group">Exit</th>
              <th className="gc-increase">Spread</th>
              <th className="gc-increase">Entry</th>
              <th className="gc-increase col-end-group">Exit</th>
              <th className="gc-status">State</th>
              <th className="gc-weight">Max (g)</th>
              <th className="gc-status">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={10} className="empty-state">No pairs match the filter.</td></tr>
            ) : filtered.map((r) => (
              <PairRow
                key={r.name}
                row={r}
                draft={drafts[r.name] || {}}
                dirty={dirtyMaps[r.name] || { any: false }}
                expanded={!!expanded[r.name]}
                onToggle={() => toggle(r.name)}
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
