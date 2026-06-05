"""Live price table — Buyer (bid) / Seller (ask) for every active contract of the
gold & silver instruments. Powers the 'Price' tab. Watch-only.

These instruments are already subscribed (Full mode) by the cross/calendar feed,
so this service only resolves their active contracts and reads bid/ask from the
quote store — no new subscription needed.
"""
from __future__ import annotations

import logging

from app.services import instrument_resolver
from app.services.market_data import quote_store

log = logging.getLogger("price_service")

# (instrument short, display name) in the client's exact display sequence.
PRICE_SEQUENCE: list[tuple[str, str]] = [
    ("gold", "Gold"),
    ("silver", "Silver"),
    ("mini", "Gold Mini"),
    ("silverm", "Silver Mini"),
    ("ten", "Gold Ten"),
    ("guinea", "Gold Guinea"),
    ("petal", "Gold Petal"),
    ("silvermic", "Silver Mic"),
    ("silver100", "Silver 100"),
]

_state: dict = {"contracts": {}}  # {short: [contract dicts]}


def refresh() -> None:
    """Resolve active contracts for the gold/silver instruments (same set the
    pair feed subscribes, so every contract has live bid/ask)."""
    active = instrument_resolver.resolve_all_active(min_days_ahead=1, max_per_instrument=6)
    _state["contracts"] = active
    n = sum(len(v) for v in active.values())
    log.info("Price: %d active contracts across %d instruments", n, len(active))


def get_table() -> dict:
    """Per-instrument Buyer/Seller price table in the client's sequence."""
    groups = []
    for short, disp in PRICE_SEQUENCE:
        contracts = _state["contracts"].get(short, [])
        rows = []
        for c in contracts:
            q = quote_store.get(c["security_id"])
            rows.append({
                "contract": c["expiry"].strftime("%d %b %Y"),
                "trading_symbol": c["trading_symbol"],
                "buyer": (q.bid or None),    # bid
                "seller": (q.ask or None),   # ask
                "ltp": (q.ltp or None),
            })
        groups.append({
            "instrument": disp,
            "short": short,
            "count": len(rows),
            "contracts": rows,
        })
    return {"groups": groups, "count": sum(len(g["contracts"]) for g in groups)}


def status() -> dict:
    return {"price_instruments": len(_state.get("contracts", {}))}
