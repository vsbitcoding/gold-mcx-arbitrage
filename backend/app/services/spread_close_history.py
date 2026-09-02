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
    from app.services import dhan_feed
    token = dhan_feed.get_live_token()
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
        time.sleep(0.4)
    _cache[sid] = (now, out)
    if len(_cache) > 64:
        _cache.clear()
    return out


def pair_history(pair_name: str, days: int) -> dict:
    """Rows newest first: date, near/far closes, ONE difference, %."""
    from app.services.pair_registry import get_pairs
    pair = next((p for p in get_pairs() if p.get("name") == pair_name), None)
    if not pair:
        return {"pair": pair_name, "rows": [], "count": 0,
                "error": "pair not live any more - only live pairs have history here"}
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
    return {"pair": pair_name, "days": days, "count": len(rows),
            "near_symbol": pair.get("small_trading_symbol"),
            "far_symbol": pair.get("big_trading_symbol"), "rows": rows}
