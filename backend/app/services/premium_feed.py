"""Live premium-calc inputs — ISOLATED, in-memory, zero DB.

  XAU/USD + XAG/USD : Finnhub free WebSocket (OANDA-priced, real-time) —
                      Deriv delisted its metals 22-Jul; IBKR's API licence
                      forbids displaying its data outside IBKR trading
  USD/INR           : TwelveData spot         (polled every ~2 min, free — barely moves)
  WTI + Brent crude : Finnhub free WebSocket  (OANDA-priced, real-time — for the
                      international CRUDE($) scrips on the app board)
  MCX gold + silver : read from the EXISTING Dhan quote_store (no new subscription)

Nothing here touches the Dhan feed, its subscriptions, or the database. Three tiny
daemon threads hold the latest values in memory; the route just reads them. If a
source drops it reconnects on its own — it can never affect the live feed.

Finnhub note: ONE WebSocket connection per API key (verified — a second
connection kicks the first). Production key must be used ONLY by this server;
the reconnect loop below recovers automatically if it ever gets kicked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import requests

from app.config import settings

log = logging.getLogger("premium_feed")

_state = {
    "xauusd": None, "xauusd_ts": 0.0,
    "xagusd": None, "xagusd_ts": 0.0,
    "deriv_connected": False,
    "ibkr_connected": False,
    "usdinr": None, "usdinr_ts": 0.0,
    "wti": None, "wti_ts": 0.0,
    "brent": None, "brent_ts": 0.0,
    "finnhub_connected": False,
}
_stop = threading.Event()

_DERIV_WSS = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"
_TD_URL = "https://api.twelvedata.com/price?symbol=USD/INR&apikey={key}"
_FINNHUB_WSS = "wss://ws.finnhub.io?token={key}"
_FINNHUB_SYMS = {
    "OANDA:WTICO_USD": "wti",
    "OANDA:BCO_USD": "brent",
    # Spot metals moved here 27-Jul: Deriv delisted them, and IBKR's API data
    # is contractually limited to trading on the IBKR account itself (no
    # display/redistribution), so it cannot feed this dashboard or the app.
    "OANDA:XAU_USD": "xauusd",
    "OANDA:XAG_USD": "xagusd",
}


# ── XAU/USD + XAG/USD via IB Gateway (real-time, free) ───────────────────
# Deriv delisted frxXAUUSD/frxXAGUSD (froze 22-Jul, caught 27-Jul), so spot
# metals now come from the paper IB Gateway running on this server: secType
# CMDTY on SMART, marketDataType 1 = real-time, no subscription, no funding.
async def _ibkr_loop() -> None:
    from ib_async import IB, Contract  # lazy — a missing lib disables only this thread

    while not _stop.is_set():
        ib = IB()
        try:
            await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT,
                                  clientId=settings.IBKR_CLIENT_ID, timeout=20)
            ib.reqMarketDataType(1)  # real-time
            tickers = {}
            for sym, key in (("XAUUSD", "xauusd"), ("XAGUSD", "xagusd")):
                c = Contract(secType="CMDTY", symbol=sym, exchange="SMART", currency="USD")
                await ib.qualifyContractsAsync(c)
                tickers[key] = ib.reqMktData(c, "", False, False)
            log.info("Premium: IB Gateway connected (XAU/USD + XAG/USD real-time)")

            stale_since = time.time()
            while not _stop.is_set() and ib.isConnected():
                await asyncio.sleep(1)
                fresh = False
                for key, t in tickers.items():
                    # mid of bid/ask; spot metals have no "last" on this feed
                    bid, ask = t.bid, t.ask
                    px = None
                    if bid == bid and ask == ask and bid and ask:
                        px = (float(bid) + float(ask)) / 2
                    elif t.last == t.last and t.last:
                        px = float(t.last)
                    if px and px != _state.get(key):
                        _state[key] = round(px, 4)
                        _state[key + "_ts"] = time.time()
                        fresh = True
                if fresh:
                    stale_since = time.time()
                    _state["ibkr_connected"] = True
                elif time.time() - stale_since > 600:
                    # Same zombie guard as the other feeds: metals trade
                    # Sun ~22:00 – Fri ~21:00 UTC, so 10 min of silence during
                    # the week means the subscription died → reconnect.
                    raise RuntimeError("no IBKR spot ticks for 10 min — forcing reconnect")
        except Exception as e:  # noqa: BLE001
            _state["ibkr_connected"] = False
            log.warning("Premium: IB Gateway error: %s (reconnect in 15s)", e)
            if _stop.wait(15):
                break
        finally:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass


def _ibkr_thread() -> None:
    try:
        asyncio.run(_ibkr_loop())
    except Exception as e:  # noqa: BLE001
        log.error("Premium: IBKR thread stopped: %s", e)


# ── XAU/USD via Deriv WebSocket — RETIRED 27-Jul (symbols delisted) ───────
async def _deriv_loop() -> None:
    import websockets  # lazy — a missing lib disables only this thread
    url = _DERIV_WSS.format(app_id=settings.DERIV_APP_ID or "1089")
    while not _stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                await ws.send(json.dumps({"ticks": "frxXAUUSD", "subscribe": 1}))
                await ws.send(json.dumps({"ticks": "frxXAGUSD", "subscribe": 1}))
                log.info("Premium: Deriv WS connected (XAU/USD + XAG/USD)")
                while not _stop.is_set():
                    # Zombie guard: the socket can stay "open" (pings answered)
                    # while the tick SUBSCRIPTION is silently dropped — caught
                    # 27-Jul after 4.8 days of frozen XAU/XAG. Metals trade
                    # Sun~22:00 IST → Sat ~02:00 IST, so 10 min of silence in
                    # market hours = dead; a weekend reconnect every 10 min is
                    # harmless (Deriv is free and reconnect is cheap).
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=600)
                    except asyncio.TimeoutError:
                        raise RuntimeError("no Deriv ticks for 10 min — forcing reconnect")
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("msg_type") == "tick" and m.get("tick"):
                        t = m["tick"]
                        q = t.get("quote")
                        if q is not None:
                            if t.get("symbol") == "frxXAGUSD":
                                _state["xagusd"] = float(q)
                                _state["xagusd_ts"] = time.time()
                            else:  # frxXAUUSD
                                _state["xauusd"] = float(q)
                                _state["xauusd_ts"] = time.time()
                            _state["deriv_connected"] = True
        except Exception as e:  # noqa: BLE001
            _state["deriv_connected"] = False
            log.warning("Premium: Deriv WS error: %s (reconnect in 5s)", e)
            if _stop.wait(5):
                break


def _deriv_thread() -> None:
    try:
        asyncio.run(_deriv_loop())
    except Exception as e:  # noqa: BLE001
        log.error("Premium: Deriv thread stopped: %s", e)


# ── WTI + Brent via Finnhub free WebSocket (real-time) ───────────────────
async def _finnhub_loop() -> None:
    import websockets  # lazy — a missing lib disables only this thread
    url = _FINNHUB_WSS.format(key=settings.FINNHUB_API_KEY)
    while not _stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=15, ping_timeout=15, close_timeout=5) as ws:
                for sym in _FINNHUB_SYMS:
                    await ws.send(json.dumps({"type": "subscribe", "symbol": sym}))
                log.info("Premium: Finnhub WS connected (WTI + Brent)")
                while not _stop.is_set():
                    # Zombie guard: a kicked/half-dead socket can stay "open"
                    # while delivering nothing (seen 21-Jul: 18h stale). Crude
                    # trades ~24/5, so 5 min of silence = dead → force reconnect.
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=300)
                    except asyncio.TimeoutError:
                        raise RuntimeError("no Finnhub data for 5 min — forcing reconnect")
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("type") == "trade":
                        for t in m.get("data", []):
                            key = _FINNHUB_SYMS.get(t.get("s"))
                            p = t.get("p")
                            if key and p is not None:
                                _state[key] = float(p)
                                _state[key + "_ts"] = time.time()
                                _state["finnhub_connected"] = True
        except Exception as e:  # noqa: BLE001
            _state["finnhub_connected"] = False
            log.warning("Premium: Finnhub WS error: %s (reconnect in 5s)", e)
            if _stop.wait(5):
                break


def _finnhub_thread() -> None:
    try:
        asyncio.run(_finnhub_loop())
    except Exception as e:  # noqa: BLE001
        log.error("Premium: Finnhub thread stopped: %s", e)


# ── USD/INR via TwelveData spot (polled ~2 min) ──────────────────────────
def _usdinr_thread() -> None:
    key = settings.TWELVEDATA_API_KEY
    if not key:
        log.warning("Premium: no TWELVEDATA_API_KEY — USD/INR disabled")
        return
    while not _stop.is_set():
        try:
            p = requests.get(_TD_URL.format(key=key), timeout=15).json().get("price")
            if p:
                _state["usdinr"] = float(p)
                _state["usdinr_ts"] = time.time()
        except Exception as e:  # noqa: BLE001
            log.warning("Premium: USD/INR poll error: %s", e)
        if _stop.wait(120):  # ~2 min → ~720/day, well under the 800/day free cap
            break


# ── MCX metal from the existing quote_store (no new subscription) ────────
def _mcx(short: str) -> dict | None:
    """Near-month MCX future for a price_service instrument key ('gold' / 'silver')."""
    try:
        from app.services import price_service
        from app.services.market_data import quote_store
        contracts = price_service._state.get("contracts", {}).get(short, [])
        if not contracts:
            return None
        c = contracts[0]  # near month
        q = quote_store.get(c["security_id"])
        if q is None:
            return None
        return {
            "ltp": (q.ltp or None), "bid": (q.bid or None), "ask": (q.ask or None),
            "expiry": c["expiry"].strftime("%d %b %Y"),
            "symbol": c.get("trading_symbol"),
        }
    except Exception:  # noqa: BLE001
        return None


def get_inputs() -> dict:
    now = time.time()
    return {
        "xauusd": _state["xauusd"],
        "xauusd_age": round(now - _state["xauusd_ts"], 1) if _state["xauusd_ts"] else None,
        "xauusd_source": "Finnhub spot (live)",
        "xagusd": _state["xagusd"],
        "xagusd_age": round(now - _state["xagusd_ts"], 1) if _state["xagusd_ts"] else None,
        "xagusd_source": "Finnhub spot (live)",
        "deriv_connected": _state["finnhub_connected"],  # legacy key: UI 'spot feed connected' flag
        "ibkr_connected": _state["ibkr_connected"],
        "usdinr": _state["usdinr"],
        "usdinr_age": round(now - _state["usdinr_ts"], 1) if _state["usdinr_ts"] else None,
        "usdinr_source": "TwelveData spot",
        "wti": _state["wti"],
        "wti_age": round(now - _state["wti_ts"], 1) if _state["wti_ts"] else None,
        "brent": _state["brent"],
        "brent_age": round(now - _state["brent_ts"], 1) if _state["brent_ts"] else None,
        "finnhub_connected": _state["finnhub_connected"],
        "mcx_gold": _mcx("gold"),
        "mcx_silver": _mcx("silver"),
        "server_time": now,
    }


def start_in_background() -> None:
    if not settings.PREMIUM_FEED_ENABLED:
        log.info("Premium feed disabled")
        return
    # NOTE: no IBKR thread — the signed Market Data API Supplement limits API
    # data to trading on the IBKR account only (no electronic display, no
    # ingestion into third-party-accessible systems). Metals come from Finnhub.
    threading.Thread(target=_usdinr_thread, daemon=True, name="premium-usdinr").start()
    if settings.FINNHUB_API_KEY:
        threading.Thread(target=_finnhub_thread, daemon=True, name="premium-finnhub").start()
    log.info("Premium feed started (IBKR XAU/XAG + TwelveData USD/INR + Finnhub WTI/Brent, in-memory)")
