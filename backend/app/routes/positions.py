from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import GRAMS_PER_LOT, PAIRS
from app.database import get_db
from app.models import Position
from app.security import get_current_user
from app.services.spread_engine import compute_pair
from app.services.trade_engine import live_pnl, manual_close

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _enrich(p: Position) -> dict:
    pair_def = next((x for x in PAIRS if x["name"] == p.pair_name), None)
    snap = compute_pair(pair_def) if pair_def else None
    big_inst = pair_def["big"] if pair_def else None
    small_inst = pair_def["small"] if pair_def else None

    big_live = small_live = None
    cover_spread = None
    if snap:
        if p.mode == "decrease":
            # Closed by buying big at ask + selling small at bid
            big_live = snap["big_ask"]
            small_live = snap["small_bid"]
            cover_spread = snap["increase_spread"]
        else:
            big_live = snap["big_bid"]
            small_live = snap["small_ask"]
            cover_spread = snap["decrease_spread"]

    big_g = GRAMS_PER_LOT.get(big_inst, 0) if big_inst else 0
    weight_g = p.big_lots * big_g

    big_action = "SELL" if p.mode == "decrease" else "BUY"
    small_action = "BUY" if p.mode == "decrease" else "SELL"

    return {
        "id": p.id,
        "pair_name": p.pair_name,
        "mode": p.mode,
        "entry_spread": p.entry_spread,
        "cover_spread": cover_spread,
        "entry_time": p.entry_time.isoformat(),
        "is_paper": p.is_paper,
        "live_pnl": live_pnl(p),
        "weight_grams": weight_g,
        # Big leg
        "big_instrument": big_inst,
        "big_action": big_action,
        "big_lots": p.big_lots,
        "big_entry_price": p.big_price,
        "big_live_price": big_live,
        # Small leg
        "small_instrument": small_inst,
        "small_action": small_action,
        "small_lots": p.small_lots,
        "small_entry_price": p.small_price,
        "small_live_price": small_live,
    }


@router.get("")
def list_open(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    rows = db.query(Position).filter(Position.status == "open").order_by(Position.id.desc()).all()
    return [_enrich(p) for p in rows]


@router.post("/{position_id}/close")
def close(position_id: int, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    closed = manual_close(db, position_id)
    if not closed:
        raise HTTPException(400, "Position not found or quote unavailable")
    return {"ok": True, "history_id": closed.id, "pnl": closed.pnl}
