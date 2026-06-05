import React from "react";
import { fmtNum } from "../utils/format.js";

// Live Buyer (bid) / Seller (ask) price for every active contract of the gold &
// silver instruments. Watch-only — price only, no spread / no %.
export default function PriceTable({ data, embedded = false }) {
  const groups = (data?.groups || []).filter((g) => g.contracts && g.contracts.length);

  return (
    <div className={`metal-page${embedded ? " metal-embedded" : ""}`}>
      {!groups.length ? (
        <div className="empty-state">Loading price data…</div>
      ) : (
        <div className="metal-cards price-cards">
          {groups.map((g) => (
            <div className="metal-card price-card" key={g.short}>
              <div className="metal-card-head">{g.instrument}</div>
              <div className="metal-card-body">
                <div className="price-row price-head-row">
                  <div className="pr-month">Expiry</div>
                  <div className="pr-buy">Buyer</div>
                  <div className="pr-sell">Seller</div>
                </div>
                {g.contracts.map((c, i) => (
                  <div className="price-row" key={i}>
                    <div className="pr-month">{c.contract}</div>
                    <div className="pr-buy">{c.buyer == null ? "—" : fmtNum(c.buyer, 2)}</div>
                    <div className="pr-sell">{c.seller == null ? "—" : fmtNum(c.seller, 2)}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
