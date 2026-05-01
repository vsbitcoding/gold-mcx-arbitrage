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


def _watchdog() -> None:
    """Watchdog forces a reconnect on three signals:
       1. Token expires in <30 min (force fresh login)
       2. During market hours, no tick in 3+ min (silent WS — common overnight)
       3. Just before market open (8:55 IST) — refresh any stale overnight WS"""
    global _active_feed
    last_premarket_check = None
    while True:
        time.sleep(60)  # check every minute
        with _state_lock:
            expiry = _state["token_expiry_epoch"]
            mode = _state["mode"]
            last_tick = _state["last_tick_epoch"]

        force_reconnect = False
        reason = ""

        # 1. Token expiring soon
        if expiry and (expiry - time.time()) < 30 * 60:
            force_reconnect = True
            reason = "token expiring"

        # 2. No tick for 3+ min during market hours
        if not force_reconnect and mode == "live" and is_market_open():
            if last_tick:
                age = time.time() - last_tick
                if age > 180:  # 3 minutes silent during market hours
                    force_reconnect = True
                    reason = f"no tick for {int(age)}s during market hours"

        # 3. Pre-market refresh: at 8:55-8:59 IST, force one reconnect to clear stale overnight WS
        ist = _ist_now()
        today = ist.date()
        if (
            ist.weekday() < 5
            and ist.hour == 8
            and ist.minute >= 55
            and last_premarket_check != today
        ):
            force_reconnect = True
            reason = "pre-market refresh"
            last_premarket_check = today

        if force_reconnect:
            log.warning("Watchdog forcing reconnect: %s", reason)
            dhan_auth.invalidate()
            try:
                if _active_feed:
                    _active_feed.close_connection()
            except Exception as e:
                log.warning("close_connection() failed in watchdog: %s", e)


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

            def on_message(_instance, data):
                if not isinstance(data, dict):
                    return
                t = data.get("type")
                sec_id = str(data.get("security_id", ""))
                name = sec_to_name.get(sec_id)
                if not name:
                    return
                ltp = float(data.get("LTP") or 0)
                bid = ask = ltp
                if t in ("Full Data", "Market Depth"):
                    depth = data.get("depth") or []
                    if depth:
                        d0 = depth[0]
                        bid = float(d0.get("bid_price") or ltp)
                        ask = float(d0.get("ask_price") or ltp)
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
