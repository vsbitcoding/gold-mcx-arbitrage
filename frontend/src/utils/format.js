// Shared display formatters. All times rendered in IST 12-hour regardless
// of browser timezone. Numbers in en-IN locale (lakh/crore separators).

export function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPnl(v) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  const sign = n >= 0 ? "+" : "−";
  return (
    sign +
    Math.abs(n).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

export function fmtSpread(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(2);
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

export function fmtDuration(secs) {
  if (secs === null || secs === undefined) return "—";
  const s = Math.round(secs);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function cap(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}
