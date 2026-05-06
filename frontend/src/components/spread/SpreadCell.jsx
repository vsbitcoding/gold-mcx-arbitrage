import React from "react";
import { fmtSpread } from "../../utils/format.js";

/**
 * Spread <td> with the standard tone color (red for decrease, green for increase).
 */
export default function SpreadCell({ value, tone = "dec", className = "" }) {
  const toneCls = tone === "dec" ? "dec-tone" : "inc-tone";
  return (
    <td className={`spread-num ${toneCls} ${className}`.trim()}>
      {fmtSpread(value)}
    </td>
  );
}
