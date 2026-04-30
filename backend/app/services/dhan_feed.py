"""Dhan WebSocket live feed worker.

Subscribes to Quote feed for the four MCX gold instruments and updates the in-memory
QuoteStore on every tick. The trigger evaluator runs after every batch of updates.
"""
import asyncio
import logging
import time

from app.config import settings
from app.database import SessionLocal
from app.services.market_data import quote_store
from app.services.trade_engine import evaluate

log = logging.getLogger("dhan_feed")

INSTRUMENT_MAP_BUILDER = lambda: {
    settings.PETAL_SECURITY_ID: "petal",
    settings.GUINEA_SECURITY_ID: "guinea",
    settings.TEN_SECURITY_ID: "ten",
    settings.MINI_SECURITY_ID: "mini",
}


async def _run_feed() -> None:
    """Run live Dhan feed using the dhanhq SDK if credentials present, else simulate."""
    if not (settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN):
        log.warning("Dhan credentials missing — running SIMULATED feed.")
        await _simulated_feed()
        return

    try:
        from dhanhq import marketfeed
    except Exception as e:
        log.error("dhanhq import failed: %s — falling back to simulated feed.", e)
        await _simulated_feed()
        return

    instrument_map = INSTRUMENT_MAP_BUILDER()
    instruments = [
        (settings.EXCHANGE_SEGMENT, sec_id, marketfeed.Quote)
        for sec_id in instrument_map.keys()
        if sec_id
    ]

    if not instruments:
        log.warning("No instrument tokens configured — running SIMULATED feed.")
        await _simulated_feed()
        return

    feed = marketfeed.DhanFeed(
        settings.DHAN_CLIENT_ID,
        settings.DHAN_ACCESS_TOKEN,
        instruments,
    )

    log.info("Dhan feed started for %d instruments.", len(instruments))

    while True:
        try:
            feed.run_forever()
            data = feed.get_data()
            if not data:
                await asyncio.sleep(0.05)
                continue
            sec_id = str(data.get("security_id"))
            instrument = instrument_map.get(sec_id)
            if not instrument:
                continue
            bid = float(data.get("best_bid_price") or data.get("BBP") or 0)
            ask = float(data.get("best_ask_price") or data.get("BAP") or 0)
            ltp = float(data.get("LTP") or 0)
            quote_store.update(instrument, bid=bid, ask=ask, ltp=ltp, ts=time.time())
            _evaluate_safely()
        except Exception as e:
            log.exception("Dhan feed loop error: %s", e)
            await asyncio.sleep(2)


async def _simulated_feed() -> None:
    """Demo feed for local testing when Dhan creds not present."""
    import random

    base = {"petal": 122.0, "guinea": 968.0, "ten": 1218.0, "mini": 12180.0}
    while True:
        for inst, mid in base.items():
            jitter = random.uniform(-0.5, 0.5)
            bid = round(mid + jitter - 0.05, 2)
            ask = round(mid + jitter + 0.05, 2)
            quote_store.update(inst, bid=bid, ask=ask, ltp=round(mid + jitter, 2), ts=time.time())
        _evaluate_safely()
        await asyncio.sleep(1.0)


def _evaluate_safely() -> None:
    db = SessionLocal()
    try:
        evaluate(db)
    except Exception as e:
        log.exception("evaluate() failed: %s", e)
    finally:
        db.close()


def start_feed_in_background(loop: asyncio.AbstractEventLoop) -> asyncio.Task:
    return loop.create_task(_run_feed())
