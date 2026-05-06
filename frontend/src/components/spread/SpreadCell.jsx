import React from "react";
import { fmtSpread } from "../../utils/format.js";
import { useFlash } from "../../utils/useFlash.js";

/**
 * <td> with a brief green/red pulse when the spread changes.
 * Use as: <SpreadCell value={...} tone="dec" className="..." />
 */
export default function SpreadCell({ value, tone = "dec", className = "" }) {
  const flash = useFlash(value);
  const toneCls = tone === "dec" ? "dec-tone" : "inc-tone";
  return (
    <td className={`spread-num ${toneCls} ${flash} ${className}`.trim()}>
      {fmtSpread(value)}
    </td>
  );
}
