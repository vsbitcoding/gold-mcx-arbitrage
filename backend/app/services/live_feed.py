"""The live market feed, whichever provider is behind it.

Callers import THIS and never a provider module: the health route, the
maintenance rolls, the paper trades, the history captures. `FEED_PROVIDER`
in .env picks dhan_feed or angel_ws_feed at startup; both expose the same
five functions, so switching provider is a one-line change and a restart.
"""
from __future__ import annotations

from app.config import settings


def _impl():
    if settings.FEED_PROVIDER == "angel":
        from app.services import angel_ws_feed as m
    else:
        from app.services import dhan_feed as m
    return m


def provider() -> str:
    return "angel" if settings.FEED_PROVIDER == "angel" else "dhan"


def is_market_open() -> bool:
    from app.services.dhan_feed import is_market_open as f   # one clock for both
    return f()


def get_status() -> dict:
    s = _impl().get_status()
    s["provider"] = provider()
    return s


def request_resubscribe(reason: str) -> str:
    return _impl().request_resubscribe(reason)


def has_expiring_today() -> bool:
    return _impl().has_expiring_today()


def get_live_token() -> str:
    """Dhan's in-process REST token; '' on Angel (its REST callers use
    angel_feed.get_session instead)."""
    return _impl().get_live_token()


def history_token() -> str:
    """Whatever the candle puller needs to prove the feed is up: Dhan's
    token, or the word 'angel' once a session exists."""
    if provider() == "angel":
        try:
            from app.services import angel_feed
            jwt, _feed, _c = angel_feed.get_session()
            return "angel" if jwt else ""
        except Exception:  # noqa: BLE001
            return ""
    return _impl().get_live_token()


def start_feed_in_background(loop):
    return _impl().start_feed_in_background(loop)
