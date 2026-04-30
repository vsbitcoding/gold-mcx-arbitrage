import React, { useEffect, useRef, useState } from "react";

export default function SpreadCell({ value, tone }) {
  const prev = useRef(value);
  const [flash, setFlash] = useState(""); // "up" | "down" | ""
  const timer = useRef(null);

  useEffect(() => {
    if (value === null || value === undefined) return;
    if (prev.current === null || prev.current === undefined) {
      prev.current = value;
      return;
    }
    if (value === prev.current) return;

    setFlash(value > prev.current ? "up" : "down");
    prev.current = value;

    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setFlash(""), 700);
    return () => timer.current && clearTimeout(timer.current);
  }, [value]);

  const display =
    value === null || value === undefined ? "—" : Number(value).toFixed(2);

  return (
    <span className={`spread-cell ${tone || ""} ${flash}`}>
      {flash === "up" && <span className="arrow">▲</span>}
      {flash === "down" && <span className="arrow">▼</span>}
      <span className="num">{display}</span>
    </span>
  );
}
