"""Webhook in, paper trades out - the Auto Trades page's whole API.

The webhook is the one route in the app a third party calls (TradingView), so
it authenticates with its own secret key instead of a login token: TradingView
cannot set headers, so the key rides the query string or the JSON body. Wrong
key answers 403 and writes nothing.

Everything else here sits behind the normal dashboard login, same as every
other page.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import settings
from app.security import get_current_user
from app.services import paper_trades

log = logging.getLogger("paper_routes")

router = APIRouter(prefix="/api", tags=["paper-trades"])


@router.post("/v1/webhook/trade")
async def webhook_trade(request: Request, key: str | None = Query(None)):
    """TradingView alert in, instant answer out.

    Body: {"type":"buy","lot":1,"symbol":"GOLDM","timeframe":"5m","temp_price":73450}
    The trade opens or flips at the exchange LTP of this very moment, read from
    memory - the temp_price is stored for comparison and prices nothing.
    """
    body_bytes = await request.body()
    raw = body_bytes.decode("utf-8", errors="ignore") if body_bytes else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        # TradingView can be configured to send form-ish text; refuse politely
        # but LOG it, so a mis-configured alert is visible in the Log tab.
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    supplied = key or payload.get("key") or payload.get("secret")
    if not settings.WEBHOOK_TRADE_KEY or supplied != settings.WEBHOOK_TRADE_KEY:
        # Deliberately NOT logged to the signal table: anyone on the internet
        # can hit a public URL, and junk must not fill the client's Log tab.
        raise HTTPException(status_code=403, detail="bad key")

    if not payload:
        return {"status": "rejected", "reason": "body must be JSON"}
    return paper_trades.process_signal(payload, raw)


@router.get("/paper/positions")
def paper_positions(_user: str = Depends(get_current_user)):
    """Open dummy positions with the live LTP and running P/L."""
    return {"positions": paper_trades.positions(),
            "symbols": paper_trades.known_symbols()}


@router.get("/paper/trades")
def paper_trades_view(
    symbol: str | None = Query(None),
    side: str | None = Query(None, pattern="^(long|short)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=5, le=100),
    _user: str = Depends(get_current_user),
):
    """Closed trades, newest first, paginated, with the summary for the tiles."""
    return paper_trades.trades(symbol=symbol, side=side, page=page, page_size=page_size)


@router.get("/paper/signals")
def paper_signals_view(
    symbol: str | None = Query(None),
    side: str | None = Query(None, pattern="^(buy|sell)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=5, le=100),
    _user: str = Depends(get_current_user),
):
    """Every webhook received, including the ignored and rejected ones - the
    reason column is the debugging surface for the client's alerts."""
    return paper_trades.signals(symbol=symbol, side=side, page=page, page_size=page_size)
