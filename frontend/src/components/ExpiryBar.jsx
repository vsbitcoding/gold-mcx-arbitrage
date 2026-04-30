import React from "react";

function fmt(d) {
  if (!d) return "—";
  // d is "YYYY-MM-DD" string from the API
  const [y, m, day] = d.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${parseInt(day,10)} ${months[parseInt(m,10)-1]}`;
}

export default function ExpiryBar({ instruments }) {
  if (!instruments) return null;
  const order = ["petal", "guinea", "ten", "mini"];
  return (
    <div className="expiry-bar">
      <span className="expiry-label">Active Contracts:</span>
      {order.map((k) => {
        const i = instruments[k];
        if (!i) return null;
        const isMini = k === "mini";
        return (
          <span key={k} className={`expiry-chip ${isMini ? "mini" : ""}`} title={i.trading_symbol}>
            <span className="expiry-name">{k}</span>
            <span className="expiry-date">{fmt(i.expiry)}</span>
          </span>
        );
      })}
      <span className="expiry-rule" title="Mini auto-rolls to next month after Petal/Guinea/Ten expiry">
        Logic: Mini Next-Month
      </span>
    </div>
  );
}
