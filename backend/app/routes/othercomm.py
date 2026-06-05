"""Live other-commodity calendar-spread table (watch-only) — powers the 'Other
Commodity' tab (Crude / NatGas / Electricity). No % column.

GET /api/othercomm/spread → per-family adjacent-month calendar spreads.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import othercomm_service

router = APIRouter(prefix="/api/othercomm", tags=["othercomm"])


@router.get("/spread")
def get_spread(user: str = Depends(get_current_user)):
    return {
        "formula": "difference = far.buy − near.sell",
        "status": othercomm_service.status(),
        **othercomm_service.get_table(),
    }
