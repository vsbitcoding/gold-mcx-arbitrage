from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LadderRule
from app.security import get_current_user

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/pause-all")
def pause_all(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Disable all ladder rules so the bot stops firing new trades.
    Open positions are NOT affected — they continue to watch their exit."""
    rules = db.query(LadderRule).all()
    for r in rules:
        r.enabled = False
    db.commit()
    return {"ok": True, "paused": len(rules)}
