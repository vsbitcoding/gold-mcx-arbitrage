"""Live Nifty / Sensex PE-options spread table + stored board history.

GET /api/options/spread  → 3-weekly-expiry × 10-strike spread table (live).
GET /api/options/history → auto-captured 10:00/15:00/15:15/15:35 IST board snapshots
                           (weekday filter → compare the last N Mondays etc.).
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import options_history_service, options_service

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/spread")
def get_spread(side: str = "below", user: str = Depends(get_current_user)):
    """side = 'below' (ATM+9, 10 rows) | 'above' (ATM+14, 15 rows) | 'squareoff' (ITM exit legs, 15 rows)."""
    side = side if side in ("below", "above", "squareoff") else "below"
    return {
        "status": options_service.status(),
        **options_service.get_spread_table(side),
    }


@router.get("/history")
def get_history(
    weekday: str | None = None,
    slot: str = "both",
    side: str = "below",
    weeks: int = 7,
    date: str | None = None,
    user: str = Depends(get_current_user),
):
    """Stored 10:00/15:00/15:15/15:35 IST board snapshots.

    weekday=mon..sun (or 0..6) → the last `weeks` same-weekday boards, newest
    first; omit → the last `weeks` snapshot days. date=YYYY-MM-DD → that day
    only. Each snapshot's weeks[].rows[] matches the live /spread row shape.
    """
    return options_history_service.get_history(weekday=weekday, slot=slot, side=side, weeks=weeks, date=date)
