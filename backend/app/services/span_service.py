"""Daily MCX SPAN-style margin source.

Maintains an in-memory cache of `security_id → ₹ margin per lot`. The
margin_service consults this cache FIRST; only if a contract is missing does
it fall back to the calibrated MARGIN_PERCENT table.

Refresh strategy:
- On startup once (if `SPAN_MARGIN_FEED_URL` is set)
- Daily at 08:30 IST via the maintenance loop
- Manual refresh exposed in the future via an admin route if needed

Feed format (JSON):
    [
      {"security_id": "459277", "margin_per_lot": 146000},
      {"security_id": "552721", "margin_per_lot": 1500},
      ...
    ]

When the broker / MCX integration provides exact margins, point the URL at
that endpoint and the engine instantly uses the live values — no other
code changes required.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

log = logging.getLogger("span")

_margins: dict[str, float] = {}                # security_id → ₹/lot
_last_refresh_at: Optional[datetime] = None
_last_refresh_ok: bool = False
_last_refresh_msg: str = "not attempted yet"


def get_margin_for_security_id(security_id: str | None) -> Optional[float]:
    if not security_id:
        return None
    return _margins.get(str(security_id))


def status() -> dict:
    return {
        "configured_url": settings.SPAN_MARGIN_FEED_URL or None,
        "last_refresh_at": (_last_refresh_at.isoformat() + "Z") if _last_refresh_at else None,
        "last_refresh_ok": _last_refresh_ok,
        "last_refresh_msg": _last_refresh_msg,
        "contracts_with_live_margin": len(_margins),
        "source": "live_span" if (_last_refresh_ok and _margins) else "fallback_percent",
    }


def refresh() -> bool:
    """Attempt to fetch the SPAN feed. Returns True on success. Always safe to call."""
    global _last_refresh_at, _last_refresh_ok, _last_refresh_msg, _margins
    _last_refresh_at = datetime.now(timezone.utc)

    url = (settings.SPAN_MARGIN_FEED_URL or "").strip()
    if not url:
        _last_refresh_ok = False
        _last_refresh_msg = "SPAN_MARGIN_FEED_URL not configured — using fallback %"
        log.info(_last_refresh_msg)
        return False

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ArbiDash/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        new_cache: dict[str, float] = {}
        for row in data if isinstance(data, list) else []:
            sid = str(row.get("security_id", "")).strip()
            try:
                margin = float(row.get("margin_per_lot", 0))
            except (TypeError, ValueError):
                continue
            if sid and margin > 0:
                new_cache[sid] = margin
        if not new_cache:
            _last_refresh_ok = False
            _last_refresh_msg = "feed returned 0 valid contracts"
            log.warning(_last_refresh_msg)
            return False
        _margins = new_cache
        _last_refresh_ok = True
        _last_refresh_msg = f"refreshed {len(new_cache)} contracts"
        log.info(_last_refresh_msg)
        return True
    except Exception as e:
        _last_refresh_ok = False
        _last_refresh_msg = f"fetch failed: {e}"
        log.warning("SPAN refresh failed: %s", e)
        return False
