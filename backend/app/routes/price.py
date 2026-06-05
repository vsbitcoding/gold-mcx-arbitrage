"""Live price table — Buyer (bid) / Seller (ask) for every active contract of the
gold & silver instruments. Powers the 'Price' tab.

GET /api/price/table → per-instrument Buyer/Seller in the client's sequence.
"""
from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services import price_service

router = APIRouter(prefix="/api/price", tags=["price"])


@router.get("/table")
def get_table(user: str = Depends(get_current_user)):
    return {
        "status": price_service.status(),
        **price_service.get_table(),
    }
