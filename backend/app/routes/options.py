"""Live Nifty / Sensex PE-options spread table.

GET /api/options-spread → 3-weekly-expiry × 10-strike spread table.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import options_service

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/spread")
def get_spread(user: str = Depends(get_current_user)):
    return {
        "status": options_service.status(),
        **options_service.get_spread_table(),
    }
