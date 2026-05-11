import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { fmtNum } from "../utils/format.js";

export default function Settings() {
  const toast = useToast();
  const [data, setData] = useState(null);
  // Draft is initialized once on first load. The periodic refresh keeps `data`
  // up to date (for the Live Status panel) but NEVER overwrites `draft` while
  // the user is typing.
  const [draft, setDraft] = useState({ balance: "", max_usage_percent: "", margin_per_fire: "" });
  const [saving, setSaving] = useState(false);
  const initialisedRef = useRef(false);

  async function loadStatusOnly() {
    try {
      const r = await api.getAccount();
      setData(r);
      if (!initialisedRef.current) {
        // Treat server 0 as "unset" so placeholder shows instead of leading "0"
        setDraft({
          balance: r.balance ? String(r.balance) : "",
          max_usage_percent: r.max_usage_percent ? String(r.max_usage_percent) : "",
          margin_per_fire: r.margin_per_fire ? String(r.margin_per_fire) : "",
        });
        initialisedRef.current = true;
      }
    } catch (e) { toast.error(e.message); }
  }

  useEffect(() => {
    loadStatusOnly();
    const t = setInterval(loadStatusOnly, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, []);

  // Compare as numbers (empty draft = 0) so "" vs 0 isn't a false-positive
  const dirty =
    data !== null && (
      Number(draft.balance || 0) !== (data.balance || 0) ||
      Number(draft.max_usage_percent || 0) !== (data.max_usage_percent || 0) ||
      Number(draft.margin_per_fire || 0) !== (data.margin_per_fire || 0)
    );

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      const body = {
        balance: draft.balance === "" ? 0 : Number(draft.balance),
        max_usage_percent: draft.max_usage_percent === "" ? 0 : Number(draft.max_usage_percent),
        margin_per_fire: draft.margin_per_fire === "" ? 0 : Number(draft.margin_per_fire),
      };
      const r = await api.updateAccount(body);
      setData(r);
      // Sync draft to confirmed saved values (0 → empty so placeholder shows)
      setDraft({
        balance: r.balance ? String(r.balance) : "",
        max_usage_percent: r.max_usage_percent ? String(r.max_usage_percent) : "",
        margin_per_fire: r.margin_per_fire ? String(r.margin_per_fire) : "",
      });
      toast.success("Settings saved");
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  }

  const usagePct = data?.usage_percent;
  const pctFillCls = usagePct == null ? "" : usagePct >= 100 ? "full" : usagePct >= 80 ? "high" : usagePct >= 50 ? "mid" : "low";

  return (
    <div className="settings-page">
      <div className="settings-head">
        <h2>Account Settings</h2>
        <p className="settings-sub">
          Trade engine uses this to block new fires once the margin cap is hit.
          Settings persist on the server and apply to all ladders.
        </p>
      </div>

      <div className="settings-grid">
        <div className="settings-card">
          <div className="settings-card-title">Account &amp; Cap</div>

          <div className="settings-row">
            <label className="settings-label">Account Balance (₹)</label>
            <input
              type="number" min="0" step="1"
              className="settings-input"
              value={draft.balance}
              onChange={(e) => setDraft((d) => ({ ...d, balance: e.target.value }))}
              placeholder="e.g. 1,00,000"
            />
          </div>

          <div className="settings-row">
            <label className="settings-label">Max Usage (%)</label>
            <input
              type="number" min="0" max="100" step="0.1"
              className="settings-input"
              value={draft.max_usage_percent}
              onChange={(e) => setDraft((d) => ({ ...d, max_usage_percent: e.target.value }))}
              placeholder="e.g. 80"
            />
          </div>

          <div className="settings-row">
            <label className="settings-label">Margin per Fire (₹)</label>
            <input
              type="number" min="0" step="1"
              className="settings-input"
              value={draft.margin_per_fire}
              onChange={(e) => setDraft((d) => ({ ...d, margin_per_fire: e.target.value }))}
              placeholder="e.g. 11,000"
            />
            <span className="settings-help">Deducted from cap for every single fire (across all pairs).</span>
          </div>

          <div className="settings-actions">
            <button
              className="btn btn-primary"
              onClick={save}
              disabled={!dirty || saving}
            >
              {saving ? "Saving…" : dirty ? "Save" : "Saved"}
            </button>
          </div>
        </div>

        <div className="settings-card settings-status-card">
          <div className="settings-card-title">Live Status</div>
          {data == null ? (
            <div className="empty-state">Loading…</div>
          ) : (
            <>
              <div className="settings-status-row">
                <span className="ss-label">Open positions</span>
                <span className="ss-value">{data.open_positions}</span>
              </div>
              <div className="settings-status-row">
                <span className="ss-label">Cap (balance × %)</span>
                <span className="ss-value">₹ {fmtNum(data.cap)}</span>
              </div>
              <div className="settings-status-row">
                <span className="ss-label">Used (open × margin)</span>
                <span className="ss-value">₹ {fmtNum(data.used)}</span>
              </div>
              <div className="settings-status-row">
                <span className="ss-label">Available</span>
                <span className={`ss-value ${data.available >= 0 ? "pos" : "neg"}`}>
                  ₹ {fmtNum(data.available)}
                </span>
              </div>

              <div className="settings-progress">
                <div className="settings-progress-bar">
                  <div
                    className={`fill ${pctFillCls}`}
                    style={{ width: `${Math.min(100, usagePct ?? 0)}%` }}
                  />
                </div>
                <div className="settings-progress-text">
                  {usagePct == null ? "Configure balance + margin to enable cap" : `${fmtNum(usagePct)} % used`}
                </div>
              </div>

              {data.cap > 0 && data.used >= data.cap && (
                <div className="settings-banner danger">
                  ⛔ Account cap reached — engine is blocking all new fires.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
