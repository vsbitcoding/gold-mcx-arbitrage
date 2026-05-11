import React, { useEffect, useRef, useState } from "react";
import { api } from "../../api/client.js";
import { useToast } from "../Toast.jsx";
import { useConfirm } from "../ConfirmDialog.jsx";
import { cap } from "../../utils/format.js";
import { PER_PAGE } from "./constants.js";

function ladderStatus(ladder) {
  if (ladder.locked) return { label: "Locked", cls: "ldr-full" };
  if (ladder.open_count > 0) return { label: `${ladder.open_count} Open`, cls: "ldr-running" };
  if (ladder.entry === null || ladder.entry === undefined) return { label: "Not set", cls: "ldr-idle" };
  return { label: "Armed", cls: "ldr-armed" };
}

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
  const fired = ladder.fired_weight_grams || 0;
  const usedPct = eff > 0 ? Math.min(100, (fired / eff) * 100) : 0;
  const fillCls = usedPct >= 100 ? "full" : usedPct >= 80 ? "high" : usedPct >= 50 ? "mid" : "low";
  const currentCap = ladder.max_weight_grams ?? null;

  function update(field, value) { setDraft((d) => ({ ...d, [field]: value })); }
  function onWeightChange(v) {
    if (v === "") return update("max_weight_grams", v);
    let n = Number(v);
    if (n > maxAllowed) n = maxAllowed;
    if (currentCap !== null && n < currentCap) n = currentCap; // one-way cap
    update("max_weight_grams", String(n));
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
  async function remove() {
    const ok = await confirm({
      title: "Delete this ladder?",
      message: `Remove ${cap(side)} ladder #${idx + 1} (entry=${ladder.entry ?? "—"}, cap=${currentCap ?? "default"}g)? Open trades will stay open.`,
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
    <tr className={`ldr-table-row ${ladder.locked ? "locked" : ""}`}>
      <td className="ldr-num">{idx + 1}</td>
      <td>
        <span className={`ladder-status ${status.cls}`}><span className="dot" />{status.label}</span>
      </td>
      <td>
        <input className={`cell ${draft.entry !== String(ladder.entry ?? "") ? "dirty" : ""}`}
          type="number" step="0.01" placeholder="Entry"
          value={draft.entry ?? ""} onChange={(e) => update("entry", e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          title="Live spread must CROSS this value (against you) before a fire is allowed." />
      </td>
      <td>
        <input className={`cell ${draft.exit !== String(ladder.exit ?? "") ? "dirty" : ""}`}
          type="number" step="0.01" placeholder="Exit"
          value={draft.exit ?? ""} onChange={(e) => update("exit", e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          title="When the cover spread reaches this, every open trade on this ladder is closed automatically." />
      </td>
      <td>
        <input className={`cell ${draft.max_weight_grams !== String(ladder.max_weight_grams ?? "") ? "dirty" : ""}`}
          type="number" min={currentCap || 0} max={maxAllowed} step="1"
          placeholder={String(defaultMaxWeight)}
          value={draft.max_weight_grams ?? ""}
          onChange={(e) => onWeightChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          title={currentCap ? `Cap can only be increased (current: ${currentCap}g)` : "Set max grams to fire on this ladder"} />
      </td>
      <td className="ldr-used">
        <div className="ldr-used-bar">
          <div className={`fill ${fillCls}`} style={{ width: `${usedPct}%` }} />
        </div>
        <div className="ldr-used-text">
          <strong>{fired}</strong>/{eff}g
        </div>
        {ladder.locked && (
          <div className="ldr-lock-note" title="This ladder hit its lifetime cap. Trades stay open; raise Max(g) to allow more fires.">
            🔒 Cap full · raise <strong>Max (g)</strong> to allow more
          </div>
        )}
      </td>
      <td className="ldr-actions">
        {dirty && (
          <button className="btn btn-primary btn-sm save-btn" onClick={save} disabled={saving}>
            {saving ? "…" : "Save"}
          </button>
        )}
        <button className="ldr-icon danger" onClick={remove} title="Delete ladder">×</button>
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

export default function LadderTable({ pairName, side, ladders, defaultMaxWeight, maxAllowed, onChange }) {
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

      <div className="ladder-help-banner">
        <strong>How it works:</strong> Set <em>Entry</em> (when to fire), <em>Exit</em> (when to close), and <em>Max (g)</em> (how much gold this ladder may ever fire). Each ladder fires automatically when the live spread crosses Entry. Cap is one-way — you can only raise it, never reduce.
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
        <div className="empty-state ladder-empty">
          <strong>No ladders yet.</strong> Add one above — Entry value is required, Exit and Max (g) are optional (defaults will be used).
        </div>
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
                  <th>Actions</th>
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
