import React, { useEffect, useMemo, useState, memo, useRef } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { useConfirm } from "./ConfirmDialog.jsx";

const STATUS_LABEL = { idle: "Idle", armed: "Armed", in_position: "In Position" };
const STATUS_CLASS = { idle: "badge-idle", armed: "badge-armed", in_position: "badge-position" };

function fmtSpread(v) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(2);
}
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

function ladderStatus(ladder) {
  if (!ladder.enabled) return { label: "Paused", cls: "ldr-paused" };
  if (ladder.open_count > 0) {
    const eff = ladder.effective_max_weight || 1;
    if (ladder.open_weight_grams >= eff) return { label: "Full", cls: "ldr-full" };
    return { label: `${ladder.open_count} open`, cls: "ldr-running" };
  }
  if (ladder.entry === null || ladder.entry === undefined) return { label: "Not set", cls: "ldr-idle" };
  return { label: "Armed", cls: "ldr-armed" };
}

function LadderCard({ ladder, defaultMaxWeight, maxAllowed, side, onChange }) {
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

  // Sync if server values change AND user isn't editing (no dirty fields)
  useEffect(() => {
    const serverEntry = ladder.entry ?? "";
    const serverExit = ladder.exit ?? "";
    const serverMax = ladder.max_weight_grams ?? "";

    setDraft((d) => {
      const wasDirty =
        String(d.entry) !== String(lastServerRef.current.entry) ||
        String(d.exit) !== String(lastServerRef.current.exit) ||
        String(d.max_weight_grams) !== String(lastServerRef.current.max_weight_grams);
      lastServerRef.current = { entry: serverEntry, exit: serverExit, max_weight_grams: serverMax };
      if (wasDirty) return d;
      return { entry: serverEntry, exit: serverExit, max_weight_grams: serverMax };
    });
  }, [ladder.entry, ladder.exit, ladder.max_weight_grams]);

  const dirty =
    String(draft.entry) !== String(ladder.entry ?? "") ||
    String(draft.exit) !== String(ladder.exit ?? "") ||
    String(draft.max_weight_grams) !== String(ladder.max_weight_grams ?? "");

  const status = ladderStatus(ladder);
  const eff = ladder.effective_max_weight || defaultMaxWeight;
  const usedPct = eff > 0 ? Math.min(100, ((ladder.open_weight_grams || 0) / eff) * 100) : 0;

  function update(field, value) {
    setDraft((d) => ({ ...d, [field]: value }));
  }

  function onWeightChange(v) {
    if (v !== "" && Number(v) > maxAllowed) {
      update("max_weight_grams", String(maxAllowed));
    } else {
      update("max_weight_grams", v);
    }
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
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function togglePause() {
    try {
      await api.updateLadder(ladder.id, {
        entry: ladder.entry,
        exit: ladder.exit,
        max_weight_grams: ladder.max_weight_grams,
        enabled: !ladder.enabled,
      });
      toast.success(ladder.enabled ? "Paused" : "Resumed");
      onChange?.();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function remove() {
    if (ladder.open_count > 0) {
      toast.error("Cannot delete — open trades for this ladder. Square off first.");
      return;
    }
    const ok = await confirm({
      title: "Delete this ladder?",
      message: `Remove ${cap(side)} ladder (entry=${ladder.entry ?? "—"}, exit=${ladder.exit ?? "—"})?`,
      confirmText: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteLadder(ladder.id);
      toast.success("Deleted");
      onChange?.();
    } catch (e) {
      toast.error(e.message);
    }
  }

  return (
    <div className={`ladder-card ${side}-card ${!ladder.enabled ? "paused" : ""}`}>
      <div className="ladder-card-top">
        <span className={`ladder-status ${status.cls}`}>
          <span className="dot" />{status.label}
        </span>
        <button
          className="ladder-icon-btn"
          onClick={togglePause}
          title={ladder.enabled ? "Pause this ladder" : "Resume"}
        >
          {ladder.enabled ? "⏸" : "▶"}
        </button>
        <button className="ladder-icon-btn danger" onClick={remove} title="Delete ladder">×</button>
      </div>

      <div className="ladder-fields">
        <label>
          <span>Entry</span>
          <input
            type="number" step="0.01" inputMode="decimal" placeholder="e.g. 200"
            value={draft.entry ?? ""}
            onChange={(e) => update("entry", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        </label>
        <label>
          <span>Exit</span>
          <input
            type="number" step="0.01" inputMode="decimal" placeholder="e.g. 100"
            value={draft.exit ?? ""}
            onChange={(e) => update("exit", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        </label>
        <label>
          <span>Max (g)</span>
          <input
            type="number" min="0" max={maxAllowed} step="1"
            placeholder={String(defaultMaxWeight)}
            value={draft.max_weight_grams ?? ""}
            onChange={(e) => onWeightChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        </label>
      </div>

      <div className="ladder-cap-row">
        <div className="ladder-cap-bar">
          <div className={`fill ${usedPct >= 100 ? "full" : usedPct >= 80 ? "high" : usedPct >= 50 ? "mid" : "low"}`}
               style={{ width: `${usedPct}%` }} />
        </div>
        <div className="ladder-cap-text">
          <strong>{ladder.open_weight_grams || 0}</strong>
          <span> / </span>
          <span>{eff}g</span>
        </div>
        {ladder.has_pending_cap && (
          <span className="ladder-pending-pill" title="Cap change applies after square-off">
            ⏳ {ladder.pending_max_weight_grams ?? "default"}g
          </span>
        )}
      </div>

      {dirty && (
        <button
          className={`ladder-save-btn ${saving ? "saving" : ""}`}
          onClick={save}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
      )}
    </div>
  );
}

function AddLadderForm({ pairName, side, defaultMaxWeight, maxAllowed, onCreated }) {
  const toast = useToast();
  const [entry, setEntry] = useState("");
  const [exit, setExit] = useState("");
  const [weight, setWeight] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (entry === "") {
      toast.error("Entry is required");
      return;
    }
    try {
      await api.createLadder({
        pair_name: pairName,
        side,
        entry: Number(entry),
        exit: exit === "" ? null : Number(exit),
        max_weight_grams: weight === "" ? null : Number(weight),
      });
      setEntry(""); setExit(""); setWeight("");
      toast.success(`${cap(side)} ladder added`);
      onCreated?.();
    } catch (e) {
      toast.error(e.message);
    }
  }

  return (
    <form className={`add-ladder ${side}-card`} onSubmit={submit}>
      <div className="add-ladder-head">+ New {cap(side)} Ladder</div>
      <div className="ladder-fields">
        <label>
          <span>Entry</span>
          <input type="number" step="0.01" inputMode="decimal" placeholder="Required"
            value={entry} onChange={(e) => setEntry(e.target.value)} />
        </label>
        <label>
          <span>Exit</span>
          <input type="number" step="0.01" inputMode="decimal" placeholder="Optional"
            value={exit} onChange={(e) => setExit(e.target.value)} />
        </label>
        <label>
          <span>Max (g)</span>
          <input type="number" min="0" max={maxAllowed} step="1"
            placeholder={String(defaultMaxWeight)}
            value={weight}
            onChange={(e) => {
              const v = e.target.value;
              if (v !== "" && Number(v) > maxAllowed) setWeight(String(maxAllowed));
              else setWeight(v);
            }} />
        </label>
      </div>
      <button type="submit" className="ladder-add-btn">Add Ladder</button>
    </form>
  );
}

const PairCard = memo(function PairCard({ row, expanded, onToggle, onChange }) {
  const decCount = row.decrease_ladders.length;
  const incCount = row.increase_ladders.length;
  const totalActive = (row.decrease_open ? 1 : 0) + (row.increase_open ? 1 : 0);

  return (
    <div className={`spread-pair-card status-${row.status}`}>
      <button className="pair-card-head" onClick={onToggle}>
        <span className="caret">{expanded ? "▾" : "▸"}</span>
        <span className="pair-card-title">{row.name}</span>
        <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
        <span className="pair-card-meta">
          {decCount + incCount > 0 && <span>{decCount + incCount} ladder{decCount + incCount > 1 ? "s" : ""}</span>}
        </span>
      </button>

      <div className="pair-card-spreads">
        <div className="spread-block dec">
          <div className="spread-label">▼ Decrease Spread</div>
          <div className="spread-value">{fmtSpread(row.decrease_spread)}</div>
        </div>
        <div className="spread-block inc">
          <div className="spread-label">▲ Increase Spread</div>
          <div className="spread-value">{fmtSpread(row.increase_spread)}</div>
        </div>
      </div>

      {expanded && (
        <div className="pair-card-ladders">
          <div className="ladder-side dec-side">
            <div className="ladder-side-head">
              <span className="side-arrow">▼</span> Decrease Ladders
              <span className="side-count">{decCount}</span>
            </div>
            <div className="ladder-grid">
              {row.decrease_ladders.map((l) => (
                <LadderCard key={l.id} ladder={l} side="decrease"
                  defaultMaxWeight={row.default_max_weight}
                  maxAllowed={row.max_allowed_weight}
                  onChange={onChange} />
              ))}
              <AddLadderForm pairName={row.name} side="decrease"
                defaultMaxWeight={row.default_max_weight}
                maxAllowed={row.max_allowed_weight}
                onCreated={onChange} />
            </div>
          </div>

          <div className="ladder-side inc-side">
            <div className="ladder-side-head">
              <span className="side-arrow">▲</span> Increase Ladders
              <span className="side-count">{incCount}</span>
            </div>
            <div className="ladder-grid">
              {row.increase_ladders.map((l) => (
                <LadderCard key={l.id} ladder={l} side="increase"
                  defaultMaxWeight={row.default_max_weight}
                  maxAllowed={row.max_allowed_weight}
                  onChange={onChange} />
              ))}
              <AddLadderForm pairName={row.name} side="increase"
                defaultMaxWeight={row.default_max_weight}
                maxAllowed={row.max_allowed_weight}
                onCreated={onChange} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

export default function LiveSpreadTable({ rows, onSaved }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState({});

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

  function toggle(name) {
    setExpanded((e) => ({ ...e, [name]: !e[name] }));
  }

  function expandAll() {
    const all = {};
    rows.forEach((r) => { all[r.name] = true; });
    setExpanded(all);
  }
  function collapseAll() {
    setExpanded({});
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h2>Live Spread Monitor</h2>
        <div className="header-controls">
          <div className="search-container">
            <input placeholder="Search pair..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <button className="btn btn-secondary btn-sm" onClick={expandAll}>Expand All</button>
          <button className="btn btn-secondary btn-sm" onClick={collapseAll}>Collapse</button>
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

      <div className="pair-cards-grid">
        {filtered.length === 0 ? (
          <div className="empty-state">No pairs match the filter.</div>
        ) : filtered.map((r) => (
          <PairCard
            key={r.name}
            row={r}
            expanded={!!expanded[r.name]}
            onToggle={() => toggle(r.name)}
            onChange={onSaved}
          />
        ))}
      </div>
    </div>
  );
}
