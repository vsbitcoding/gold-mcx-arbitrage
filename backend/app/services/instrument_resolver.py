"""Resolve all active MCX gold contracts (Petal/Guinea/Ten/Mini) from the
Dhan scrip master CSV. Returns up to 6 future expiries per instrument."""
from __future__ import annotations

import csv
import io
import logging
import os
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("instrument_resolver")

CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
CACHE_FILE = "/tmp/dhan-scrip-master.csv"
CACHE_TTL_SECONDS = 6 * 3600

SYMBOL_MAP = {
    "petal": "GOLDPETAL",
    "guinea": "GOLDGUINEA",
    "ten": "GOLDTEN",
    "mini": "GOLDM",
    # Mini→Full families (client-requested)
    "gold": "GOLD",          # GOLD full (1 kg)
    "silver": "SILVER",      # SILVER full (30 kg)
    "silverm": "SILVERM",    # SILVER MINI (5 kg)
    "silvermic": "SILVERMIC",  # SILVER MIC (1 kg)
    "silver100": "SILVER100",  # SILVER 100 (100 g)
}


def _cache_valid() -> bool:
    try:
        st = os.stat(CACHE_FILE)
        return (time.time() - st.st_mtime) < CACHE_TTL_SECONDS
    except FileNotFoundError:
        return False


def _download_csv() -> str:
    if _cache_valid():
        try:
            with open(CACHE_FILE, "r") as f:
                return f.read()
        except Exception:
            pass
    log.info("Downloading Dhan scrip master CSV...")
    with urllib.request.urlopen(CSV_URL, timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    try:
        with open(CACHE_FILE, "w") as f:
            f.write(body)
    except Exception as e:
        log.warning("Could not cache CSV: %s", e)
    return body


def _parse_expiry(s: str) -> Optional[datetime]:
    if not s or s == "NA":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(s.split()[0], "%Y-%m-%d")
        except Exception:
            return None


def _all_candidates_by_symbol(min_days_ahead: int) -> dict[str, list]:
    """Return all valid future contracts grouped by symbol, sorted by expiry."""
    csv_text = _download_csv()
    cutoff = datetime.now() + timedelta(days=min_days_ahead)
    out: dict[str, list] = {sym: [] for sym in SYMBOL_MAP.values()}
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if row.get("SEM_EXM_EXCH_ID") != "MCX":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        symbol = ts.split("-", 1)[0]
        if symbol not in out:
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry or expiry < cutoff:
            continue
        out[symbol].append({
            "security_id": row.get("SEM_SMST_SECURITY_ID"),
            "trading_symbol": ts,
            "expiry": expiry,
            "lot_units": row.get("SEM_LOT_UNITS"),
        })
    for sym in out:
        out[sym].sort(key=lambda r: r["expiry"])
    return out


def resolve_all_active(min_days_ahead: int = 1, max_per_instrument: int = 6) -> dict[str, list[dict]]:
    """Return all active contracts per short instrument name.

    Returns: {"petal": [c1, c2, ..., c6], "guinea": [...], "ten": [...], "mini": [...]}
    Each contract dict has: security_id, trading_symbol, expiry, lot_units.
    Sorted by expiry ascending. Skips contracts expiring within min_days_ahead.
    """
    candidates = _all_candidates_by_symbol(min_days_ahead)
    out: dict[str, list[dict]] = {}
    for short, sym in SYMBOL_MAP.items():
        rows = candidates.get(sym, [])[:max_per_instrument]
        if not rows:
            log.warning("No active contracts found for %s (%s)", short, sym)
            continue
        out[short] = rows
        log.info(
            "Resolved %d %s contracts: %s",
            len(rows), short,
            ", ".join(f"{r['trading_symbol']}(id={r['security_id']})" for r in rows),
        )
    return out


# Backward-compat: keep old single-contract API for callers that still need it
def resolve_near_month_ids(
    min_days_ahead: int = 3, mini_rule: str = "next_month"
) -> dict[str, dict]:
    """Legacy API used by older code paths. Returns one contract per instrument.
    For new multi-pair system, use resolve_all_active() instead."""
    all_active = resolve_all_active(min_days_ahead=min_days_ahead, max_per_instrument=12)
    out: dict[str, dict] = {}
    for short in ("petal", "guinea", "ten"):
        rows = all_active.get(short, [])
        if rows:
            out[short] = rows[0]
    eom_expiry = None
    for short in ("petal", "guinea", "ten"):
        if short in out:
            eom_expiry = out[short]["expiry"]
            break
    mini_rows = all_active.get("mini", [])
    if mini_rows:
        if mini_rule == "next_month" and eom_expiry:
            picked = next((r for r in mini_rows if r["expiry"] > eom_expiry), None)
            out["mini"] = picked or mini_rows[0]
        elif mini_rule == "same_month" and eom_expiry:
            picked = next(
                (r for r in mini_rows
                 if r["expiry"].year == eom_expiry.year and r["expiry"].month == eom_expiry.month),
                None,
            )
            out["mini"] = picked or mini_rows[0]
        else:
            out["mini"] = mini_rows[0]
    return out
