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


def resolve_near_month_ids(min_days_ahead: int = 0) -> dict[str, dict]:
    """Return {short_name: {security_id, trading_symbol, expiry, lot_size}} for the
    nearest non-expired MCX FUTCOM contract per instrument.

    min_days_ahead=0 -> include contracts expiring today
    min_days_ahead=1 -> only contracts expiring tomorrow or later
    """
    csv_text = _download_csv()
    cutoff = datetime.now() + timedelta(days=min_days_ahead)

    # symbol -> list of (expiry_dt, security_id, trading_symbol, lot_units)
    candidates: dict[str, list] = {sym: [] for sym in SYMBOL_MAP.values()}

    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if row.get("SEM_EXM_EXCH_ID") != "MCX":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        # Match e.g. GOLDPETAL-30Apr2026-FUT, GOLDM-05May2026-FUT
        symbol = ts.split("-", 1)[0]
        if symbol not in candidates:
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry or expiry < cutoff:
            continue
        candidates[symbol].append({
            "security_id": row.get("SEM_SMST_SECURITY_ID"),
            "trading_symbol": ts,
            "expiry": expiry,
            "lot_units": row.get("SEM_LOT_UNITS"),
        })

    out: dict[str, dict] = {}
    for short, sym in SYMBOL_MAP.items():
        rows = sorted(candidates.get(sym, []), key=lambda r: r["expiry"])
        if not rows:
            log.warning("No active contract found for %s (%s)", short, sym)
            continue
        pick = rows[0]
        out[short] = pick
        log.info(
            "Resolved %s -> %s (id=%s, expires %s)",
            short, pick["trading_symbol"], pick["security_id"], pick["expiry"].strftime("%Y-%m-%d"),
        )
    return out
