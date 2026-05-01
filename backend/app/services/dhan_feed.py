"""Dhan WebSocket live feed using official dhanhq SDK MarketFeed.

24/7 design:
  - On startup: generate access_token via TOTP+MPIN, resolve current MCX securities
  - Run dhanhq MarketFeed in dedicated thread (handles binary decode + reconnect)
  - Watchdog thread: every 5 min checks token expiry; if < 30 min remaining,
    closes WS to force reconnect with fresh token
  - On disconnect (network/token/market close): retry loop regenerates token
    and reconnects with exponential backoff capped at 2 min
  - Falls back to simulated feed only if credentials are completely missing
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> datetime:
    return datetime.now(IST)


def is_market_open() -> bool:
    """MCX commodity hours: Mon-Fri 9:00 AM to 11:30 PM IST. Saturday morning
    session and holidays not supported (treats as closed — safe default)."""
    n = _ist_now()
    # weekday(): Mon=0 ... Sun=6. Closed on Sat (5) and Sun (6).
    if n.weekday() >= 5:
        return False
    open_t = n.replace(hour=9, minute=0, second=0, microsecond=0)
    close_t = n.replace(hour=23, minute=30, second=0, microsecond=0)
    return open_t <= n <= close_t

from app.config import settings
from app.database import SessionLocal
from app.services import dhan_auth
from app.services.broadcaster import broadcaster
from app.services.instrument_resolver import resolve_near_month_ids
from app.services.market_data import quote_store
from app.services.snapshot import build_live_payload
from app.services.trade_engine import evaluate

log = logging.getLogger("dhan_feed")

# Module-level state for status endpoint + watchdog
_state: dict = {
    "mode": "starting",          # starting | live | simulated | reconnecting
    "client_id": "",
    "client_name": "",
    "token_expiry_epoch": 0.0,
    "last_tick_epoch": 0.0,
    "last_token_refresh_epoch": 0.0,
    "instruments": {},
    "ws_connected": False,
    "reconnect_count": 0,
    "last_error": "",
}
_state_lock = threading.Lock()
_active_feed = None  # current MarketFeed instance (for watchdog to close)


def get_status() -> dict:
    with _state_lock:
        s = dict(_state)
    s["token_expires_in_seconds"] = max(0, int(s["token_expiry_epoch"] - time.time()))
    s["last_tick_age_seconds"] = (
        int(time.time() - s["last_tick_epoch"]) if s["last_tick_epoch"] else None
    )
    s["server_time"] = datetime.now(timezone.utc).isoformat()
    s["market_open"] = is_market_open()
    return s


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


def _eval_and_broadcast() -> None:
    db = SessionLocal()
    try:
        evaluate(db)
        if broadcaster.client_count > 0:
            payload = build_live_payload(db)
            broadcaster.push_threadsafe({"type": "snapshot", "data": payload})
    except Exception as e:
        log.exception("evaluate() failed: %s", e)
    finally:
        db.close()


# Backward-compat alias
def _eval_safely() -> None:
    _eval_and_broadcast()


_last_reconnect_epoch: float = 0.0
RECONNECT_GRACE_SECONDS = 300  # don't force another reconnect within 5 min


def _trigger_reconnect(reason: str) -> None:
    """Force a WS reconnect, with grace-period guard so we never bounce."""
    global _active_feed, _last_reconnect_epoch
    if time.time() - _last_reconnect_epoch < RECONNECT_GRACE_SECONDS:
        return  # in grace window, skip
    _last_reconnect_epoch = time.time()
    log.warning("Watchdog forcing reconnect: %s", reason)
    dhan_auth.invalidate()
    try:
        if _active_feed:
            _active_feed.close_connection()
    except Exception as e:
        log.warning("close_connection() failed: %s", e)


def _watchdog() -> None:
    """Watchdog signals (with 5-min grace between forced reconnects):
       1. Token expires in <30 min → force fresh login
       2. Market hours + no tick in 3+ min → silent WS, reconnect
       3. Just AFTER market open (9:01-9:05 IST) → daily fresh subscription"""
    last_postmarket_open = None
    while True:
        time.sleep(60)
        with _state_lock:
            expiry = _state["token_expiry_epoch"]
            mode = _state["mode"]
            last_tick = _state["last_tick_epoch"]

        # 1. Token expiring soon
        if expiry and (expiry - time.time()) < 30 * 60:
            _trigger_reconnect("token expiring")
            continue

        # 2. Silent feed during market hours
        if mode == "live" and is_market_open() and last_tick:
            age = time.time() - last_tick
            if age > 180:
                _trigger_reconnect(f"no tick for {int(age)}s during market hours")
                continue

        # 3. Daily fresh-subscription right AFTER market opens (9:01-9:05 IST)
        ist = _ist_now()
        today = ist.date()
        if (
            ist.weekday() < 5
            and ist.hour == 9
            and 1 <= ist.minute <= 5
            and last_postmarket_open != today
        ):
            _trigger_reconnect("post-open fresh subscription")
            last_postmarket_open = today


def _run_real_feed_thread() -> None:
    """Blocking SDK feed loop with reconnect + token refresh."""
    global _active_feed
    from dhanhq import marketfeed
    from dhanhq.dhan_context import DhanContext

    backoff = 5
    while True:
        try:
            _set_state(mode="reconnecting", ws_connected=False)
            token = dhan_auth.get_token(
                settings.DHAN_CLIENT_ID,
                settings.DHAN_MPIN,
                settings.DHAN_TOTP_SECRET,
            )
            _set_state(
                client_id=token.client_id,
                client_name=token.client_name,
                token_expiry_epoch=token.expiry_epoch,
                last_token_refresh_epoch=time.time(),
            )
            log.info(
                "Token OK: %s, expires %s (in %.1f hours)",
                token.client_name,
                datetime.fromtimestamp(token.expiry_epoch).strftime("%Y-%m-%d %H:%M"),
                token.expires_in() / 3600,
            )

            # Logic 1 (Mini Next-Month): Petal/Guinea/Ten = nearest end-of-month
            # (with 3-day buffer to skip illiquid expiry days), Mini = next-month
            # contract after that expiry. Auto-rolls every month.
            resolved = resolve_near_month_ids(min_days_ahead=3, mini_rule="next_month")
            if not resolved:
                # Last-resort fallback if buffer too aggressive
                resolved = resolve_near_month_ids(min_days_ahead=0, mini_rule="next_month")
            if not resolved:
                raise RuntimeError("No active MCX gold instruments resolved.")

            sec_to_name = {str(info["security_id"]): short for short, info in resolved.items()}
            instruments_meta = {
                short: {
                    "security_id": info["security_id"],
                    "trading_symbol": info["trading_symbol"],
                    "expiry": info["expiry"].strftime("%Y-%m-%d"),
                }
                for short, info in resolved.items()
            }
            _set_state(instruments=instruments_meta)

            instruments = [
                (marketfeed.MarketFeed.MCX, str(info["security_id"]), marketfeed.MarketFeed.Full)
                for info in resolved.values()
            ]
            log.info(
                "Subscribing %d instruments: %s",
                len(instruments),
                ", ".join(f"{n}={i['security_id']}" for n, i in resolved.items()),
            )

            ctx = DhanContext(settings.DHAN_CLIENT_ID, token.access_token)
            last_eval = [0.0]
            tick_counts: dict[str, int] = {}

            def on_message(_instance, data):
                if not isinstance(data, dict):
                    return
                t = data.get("type")
                sec_id = str(data.get("security_id", ""))
                name = sec_to_name.get(sec_id)
                if not name:
                    return

                key = f"{name}:{t}"
                tick_counts[key] = tick_counts.get(key, 0) + 1
                if tick_counts[key] == 1:
                    log.info("FIRST tick %s: ltp=%s depth=%s keys=%s",
                             key, data.get("LTP"),
                             bool(data.get("depth")),
                             list(data.keys())[:8])

                try:
                    ltp = float(data.get("LTP") or 0)
                except (TypeError, ValueError):
                    ltp = 0.0
                bid = ask = ltp
                if t in ("Full Data", "Market Depth"):
                    depth = data.get("depth") or []
                    if depth:
                        d0 = depth[0]
                        try:
                            b = float(d0.get("bid_price") or 0)
                            a = float(d0.get("ask_price") or 0)
                            bid = b if b > 0 else ltp
                            ask = a if a > 0 else ltp
                        except (TypeError, ValueError):
                            pass

                # Preserve previous good prices if this tick has zeros (e.g. OI-only packets)
                existing = quote_store.get(name)
                bid = bid or existing.bid
                ask = ask or existing.ask
                ltp = ltp or existing.ltp
                if bid or ask or ltp:
                    quote_store.update(name, bid=bid, ask=ask, ltp=ltp, ts=time.time())
                _set_state(last_tick_epoch=time.time(), ws_connected=True, mode="live")

                now = time.time()
                if now - last_eval[0] > 0.5:
                    _eval_and_broadcast()
                    last_eval[0] = now

            def on_error(_instance, err):
                log.warning("MarketFeed error: %s", err)
                _set_state(last_error=str(err)[:200])

            def on_close(_instance):
                log.info("MarketFeed connection closed.")
                _set_state(ws_connected=False)

            feed = marketfeed.MarketFeed(
                ctx,
                instruments,
                version="v2",
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            _active_feed = feed
            # Reset stale-tick timer so watchdog gives this connection a 3-min
            # grace window before considering it silent.
            _set_state(last_tick_epoch=time.time())
            log.info("Starting MarketFeed.run() — real ticks incoming.")
            feed.run()  # blocking until disconnect
            log.info("MarketFeed.run() exited normally.")
            backoff = 5
        except Exception as e:
            log.exception("Feed loop error: %s — retrying in %ds", e, backoff)
            _set_state(last_error=str(e)[:200])
            dhan_auth.invalidate()
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
        finally:
            _active_feed = None
            with _state_lock:
                _state["reconnect_count"] += 1
                _state["ws_connected"] = False


def _run_simulated_thread() -> None:
    import random
    base = {"petal": 122.0, "guinea": 968.0, "ten": 1218.0, "mini": 12180.0}
    log.warning("SIMULATED feed (no Dhan credentials).")
    _set_state(mode="simulated", instruments={k: {"trading_symbol": k.upper()} for k in base})
    while True:
        for inst, mid in base.items():
            jitter = random.uniform(-0.5, 0.5)
            quote_store.update(
                inst,
                bid=round(mid + jitter - 0.05, 2),
                ask=round(mid + jitter + 0.05, 2),
                ltp=round(mid + jitter, 2),
                ts=time.time(),
            )
        _eval_and_broadcast()
        _set_state(last_tick_epoch=time.time())
        time.sleep(1.0)


def start_feed_in_background(loop: asyncio.AbstractEventLoop):
    creds_ok = bool(
        settings.DHAN_CLIENT_ID and settings.DHAN_MPIN and settings.DHAN_TOTP_SECRET
    )
    target = _run_real_feed_thread if creds_ok else _run_simulated_thread
    feed_thread = threading.Thread(target=target, daemon=True, name="dhan-feed")
    feed_thread.start()
    if creds_ok:
        watch_thread = threading.Thread(target=_watchdog, daemon=True, name="dhan-watchdog")
        watch_thread.start()
    return feed_thread
