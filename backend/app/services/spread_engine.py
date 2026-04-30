"""Pure spread math. Decrease and Increase spreads from bid/ask only (no LTP)."""
from app.config import MULTIPLIERS, PAIRS
from app.services.market_data import quote_store


def _rate(price: float, instrument: str) -> float:
    return price * MULTIPLIERS.get(instrument, 1.0)


def compute_pair(pair: dict) -> dict:
    """Compute decrease and increase spreads for a single pair."""
    big_q = quote_store.get(pair["big"])
    small_q = quote_store.get(pair["small"])

    decrease_spread = None
    increase_spread = None

    if big_q.bid and small_q.ask:
        decrease_spread = round(_rate(big_q.bid, pair["big"]) - _rate(small_q.ask, pair["small"]), 4)
    if big_q.ask and small_q.bid:
        increase_spread = round(_rate(big_q.ask, pair["big"]) - _rate(small_q.bid, pair["small"]), 4)

    return {
        "name": pair["name"],
        "big": pair["big"],
        "small": pair["small"],
        "big_lots": pair["big_lots"],
        "small_lots": pair["small_lots"],
        "big_bid": big_q.bid,
        "big_ask": big_q.ask,
        "small_bid": small_q.bid,
        "small_ask": small_q.ask,
        "decrease_spread": decrease_spread,
        "increase_spread": increase_spread,
    }


def compute_all() -> list[dict]:
    return [compute_pair(p) for p in PAIRS]
