"""UUID-backed sessions and cached, server-enforced page permissions."""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import threading
import time

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordBearer

from app.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


PAGES: list[tuple[str, str]] = [
    ("cross", "Cross Pair"), ("calendar", "Calendar Spread"),
    ("metals", "Metal Spread"), ("othercomm", "Other Commodity Spread"),
    ("price", "Metal Price"), ("calculator", "ETF vs MCX"), ("premium", "Premium"),
    ("goldopt", "Commodity Option"), ("nsemcx", "NSE vs MCX"),
    ("mcxnymex", "MCX vs NYMEX"), ("making", "Making Price"),
    ("stock", "Bullion Stock"), ("intl", "COMEX + NYMEX"),
    ("ivcalc", "IV Calculator"), ("options", "Nifty / Sensex"),
    ("bankoptions", "BANKEX / BANKNIFTY"),
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
    "bankoptions": ("/api/bank-options/",),
    "autotrades": ("/api/paper/", "/api/v1/webhook/trade"),
}
BOARD_PAGES = ("cross", "calendar", "signals")     # the pages fed by /ws/live
# Every login may reach these: its own session, the health pill, the feed pill.
COMMON_PREFIXES = ("/api/auth/",)
COMMON_EXACT = ("/api/health", "/api/feed/status")

# Both REST and sockets share these bounded caches. An edit invalidates them
# immediately in this single-worker app; external DB edits expire within 60 s.
_PERM_TTL = 60.0
_CACHE_LIMIT = 1024
_cache_lock = threading.RLock()
_identity_cache: OrderedDict[str, tuple[dict | None, float]] = OrderedDict()
_name_cache: OrderedDict[str, tuple[str | None, float]] = OrderedDict()


class AuthenticatedUser(str):
    """Existing route contracts keep a username string, plus a permanent owner."""
    def __new__(cls, identity: dict, expires_at: float):
        value = super().__new__(cls, identity["username"])
        value.auth_uid = identity["uid"]
        value.session_version = identity["version"]
        value.expires_at = expires_at
        return value


def _parse_pages(raw) -> list[str]:
    try:
        vals = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        vals = []
    return [p for p in vals if isinstance(p, str) and p in PAGE_KEYS] if isinstance(vals, list) else []


def _put(cache, key, value, now):
    cache[key] = (value, now)
    cache.move_to_end(key)
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)


def _identity(*, uid: str | None = None, username: str | None = None) -> dict | None:
    from app.database import SessionLocal
    from app.models import User
    now = time.monotonic()
    # Serialize cache misses too: 20 sockets for one login must not run 20 DB
    # reads together at the expiry boundary. Ordinary ticks only read memory.
    with _cache_lock:
        if uid is None:
            hit = _name_cache.get(username)
            if hit and now - hit[1] < _PERM_TTL:
                uid = hit[0]
                if uid is None:
                    return None
        hit = _identity_cache.get(uid) if uid else None
        if hit and now - hit[1] < _PERM_TTL:
            return hit[0]
        try:
            with SessionLocal() as db:
                query = db.query(User)
                row = query.filter(User.auth_uid == uid).first() if uid else query.filter(User.username == username).first()
                if row is None:
                    result = None
                else:
                    role = row.role or "admin"
                    pages = list(PAGE_KEYS) if role == "admin" else ["autotrades"] if role == "trader" else _parse_pages(row.pages)
                    result = {"uid": row.auth_uid, "username": row.username,
                              "version": row.session_version, "role": role, "pages": pages,
                              "active": row.is_active is None or bool(row.is_active)}
        except Exception:
            # Expired cached access must not be extended indefinitely on DB errors.
            raise HTTPException(503, "Account verification is temporarily unavailable.") from None
        if result:
            _put(_identity_cache, result["uid"], result, now)
            _put(_name_cache, result["username"], result["uid"], now)
        else:
            if uid:
                _put(_identity_cache, uid, None, now)
            if username:
                _put(_name_cache, username, None, now)
        return result


def forget(username: str | None = None, uid: str | None = None) -> None:
    """Invalidate renamed, reset, disabled and deleted identities after commit."""
    with _cache_lock:
        if username:
            hit = _name_cache.pop(str(username), None)
            uid = uid or (hit[0] if hit else None) or getattr(username, "auth_uid", None)
        if uid:
            _identity_cache.pop(uid, None)
            for name, hit in list(_name_cache.items()):
                if hit[0] == uid:
                    _name_cache.pop(name, None)


def clear_auth_cache() -> None:
    with _cache_lock:
        _identity_cache.clear()
        _name_cache.clear()


def perms_of(username: str) -> dict:
    identity = _identity(uid=getattr(username, "auth_uid", None), username=str(username))
    return identity or {"role": "user", "pages": [], "active": False}


def _path_matches(path: str, prefix: str) -> bool:
    base = prefix.rstrip("/")
    return path == base or path.startswith(base + "/")


def may(username: str, path: str) -> bool:
    perm = perms_of(username)
    if not perm["active"]:
        return False
    if perm["role"] == "admin":
        return True
    if path in COMMON_EXACT or any(_path_matches(path, p) for p in COMMON_PREFIXES):
        return True
    return any(_path_matches(path, prefix) for page in perm["pages"] for prefix in PAGE_PREFIXES.get(page, ()))


def may_board(username: str) -> bool:
    perm = perms_of(username)
    return perm["active"] and (perm["role"] == "admin" or any(p in perm["pages"] for p in BOARD_PAGES))


def create_access_token(username: str) -> str:
    settings.validate_signing_key()
    identity = _identity(username=str(username))
    if not identity or not identity["active"] or not identity["uid"]:
        raise HTTPException(401, "This login is unavailable.")
    now = datetime.now(timezone.utc)
    payload = {"sub": identity["uid"], "ver": identity["version"], "auth_v": 2,
               "iat": now, "exp": now + timedelta(hours=TOKEN_EXPIRE_HOURS)}
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm=ALGORITHM)


def _credentials_error():
    return HTTPException(401, "Invalid or expired session. Please sign in again.",
                         headers={"WWW-Authenticate": "Bearer"})


def authenticate(token: str) -> AuthenticatedUser:
    settings.validate_signing_key()
    try:
        payload = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=[ALGORITHM],
                             options={"require": ["sub", "exp", "iat", "ver", "auth_v"]})
        if (payload["auth_v"] != 2 or not isinstance(payload["sub"], str)
                or type(payload["ver"]) is not int or type(payload["exp"]) not in (int, float)):
            raise _credentials_error()
    except jwt.PyJWTError:
        raise _credentials_error() from None
    identity = _identity(uid=payload["sub"])
    if not identity or not identity["active"] or identity["version"] != payload["ver"]:
        raise _credentials_error()
    return AuthenticatedUser(identity, payload["exp"])


def session_valid(user: AuthenticatedUser, *, board: bool = False) -> bool:
    """Cheap per-broadcast expiry/cache check, shared across this user's sockets."""
    if time.time() >= user.expires_at:
        return False
    try:
        identity = _identity(uid=user.auth_uid)
    except HTTPException:
        return False
    if not identity or not identity["active"] or identity["version"] != user.session_version:
        return False
    return not board or identity["role"] == "admin" or any(p in identity["pages"] for p in BOARD_PAGES)


def get_current_user(token: str = Depends(oauth2_scheme), request: Request = None) -> str:
    if request is not None and getattr(request.state, "auth_token", None) == token:
        return request.state.auth_user
    return authenticate(token)


def get_current_user_flex(
    header_token: str | None = Depends(oauth2_scheme_optional),
    token: str | None = Query(None, description="login token, for plain-URL access"),
    request: Request = None,
) -> str:
    tok = header_token or token
    if not tok:
        raise _credentials_error()
    return get_current_user(tok, request)


def require_admin(username: str = Depends(get_current_user)) -> str:
    perm = perms_of(username)
    if not perm["active"] or perm["role"] != "admin":
        raise HTTPException(403, "Only an admin can manage users.")
    return username


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
