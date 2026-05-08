"""Extra subscriptions for the Calculator page:
- GOLDBEES (NIPPON India Gold ETF, NSE equity, security_id 1660)
- Full Gold MCX front-month (lot = 1 kg, symbol = GOLD)
- Future: Silver counterparts (placeholder until client confirms formula).

These are NOT part of the 56-pair arbitrage registry — they're a side-channel
subscription whose ticks land in the same `quote_store`, keyed by security_id.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.services.instrument_resolver import _download_csv, _parse_expiry

log = logging.getLogger("extra_instruments")

# NSE security IDs (verified against Dhan scrip master — NIP IND ETF GOLD BEES / NETF SILVER)
GOLDBEES_NSE_SECURITY_ID = "14428"
GOLDBEES_TRADING_SYMBOL = "GOLDBEES"

SILVERBEES_NSE_SECURITY_ID = "8080"
SILVERBEES_TRADING_SYMBOL = "SILVERBEES"

# Cached resolution of the Full Gold front-month (refreshed via refresh()).
_state: dict = {
    "gold_full": None,    # {security_id, trading_symbol, expiry, lot_units}
}


def _resolve_full_gold_front_month(min_days_ahead: int = 1) -> Optional[dict]:
    """Find the nearest active 'GOLD' (1 kg full) MCX contract."""
    csv_text = _download_csv()
    cutoff = datetime.now() + timedelta(days=min_days_ahead)
    candidates: list[dict] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if row.get("SEM_EXM_EXCH_ID") != "MCX":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        # Filter the bare "GOLD" symbol — exclude GOLDM, GOLDPETAL, GOLDGUINEA, GOLDTEN.
        symbol = ts.split("-", 1)[0]
        if symbol != "GOLD":
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry or expiry < cutoff:
            continue
        candidates.append({
            "security_id": str(row.get("SEM_SMST_SECURITY_ID")),
            "trading_symbol": ts,
            "expiry": expiry,
            "lot_units": row.get("SEM_LOT_UNITS"),
        })
    candidates.sort(key=lambda r: r["expiry"])
    return candidates[0] if candidates else None


def refresh() -> None:
    """Resolve front-month Full Gold once and cache. Called at feed startup."""
    full = _resolve_full_gold_front_month()
    _state["gold_full"] = full
    if full:
        log.info(
            "Full Gold front-month: %s (id=%s, expiry=%s)",
            full["trading_symbol"], full["security_id"], full["expiry"].date(),
        )
    else:
        log.warning("Could not resolve Full Gold front-month contract.")


def get_full_gold() -> Optional[dict]:
    return _state.get("gold_full")


def get_extra_subscriptions() -> tuple[list[tuple], dict[str, dict]]:
    """Return (instruments, metadata) for Dhan feed.

    instruments: list of (exchange, security_id, request_code)
    metadata: {security_id: {short, trading_symbol, kind, ...}}
    """
    from dhanhq import marketfeed  # imported lazily — only present in venv

    instruments: list[tuple] = []
    meta: dict[str, dict] = {}

    # GOLDBEES — NSE equity
    instruments.append(
        (marketfeed.MarketFeed.NSE, GOLDBEES_NSE_SECURITY_ID, marketfeed.MarketFeed.Full)
    )
    meta[GOLDBEES_NSE_SECURITY_ID] = {
        "short": "goldbees",
        "trading_symbol": GOLDBEES_TRADING_SYMBOL,
        "kind": "etf",
    }

    # SILVERBEES — NSE equity (pre-subscribe for the upcoming silver calculator)
    instruments.append(
        (marketfeed.MarketFeed.NSE, SILVERBEES_NSE_SECURITY_ID, marketfeed.MarketFeed.Full)
    )
    meta[SILVERBEES_NSE_SECURITY_ID] = {
        "short": "silverbees",
        "trading_symbol": SILVERBEES_TRADING_SYMBOL,
        "kind": "etf",
    }

    # Full Gold MCX
    full = get_full_gold()
    if full:
        instruments.append(
            (marketfeed.MarketFeed.MCX, full["security_id"], marketfeed.MarketFeed.Full)
        )
        meta[full["security_id"]] = {
            "short": "gold_full",
            "trading_symbol": full["trading_symbol"],
            "expiry": full["expiry"].isoformat(),
            "kind": "mcx_future",
        }

    return instruments, meta
