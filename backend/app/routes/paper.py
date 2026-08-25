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
from app.security import get_current_user_flex
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

    # Inputs may ride the URL as well as the body (client, 20-Aug):
    #   .../webhook/trade?key=...&type=buy&symbol=GOLDM&lot=1&timeframe=5m
    # The body wins wherever both name a field, because TradingView's URL is
    # static while its message carries live values like {{close}}. Still POST
    # only, never GET - WhatsApp and browsers prefetch GET links to build
    # previews, and a pasted link must not be able to fire a trade.
    qp = {k: v for k, v in request.query_params.items() if k != "key"}
    payload = {**qp, **payload}

    if not payload:
        return {"status": "rejected", "reason": "send fields in the JSON body or the URL"}
    return paper_trades.process_signal(payload, raw or json.dumps(qp))


@router.post("/paper/manual-signal")
def paper_manual_signal(body: dict, user: str = Depends(get_current_user_flex)):
    """The Manual Signal button: exactly the webhook's path - same flip rules,
    same account fan-out, same live price - fired from the page when
    TradingView drops a delivery. The UI confirms before calling; the Log rows
    carry "manual signal by <user>" so a hand-sent one never masquerades.
    Everything the webhook would refuse (market closed, system stopped, unknown
    symbol), this refuses identically."""
    return paper_trades.process_signal(body, json.dumps(body),
                                       via=f"manual signal by {user}")


@router.get("/paper/positions")
def paper_positions(_user: str = Depends(get_current_user_flex)):
    """Open dummy positions with the live LTP and running P/L, plus everything
    the page's controls need in the same poll: the dropdown lists and whether
    the system is running."""
    return {"positions": paper_trades.positions(),
            "symbols": paper_trades.known_symbols(),
            "timeframes": paper_trades.known_timeframes(),
            "accounts": paper_trades.accounts_list(),
            "state": paper_trades.state()}


@router.get("/paper/state")
def paper_state(_user: str = Depends(get_current_user_flex)):
    return paper_trades.state()


@router.post("/paper/state")
def paper_set_state(body: dict, user: str = Depends(get_current_user_flex)):
    """Start or stop the whole paper system.

    Stop books every open trade at that moment's price with exit_reason='stop',
    then refuses webhooks (still logged) until Start. Recorded with who did it.
    """
    on = bool(body.get("enabled"))
    return paper_trades.set_enabled(on, user)


@router.post("/paper/close/{trade_id}")
def paper_close_trade(trade_id: int, user: str = Depends(get_current_user_flex)):
    """Manually close one open trade at the current price (exit_reason='manual').
    The UI double-confirms before calling; a wrong id or an already-closed
    trade answers 409 rather than pretending."""
    res = paper_trades.close_trade(trade_id, user)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("reason", "cannot close"))
    return res


@router.get("/paper/accounts")
def paper_accounts(_user: str = Depends(get_current_user_flex)):
    """Accounts with their symbol lists. Angel fields come back masked."""
    return {"accounts": paper_trades.accounts_list()}


@router.post("/paper/accounts")
def paper_account_create(body: dict, _user: str = Depends(get_current_user_flex)):
    res = paper_trades.account_save(body)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("reason"))
    return res


@router.put("/paper/accounts/{account_id}")
def paper_account_update(account_id: int, body: dict,
                         _user: str = Depends(get_current_user_flex)):
    res = paper_trades.account_save(body, account_id)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("reason"))
    return res


@router.delete("/paper/accounts/{account_id}")
def paper_account_delete(account_id: int, _user: str = Depends(get_current_user_flex)):
    res = paper_trades.account_delete(account_id)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("reason"))
    return res


@router.post("/paper/symbols")
def paper_symbol_add(body: dict, _user: str = Depends(get_current_user_flex)):
    """Manage Symbols: add (resolves against the scrip master, typos refused)
    or rename when `old` is supplied."""
    if body.get("old"):
        res = paper_trades.symbol_rename(body["old"], body.get("symbol"))
    else:
        res = paper_trades.symbol_add(body.get("symbol"))
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("reason"))
    return res


@router.delete("/paper/symbols/{symbol}")
def paper_symbol_delete(symbol: str, _user: str = Depends(get_current_user_flex)):
    res = paper_trades.symbol_delete(symbol)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("reason"))
    return res


@router.get("/paper/trades")
def paper_trades_view(
    symbol: str | None = Query(None),
    side: str | None = Query(None, pattern="^(long|short)$"),
    timeframe: str | None = Query(None),
    account_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=5, le=100),
    _user: str = Depends(get_current_user_flex),
):
    """Closed trades, newest first, paginated, with the summary for the tiles."""
    return paper_trades.trades(symbol=symbol, side=side, timeframe=timeframe,
                               account_id=account_id, page=page, page_size=page_size)


@router.get("/paper/signals")
def paper_signals_view(
    symbol: str | None = Query(None),
    side: str | None = Query(None, pattern="^(buy|sell)$"),
    timeframe: str | None = Query(None),
    account: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=5, le=100),
    _user: str = Depends(get_current_user_flex),
):
    """Every webhook received, including the ignored and rejected ones - the
    reason column is the debugging surface for the client's alerts."""
    return paper_trades.signals(symbol=symbol, side=side, timeframe=timeframe,
                                account=account, page=page, page_size=page_size)
