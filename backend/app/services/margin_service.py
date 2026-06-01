"""Margin requirement service.

Returns rupee margin per pair-fire and per open position. Today uses
hardcoded percentages calibrated against real broker leverage figures
(SEBI SPAN + ELM range). Designed so the engine treats this as a black box —
the source can be swapped for a daily MCX SPAN file later without touching
the rest of the codebase.

Calibration source: typical Dhan/Zerodha/Upstox margin % for MCX commodity
futures (verified against the 10.78X leverage shown for GOLDGUINEA).
"""
from __future__ import annotations

from typing import Optional

from app.models import Position
from app.services import pair_registry, span_service
from app.services.market_data import quote_store

# Margin percentage applied to (lots × price) for each MCX instrument leg.
# Tuned to match real broker margins within ~5%.
MARGIN_PERCENT: dict[str, float] = {
    "petal":     10.0,
    "guinea":     9.3,
    "ten":       10.0,
    "mini":      10.0,
    "silvermic": 11.0,
    "silverm":   12.0,
    "silver":    13.0,
    "silver100": 11.0,
}

DEFAULT_PCT = 10.0


def get_margin_percent(instrument: str | None) -> float:
    if not instrument:
        return DEFAULT_PCT
    return MARGIN_PERCENT.get(instrument.lower(), DEFAULT_PCT)


def _leg_value(lots: int, price: float | None) -> float:
    if not price or not lots:
        return 0.0
    return lots * price


def _leg_margin(security_id: str | None, instrument: str | None, lots: int, price: float | None) -> float:
    """Resolve one leg's margin. SPAN cache first, fallback to % × LTP."""
    if not lots:
        return 0.0
    span = span_service.get_margin_for_security_id(security_id)
    if span is not None:
        return lots * span
    pct = get_margin_percent(instrument) / 100.0
    return _leg_value(lots, price) * pct


def margin_for_position(p: Position) -> float:
    """Margin locked by a single open paper position.

    Prefers SPAN value per leg (security_id keyed). Falls back to
    `lots × entry_price × instrument %` only if SPAN cache has no entry
    for that contract.
    """
    pair = pair_registry.get_pair(p.pair_name)
    if not pair:
        return 0.0
    return (
        _leg_margin(pair.get("big_security_id"), pair.get("big"), p.big_lots, p.big_price)
        + _leg_margin(pair.get("small_security_id"), pair.get("small"), p.small_lots, p.small_price)
    )


def _live_price_for_leg(security_id: str | None) -> float | None:
    if not security_id:
        return None
    q = quote_store.get(security_id)
    return q.ltp or q.bid or q.ask or None


def estimated_margin_for_fire(pair: dict) -> float:
    """Estimate margin a NEW fire of this pair would consume right now.

    SPAN cache first per leg; falls back to live LTP × instrument %.
    """
    big_price = _live_price_for_leg(pair.get("big_security_id"))
    small_price = _live_price_for_leg(pair.get("small_security_id"))
    return (
        _leg_margin(pair.get("big_security_id"), pair.get("big"), pair.get("big_lots", 0), big_price)
        + _leg_margin(pair.get("small_security_id"), pair.get("small"), pair.get("small_lots", 0), small_price)
    )


def reference_table() -> list[dict]:
    """For UI display: instrument → margin % table."""
    return [
        {"instrument": k.upper(), "margin_percent": v}
        for k, v in MARGIN_PERCENT.items()
    ]
