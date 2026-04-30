from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Position
from app.security import get_current_user
from app.services.trade_engine import live_pnl, manual_close

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("")
def list_open(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    rows = db.query(Position).filter(Position.status == "open").order_by(Position.id.desc()).all()
    return [
        {
            "id": p.id,
            "pair_name": p.pair_name,
            "mode": p.mode,
            "entry_spread": p.entry_spread,
            "entry_time": p.entry_time.isoformat(),
            "big_lots": p.big_lots,
            "small_lots": p.small_lots,
            "big_price": p.big_price,
            "small_price": p.small_price,
            "is_paper": p.is_paper,
            "live_pnl": live_pnl(p),
        }
        for p in rows
    ]


@router.post("/{position_id}/close")
def close(position_id: int, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    closed = manual_close(db, position_id)
    if not closed:
        raise HTTPException(400, "Position not found or quote unavailable")
    return {"ok": True, "history_id": closed.id, "pnl": closed.pnl}
