from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import create_access_token, forget, get_current_user, perms_of, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.is_active is not None and not user.is_active:
        raise HTTPException(status_code=401, detail="This login has been disabled.")
    user.last_login = datetime.utcnow()
    db.commit()
    forget(user.username)
    perm = perms_of(user.username)
    return {"access_token": create_access_token(user.username), "token_type": "bearer",
            # The frontend shows only the pages listed here; the server wall
            # (main._confine) enforces the same list on every API call.
            "role": perm["role"], "pages": perm["pages"], "username": user.username}


@router.get("/me")
def me(username: str = Depends(get_current_user)):
    """The current login's pages - re-read on every dashboard load, so an
    edit by the admin shows on the next refresh without a new login."""
    perm = perms_of(username)
    return {"username": username, "role": perm["role"], "pages": perm["pages"]}
