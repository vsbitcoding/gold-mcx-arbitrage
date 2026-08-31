"""Per-pair spread math. Reads quotes from quote_store keyed by security_id.

Decrease Spread = (Big.bid × big_mult) − (Small.ask × small_mult)
Increase Spread = (Big.ask × big_mult) − (Small.bid × small_mult)

For cross pairs the multipliers come from MULTIPLIERS.
For calendar pairs both legs use the SAME instrument multiplier.
"""
from __future__ import annotations

from app.config import MULTIPLIERS
from app.services.market_data import clean_sides, quote_store
from app.services.pair_registry import get_pairs


def _rate(price: float, instrument: str) -> float:
    return price * MULTIPLIERS.get(instrument, 1.0)


def _bid(q):
    b, _a = clean_sides(q)          # crossed ghost -> no bid; fall to last trade
    return b or q.ltp


def _ask(q):
    _b, a = clean_sides(q)
    return a or q.ltp


def compute_pair(pair: dict) -> dict:
    """Compute decrease/increase spreads for a pair using its security_id quotes."""
    big_q = quote_store.get(pair["big_security_id"])
    small_q = quote_store.get(pair["small_security_id"])

    big_bid = _bid(big_q); big_ask = _ask(big_q)
    small_bid = _bid(small_q); small_ask = _ask(small_q)

    decrease_spread = None
    increase_spread = None

    if big_bid and small_ask:
        decrease_spread = round(
            _rate(big_bid, pair["big"]) - _rate(small_ask, pair["small"]), 4
        )
    if big_ask and small_bid:
        increase_spread = round(
            _rate(big_ask, pair["big"]) - _rate(small_bid, pair["small"]), 4
        )

    # Spread as % of the near/small leg's price (multiplier-correct; same value
    # the dashboard shows on Calendar). decrease_pct = decrease ÷ (small ask × mult).
    decrease_pct = None
    increase_pct = None
    small_ask_val = _rate(small_ask, pair["small"]) if small_ask else 0
    small_bid_val = _rate(small_bid, pair["small"]) if small_bid else 0
    if decrease_spread is not None and small_ask_val:
        decrease_pct = round(decrease_spread / small_ask_val * 100, 2)
    if increase_spread is not None and small_bid_val:
        increase_pct = round(increase_spread / small_bid_val * 100, 2)

    return {
        "name": pair["name"],
        "type": pair["type"],
        "label": pair.get("label", pair["name"]),
        "group_label": pair.get("group_label", pair.get("label", pair["name"])),
        "mcx_label": pair.get("mcx_label", pair.get("label", pair["name"])),
        "expiry_label": pair.get("expiry_label", ""),
        "expiry_short": pair.get("expiry_short", ""),
        "big": pair["big"],
        "small": pair["small"],
        "big_lots": pair["big_lots"],
        "small_lots": pair["small_lots"],
        "big_security_id": pair["big_security_id"],
        "small_security_id": pair["small_security_id"],
        "big_trading_symbol": pair.get("big_trading_symbol", ""),
        "small_trading_symbol": pair.get("small_trading_symbol", ""),
        "big_expiry": pair.get("big_expiry", ""),
        "small_expiry": pair.get("small_expiry", ""),
        "big_bid": big_bid,
        "big_ask": big_ask,
        "small_bid": small_bid,
        "small_ask": small_ask,
        "decrease_spread": decrease_spread,
        "increase_spread": increase_spread,
        "decrease_pct": decrease_pct,
        "increase_pct": increase_pct,
    }


def compute_all() -> list[dict]:
    return [compute_pair(p) for p in get_pairs()]
