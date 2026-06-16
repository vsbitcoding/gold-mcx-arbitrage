"""Build the live spread payload (WATCH-ONLY).

Trade-firing was removed (see docs/TRADE_FIRING_SYSTEM.md). The payload is now
just the computed spreads for every pair — no ladders, positions, or status.
"""
from app.services.spread_engine import compute_all


def build_live_payload(db=None) -> list[dict]:
    return compute_all()
