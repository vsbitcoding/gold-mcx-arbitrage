from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import PAIRS
from app.database import get_db
from app.models import PairRule
from app.security import get_current_user
from app.services.snapshot import build_live_payload

router = APIRouter(prefix="/api/pairs", tags=["pairs"])


class RuleUpdate(BaseModel):
    decrease_entry: float | None = None
    decrease_exit: float | None = None
    increase_entry: float | None = None
    increase_exit: float | None = None


def _ensure_rules(db: Session) -> None:
    existing = {r.pair_name for r in db.query(PairRule).all()}
    for p in PAIRS:
        if p["name"] not in existing:
            db.add(PairRule(pair_name=p["name"]))
    db.commit()


@router.get("/live")
def live(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    _ensure_rules(db)
    return build_live_payload(db)


@router.put("/{pair_name}/rule")
def update_rule(
    pair_name: str,
    body: RuleUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    valid = {p["name"] for p in PAIRS}
    if pair_name not in valid:
        raise HTTPException(404, "Unknown pair")

    rule = db.query(PairRule).filter(PairRule.pair_name == pair_name).first()
    if not rule:
        rule = PairRule(pair_name=pair_name)
        db.add(rule)

    rule.decrease_entry = body.decrease_entry
    rule.decrease_exit = body.decrease_exit
    rule.increase_entry = body.increase_entry
    rule.increase_exit = body.increase_exit
    db.commit()
    return {"ok": True}
