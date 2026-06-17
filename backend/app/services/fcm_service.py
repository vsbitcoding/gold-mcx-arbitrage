"""Firebase Cloud Messaging (FCM HTTP v1) push service — watch-only signal alerts.

Self-contained: mints an OAuth access token from the service-account key
(PyJWT RS256 → oauth2 token exchange) and POSTs to the FCM v1 send endpoint.
No firebase-admin / grpc dependency.

Device tokens are registered by the mobile app via POST /api/v1/devices/register
and stored in the `device_tokens` table. On a new signal, every active device
gets one push. Dead tokens (UNREGISTERED) are auto-deactivated.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

import httpx
import jwt

from app.config import settings
from app.database import SessionLocal
from app.models import DeviceToken

log = logging.getLogger("fcm_service")

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

_sa: dict | None = None           # parsed service-account JSON
_sa_loaded = False
_access = {"value": None, "exp": 0.0}
_lock = threading.Lock()
_warned_disabled = False


def _load_sa() -> dict | None:
    """Load + cache the service-account key. Returns None if not configured."""
    global _sa, _sa_loaded, _warned_disabled
    if _sa_loaded:
        return _sa
    _sa_loaded = True
    path = (settings.FCM_KEY_PATH or "").strip()
    if not path:
        return None
    try:
        with open(path) as f:
            _sa = json.load(f)
        log.info("FCM enabled — project %s", _sa.get("project_id"))
    except Exception as e:
        _sa = None
        if not _warned_disabled:
            log.warning("FCM disabled — cannot read key at %s: %s", path, e)
            _warned_disabled = True
    return _sa


def enabled() -> bool:
    return _load_sa() is not None


def _access_token() -> str | None:
    """Mint (and cache ~1h) an OAuth2 access token for FCM v1."""
    sa = _load_sa()
    if not sa:
        return None
    with _lock:
        now = time.time()
        if _access["value"] and _access["exp"] - now > 120:
            return _access["value"]
        iat = int(now)
        assertion = jwt.encode(
            {"iss": sa["client_email"], "scope": _SCOPE, "aud": _TOKEN_URL,
             "iat": iat, "exp": iat + 3600},
            sa["private_key"], algorithm="RS256",
        )
        try:
            r = httpx.post(_TOKEN_URL, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion}, timeout=15)
            r.raise_for_status()
            body = r.json()
        except Exception as e:
            log.warning("FCM token mint failed: %s", e)
            return None
        _access["value"] = body["access_token"]
        _access["exp"] = now + float(body.get("expires_in", 3600))
        return _access["value"]


def _send_one(client: httpx.Client, url: str, headers: dict, token: str,
              title: str, body: str, data: dict | None) -> int:
    """Send to one token. Returns HTTP status (or 0 on exception)."""
    msg = {"message": {
        "token": token,
        "notification": {"title": title, "body": body},
        "android": {"priority": "high", "notification": {"sound": "default"}},
        "apns": {"headers": {"apns-priority": "10"},
                 "payload": {"aps": {"sound": "default"}}},
    }}
    if data:
        msg["message"]["data"] = {k: str(v) for k, v in data.items()}
    try:
        resp = client.post(url, headers=headers, json=msg)
        return resp.status_code
    except Exception as e:
        log.warning("FCM send error: %s", e)
        return 0


def send_to_tokens(tokens: list[str], title: str, body: str, data: dict | None = None):
    """Push to each token. Returns (ok, fail, dead_tokens)."""
    sa = _load_sa()
    at = _access_token()
    if not sa or not at or not tokens:
        return 0, 0, []
    url = f"https://fcm.googleapis.com/v1/projects/{sa['project_id']}/messages:send"
    headers = {"Authorization": f"Bearer {at}", "Content-Type": "application/json"}
    ok = fail = 0
    dead: list[str] = []
    with httpx.Client(timeout=15) as client:
        for t in tokens:
            st = _send_one(client, url, headers, t, title, body, data)
            if st == 200:
                ok += 1
            else:
                fail += 1
                if st in (404, 400):     # UNREGISTERED / INVALID token → stop sending to it
                    dead.append(t)
    return ok, fail, dead


# ───────────────────────── device-token registry ─────────────────────────
def register_device(token: str | None, device_id: str | None, platform: str | None) -> dict:
    """Upsert a device. Pragnesh's rule: a BLANK token never overwrites a saved
    one — we keep the last valid token for that device."""
    token = (token or "").strip()
    device_id = (device_id or "").strip()
    platform = (platform or "android").strip().lower() or "android"
    key = device_id or token
    if not key:
        return {"ok": False, "saved": False, "reason": "no device_id or token"}
    db = SessionLocal()
    try:
        row = db.query(DeviceToken).filter(DeviceToken.device_id == key).first()
        if row is None and token:
            row = db.query(DeviceToken).filter(DeviceToken.token == token).first()
        if row:
            if token:                         # only a REAL token overwrites
                row.token = token
            row.platform = platform
            row.active = True
            row.updated_at = datetime.utcnow()
            saved = bool(token)
        else:
            if not token:                     # blank token + brand-new device → nothing to store
                return {"ok": True, "saved": False, "reason": "blank token ignored"}
            db.add(DeviceToken(device_id=key, token=token, platform=platform, active=True))
            saved = True
        db.commit()
        return {"ok": True, "saved": saved}
    except Exception as e:
        db.rollback()
        log.warning("register_device failed: %s", e)
        return {"ok": False, "saved": False, "reason": "error"}
    finally:
        db.close()


def active_tokens() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(DeviceToken.token).filter(DeviceToken.active.is_(True)).all()
        # de-dupe while keeping non-empty
        seen, out = set(), []
        for (t,) in rows:
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out
    finally:
        db.close()


def device_count() -> int:
    db = SessionLocal()
    try:
        return db.query(DeviceToken).filter(DeviceToken.active.is_(True)).count()
    finally:
        db.close()


def _deactivate(tokens: list[str]) -> None:
    if not tokens:
        return
    db = SessionLocal()
    try:
        db.query(DeviceToken).filter(DeviceToken.token.in_(tokens)).update(
            {DeviceToken.active: False}, synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("deactivate dead tokens failed: %s", e)
    finally:
        db.close()


# ───────────────────────── new-signal push (non-blocking) ─────────────────────────
def notify_new_signal(sig: dict) -> None:
    """Fire-and-forget: spawn a worker so the signal writer loop never blocks on HTTP."""
    if not enabled():
        return
    threading.Thread(target=_notify_worker, args=(sig,), daemon=True,
                     name="fcm_notify").start()


def _notify_worker(sig: dict) -> None:
    try:
        tokens = active_tokens()
        if not tokens:
            return
        narrow = sig.get("direction") == "narrow"
        arrow = "▼ NARROW" if narrow else "▲ WIDEN"
        entry = sig.get("entry")
        target = sig.get("target")
        title = f"⚡ {sig.get('label', 'Signal')} — {arrow}"
        body = f"Fired @ {round(entry):,} → target {round(target):,}" if entry is not None and target is not None else "New signal"
        ok, fail, dead = send_to_tokens(tokens, title, body, data={
            "type": "signal",
            "pair": sig.get("label", ""),
            "direction": sig.get("direction", ""),
            "entry": entry, "target": target,
            "stop": sig.get("stop"),
            "expiry": sig.get("expiry_label", ""),
        })
        if dead:
            _deactivate(dead)
        log.info("signal push '%s': %d ok · %d fail · %d dead", sig.get("label"), ok, fail, len(dead))
    except Exception as e:
        log.warning("notify_new_signal worker failed: %s", e)
