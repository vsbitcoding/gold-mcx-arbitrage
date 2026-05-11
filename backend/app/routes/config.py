"""Account-wide configuration: balance and max-usage %.

Margin per pair is auto-calculated by margin_service (live LTP × instrument %).
Settings is a singleton row in `account_config`; auto-created on first GET.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccountConfig, Position
from app.security import get_current_user
from app.services import activity, margin_service, span_service

router = APIRouter(prefix="/api/config", tags=["config"])


def _get_or_create(db: Session) -> AccountConfig:
    row = db.query(AccountConfig).first()
    if not row:
        row = AccountConfig(balance=0.0, max_usage_percent=80.0, margin_per_fire=0.0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _to_dict(c: AccountConfig, db: Session) -> dict:
    open_positions = db.query(Position).filter(Position.status == "open").all()
    used = sum(margin_service.margin_for_position(p) for p in open_positions)
    cap = (c.balance or 0) * (c.max_usage_percent or 0) / 100.0
    return {
        "balance": c.balance,
        "max_usage_percent": c.max_usage_percent,
        "cap": round(cap, 2),
        "used": round(used, 2),
        "available": round(cap - used, 2),
        "usage_percent": round((used / cap * 100), 2) if cap > 0 else None,
        "open_positions": len(open_positions),
        "margin_reference": margin_service.reference_table(),
        "span_status": span_service.status(),
    }


class AccountUpdate(BaseModel):
    balance: float | None = Field(None, ge=0)
    max_usage_percent: float | None = Field(None, ge=0, le=100)


@router.get("/account")
def get_account(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    return _to_dict(_get_or_create(db), db)


@router.put("/account")
def update_account(
    body: AccountUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    row = _get_or_create(db)
    changes: list[str] = []
    if body.balance is not None and body.balance != row.balance:
        changes.append(f"balance ₹{row.balance:.0f} → ₹{body.balance:.0f}")
        row.balance = body.balance
    if body.max_usage_percent is not None and body.max_usage_percent != row.max_usage_percent:
        changes.append(f"max-usage {row.max_usage_percent:.0f}% → {body.max_usage_percent:.0f}%")
        row.max_usage_percent = body.max_usage_percent
    db.commit()
    if changes:
        activity.log(
            db, "account_config_updated",
            actor="user",
            summary="Account config: " + ", ".join(changes),
            details={"balance": row.balance, "max_usage_percent": row.max_usage_percent},
            commit=True,
        )
    return _to_dict(row, db)
