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

# Cached resolution of MCX front-months (refreshed via refresh()).
_state: dict = {
    "gold_full": None,    # {security_id, trading_symbol, expiry, lot_units}
    "silver_full": None,
}

# The old spec rolled one week early; the client replaced it on 31-Aug-2026
# after it put SILVERM on November while August still traded: a contract now
# stays current until 23:00 of its own expiry day. One rule for the whole
# system, defined once in instrument_resolver.live_cutoff.


def _resolve_front_month(symbol: str, min_days_ahead: int | None = None) -> Optional[dict]:
    """Find the CURRENT MCX FUTCOM contract for the base symbol.

    Default: the expiry-day rule (current until 23:00 of expiry day). Passing
    an explicit `min_days_ahead` keeps the old buffer semantics for any caller
    that needs them.
    """
    from app.services.instrument_resolver import live_cutoff
    csv_text = _download_csv()
    cutoff = (live_cutoff() if min_days_ahead is None
              else datetime.now() + timedelta(days=min_days_ahead))
    candidates: list[dict] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if row.get("SEM_EXM_EXCH_ID") != "MCX":
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "FUTCOM":
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        base = ts.split("-", 1)[0]
        if base != symbol:
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
    """Resolve front-month Full Gold + Full Silver once and cache."""
    _state["gold_full"] = _resolve_front_month("GOLD")
    _state["silver_full"] = _resolve_front_month("SILVER")
    for key, name in (("gold_full", "Full Gold"), ("silver_full", "Full Silver")):
        rec = _state.get(key)
        if rec:
            log.info(
                "%s front-month: %s (id=%s, expiry=%s)",
                name, rec["trading_symbol"], rec["security_id"], rec["expiry"].date(),
            )
        else:
            log.warning("Could not resolve %s front-month contract.", name)


def get_full_gold() -> Optional[dict]:
    return _state.get("gold_full")


def get_full_silver() -> Optional[dict]:
    return _state.get("silver_full")


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
    gold_full = get_full_gold()
    if gold_full:
        instruments.append(
            (marketfeed.MarketFeed.MCX, gold_full["security_id"], marketfeed.MarketFeed.Full)
        )
        meta[gold_full["security_id"]] = {
            "short": "gold_full",
            "trading_symbol": gold_full["trading_symbol"],
            "expiry": gold_full["expiry"].isoformat(),
            "kind": "mcx_future",
        }

    # Full Silver MCX
    silver_full = get_full_silver()
    if silver_full:
        instruments.append(
            (marketfeed.MarketFeed.MCX, silver_full["security_id"], marketfeed.MarketFeed.Full)
        )
        meta[silver_full["security_id"]] = {
            "short": "silver_full",
            "trading_symbol": silver_full["trading_symbol"],
            "expiry": silver_full["expiry"].isoformat(),
            "kind": "mcx_future",
        }

    return instruments, meta
