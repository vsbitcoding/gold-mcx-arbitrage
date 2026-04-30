"""Resolve current near-month MCX gold security IDs from Dhan scrip master CSV.

CSV: https://images.dhan.co/api-data/api-scrip-master.csv
Header: SEM_EXM_EXCH_ID, SEM_SEGMENT, SEM_SMST_SECURITY_ID, SEM_INSTRUMENT_NAME,
        SEM_EXPIRY_CODE, SEM_TRADING_SYMBOL, SEM_LOT_UNITS, SEM_CUSTOM_SYMBOL,
        SEM_EXPIRY_DATE, ...

Picks the nearest expiry > today for each contract.
"""
from __future__ import annotations

import csv
import io
import logging
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("instrument_resolver")

CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
CACHE_FILE = "/tmp/dhan-scrip-master.csv"
CACHE_TTL_SECONDS = 6 * 3600  # refresh CSV every 6 hours

# Map our short instrument names to the trading symbol prefix used in CSV
SYMBOL_MAP = {
    "petal": "GOLDPETAL",
    "guinea": "GOLDGUINEA",
    "ten": "GOLDTEN",
    "mini": "GOLDM",  # GOLDM = Gold Mini
}


def _download_csv() -> str:
    try:
        st = time.time() - (CACHE_TTL_SECONDS + 1)
        if _cache_valid():
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


def _cache_valid() -> bool:
    import os
    try:
        st = os.stat(CACHE_FILE)
        return (time.time() - st.st_mtime) < CACHE_TTL_SECONDS
    except FileNotFoundError:
        return False


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


def resolve_near_month_ids(
    min_days_ahead: int = 3,
    mini_rule: str = "next_month",
) -> dict[str, dict]:
    """Return {short_name: contract_info} for current active MCX gold contracts.

    Logic:
      - Petal / Guinea / Ten -> nearest expiry that is >= today + min_days_ahead
        (default 3 days, so we don't trade illiquid expiry-day contracts)
      - Mini -> depends on mini_rule:
        * "next_month": first Mini contract that expires AFTER the
          end-of-month leg's expiry (Logic 1: pairs end-of-month + next-Mini)
        * "same_month": first Mini contract that expires in the SAME calendar
          month as the end-of-month leg (Logic 2)
        * "nearest": nearest Mini, no special pairing logic
    """
    candidates = _all_candidates_by_symbol(min_days_ahead)
    out: dict[str, dict] = {}

    for short in ("petal", "guinea", "ten"):
        sym = SYMBOL_MAP[short]
        rows = candidates.get(sym, [])
        if not rows:
            log.warning("No active contract for %s (%s)", short, sym)
            continue
        out[short] = rows[0]

    # Reference expiry from end-of-month leg (use Petal as anchor; all 3 share
    # the same end-of-month date so this is fine even if one is missing)
    eom_expiry = None
    for short in ("petal", "guinea", "ten"):
        if short in out:
            eom_expiry = out[short]["expiry"]
            break

    mini_rows = candidates.get(SYMBOL_MAP["mini"], [])
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
    else:
        log.warning("No active Mini contract")

    for short, info in out.items():
        log.info(
            "Resolved %s -> %s (id=%s, expires %s)",
            short, info["trading_symbol"], info["security_id"],
            info["expiry"].strftime("%Y-%m-%d"),
        )
    return out
