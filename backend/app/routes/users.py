"""User management for the admin (client's ask, 03-Sep-2026).

The admin creates logins, ticks which pages each may see, edits them later,
switches them off, or deletes them. Every change drops the permission cache,
so the wall in main._confine_traders applies it at once.

Guard rails: an admin cannot delete, downgrade or disable their own login,
and the last active admin can never be removed - the dashboard must always
have someone who can manage it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import PAGE_KEYS, PAGES, ROLES, forget, hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])

_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")


class UserIn(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str = "user"
    pages: list[str] = []
    active: bool = True


def _pages_of(u: User) -> list[str]:
    if u.role == "admin":
        return list(PAGE_KEYS)
    if u.role == "trader":
        return ["autotrades"]
    try:
        return [p for p in (json.loads(u.pages) if u.pages else []) if p in PAGE_KEYS]
    except (TypeError, ValueError):
        return []


def _out(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "role": u.role or "admin",
        "pages": _pages_of(u), "active": u.is_active is None or bool(u.is_active),
        "created_by": u.created_by, "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }


def _clean(body: UserIn, *, creating: bool) -> tuple[str | None, str | None, str, list[str]]:
    name = (body.username or "").strip().lower() or None
    if creating or name is not None:
        if not name or not _NAME.match(name):
            raise HTTPException(400, "Username: 3 to 32 characters, letters, digits, . _ - only.")
    pw = body.password or None
    if creating and not pw:
        raise HTTPException(400, "Password is required.")
    if pw is not None and len(pw) < 6:
        raise HTTPException(400, "Password: at least 6 characters.")
    role = (body.role or "user").strip().lower()
    if role not in ROLES:
        raise HTTPException(400, f"Role must be one of {', '.join(ROLES)}.")
    pages = [p for p in dict.fromkeys(body.pages or []) if p in PAGE_KEYS]
    if role == "user" and not pages:
        raise HTTPException(400, "Tick at least one page for this user.")
    return name, pw, role, pages


def _active_admins(db: Session, except_id: int | None = None) -> int:
    q = db.query(User).filter(User.role == "admin")
    n = 0
    for u in q.all():
        if u.id == except_id:
            continue
        if u.is_active is None or u.is_active:
            n += 1
    return n


@router.get("/pages")
def list_pages(_: str = Depends(require_admin)):
    return {"pages": [{"key": k, "label": lbl} for k, lbl in PAGES]}


@router.get("")
def list_users(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
    return {"users": [_out(u) for u in rows], "count": len(rows)}


@router.post("")
def create_user(body: UserIn, admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    name, pw, role, pages = _clean(body, creating=True)
    if db.query(User.id).filter(User.username == name).first():
        raise HTTPException(409, f"'{name}' already exists.")
    u = User(username=name, password_hash=hash_password(pw), role=role,
             pages=json.dumps(pages) if role == "user" else None,
             is_active=1 if body.active else 0, created_by=admin,
             created_at=datetime.utcnow())
    db.add(u)
    db.commit()
    db.refresh(u)
    return _out(u)


@router.put("/{user_id}")
def update_user(user_id: int, body: UserIn, admin: str = Depends(require_admin),
                db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "No such user.")
    name, pw, role, pages = _clean(body, creating=False)
    if u.username == admin and (role != "admin" or not body.active):
        raise HTTPException(400, "You cannot downgrade or disable your own login.")
    if u.role == "admin" and (role != "admin" or not body.active) and _active_admins(db, u.id) == 0:
        raise HTTPException(400, "This is the last active admin; make another admin first.")
    # Existing logins keep their capitals ("Dharmesh"): a name that only differs
    # in case is the same name, not a rename.
    if name and name != u.username and name.lower() != u.username.lower():
        if db.query(User.id).filter(User.username == name).first():
            raise HTTPException(409, f"'{name}' already exists.")
        forget(u.username)
        u.username = name
    if pw:
        u.password_hash = hash_password(pw)
    u.role = role
    u.pages = json.dumps(pages) if role == "user" else None
    u.is_active = 1 if body.active else 0
    db.commit()
    forget(u.username)
    db.refresh(u)
    return _out(u)


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "No such user.")
    if u.username == admin:
        raise HTTPException(400, "You cannot delete your own login.")
    if u.role == "admin" and _active_admins(db, u.id) == 0:
        raise HTTPException(400, "This is the last active admin; make another admin first.")
    name = u.username
    db.delete(u)
    db.commit()
    forget(name)
    return {"ok": True, "deleted": name}
