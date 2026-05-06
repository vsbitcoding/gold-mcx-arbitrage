import { useEffect, useRef, useState } from "react";

/**
 * Trigger a brief CSS class when a numeric value changes.
 * Returns "flash-up" when value increased, "flash-down" when decreased,
 * empty string otherwise. Auto-clears after `ms` milliseconds.
 */
export function useFlash(value, ms = 350) {
  const prev = useRef(value);
  const [flash, setFlash] = useState("");

  useEffect(() => {
    if (prev.current === undefined || prev.current === null || value === undefined || value === null) {
      prev.current = value;
      return;
    }
    if (Number(value) > Number(prev.current)) setFlash("flash-up");
    else if (Number(value) < Number(prev.current)) setFlash("flash-down");
    prev.current = value;
    if (!flash) return;
    const t = setTimeout(() => setFlash(""), ms);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return flash;
}
