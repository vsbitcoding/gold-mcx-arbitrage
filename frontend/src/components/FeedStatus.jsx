import React from "react";

function fmtHM(seconds) {
  if (seconds === null || seconds === undefined || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export default function FeedStatus({ status }) {
  if (!status) return null;
  const live = status.mode === "live";
  const sim = status.mode === "simulated";
  const tickAge = status.last_tick_age_seconds;
  const stale = tickAge !== null && tickAge > 30;

  const cls = sim ? "feed-sim" : live ? (stale ? "feed-stale" : "feed-live") : "feed-down";
  const label = sim ? "DEMO" : live ? (stale ? "STALE" : "LIVE") : "DOWN";

  const tooltip = [
    `Mode: ${status.mode}`,
    `Client: ${status.client_name || "—"}`,
    `Token expires in: ${fmtHM(status.token_expires_in_seconds)}`,
    `Last tick: ${tickAge === null ? "never" : tickAge + "s ago"}`,
    `Reconnects: ${status.reconnect_count}`,
  ].join("\n");

  return (
    <div className={`feed-pill ${cls}`} title={tooltip}>
      <span className="feed-dot" />
      <span className="feed-label">{label}</span>
      <span className="feed-meta">{fmtHM(status.token_expires_in_seconds)}</span>
    </div>
  );
}
