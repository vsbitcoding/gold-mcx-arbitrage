from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PairRule
from app.security import get_current_user

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/pause-all")
def pause_all(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Clear all entry/exit values across pairs to disarm all rules."""
    rules = db.query(PairRule).all()
    for r in rules:
        r.decrease_entry = None
        r.decrease_exit = None
        r.increase_entry = None
        r.increase_exit = None
    db.commit()
    return {"ok": True, "paused": len(rules)}
