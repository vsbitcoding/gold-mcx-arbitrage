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

function LadderRow({ ladder, defaultMaxWeight, maxAllowed, side, onSaved, onDeleted }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [draft, setDraft] = useState({
    entry: ladder.entry ?? "",
    exit: ladder.exit ?? "",
    max_weight_grams: ladder.max_weight_grams ?? "",
  });
  const [saving, setSaving] = useState(false);

  // Sync draft when ladder changes server-side AND user isn't editing
  useEffect(() => {
    setDraft((d) => {
      const serverEntry = ladder.entry ?? "";
      const serverExit = ladder.exit ?? "";
      const serverMax = ladder.max_weight_grams ?? "";
      // Only update if local matches some prior server state (avoid trampling user edits)
      const dirty =
        String(d.entry) !== String(serverEntry) ||
        String(d.exit) !== String(serverExit) ||
        String(d.max_weight_grams) !== String(serverMax);
      if (!dirty) {
        return { entry: serverEntry, exit: serverExit, max_weight_grams: serverMax };
      }
      return d;
    });
  }, [ladder.entry, ladder.exit, ladder.max_weight_grams]);

  const dirty =
    String(draft.entry) !== String(ladder.entry ?? "") ||
    String(draft.exit) !== String(ladder.exit ?? "") ||
    String(draft.max_weight_grams) !== String(ladder.max_weight_grams ?? "");

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
    if (!dirty) return;
    setSaving(true);
    try {
      const body = {
        entry: draft.entry === "" ? null : Number(draft.entry),
        exit: draft.exit === "" ? null : Number(draft.exit),
        max_weight_grams: draft.max_weight_grams === "" ? null : Number(draft.max_weight_grams),
      };
      await api.updateLadder(ladder.id, body);
      toast.success(`Ladder updated`);
      onSaved?.();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
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
      toast.success("Ladder deleted");
      onDeleted?.();
    } catch (e) {
      toast.error(e.message);
    }
  }

  const cellCls = (k) => `cell ${String(draft[k]) !== String(ladder[k] ?? "") ? "dirty" : ""}`;

  return (
    <div className={`ladder-row ${ladder.open_count > 0 ? "active" : ""}`}>
      <input className={cellCls("entry")} type="number" step="0.01" placeholder="Entry"
        value={draft.entry ?? ""} onChange={(e) => update("entry", e.target.value)} />
      <input className={cellCls("exit")} type="number" step="0.01" placeholder="Exit"
        value={draft.exit ?? ""} onChange={(e) => update("exit", e.target.value)} />
      <input className={cellCls("max_weight_grams")} type="number" min="0" max={maxAllowed} step="1"
        placeholder={String(defaultMaxWeight)}
        value={draft.max_weight_grams ?? ""}
        onChange={(e) => onWeightChange(e.target.value)} />
      <div className="ladder-meta">
        <div className="ladder-weight">
          {ladder.open_weight_grams || 0}/{ladder.max_weight_grams ?? defaultMaxWeight}g
          {ladder.open_count > 0 && <span className="ladder-count" title="Open positions">{ladder.open_count}</span>}
        </div>
        {ladder.has_pending_cap && (
          <div className="ladder-pending">⏳ {ladder.pending_max_weight_grams ?? "default"}g</div>
        )}
      </div>
      <div className="ladder-actions">
        <button className={`btn btn-primary btn-sm ${dirty ? "dirty" : ""}`} onClick={save} disabled={saving || !dirty}>
          {dirty ? "Save *" : "Saved"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={remove}>×</button>
      </div>
    </div>
  );
}

function NewLadderForm({ pairName, side, defaultMaxWeight, maxAllowed, onCreated }) {
  const toast = useToast();
  const [entry, setEntry] = useState("");
  const [exit, setExit] = useState("");
  const [weight, setWeight] = useState("");
  const [open, setOpen] = useState(false);

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
      setOpen(false);
      toast.success("Ladder added");
      onCreated?.();
    } catch (e) {
      toast.error(e.message);
    }
  }

  if (!open) {
    return (
      <button className="btn btn-secondary btn-sm add-ladder-btn" onClick={() => setOpen(true)}>
        + Add {cap(side)} Ladder
      </button>
    );
  }

  return (
    <form className="ladder-row new" onSubmit={submit}>
      <input className="cell" type="number" step="0.01" placeholder="Entry" value={entry} onChange={(e) => setEntry(e.target.value)} autoFocus />
      <input className="cell" type="number" step="0.01" placeholder="Exit" value={exit} onChange={(e) => setExit(e.target.value)} />
      <input className="cell" type="number" min="0" max={maxAllowed} step="1"
        placeholder={String(defaultMaxWeight)}
        value={weight}
        onChange={(e) => {
          const v = e.target.value;
          if (v !== "" && Number(v) > maxAllowed) setWeight(String(maxAllowed));
          else setWeight(v);
        }} />
      <div></div>
      <div className="ladder-actions">
        <button className="btn btn-primary btn-sm" type="submit">Add</button>
        <button className="btn btn-secondary btn-sm" type="button" onClick={() => setOpen(false)}>×</button>
      </div>
    </form>
  );
}

const PairCard = memo(function PairCard({ row, expanded, onToggle, onChange }) {
  const bigMult = MULTIPLIERS[row.big] ?? 1;
  const smallMult = MULTIPLIERS[row.small] ?? 1;

  return (
    <div className={`spread-pair-card status-${row.status}`}>
      <div className="pair-card-head">
        <button className="pair-card-toggle" onClick={onToggle}>
          <span className="caret">{expanded ? "▾" : "▸"}</span>
          <span className="pair-card-title">{row.name}</span>
        </button>
        <span className={`badge ${STATUS_CLASS[row.status] || "badge-idle"}`}>
          <span className="blip" />
          {STATUS_LABEL[row.status] || row.status}
        </span>
      </div>

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
            <div className="ladder-side-head">▼ Decrease Ladders</div>
            <div className="ladder-list">
              <div className="ladder-headers">
                <span>Entry</span>
                <span>Exit</span>
                <span>Max (g)</span>
                <span>Status</span>
                <span></span>
              </div>
              {row.decrease_ladders.length === 0 && (
                <div className="ladder-empty">No decrease ladders. Click + to add.</div>
              )}
              {row.decrease_ladders.map((l) => (
                <LadderRow key={l.id} ladder={l} side="decrease"
                  defaultMaxWeight={row.default_max_weight}
                  maxAllowed={row.max_allowed_weight}
                  onSaved={onChange} onDeleted={onChange} />
              ))}
              <NewLadderForm pairName={row.name} side="decrease"
                defaultMaxWeight={row.default_max_weight}
                maxAllowed={row.max_allowed_weight}
                onCreated={onChange} />
            </div>
          </div>

          <div className="ladder-side inc-side">
            <div className="ladder-side-head">▲ Increase Ladders</div>
            <div className="ladder-list">
              <div className="ladder-headers">
                <span>Entry</span>
                <span>Exit</span>
                <span>Max (g)</span>
                <span>Status</span>
                <span></span>
              </div>
              {row.increase_ladders.length === 0 && (
                <div className="ladder-empty">No increase ladders. Click + to add.</div>
              )}
              {row.increase_ladders.map((l) => (
                <LadderRow key={l.id} ladder={l} side="increase"
                  defaultMaxWeight={row.default_max_weight}
                  maxAllowed={row.max_allowed_weight}
                  onSaved={onChange} onDeleted={onChange} />
              ))}
              <NewLadderForm pairName={row.name} side="increase"
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
