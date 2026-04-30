from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TradeHistory
from app.security import get_current_user

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(TradeHistory)
        .filter(TradeHistory.exit_time >= since)
        .order_by(TradeHistory.exit_time.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "pair_name": r.pair_name,
            "mode": r.mode,
            "entry_spread": r.entry_spread,
            "exit_spread": r.exit_spread,
            "entry_time": r.entry_time.isoformat(),
            "exit_time": r.exit_time.isoformat(),
            "big_lots": r.big_lots,
            "small_lots": r.small_lots,
            "pnl": r.pnl,
            "is_paper": r.is_paper,
            "closed_by": r.closed_by,
        }
        for r in rows
    ]
