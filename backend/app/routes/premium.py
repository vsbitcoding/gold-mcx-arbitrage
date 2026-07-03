"""Live premium-calc inputs (XAU/USD + USD/INR + MCX gold). Read-only, in-memory."""
from fastapi import APIRouter

from app.services import premium_feed

router = APIRouter(prefix="/api", tags=["premium"])


@router.get("/premium-inputs")
def premium_inputs():
    return premium_feed.get_inputs()
