import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";
import { fmtNum } from "../utils/format.js";

export default function Settings() {
  const toast = useToast();
  const [data, setData] = useState(null);
  // Draft initialised ONCE on first load. Periodic refresh keeps `data` fresh
  // (for the Live Status panel) but never touches the input fields while typing.
  const [draft, setDraft] = useState({ balance: "", max_usage_percent: "" });
  const [saving, setSaving] = useState(false);
  const initialisedRef = useRef(false);

  async function loadStatusOnly() {
    try {
      const r = await api.getAccount();
      setData(r);
      if (!initialisedRef.current) {
        setDraft({
          balance: r.balance ? String(r.balance) : "",
          max_usage_percent: r.max_usage_percent ? String(r.max_usage_percent) : "",
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

  const dirty =
    data !== null && (
      Number(draft.balance || 0) !== (data.balance || 0) ||
      Number(draft.max_usage_percent || 0) !== (data.max_usage_percent || 0)
    );

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      const body = {
        balance: draft.balance === "" ? 0 : Number(draft.balance),
        max_usage_percent: draft.max_usage_percent === "" ? 0 : Number(draft.max_usage_percent),
      };
      const r = await api.updateAccount(body);
      setData(r);
      setDraft({
        balance: r.balance ? String(r.balance) : "",
        max_usage_percent: r.max_usage_percent ? String(r.max_usage_percent) : "",
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
          Set your trading account balance and the percentage you're willing to deploy.
          Margin per trade is auto-calculated from live MCX prices using SEBI-aligned
          margin percentages (no manual margin entry needed).
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
            <span className="settings-help">Cap = Balance × this %. Engine blocks fires that would exceed it.</span>
          </div>

          <div className="settings-actions">
            <button className="btn btn-primary" onClick={save} disabled={!dirty || saving}>
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
                <span className="ss-label">Active positions (live ladders)</span>
                <span className="ss-value">{data.open_positions}</span>
              </div>
              <div className="settings-status-row">
                <span className="ss-label">Cap (balance × %)</span>
                <span className="ss-value">₹ {fmtNum(data.cap)}</span>
              </div>
              <div className="settings-status-row">
                <span className="ss-label">Used (counts toward cap)</span>
                <span className="ss-value">₹ {fmtNum(data.used)}</span>
              </div>
              <div className="settings-status-row">
                <span className="ss-label">Available</span>
                <span className={`ss-value ${data.available >= 0 ? "pos" : "neg"}`}>
                  ₹ {fmtNum(data.available)}
                </span>
              </div>
              {data.orphan_positions > 0 && (
                <div className="settings-status-row" title="Trades whose ladder was removed by the daily auto-clear. They stay open and show their own exposure, but do NOT block new ladders from firing. Square them off from each pair's Positions popup.">
                  <span className="ss-label">⚠ Orphan trades (info only, not capped)</span>
                  <span className="ss-value" style={{ color: "#b45309" }}>
                    {data.orphan_positions} · ₹ {fmtNum(data.orphan_used)}
                  </span>
                </div>
              )}

              <div className="settings-progress">
                <div className="settings-progress-bar">
                  <div className={`fill ${pctFillCls}`} style={{ width: `${Math.min(100, usagePct ?? 0)}%` }} />
                </div>
                <div className="settings-progress-text">
                  {usagePct == null ? "Configure balance to enable cap" : `${fmtNum(usagePct)} % used`}
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

        <div className="settings-card">
          <div className="settings-card-title">Margin Source</div>
          {data?.span_status && (
            <div style={{ marginBottom: 10 }}>
              <span className={`margin-chip ${data.span_status.source === "live_span" ? "" : "warn"}`}>
                {data.span_status.source === "live_span"
                  ? `● Live SPAN · ${data.span_status.contracts_with_live_margin} contracts`
                  : "● Fallback % (SPAN feed not configured)"}
              </span>
              {data.span_status.last_refresh_at && (
                <div className="settings-help" style={{ marginTop: 6 }}>
                  Last refresh: {new Date(data.span_status.last_refresh_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: true })}
                  <br />
                  Status: {data.span_status.last_refresh_msg}
                </div>
              )}
            </div>
          )}
          <p className="settings-help" style={{ marginBottom: 8 }}>
            Engine prefers <strong>live SPAN ₹/lot</strong> per contract (when feed configured). Falls back to <code>(lots × live LTP × instrument %)</code> when SPAN value missing.
            All calibrated against real broker SPAN+ELM ratios.
          </p>
          <table className="info-table" style={{ fontSize: 12 }}>
            <thead>
              <tr><th>Instrument</th><th>Fallback %</th></tr>
            </thead>
            <tbody>
              {(data?.margin_reference || []).map((m) => (
                <tr key={m.instrument}>
                  <td>{m.instrument}</td>
                  <td className="num">{fmtNum(m.margin_percent)} %</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
