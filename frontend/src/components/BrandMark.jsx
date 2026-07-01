import React from "react";

// Gurukrupa Bullion mark, rendered inline so it follows the app theme:
// fill = var(--brand-gold) → deeper gold on light, brighter gold on dark.
export default function BrandMark({ className = "", size = 28, title = "Gurukrupa Bullion" }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="-8 -8 79 71"
      role="img"
      aria-label={title}
      fill="var(--brand-gold)"
    >
      <polygon points="20,0 29,17 19,34 0,34" />
      <polygon points="43,0 34,17 44,34 63,34" />
      <polygon points="21,38 42,38 51,55 12,55" />
    </svg>
  );
}
