"""Dhan WebSocket live feed using official dhanhq SDK MarketFeed.

Auto-flow:
  1. Generate access_token from TOTP + MPIN (services.dhan_auth)
  2. Resolve near-month MCX security IDs (services.instrument_resolver)
  3. Use dhanhq.marketfeed.MarketFeed (Full mode) to receive bid/ask + depth
  4. Update QuoteStore on every tick + run trigger evaluator

Falls back to simulated random feed only if credentials are missing entirely.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from app.config import settings
from app.database import SessionLocal
from app.services import dhan_auth
from app.services.instrument_resolver import resolve_near_month_ids
from app.services.market_data import quote_store
from app.services.trade_engine import evaluate

log = logging.getLogger("dhan_feed")


def _eval_safely() -> None:
    db = SessionLocal()
    try:
        evaluate(db)
    except Exception as e:
        log.exception("evaluate() failed: %s", e)
    finally:
        db.close()


def _run_real_feed_thread() -> None:
    """Blocking SDK feed loop; runs in its own thread."""
    from dhanhq import marketfeed
    from dhanhq.dhan_context import DhanContext

    while True:
        try:
            token = dhan_auth.get_token(
                settings.DHAN_CLIENT_ID,
                settings.DHAN_MPIN,
                settings.DHAN_TOTP_SECRET,
            )
            log.info("Token OK, expires in %.0f min. Resolving instruments...", token.expires_in() / 60)

            resolved = resolve_near_month_ids(min_days_ahead=0)
            if not resolved:
                raise RuntimeError("No active MCX gold instruments resolved.")

            sec_to_name = {str(info["security_id"]): short for short, info in resolved.items()}

            # Build SDK instrument tuples: (exchange_code, security_id_str, request_code)
            # 5 = MCX_COMM, 21 = Full (gives bid/ask depth)
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
                if t == "Full Data":
                    depth = data.get("depth") or []
                    if depth:
                        d0 = depth[0]
                        bid = float(d0.get("bid_price") or ltp)
                        ask = float(d0.get("ask_price") or ltp)
                elif t == "Market Depth":
                    depth = data.get("depth") or []
                    if depth:
                        d0 = depth[0]
                        bid = float(d0.get("bid_price") or ltp)
                        ask = float(d0.get("ask_price") or ltp)
                quote_store.update(name, bid=bid, ask=ask, ltp=ltp, ts=time.time())

                # Throttle DB evaluator (~2 Hz)
                now = time.time()
                if now - last_eval[0] > 0.5:
                    _eval_safely()
                    last_eval[0] = now

            def on_error(_instance, err):
                log.warning("MarketFeed error: %s", err)

            feed = marketfeed.MarketFeed(
                ctx,
                instruments,
                version="v2",
                on_message=on_message,
                on_error=on_error,
            )
            log.info("Starting MarketFeed.run() — real ticks incoming.")
            feed.run()  # blocking
        except Exception as e:
            log.exception("Feed loop crashed: %s", e)
            dhan_auth.invalidate()
            time.sleep(5)


def _run_simulated_thread() -> None:
    import random
    base = {"petal": 122.0, "guinea": 968.0, "ten": 1218.0, "mini": 12180.0}
    log.warning("SIMULATED feed (no Dhan credentials).")
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
        _eval_safely()
        time.sleep(1.0)


def start_feed_in_background(loop: asyncio.AbstractEventLoop):
    creds_ok = bool(
        settings.DHAN_CLIENT_ID and settings.DHAN_MPIN and settings.DHAN_TOTP_SECRET
    )
    target = _run_real_feed_thread if creds_ok else _run_simulated_thread
    t = threading.Thread(target=target, daemon=True, name="dhan-feed")
    t.start()
    return t
