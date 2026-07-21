"""Dhan auto-login: TOTP + MPIN -> access token via Dhan auth endpoint.

Uses the official endpoint:
    POST https://auth.dhan.co/app/generateAccessToken
        ?dhanClientId=<id>&pin=<mpin>&totp=<6-digit code from TOTP secret>

Token is cached in memory AND on disk (owner-only file, ~24h validity), so a
backend deploy/restart REUSES the existing token instead of minting a new one:
no TOTP wait, no "once every 2 minutes" limit, no 15-min cooldown risk — the
feed is back in seconds. Minting happens only when no valid token exists or an
auth-invalid error forces a fresh one (invalidate(disk=True)).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("dhan_auth")

DHAN_AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
REFRESH_BEFORE_EXPIRY_SECONDS = 30 * 60  # refresh if token expires within 30 min
# backend/.dhan_token_cache.json — untracked (gitignored) so `git reset --hard`
# deploys never touch it; chmod 600 (holds a live trading token).
_CACHE_FILE = Path(__file__).resolve().parents[2] / ".dhan_token_cache.json"


def generate_totp(secret: str, period: int = 30, digits: int = 6) -> str:
    """RFC 6238 TOTP. Compatible with Google Authenticator / Authy."""
    secret_clean = secret.replace(" ", "").upper()
    pad = "=" * ((8 - len(secret_clean) % 8) % 8)
    key = base64.b32decode(secret_clean + pad)
    counter = int(time.time() // period)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0xF
    code = (struct.unpack(">I", h[o : o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


@dataclass
class DhanToken:
    access_token: str
    expiry_epoch: float
    client_id: str
    client_name: str

    def expires_in(self) -> float:
        return self.expiry_epoch - time.time()

    def needs_refresh(self) -> bool:
        return self.expires_in() < REFRESH_BEFORE_EXPIRY_SECONDS


_cached: Optional[DhanToken] = None


def _load_disk() -> Optional[DhanToken]:
    """Valid token from the disk cache, or None."""
    try:
        d = json.loads(_CACHE_FILE.read_text())
        tok = DhanToken(access_token=d["access_token"], expiry_epoch=float(d["expiry_epoch"]),
                        client_id=d.get("client_id", ""), client_name=d.get("client_name", ""))
        if tok.access_token and not tok.needs_refresh():
            return tok
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — corrupt cache → just re-mint
        log.warning("token cache unreadable (%s) — will mint fresh", e)
    return None


def _save_disk(tok: DhanToken) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps({
            "access_token": tok.access_token, "expiry_epoch": tok.expiry_epoch,
            "client_id": tok.client_id, "client_name": tok.client_name,
        }))
        os.chmod(_CACHE_FILE, 0o600)
    except Exception as e:  # noqa: BLE001 — cache is an optimisation, never fatal
        log.warning("token cache write failed: %s", e)


def _parse_expiry(expiry_str: str) -> float:
    """'2026-05-01T12:02:48.562' (IST naive) -> epoch seconds (UTC)."""
    try:
        dt = datetime.fromisoformat(expiry_str.replace("Z", ""))
    except Exception:
        return time.time() + 12 * 3600
    if dt.tzinfo is None:
        # Dhan returns IST-naive; treat as UTC+5:30
        from datetime import timedelta
        dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return dt.timestamp()


_last_auth_attempt: float = 0.0
_last_totp_used: str = ""


def fetch_token(client_id: str, pin: str, totp_secret: str) -> DhanToken:
    """Generate fresh access token. Raises on failure.

    Dhan rejects reuse of the same TOTP code within its 30s window. If we just
    used a code, wait until the next window before retrying.
    """
    global _last_auth_attempt, _last_totp_used
    code = generate_totp(totp_secret)
    if code == _last_totp_used:
        # Wait until next 30s window starts (max 31s)
        seconds_into_window = int(time.time()) % 30
        wait_s = (30 - seconds_into_window) + 1
        log.info("TOTP %s already used in this window — waiting %ds for fresh code.", code, wait_s)
        time.sleep(wait_s)
        code = generate_totp(totp_secret)
    _last_totp_used = code
    _last_auth_attempt = time.time()

    qs = urllib.parse.urlencode({"dhanClientId": client_id, "pin": pin, "totp": code})
    url = f"{DHAN_AUTH_URL}?{qs}"
    req = urllib.request.Request(url, method="POST", headers={"Accept": "application/json"})
    log.info("Dhan auth: generating access token (TOTP=%s)", code)
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    token = data.get("accessToken")
    if not token:
        raise RuntimeError(f"Dhan auth failed: {body[:300]}")
    tok = DhanToken(
        access_token=token,
        expiry_epoch=_parse_expiry(data.get("expiryTime", "")),
        client_id=data.get("dhanClientId", client_id),
        client_name=data.get("dhanClientName", ""),
    )
    log.info(
        "Dhan auth OK: client=%s name=%s expires_in=%.0f min",
        tok.client_id, tok.client_name, tok.expires_in() / 60,
    )
    return tok


def get_token(client_id: str, pin: str, totp_secret: str) -> DhanToken:
    """Cached, auto-refreshing token getter: memory → disk → mint.

    The disk hop is what makes deploys safe: after a restart (or a benign
    in-memory invalidate) the still-valid token is reused — no new login."""
    global _cached
    if _cached and not _cached.needs_refresh():
        return _cached
    disk = _load_disk()
    if disk:
        log.info("Reusing cached Dhan token (expires in %.1f h) — no fresh login needed.",
                 disk.expires_in() / 3600)
        _cached = disk
        return _cached
    _cached = fetch_token(client_id, pin, totp_secret)
    _save_disk(_cached)
    return _cached


def invalidate(disk: bool = False) -> None:
    """Drop the in-memory token. disk=True also deletes the on-disk cache —
    use ONLY for auth-invalid errors (revoked/expired token), otherwise the
    next get_token() harmlessly reloads the same valid token from disk."""
    global _cached
    _cached = None
    if disk:
        try:
            _CACHE_FILE.unlink(missing_ok=True)
            log.info("Disk token cache invalidated — next get_token() mints fresh.")
        except Exception as e:  # noqa: BLE001
            log.warning("token cache delete failed: %s", e)


def current_expires_in() -> Optional[float]:
    """Seconds left on whichever token would be used next (memory, else the
    raw disk file — no refresh-margin filter, may be negative). None = no
    token cached anywhere. Lets the feed distinguish an expired-token error
    flood from a genuine Dhan rate-limit."""
    if _cached:
        return _cached.expires_in()
    try:
        d = json.loads(_CACHE_FILE.read_text())
        return float(d["expiry_epoch"]) - time.time()
    except Exception:  # noqa: BLE001
        return None
