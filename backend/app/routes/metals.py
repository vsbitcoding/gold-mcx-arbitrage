"""Live base-metal calendar-spread table (watch-only) — powers the 'Metal' tab.

GET /api/metals/spread → per-metal adjacent-month calendar spreads.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import metals_service

router = APIRouter(prefix="/api/metals", tags=["metals"])


@router.get("/spread")
def get_spread(user: str = Depends(get_current_user)):
    return {
        "formula": "difference = far.buy − near.sell ; pct = difference ÷ near.sell × 100",
        "status": metals_service.status(),
        **metals_service.get_table(),
    }
