import React from "react";

export default function SpreadCell({ value, tone }) {
  const display =
    value === null || value === undefined ? "—" : Number(value).toFixed(2);
  return (
    <span className={`spread-cell ${tone || ""}`}>
      <span className="num">{display}</span>
    </span>
  );
}
