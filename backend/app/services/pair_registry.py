"""Centralised registry of currently-active trading pairs (cross + calendar).

Generated from the instrument resolver and pair_generator. Kept in memory and
refreshed when contracts roll. Most of the app reads from `get_pairs()` —
including spread engine, snapshot, trade engine.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from app.services.instrument_resolver import resolve_all_active
from app.services.pair_generator import generate_all

log = logging.getLogger("pair_registry")

_pairs: list[dict] = []
_pair_by_name: dict[str, dict] = {}
_subscriptions: dict[str, dict] = {}  # security_id -> {short_instrument, trading_symbol, expiry_iso}
_lock = threading.Lock()


def refresh(min_days_ahead: int = 1, max_per_instrument: int = 6) -> int:
    """Re-fetch contracts and rebuild pair list. Returns number of pairs."""
    active = resolve_all_active(min_days_ahead=min_days_ahead, max_per_instrument=max_per_instrument)
    pairs = generate_all(active)

    subs: dict[str, dict] = {}
    for short, contracts in active.items():
        for c in contracts:
            sid = str(c["security_id"])
            subs[sid] = {
                "short": short,
                "trading_symbol": c["trading_symbol"],
                "expiry": c["expiry"].isoformat(),
            }

    with _lock:
        _pairs.clear()
        _pairs.extend(pairs)
        _pair_by_name.clear()
        for p in pairs:
            _pair_by_name[p["name"]] = p
        _subscriptions.clear()
        _subscriptions.update(subs)

    log.info(
        "Pair registry refreshed: %d pairs (%d cross + %d calendar) across %d unique contracts",
        len(pairs),
        sum(1 for p in pairs if p["type"] == "cross"),
        sum(1 for p in pairs if p["type"] == "calendar"),
        len(subs),
    )
    return len(pairs)


def get_pairs() -> list[dict]:
    with _lock:
        return list(_pairs)


def get_pair(name: str) -> Optional[dict]:
    with _lock:
        return _pair_by_name.get(name)


def get_subscriptions() -> dict[str, dict]:
    """All security_ids we should subscribe to. Keys are str."""
    with _lock:
        return dict(_subscriptions)


def is_empty() -> bool:
    with _lock:
        return not _pairs
