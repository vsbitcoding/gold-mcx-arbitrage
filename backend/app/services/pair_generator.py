"""Generate the full set of trading pair configs from active MCX contracts.

Two pair types:
  - Cross:    different instruments, SAME expiry month (e.g. Petal-May vs Guinea-May)
  - Calendar: same instrument, DIFFERENT months (e.g. Petal Jun vs Petal May)

Cross uses the existing fixed lot ratios (8:1, 10:1, 100:1, 5:4, 25:2, 10:1).
Calendar uses 1:1 lots, with FAR month as "big leg" (per client spec).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("pair_generator")

# Cross-pair config: short_big, short_small, big_lots, small_lots
CROSS_TEMPLATES = [
    ("petal", "guinea", 8, 1),
    ("petal", "ten", 10, 1),
    ("petal", "mini", 100, 1),
    ("guinea", "ten", 5, 4),
    ("guinea", "mini", 25, 2),
    ("ten", "mini", 10, 1),
]

CALENDAR_INSTRUMENTS = ["petal", "guinea", "ten", "mini"]


def _expiry_tag(dt: datetime) -> str:
    """Compact expiry label for pair name: 2026-05-29."""
    return dt.strftime("%Y-%m-%d")


def _expiry_short(dt: datetime) -> str:
    """Human-friendly short label: 29 May."""
    return dt.strftime("%-d %b")


def generate_cross_pairs(active: dict[str, list[dict]]) -> list[dict]:
    """For each cross template × each (matching) expiry month, build a pair.

    'Matching' means both legs have a contract in the same calendar month.
    For Mini pairs, "same month" means Mini's nearest contract that pairs with
    that month (since Mini expires on 5th — usually Mini's month name aligns
    to the EOM contract's month).
    """
    pairs: list[dict] = []
    for big, small, big_lots, small_lots in CROSS_TEMPLATES:
        big_contracts = active.get(big, [])
        small_contracts = active.get(small, [])
        if not big_contracts or not small_contracts:
            continue

        # Iterate over big leg's expiries; for each, find the same-calendar-month
        # contract on the small leg.
        for bc in big_contracts:
            sc = _match_contract_for_month(small_contracts, bc["expiry"])
            if not sc:
                continue
            month_tag = _expiry_tag(bc["expiry"])
            pairs.append({
                "type": "cross",
                "name": f"{big.capitalize()}-{small.capitalize()}@{month_tag}",
                "label": f"{big.capitalize()}-{small.capitalize()}",
                "expiry_label": _expiry_short(bc["expiry"]),
                "big": big,
                "small": small,
                "big_lots": big_lots,
                "small_lots": small_lots,
                "big_security_id": bc["security_id"],
                "small_security_id": sc["security_id"],
                "big_trading_symbol": bc["trading_symbol"],
                "small_trading_symbol": sc["trading_symbol"],
                "big_expiry": bc["expiry"].isoformat(),
                "small_expiry": sc["expiry"].isoformat(),
            })
    return pairs


def generate_calendar_pairs(active: dict[str, list[dict]]) -> list[dict]:
    """For each instrument, generate adjacent-month calendar pairs (M1-M2, M2-M3, ...).

    Big leg = FAR month, Small leg = NEAR month (per client spec).
    1:1 lot ratio.
    """
    pairs: list[dict] = []
    for short in CALENDAR_INSTRUMENTS:
        contracts = active.get(short, [])
        if len(contracts) < 2:
            continue
        # Adjacent month pairs only (5 pairs from 6 contracts)
        for i in range(len(contracts) - 1):
            near = contracts[i]
            far = contracts[i + 1]
            near_tag = _expiry_tag(near["expiry"])
            far_tag = _expiry_tag(far["expiry"])
            name = f"{short.capitalize()}@{near_tag}/{far_tag}"
            pairs.append({
                "type": "calendar",
                "name": name,
                "label": short.capitalize(),
                "expiry_label": f"{_expiry_short(near['expiry'])} → {_expiry_short(far['expiry'])}",
                "big": short,
                "small": short,
                "big_lots": 1,
                "small_lots": 1,
                "big_security_id": far["security_id"],   # FAR = big leg
                "small_security_id": near["security_id"], # NEAR = small leg
                "big_trading_symbol": far["trading_symbol"],
                "small_trading_symbol": near["trading_symbol"],
                "big_expiry": far["expiry"].isoformat(),
                "small_expiry": near["expiry"].isoformat(),
            })
    return pairs


def _match_contract_for_month(contracts: list[dict], target_expiry: datetime) -> Optional[dict]:
    """Find contract whose expiry is in the same calendar month as target.
    For Mini (expires on 5th), this pairs Mini-of-month-X with Petal/Ten/Guinea-of-month-X.
    Falls back to nearest expiry if exact month not found."""
    same_month = [
        c for c in contracts
        if c["expiry"].year == target_expiry.year
        and c["expiry"].month == target_expiry.month
    ]
    if same_month:
        return same_month[0]
    # Fallback: closest expiry
    nearest = min(contracts, key=lambda c: abs((c["expiry"] - target_expiry).total_seconds()))
    return nearest


def generate_all(active: dict[str, list[dict]]) -> list[dict]:
    return generate_cross_pairs(active) + generate_calendar_pairs(active)
