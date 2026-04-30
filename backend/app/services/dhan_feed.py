"""Dhan WebSocket live feed.

Auto-flow:
  1. Generate access_token from TOTP + MPIN (services.dhan_auth)
  2. Resolve near-month MCX security IDs (services.instrument_resolver)
  3. Connect to Dhan v2 marketfeed WebSocket subscribing to Quote (bid/ask) packets
  4. Update QuoteStore on every tick + run trigger evaluator

Falls back to simulated random feed only if credentials are missing entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from typing import Optional

import websockets

from app.config import settings
from app.database import SessionLocal
from app.services import dhan_auth
from app.services.instrument_resolver import resolve_near_month_ids
from app.services.market_data import quote_store
from app.services.trade_engine import evaluate

log = logging.getLogger("dhan_feed")

DHAN_WS_URL = (
    "wss://api-feed.dhan.co?version=2&token={token}&clientId={client_id}&authType=2"
)

# Dhan v2 segment codes
SEG_MCX = 5
QUOTE_PACKET = 4  # Quote feed (best bid/ask + LTP)
TICKER_PACKET = 2  # ticker (LTP only)


def _eval_safely() -> None:
    db = SessionLocal()
    try:
        evaluate(db)
    except Exception as e:
        log.exception("evaluate() failed: %s", e)
    finally:
        db.close()


def _build_subscription(segment: int, security_ids: list[str], packet_type: int = QUOTE_PACKET) -> bytes:
    """Build Dhan v2 binary subscribe message.

    Header (83 bytes):
        FeedRequestCode (1)  = packet_type (subscribe = 15 for v2 JSON; binary uses 11/12)
    For v2, JSON-based subscribe on quote feed:
        {"RequestCode": 15, "InstrumentCount": N,
         "InstrumentList": [{"ExchangeSegment": "MCX_COMM", "SecurityId": "..."}, ...]}
    """
    raise NotImplementedError  # using JSON path below


def _segment_name(seg: int) -> str:
    return {1: "NSE_EQ", 2: "NSE_FNO", 3: "BSE_EQ", 4: "BSE_FNO", 5: "MCX_COMM"}.get(seg, "MCX_COMM")


async def _run_real_feed() -> None:
    """Generate token, resolve instruments, connect to Dhan WS, dispatch ticks."""
    token = dhan_auth.get_token(settings.DHAN_CLIENT_ID, settings.DHAN_MPIN, settings.DHAN_TOTP_SECRET)
    log.info("Got access token (expires in %.0f min). Resolving instruments...", token.expires_in() / 60)

    resolved = resolve_near_month_ids(min_days_ahead=0)
    if not resolved:
        raise RuntimeError("Could not resolve any MCX gold instruments from scrip master")

    # Map security_id (str) -> short instrument name
    sec_to_name = {info["security_id"]: short for short, info in resolved.items()}
    instruments = [
        {"ExchangeSegment": "MCX_COMM", "SecurityId": str(info["security_id"])}
        for info in resolved.values()
    ]
    log.info("Subscribing to %d instruments: %s", len(instruments),
             ", ".join(f"{s}={i['security_id']}" for s, i in resolved.items()))

    url = DHAN_WS_URL.format(token=token.access_token, client_id=settings.DHAN_CLIENT_ID)
    async with websockets.connect(url, max_size=2 ** 20, ping_interval=30, ping_timeout=20) as ws:
        # Subscribe to Quote (bid/ask) packets
        sub = {
            "RequestCode": 17,  # 15=Ticker, 17=Quote, 21=Full
            "InstrumentCount": len(instruments),
            "InstrumentList": instruments,
        }
        await ws.send(json.dumps(sub))
        log.info("Subscribed. Waiting for ticks...")

        last_eval = 0.0
        while True:
            msg = await ws.recv()
            if isinstance(msg, str):
                # JSON status messages
                log.debug("WS text: %s", msg[:200])
                continue
            _decode_packet(msg, sec_to_name)
            now = time.time()
            if now - last_eval > 0.4:  # rate-limit DB evaluator to ~2.5 Hz
                _eval_safely()
                last_eval = now


def _decode_packet(buf: bytes, sec_to_name: dict[str, str]) -> None:
    """Decode Dhan v2 binary packet.

    Header (8 bytes):
        feed_response_code (1, uint8)
        message_length     (2, uint16 LE)
        exchange_segment   (1, uint8)
        security_id        (4, uint32 LE)

    Quote response code = 4. Body layout (per Dhan v2 docs):
        LTP (float32), LTQ (uint16), LTT (uint32), ATP (float32), VOL (uint32),
        TBQ (uint32), TSQ (uint32), OPEN (float32), CLOSE (float32),
        HIGH (float32), LOW (float32),
        + Best Bid/Ask packet for Quote
    """
    if len(buf) < 8:
        return
    code = buf[0]
    seg = buf[3]
    sec_id = struct.unpack_from("<I", buf, 4)[0]
    name = sec_to_name.get(str(sec_id))
    if not name:
        return

    if code == 4:  # Quote packet
        # Quote payload layout (after 8-byte header):
        # LTP f32, LTQ u16, LTT u32, ATP f32, Vol u32, TBQ u32, TSQ u32,
        # Open f32, Close f32, High f32, Low f32, BestBid f32, BestAsk f32,
        # BestBidQty u16, BestAskQty u16
        # Total ~ 8 + 4+2+4+4+4+4+4+4+4+4+4+4+4+2+2 = 62 bytes
        try:
            ltp = struct.unpack_from("<f", buf, 8)[0]
            # Find bid/ask near the end of Quote packet (variable across SDK versions)
            # Search safely:
            offset_bid = 8 + 4 + 2 + 4 + 4 + 4 + 4 + 4 + 4 + 4 + 4 + 4
            if len(buf) >= offset_bid + 8:
                bid = struct.unpack_from("<f", buf, offset_bid)[0]
                ask = struct.unpack_from("<f", buf, offset_bid + 4)[0]
            else:
                bid = ask = ltp
        except struct.error:
            return
        quote_store.update(name, bid=float(bid), ask=float(ask), ltp=float(ltp), ts=time.time())
    elif code == 2:  # Ticker (LTP only)
        try:
            ltp = struct.unpack_from("<f", buf, 8)[0]
        except struct.error:
            return
        # Use LTP for both bid and ask if no quote packet available
        existing = quote_store.get(name)
        b = existing.bid or float(ltp)
        a = existing.ask or float(ltp)
        quote_store.update(name, bid=b, ask=a, ltp=float(ltp), ts=time.time())


async def _simulated_feed() -> None:
    """Demo feed for local testing when Dhan creds not present."""
    import random
    base = {"petal": 122.0, "guinea": 968.0, "ten": 1218.0, "mini": 12180.0}
    log.warning("Running SIMULATED feed (no real Dhan credentials).")
    while True:
        for inst, mid in base.items():
            jitter = random.uniform(-0.5, 0.5)
            bid = round(mid + jitter - 0.05, 2)
            ask = round(mid + jitter + 0.05, 2)
            quote_store.update(inst, bid=bid, ask=ask, ltp=round(mid + jitter, 2), ts=time.time())
        _eval_safely()
        await asyncio.sleep(1.0)


async def _run_with_retry() -> None:
    creds_ok = bool(settings.DHAN_CLIENT_ID and settings.DHAN_MPIN and settings.DHAN_TOTP_SECRET)
    if not creds_ok:
        await _simulated_feed()
        return

    backoff = 5
    while True:
        try:
            await _run_real_feed()
        except Exception as e:
            log.exception("Feed connection error: %s — retrying in %ds", e, backoff)
            dhan_auth.invalidate()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)
        else:
            backoff = 5


def start_feed_in_background(loop: asyncio.AbstractEventLoop) -> asyncio.Task:
    return loop.create_task(_run_with_retry())
