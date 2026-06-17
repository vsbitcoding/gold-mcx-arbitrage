"""Live Nifty / Sensex PE-options spread table.

GET /api/options-spread → 3-weekly-expiry × 10-strike spread table.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import options_service

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/spread")
def get_spread(side: str = "below", user: str = Depends(get_current_user)):
    """side = 'below' (ATM+9, 10 rows) | 'above' (ATM+14, 15 rows) | 'squareoff' (ITM exit legs, 15 rows)."""
    side = side if side in ("below", "above", "squareoff") else "below"
    return {
        "status": options_service.status(),
        **options_service.get_spread_table(side),
    }
