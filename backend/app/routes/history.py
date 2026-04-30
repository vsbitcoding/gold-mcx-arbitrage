from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import PAIRS
from app.database import get_db
from app.models import TradeHistory
from app.security import get_current_user

router = APIRouter(prefix="/api/history", tags=["history"])


def _pair_def(name: str) -> dict | None:
    return next((p for p in PAIRS if p["name"] == name), None)


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
    out = []
    for r in rows:
        pair_def = _pair_def(r.pair_name)
        big_inst = pair_def["big"] if pair_def else None
        small_inst = pair_def["small"] if pair_def else None
        big_action = "SELL" if r.mode == "decrease" else "BUY"
        small_action = "BUY" if r.mode == "decrease" else "SELL"
        # Duration in seconds
        duration = (r.exit_time - r.entry_time).total_seconds() if r.entry_time else 0
        out.append({
            "id": r.id,
            "pair_name": r.pair_name,
            "mode": r.mode,
            "entry_spread": r.entry_spread,
            "exit_spread": r.exit_spread,
            "entry_time": r.entry_time.isoformat() if r.entry_time else None,
            "exit_time": r.exit_time.isoformat() if r.exit_time else None,
            "duration_seconds": duration,
            "big_instrument": big_inst,
            "big_action": big_action,
            "big_lots": r.big_lots,
            "big_entry_price": r.big_entry_price,
            "big_exit_price": r.big_exit_price,
            "small_instrument": small_inst,
            "small_action": small_action,
            "small_lots": r.small_lots,
            "small_entry_price": r.small_entry_price,
            "small_exit_price": r.small_exit_price,
            "weight_grams": r.weight_grams,
            "pnl": r.pnl,
            "is_paper": r.is_paper,
            "closed_by": r.closed_by,
        })
    return out
