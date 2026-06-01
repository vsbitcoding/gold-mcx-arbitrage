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

# Cross-pair config: (short_big, short_small, big_lots, small_lots, match_mode)
#   match_mode: "same"  → small leg same calendar month as big
#               "next"  → small leg = next month AFTER big expiry (gold Mini logic)
#               "sonext"→ small leg = same month if it exists, else next after
CROSS_TEMPLATES = [
    ("petal", "guinea", 8, 1, "same"),
    ("petal", "ten", 10, 1, "same"),
    ("petal", "mini", 100, 1, "next"),
    ("guinea", "ten", 5, 4, "same"),
    ("guinea", "mini", 25, 2, "next"),
    ("ten", "mini", 10, 1, "next"),
    # Mini → Full families (client-requested, lot ratios per client note)
    ("mini", "gold", 10, 1, "sonext"),          # GOLD MINI × GOLD full
    ("silverm", "silver", 5, 1, "sonext"),      # SILVER MINI × SILVER full
    ("silvermic", "silverm", 5, 1, "sonext"),   # SILVER MIC × SILVER MINI
    # SILVER100 families — spread = (SILVER100 × 100) − small leg (client formula).
    # The ×100 lives in MULTIPLIERS["silver100"]. Lots are weight-balanced per client:
    #   10 × SILVER100 (100g) = 1000g = 1 × SILVER MIC (1 kg)
    #   50 × SILVER100 (100g) = 5000g = 1 × SILVER MINI (5 kg)
    ("silver100", "silvermic", 10, 1, "sonext"),  # SILVER100 × SILVER MIC  (10:1)
    ("silver100", "silverm", 50, 1, "sonext"),    # SILVER100 × SILVER MINI (50:1)
]

CALENDAR_INSTRUMENTS = [
    "petal", "guinea", "ten", "mini",
    "gold", "silver", "silverm", "silvermic", "silver100",
]

# Display names (GOLD prefix dropped — common knowledge it's gold trading)
MCX_SYMBOL = {
    "petal": "PETAL",
    "guinea": "GUINEA",
    "ten": "TEN",
    "mini": "MINI",
    "gold": "GOLD",
    "silver": "SILVER",
    "silverm": "SILVER MINI",
    "silvermic": "SILVER MIC",
    "silver100": "SILVER 100",
}


def _expiry_tag(dt: datetime) -> str:
    """Stable internal name part: 2026-05-29."""
    return dt.strftime("%Y-%m-%d")


def _expiry_mcx(dt: datetime) -> str:
    """MCX-style short expiry: 29MAY26."""
    return dt.strftime("%d%b%y").upper()


def _expiry_short(dt: datetime) -> str:
    """Human label: 29 May 2026."""
    return dt.strftime("%-d %b %Y")


def generate_cross_pairs(active: dict[str, list[dict]]) -> list[dict]:
    """For each cross template × each (matching) expiry month, build a pair.

    Pairing rule:
      - Non-Mini pairs (Petal-Guinea, Petal-Ten, Guinea-Ten):
        same-calendar-month for both legs.
      - Mini pairs (Petal-Mini, Guinea-Mini, Ten-Mini):
        Mini leg = NEXT month AFTER the big leg's expiry (Logic 1, per client).
        e.g. Petal 29 May → Mini 5 Jun.
    """
    pairs: list[dict] = []
    for big, small, big_lots, small_lots, match_mode in CROSS_TEMPLATES:
        big_contracts = active.get(big, [])
        small_contracts = active.get(small, [])
        if not big_contracts or not small_contracts:
            continue

        for bc in big_contracts:
            if match_mode == "next":
                sc = _match_next_month_after(small_contracts, bc["expiry"])
            elif match_mode == "sonext":
                sc = _match_same_or_next(small_contracts, bc["expiry"])
            else:  # "same"
                sc = _match_contract_for_month(small_contracts, bc["expiry"])
            if not sc:
                continue
            month_tag = _expiry_tag(bc["expiry"])
            big_sym = MCX_SYMBOL[big]
            small_sym = MCX_SYMBOL[small]
            pairs.append({
                "type": "cross",
                "name": f"{big.capitalize()}-{small.capitalize()}@{month_tag}",
                "label": f"{big_sym} / {small_sym}",
                "group_label": f"{big_sym} / {small_sym}",
                "mcx_label": f"{big_sym} / {small_sym}",
                "expiry_label": _expiry_short(bc["expiry"]),
                "expiry_short": _expiry_mcx(bc["expiry"]),
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
            sym = MCX_SYMBOL[short]
            far_short = _expiry_mcx(far["expiry"])
            near_short = _expiry_mcx(near["expiry"])
            pairs.append({
                "type": "calendar",
                "name": name,
                "label": f"{sym} {far_short}-{near_short}",
                "group_label": sym,
                "mcx_label": f"{sym} {far_short} / {sym} {near_short}",
                "expiry_label": f"Far {_expiry_short(far['expiry'])} − Near {_expiry_short(near['expiry'])}",
                "expiry_short": f"{far_short}-{near_short}",
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
    """Find contract whose expiry is in the same calendar month as target."""
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


def _match_next_month_after(contracts: list[dict], target_expiry: datetime) -> Optional[dict]:
    """Find first contract whose expiry is AFTER target_expiry (Logic 1 for Mini)."""
    after = [c for c in contracts if c["expiry"] > target_expiry]
    if not after:
        return None
    return min(after, key=lambda c: c["expiry"])


def _match_same_or_next(contracts: list[dict], target_expiry: datetime) -> Optional[dict]:
    """Same calendar month if a contract exists there, else the next one after.

    Used for Mini→Full families: the smaller leg trades monthly while the
    full contract only has a few months a year (per client's note).
    """
    same = [
        c for c in contracts
        if c["expiry"].year == target_expiry.year
        and c["expiry"].month == target_expiry.month
    ]
    if same:
        return same[0]
    return _match_next_month_after(contracts, target_expiry)


def generate_all(active: dict[str, list[dict]]) -> list[dict]:
    return generate_cross_pairs(active) + generate_calendar_pairs(active)
