"""Close-based spread history for one calendar pair, computed on demand.

The client's rule (02-Sep): the Spread History view shows ONE value per day,
from closing prices - not the live decrease/increase pair, whose two numbers
he found more noise than signal. Daily closes exist at Dhan for every MCX
contract, so the whole series is derived when asked and cached for an hour;
nothing new is stored, and the daily_spread table keeps serving the bullion
stock correlation untouched.

Token discipline: reuses the live feed's token (get_live_token) - minting a
standalone token would kill the socket.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import requests

from app.config import settings

log = logging.getLogger("spread_close_history")

_HIST_URL = "https://api.dhan.co/v2/charts/historical"
_lock = threading.Lock()
_cache: dict = {}          # sid -> (fetched_at, {date: close})
_CACHE_TTL = 3600.0


def _closes(sid: str, days: int) -> dict[str, float]:
    now = time.time()
    hit = _cache.get(sid)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    # The feed's socket token is NOT the right one for REST: the socket keeps
    # working on a token that a later in-process re-mint has invalidated for
    # REST (seen 02-Sep 14:30 - history went blank while the feed ticked on).
    # dhan_auth.get_token is the cached, auto-refreshing one every REST caller
    # uses; in-process it never mints while a valid token exists.
    from app.services import dhan_auth
    token = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN,
                                settings.DHAN_TOTP_SECRET).access_token
    to = datetime.now().date()
    out: dict[str, float] = {}
    # Dhan rejects windows starting before listing (DH-905); shrink until it
    # answers, so a young contract contributes whatever it actually has.
    for win in [w for w in (days, 180, 90, 45, 21) if w <= max(days, 21)]:
        try:
            r = requests.post(_HIST_URL, headers={
                "access-token": token, "client-id": settings.DHAN_CLIENT_ID,
                "Content-Type": "application/json"}, json={
                "securityId": str(sid), "exchangeSegment": "MCX_COMM",
                "instrument": "FUTCOM", "expiryCode": 0, "oi": False,
                "fromDate": (to - timedelta(days=win + 7)).isoformat(),
                "toDate": to.isoformat()}, timeout=25)
            d = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("closes %s: %s", sid, e)
            break
        if "close" in d:
            for ts, cl in zip(d.get("timestamp") or [], d.get("close") or []):
                out[datetime.fromtimestamp(ts).date().isoformat()] = cl
            break
        # Say what Dhan said. A silent empty answer is how this went blank on
        # the client's screen without a line in the log.
        code = str(d.get("errorCode") or d.get("errorType") or d)[:80]
        log.warning("closes %s window %d: %s", sid, win, code)
        if "DH-905" not in code:          # only the listing-window error is worth retrying
            break
        time.sleep(0.4)
    # Cache only what Dhan actually gave. An empty answer during the dead-token
    # window on 02-Sep was cached for the full hour and kept a live pair blank
    # long after the token was fixed. Empties get a minute, so a burst of
    # clicks does not hammer Dhan but a fixed token shows through quickly.
    _cache[sid] = (now if out else now - _CACHE_TTL + 60, out)
    if len(_cache) > 64:
        _cache.clear()
    return out


def record_pairs() -> None:
    """Remember every live calendar pair's legs, so expiry cannot erase its
    history. Called after each pair-registry refresh; upserts are cheap."""
    from app.database import SessionLocal
    from app.models import PairLeg
    from app.services.pair_registry import get_pairs
    pairs = [p for p in get_pairs() if p.get("type") == "calendar"]
    if not pairs:
        return
    db = SessionLocal()
    try:
        known = {r.name: r for r in db.query(PairLeg).all()}
        now = datetime.now()
        for p in pairs:
            row = known.get(p["name"])
            if not row:
                row = PairLeg(name=p["name"])
                db.add(row)
            row.group_label = p.get("group_label")
            row.big_security_id = str(p["big_security_id"])
            row.small_security_id = str(p["small_security_id"])
            row.big_symbol = p.get("big_trading_symbol")
            row.small_symbol = p.get("small_trading_symbol")
            row.last_seen = now
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("record_pairs failed: %s", e)
    finally:
        db.close()


def list_pairs() -> list[dict]:
    """Everything selectable in the history dialog: live pairs first, then the
    remembered expired ones, newest expiry group first."""
    from app.database import SessionLocal
    from app.models import PairLeg
    from app.services.pair_registry import get_pairs
    live = {p["name"]: p for p in get_pairs() if p.get("type") == "calendar"}
    out = [{"name": n, "title": p.get("mcx_label") or p.get("label") or n,
            "expired": False} for n, p in live.items()]
    db = SessionLocal()
    try:
        for r in db.query(PairLeg).order_by(PairLeg.name.desc()).all():
            if r.name in live:
                continue
            title = f"{r.group_label or ''} {r.big_symbol or ''} / {r.small_symbol or ''}".strip()
            out.append({"name": r.name, "title": title or r.name, "expired": True})
    finally:
        db.close()
    return out


def _legs_of(pair_name: str) -> dict | None:
    """The pair's legs - from the live registry, or the memory of it."""
    from app.services.pair_registry import get_pairs
    pair = next((p for p in get_pairs() if p.get("name") == pair_name), None)
    if pair:
        return pair
    from app.database import SessionLocal
    from app.models import PairLeg
    db = SessionLocal()
    try:
        r = db.query(PairLeg).filter(PairLeg.name == pair_name).first()
        if not r:
            return None
        return {"name": r.name, "big_security_id": r.big_security_id,
                "small_security_id": r.small_security_id,
                "big_trading_symbol": r.big_symbol,
                "small_trading_symbol": r.small_symbol}
    finally:
        db.close()


def pair_history(pair_name: str, days: int) -> dict:
    """Rows newest first: date, near/far closes, ONE difference, %."""
    pair = _legs_of(pair_name)
    if not pair:
        return {"pair": pair_name, "rows": [], "count": 0,
                "error": "unknown pair - it was never recorded"}
    with _lock:
        far = _closes(pair["big_security_id"], days)
        near = _closes(pair["small_security_id"], days)
    cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
    rows = []
    for d in sorted(set(far) & set(near), reverse=True):
        if d < cutoff:
            continue
        diff = round(far[d] - near[d], 2)
        rows.append({
            "date": d, "near": near[d], "far": far[d], "diff": diff,
            "pct": round(diff / near[d] * 100, 2) if near[d] else None,
        })
    log.info("spread-history %s: %d rows over %d days (near %d, far %d candles)",
             pair_name, len(rows), days, len(near), len(far))
    return {"pair": pair_name, "days": days, "count": len(rows),
            # so the dialog can say WHICH leg has no closes - a far month that
            # has never traded has no daily candles, and that is not a fault
            "near_days": len(near), "far_days": len(far),
            "near_symbol": pair.get("small_trading_symbol"),
            "far_symbol": pair.get("big_trading_symbol"), "rows": rows}
