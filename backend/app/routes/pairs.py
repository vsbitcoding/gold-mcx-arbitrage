from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.security import get_current_user
from app.services.snapshot import build_live_payload

router = APIRouter(prefix="/api/pairs", tags=["pairs"])


@router.get("/live")
def live(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    return build_live_payload(db)


@router.get("/spread-history")
def spread_history(pair: str, days: int = 120,
                   user: str = Depends(get_current_user)):
    """Day-by-day spread of one calendar pair, from each leg's DAILY CLOSE -
    one value per day, the client's rule (02-Sep: "increase-decrease karta
    single value aapi de, based on closing price"). Computed on demand from
    Dhan candles behind an hour's cache; nothing is stored."""
    days = max(7, min(int(days), 400))
    from app.services.spread_close_history import pair_history
    return pair_history(pair, days)
