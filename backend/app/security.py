from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer

from app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise creds_error
        return username
    except jwt.PyJWTError:
        raise creds_error


# --------------------------------------------------------------------------- #
# Trader confinement.
#
# The UI hides every other page from a 'trader' login, but hiding is not a
# wall: bhavesh's token opened /api/pairs/live perfectly well when checked
# (20-Aug). The wall is here - the role comes from the DATABASE per request
# (60 s cache), not from a claim inside the token, so it holds for tokens
# minted before roles existed and takes effect the moment a row changes.
# --------------------------------------------------------------------------- #
_role_cache: dict[str, tuple[str, float]] = {}
_ROLE_TTL = 60.0

# What a trader login may touch. Everything else under /api answers 403.
TRADER_PREFIXES = ("/api/auth/", "/api/paper/", "/api/v1/webhook/trade")
TRADER_EXACT = ("/api/health", "/api/feed/status")


def role_of(username: str) -> str:
    from time import time as _now
    hit = _role_cache.get(username)
    if hit and _now() - hit[1] < _ROLE_TTL:
        return hit[0]
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        row = db.query(User.role).filter(User.username == username).first()
        role = (row[0] if row and row[0] else "admin")
    except Exception:  # noqa: BLE001 - fail CLOSED for traders, open for admin? No:
        # a DB hiccup must not lock the admin out of his own dashboard, and the
        # cache means this path is rare. Unknown -> treat as admin ONLY if the
        # user was already cached as admin; otherwise trader-safe default.
        role = hit[0] if hit else "trader"
    finally:
        db.close()
    _role_cache[username] = (role, _now())
    return role


def trader_may(path: str) -> bool:
    return path in TRADER_EXACT or any(path.startswith(p) for p in TRADER_PREFIXES)


# Header-optional variant of the scheme above, for endpoints that also accept
# the token as a query parameter. auto_error=False means "no header" arrives
# here as None instead of an instant 401, so the query fallback gets its turn.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user_flex(
    header_token: str | None = Depends(oauth2_scheme_optional),
    token: str | None = Query(None, description="login token, for plain-URL access"),
) -> str:
    """The same login token, from the Authorization header OR ?token=.

    The dashboard sends the header; a bare link pasted into a browser cannot,
    so the query form exists for that (client, 20-Aug). Same JWT, same expiry,
    same secret - only the envelope differs. Used by the Auto Trades reads
    only; every other page keeps the header-only rule it always had.
    """
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    tok = header_token or token
    if not tok:
        raise creds_error
    try:
        payload = jwt.decode(tok, settings.APP_SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise creds_error
        return username
    except jwt.PyJWTError:
        raise creds_error


def verify_api_key_value(key: str | None) -> bool:
    if not key:
        return False
    return key in settings.public_api_keys


def require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    api_key: str | None = Query(None),
) -> str:
    """FastAPI dependency: accept `X-API-Key` header or `api_key` query param."""
    key = x_api_key or api_key
    if not verify_api_key_value(key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return key
