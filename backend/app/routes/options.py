"""Live Nifty / Sensex PE-options spread table.

GET /api/options-spread → 3-weekly-expiry × 10-strike spread table.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import options_service

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/spread")
def get_spread(side: str = "below", user: str = Depends(get_current_user)):
    """side = 'below' (ATM + 9 lower, 10 rows) | 'above' (ATM + 14 higher, 15 rows)."""
    side = "above" if side == "above" else "below"
    return {
        "status": options_service.status(),
        **options_service.get_spread_table(side),
    }
