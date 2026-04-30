"""Dhan auto-login: TOTP + MPIN -> access token via Dhan auth endpoint.

Uses the official endpoint:
    POST https://auth.dhan.co/app/generateAccessToken
        ?dhanClientId=<id>&pin=<mpin>&totp=<6-digit code from TOTP secret>

Token is cached in memory and refreshed when within 30 minutes of expiry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import struct
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("dhan_auth")

DHAN_AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
REFRESH_BEFORE_EXPIRY_SECONDS = 30 * 60  # refresh if token expires within 30 min


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
    """Cached, auto-refreshing token getter."""
    global _cached
    if _cached and not _cached.needs_refresh():
        return _cached
    _cached = fetch_token(client_id, pin, totp_secret)
    return _cached


def invalidate() -> None:
    global _cached
    _cached = None
