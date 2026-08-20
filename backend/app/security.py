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
