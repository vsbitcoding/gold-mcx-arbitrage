"""The live market feed, as every caller sees it.

Callers import THIS and never the provider module: the health route, the
maintenance rolls, the paper trades, the history captures. The provider is
Angel One (angel_ws_feed); keeping the facade means a future provider is a
change here and nowhere else.
"""
from __future__ import annotations

from app.services import angel_ws_feed as _impl


def provider() -> str:
    return "angel"


def is_market_open() -> bool:
    return _impl.is_market_open()


def get_status() -> dict:
    s = _impl.get_status()
    s["provider"] = provider()
    return s


def request_resubscribe(reason: str) -> str:
    return _impl.request_resubscribe(reason)


def has_expiring_today() -> bool:
    return _impl.has_expiring_today()


def history_token() -> str:
    """Non-empty once an Angel session exists - the candle puller's go-ahead."""
    try:
        from app.services import angel_feed
        jwt, _feed, _c = angel_feed.get_session()
        return "angel" if jwt else ""
    except Exception:  # noqa: BLE001
        return ""


def start_feed_in_background(loop):
    return _impl.start_feed_in_background(loop)
