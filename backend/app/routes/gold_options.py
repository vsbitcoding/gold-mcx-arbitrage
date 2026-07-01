"""Live GOLD vs GOLD MINI option-spread table (watch-only).

GET /api/gold-options/spread → per-strike GOLD/GOLDM option spreads (both sides),
for the current + next monthly expiry.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import goldopt_service

router = APIRouter(prefix="/api/gold-options", tags=["gold-options"])


@router.get("/spread")
def get_spread(user: str = Depends(get_current_user)):
    return {
        "status": goldopt_service.status(),
        **goldopt_service.get_spread_table(),
    }
