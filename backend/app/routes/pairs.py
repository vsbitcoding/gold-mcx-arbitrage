from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import PAIRS
from app.database import get_db
from app.models import PairRule, Position
from app.security import get_current_user
from app.services.spread_engine import compute_all

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
    rules = {r.pair_name: r for r in db.query(PairRule).all()}
    open_positions = {p.pair_name for p in db.query(Position).filter(Position.status == "open").all()}
    snaps = compute_all()
    out = []
    for s in snaps:
        rule = rules.get(s["name"])
        in_position = s["name"] in open_positions
        decrease_armed = rule and rule.decrease_entry is not None
        increase_armed = rule and rule.increase_entry is not None
        if in_position:
            status = "in_position"
        elif decrease_armed or increase_armed:
            status = "armed"
        else:
            status = "idle"
        out.append({
            **s,
            "decrease_entry": rule.decrease_entry if rule else None,
            "decrease_exit": rule.decrease_exit if rule else None,
            "increase_entry": rule.increase_entry if rule else None,
            "increase_exit": rule.increase_exit if rule else None,
            "status": status,
        })
    return out


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

    open_pos = db.query(Position).filter(Position.pair_name == pair_name, Position.status == "open").first()
    if open_pos:
        raise HTTPException(400, "Cannot edit rule while a trade is open. Square off first.")

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
