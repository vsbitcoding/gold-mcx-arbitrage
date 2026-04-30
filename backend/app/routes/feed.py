from fastapi import APIRouter, Depends

from app.security import get_current_user
from app.services.dhan_feed import get_status

router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get("/status")
def feed_status(_user: str = Depends(get_current_user)):
    return get_status()
