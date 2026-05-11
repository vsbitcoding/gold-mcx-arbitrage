"""Account-wide configuration: balance, max-usage %, margin per fire.

Singleton row in `account_config`. Auto-created on first GET.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccountConfig, Position
from app.security import get_current_user
from app.services import activity

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
    open_count = db.query(Position).filter(Position.status == "open").count()
    used = open_count * (c.margin_per_fire or 0)
    cap = (c.balance or 0) * (c.max_usage_percent or 0) / 100.0
    return {
        "balance": c.balance,
        "max_usage_percent": c.max_usage_percent,
        "margin_per_fire": c.margin_per_fire,
        "cap": round(cap, 2),
        "used": round(used, 2),
        "available": round(cap - used, 2),
        "usage_percent": round((used / cap * 100), 2) if cap > 0 else None,
        "open_positions": open_count,
    }


class AccountUpdate(BaseModel):
    balance: float | None = Field(None, ge=0)
    max_usage_percent: float | None = Field(None, ge=0, le=100)
    margin_per_fire: float | None = Field(None, ge=0)


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
    if body.margin_per_fire is not None and body.margin_per_fire != row.margin_per_fire:
        changes.append(f"margin/fire ₹{row.margin_per_fire:.0f} → ₹{body.margin_per_fire:.0f}")
        row.margin_per_fire = body.margin_per_fire
    db.commit()
    if changes:
        activity.log(
            db, "account_config_updated",
            actor="user",
            summary="Account config: " + ", ".join(changes),
            details={"balance": row.balance, "max_usage_percent": row.max_usage_percent, "margin_per_fire": row.margin_per_fire},
            commit=True,
        )
    return _to_dict(row, db)
