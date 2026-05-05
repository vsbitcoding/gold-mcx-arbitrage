from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import MAX_ALLOWED_WEIGHT_GRAMS
from app.database import get_db
from app.models import LadderRule, Position
from app.security import get_current_user
from app.services import pair_registry
from app.services.trade_engine import prime_armed_state

router = APIRouter(prefix="/api/ladders", tags=["ladders"])


class LadderCreate(BaseModel):
    pair_name: str
    side: str = Field(..., pattern="^(decrease|increase)$")
    entry: float | None = None
    exit: float | None = None
    max_weight_grams: int | None = None


class LadderUpdate(BaseModel):
    entry: float | None = None
    exit: float | None = None
    max_weight_grams: int | None = None
    enabled: bool | None = None


def _validate_weight(w: int | None) -> None:
    if w is None:
        return
    if w < 0:
        raise HTTPException(400, "Max weight must be 0 or higher")
    if w > MAX_ALLOWED_WEIGHT_GRAMS:
        raise HTTPException(400, f"Max weight cannot exceed {MAX_ALLOWED_WEIGHT_GRAMS}g")


def _to_dict(rule: LadderRule) -> dict:
    return {
        "id": rule.id,
        "pair_name": rule.pair_name,
        "side": rule.side,
        "entry": rule.entry,
        "exit": rule.exit,
        "max_weight_grams": rule.max_weight_grams,
        "pending_max_weight_grams": rule.pending_max_weight_grams,
        "has_pending_cap": bool(rule.has_pending_cap),
        "sort_order": rule.sort_order or 0,
        "enabled": bool(rule.enabled),
    }


@router.get("")
def list_ladders(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    rows = db.query(LadderRule).order_by(LadderRule.pair_name, LadderRule.side, LadderRule.sort_order, LadderRule.id).all()
    return [_to_dict(r) for r in rows]


@router.post("")
def create_ladder(
    body: LadderCreate,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    if not pair_registry.get_pair(body.pair_name):
        raise HTTPException(404, "Unknown pair")
    _validate_weight(body.max_weight_grams)

    # sort_order = max + 1 for this pair-side
    last = (
        db.query(LadderRule)
        .filter(LadderRule.pair_name == body.pair_name, LadderRule.side == body.side)
        .order_by(LadderRule.sort_order.desc())
        .first()
    )
    next_order = (last.sort_order + 1) if last else 0

    rule = LadderRule(
        pair_name=body.pair_name,
        side=body.side,
        entry=body.entry,
        exit=body.exit,
        max_weight_grams=body.max_weight_grams,
        sort_order=next_order,
        enabled=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    prime_armed_state(rule.id)
    return _to_dict(rule)


@router.put("/{rule_id}")
def update_ladder(
    rule_id: int,
    body: LadderUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    rule = db.query(LadderRule).filter(LadderRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Ladder not found")
    _validate_weight(body.max_weight_grams)

    rule.entry = body.entry
    rule.exit = body.exit
    if body.enabled is not None:
        rule.enabled = body.enabled

    # Cap update — if open positions for this ladder, store as pending
    has_open = (
        db.query(Position)
        .filter(Position.ladder_rule_id == rule_id, Position.status == "open")
        .first()
        is not None
    )
    if has_open and body.max_weight_grams != rule.max_weight_grams:
        rule.pending_max_weight_grams = body.max_weight_grams
        rule.has_pending_cap = 1
    else:
        rule.max_weight_grams = body.max_weight_grams
        rule.pending_max_weight_grams = None
        rule.has_pending_cap = 0

    db.commit()
    prime_armed_state(rule.id)
    return _to_dict(rule)


@router.delete("/{rule_id}")
def delete_ladder(
    rule_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    rule = db.query(LadderRule).filter(LadderRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Ladder not found")
    has_open = (
        db.query(Position)
        .filter(Position.ladder_rule_id == rule_id, Position.status == "open")
        .first()
        is not None
    )
    if has_open:
        raise HTTPException(400, "Cannot delete — open trades exist for this ladder. Square off first.")
    db.delete(rule)
    db.commit()
    return {"ok": True}
