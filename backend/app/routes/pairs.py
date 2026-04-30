from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import PAIRS
from app.database import get_db
from app.models import PairRule, Position
from app.security import get_current_user
from app.services.spread_engine import compute_all
from app.services.trade_engine import open_position_for_side

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


def _row_status(rule: PairRule | None, dec_open: bool, inc_open: bool) -> str:
    """Aggregate row status: in_position if any side open, armed if any rule set, else idle."""
    if dec_open or inc_open:
        return "in_position"
    if rule and (rule.decrease_entry is not None or rule.increase_entry is not None):
        return "armed"
    return "idle"


@router.get("/live")
def live(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    _ensure_rules(db)
    rules = {r.pair_name: r for r in db.query(PairRule).all()}
    open_dec = {
        p.pair_name
        for p in db.query(Position)
        .filter(Position.status == "open", Position.mode == "decrease")
        .all()
    }
    open_inc = {
        p.pair_name
        for p in db.query(Position)
        .filter(Position.status == "open", Position.mode == "increase")
        .all()
    }
    snaps = compute_all()
    out = []
    for s in snaps:
        rule = rules.get(s["name"])
        dec_open = s["name"] in open_dec
        inc_open = s["name"] in open_inc
        out.append({
            **s,
            "decrease_entry": rule.decrease_entry if rule else None,
            "decrease_exit": rule.decrease_exit if rule else None,
            "increase_entry": rule.increase_entry if rule else None,
            "increase_exit": rule.increase_exit if rule else None,
            "decrease_open": dec_open,
            "increase_open": inc_open,
            "status": _row_status(rule, dec_open, inc_open),
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

    rule = db.query(PairRule).filter(PairRule.pair_name == pair_name).first()
    if not rule:
        rule = PairRule(pair_name=pair_name)
        db.add(rule)

    # Block edits ONLY for the side that has an open position.
    dec_open = open_position_for_side(db, pair_name, "decrease") is not None
    inc_open = open_position_for_side(db, pair_name, "increase") is not None

    if dec_open and (body.decrease_entry != rule.decrease_entry or body.decrease_exit != rule.decrease_exit):
        raise HTTPException(400, "Decrease trade is open. Square off before changing Decrease entry/exit.")
    if inc_open and (body.increase_entry != rule.increase_entry or body.increase_exit != rule.increase_exit):
        raise HTTPException(400, "Increase trade is open. Square off before changing Increase entry/exit.")

    rule.decrease_entry = body.decrease_entry
    rule.decrease_exit = body.decrease_exit
    rule.increase_entry = body.increase_entry
    rule.increase_exit = body.increase_exit
    db.commit()
    return {"ok": True}
