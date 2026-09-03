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


# --------------------------------------------------------------------------- #
# Page-wise permissions (client, 03-Sep-2026).
#
# The admin creates logins and ticks the tabs each may see. Hiding tabs in the
# browser is not a wall, so every API prefix belongs to a page, and a 'user'
# login gets 403 outside the pages it was given - the same discipline as the
# trader wall above, driven by the users table (60 s cache) rather than the
# token, so an edit takes effect within a minute without a new login.
# --------------------------------------------------------------------------- #
PAGES: list[tuple[str, str]] = [
    ("cross", "Cross Pair"), ("calendar", "Calendar Spread"),
    ("metals", "Metal Spread"), ("othercomm", "Other Commodity Spread"),
    ("price", "Metal Price"), ("calculator", "ETF vs MCX"), ("premium", "Premium"),
    ("goldopt", "Commodity Option"), ("nsemcx", "NSE vs MCX"),
    ("mcxnymex", "MCX vs NYMEX"), ("making", "Making Price"),
    ("stock", "Bullion Stock"), ("intl", "COMEX + NYMEX"),
    ("ivcalc", "IV Calculator"), ("options", "Nifty / Sensex"),
    ("signals", "Signals"), ("autotrades", "Auto Trades"),
]
PAGE_KEYS = [k for k, _ in PAGES]
ROLES = ("admin", "user", "trader")

# Which API surface each page needs. The live board socket (/ws/live) and the
# pairs routes serve the spread pages; a page that only reads its own router
# lists just that.
PAGE_PREFIXES: dict[str, tuple[str, ...]] = {
    "cross": ("/api/pairs/", "/api/activity", "/api/positions", "/api/history", "/api/ladders", "/api/config/"),
    "calendar": ("/api/pairs/", "/api/activity", "/api/positions", "/api/history", "/api/ladders", "/api/config/"),
    "signals": ("/api/pairs/", "/api/signals", "/api/activity"),
    "metals": ("/api/metals/",),
    "othercomm": ("/api/othercomm/",),
    "price": ("/api/price/",),
    "making": ("/api/price/",),
    "calculator": ("/api/calculator/",),
    "premium": ("/api/premium-inputs", "/api/calculator/"),
    "goldopt": ("/api/gold-options/",),
    "nsemcx": ("/api/nse-mcx",),
    "mcxnymex": ("/api/crude-iv", "/api/nse-mcx-crude"),
    "stock": ("/api/bullion-stock/",),
    "intl": ("/api/international",),
    "ivcalc": ("/api/iv-calculator", "/api/nse-mcx"),
    "options": ("/api/options/",),
    "autotrades": ("/api/paper/", "/api/v1/webhook/trade", "/api/scrips/"),
}
BOARD_PAGES = ("cross", "calendar", "signals")     # the pages fed by /ws/live
# Every login may reach these: its own session, the health pill, the feed pill.
COMMON_PREFIXES = ("/api/auth/",)
COMMON_EXACT = ("/api/health", "/api/feed/status")

_perm_cache: dict[str, tuple[dict, float]] = {}
_PERM_TTL = 60.0


def _parse_pages(raw) -> list[str]:
    import json
    try:
        vals = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        vals = []
    return [p for p in vals if p in PAGE_KEYS]


def perms_of(username: str) -> dict:
    """{'role', 'pages', 'active'} for a login - admin = every page."""
    from time import time as _now
    hit = _perm_cache.get(username)
    if hit and _now() - hit[1] < _PERM_TTL:
        return hit[0]
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        row = db.query(User.role, User.pages, User.is_active).filter(User.username == username).first()
        if not row:
            perm = {"role": "user", "pages": [], "active": False}
        else:
            role = row[0] or "admin"
            if role == "admin":
                pages = list(PAGE_KEYS)
            elif role == "trader":
                pages = ["autotrades"]
            else:
                pages = _parse_pages(row[1])
            perm = {"role": role, "pages": pages, "active": row[2] is None or bool(row[2])}
    except Exception:  # noqa: BLE001 - DB hiccup: keep what we knew, else deny
        perm = hit[0] if hit else {"role": "user", "pages": [], "active": True}
    finally:
        db.close()
    _perm_cache[username] = (perm, _now())
    _role_cache[username] = (perm["role"], _now())
    return perm


def forget(username: str) -> None:
    """Drop the cached permissions after an edit, so it applies at once."""
    _perm_cache.pop(username, None)
    _role_cache.pop(username, None)


def may(username: str, path: str) -> bool:
    perm = perms_of(username)
    if not perm["active"]:
        return False
    if perm["role"] == "admin":
        return True
    if path in COMMON_EXACT or any(path.startswith(p) for p in COMMON_PREFIXES):
        return True
    for page in perm["pages"]:
        for pre in PAGE_PREFIXES.get(page, ()):
            if path == pre or path.startswith(pre) or path == pre.rstrip("/"):
                return True
    return False


def may_board(username: str) -> bool:
    """The live board socket streams every spread pair - one of the board
    pages must be on the list."""
    perm = perms_of(username)
    return perm["active"] and (perm["role"] == "admin" or any(p in perm["pages"] for p in BOARD_PAGES))


def require_admin(username: str = Depends(get_current_user)) -> str:
    if perms_of(username)["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can manage users.")
    return username


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
