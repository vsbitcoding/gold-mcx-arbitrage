"""Build the live spread payload (WATCH-ONLY).

Trade-firing was removed (see docs/TRADE_FIRING_SYSTEM.md). The payload is the
computed spreads for every pair plus, for cross pairs, the live mean-reversion
SIGNAL (direction + entry + target) when one is active.
"""
from app.services import signal_service
from app.services.spread_engine import compute_all


def build_live_payload(db=None) -> list[dict]:
    snaps = compute_all()
    try:
        sigs = signal_service.evaluate_all(snaps)
        for s in snaps:
            s["signal"] = sigs.get(s.get("name"))
    except Exception:
        # never let signal evaluation break the live payload
        for s in snaps:
            s.setdefault("signal", None)
    return snaps
