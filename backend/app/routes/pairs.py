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
    """Daily spread history for one pair (client, 02-Sep: he wants the stored
    numbers visible, not just stored). Rows before a pair went live are the
    close-based backfill - decrease and increase equal there by construction."""
    days = max(7, min(int(days), 400))
    from datetime import datetime, timedelta
    from app.models import DailySpread
    db = SessionLocal()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = (db.query(DailySpread)
                .filter(DailySpread.pair_name == pair,
                        DailySpread.snap_date >= cutoff)
                .order_by(DailySpread.snap_date.desc()).all())
        return {"pair": pair, "days": days, "count": len(rows), "rows": [{
            "date": r.snap_date,
            "decrease": r.decrease_spread, "decrease_pct": r.decrease_pct,
            "increase": r.increase_spread, "increase_pct": r.increase_pct,
        } for r in rows]}
    finally:
        db.close()
