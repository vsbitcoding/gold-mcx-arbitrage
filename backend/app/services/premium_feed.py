"""Live premium-calc inputs — ISOLATED, in-memory, zero DB.

  XAU/USD + XAG/USD : IBKR real-time spot, read from services/ibkr_feed (the
                      client's paid COMEX/NYMEX account — 30-Jul, his decision;
                      Finnhub retired, Deriv delisted its metals 22-Jul)
  USD/INR           : TwelveData spot         (polled every ~2 min, free — barely moves)
  WTI + Brent crude : IBKR CL / BZ futures, also via ibkr_feed (for the
                      international CRUDE($) scrips on the app board)
  MCX gold + silver : read from the EXISTING Dhan quote_store (no new subscription)

Nothing here touches the Dhan feed, its subscriptions, or the database. Three tiny
daemon threads hold the latest values in memory; the route just reads them. If a
source drops it reconnects on its own — it can never affect the live feed.

Rollback: the Finnhub WebSocket code below is intact but dormant. Set
FINNHUB_ENABLED=true and IBKR_SPOTS_ENABLED=false in .env to switch back in one
restart. (Finnhub allows ONE WebSocket connection per key — a second kicks the
first — so its key must be used only by this server.)
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


# ── which USD/INR the premium maths gets ─────────────────────────────────
# TwelveData's free tier answers every two minutes, and the Premium tab
# multiplies a live gold price by whatever it last said - a rate 107 seconds
# old was quietly putting tens of rupees per ten grams into every GST card.
# Angel carries USDINR as an NSE currency future with a real two-way market,
# already ticking every three seconds inside the NSE-vs-MCX feed, so it costs
# no extra request. TwelveData stays as the fallback for when Angel is down or
# between sessions.
#
# The two are not the same instrument: a near-month future carries a little
# cost of carry over spot, about 0.03% (95.4275 against 95.40105 on 14-Aug,
# ~45 rupees per ten grams of gold). Freshness is worth more than that gap.
_FX_FRESH = 90


def _usdinr() -> tuple[float | None, float | None, str]:
    """Rate, age in seconds, and where it came from."""
    try:
        from app.services import angel_feed
        d = angel_feed.get_data()
        u = d.get("usdinr") or {}
        age = d.get("age")
        rate = u.get("mid") or u.get("ltp")
        if rate and age is not None and age <= _FX_FRESH:
            return round(float(rate), 4), age, "NSE USD/INR future (Angel, live)"
    except Exception as e:  # noqa: BLE001 - the fallback below must always work
        log.debug("Premium: Angel USD/INR unavailable (%s)", e)
    ts = _state["usdinr_ts"]
    return (_state["usdinr"],
            round(time.time() - ts, 1) if ts else None,
            "TwelveData spot (~2 min)")


# ── MCX metal from the existing quote_store (no new subscription) ────────
def _mcx(short: str) -> dict | None:
    """Near-month MCX future for a price_service instrument key ('gold' / 'silver')."""
    try:
        from app.services import price_service
        from app.services.market_data import clean_sides, quote_store
        contracts = price_service._state.get("contracts", {}).get(short, [])
        if not contracts:
            return None
        c = contracts[0]  # near month
        q = quote_store.get(c["security_id"])
        if q is None:
            return None
        bid, ask = clean_sides(q)
        return {
            "ltp": (q.ltp or None), "bid": bid, "ask": ask,
            "expiry": c["expiry"].strftime("%d %b %Y"),
            "symbol": c.get("trading_symbol"),
        }
    except Exception:  # noqa: BLE001
        return None


def _ibkr_spots() -> dict:
    """Spot metals + crude/Brent from the IBKR feed (mid of bid/ask)."""
    try:
        from app.services import ibkr_feed
        d = ibkr_feed.get_data()
    except Exception:  # noqa: BLE001
        return {}

    def mid(o):
        if not o:
            return None, None
        b, a = o.get("bid"), o.get("ask")
        if b and a:
            return round((b + a) / 2, 4), o.get("age")
        v = b or a or o.get("last")
        return (round(v, 4) if v else None), o.get("age")

    xau, xau_age = mid(d.get("gold_spot"))
    xag, xag_age = mid(d.get("silver_spot"))
    wti, wti_age = mid(d.get("crude_future"))
    brent, brent_age = mid(d.get("brent_future"))
    return {"xau": xau, "xau_age": xau_age, "xag": xag, "xag_age": xag_age,
            "wti": wti, "wti_age": wti_age, "brent": brent, "brent_age": brent_age,
            "connected": d.get("connected")}


def get_inputs() -> dict:
    now = time.time()
    fx, fx_age, fx_source = _usdinr()
    ib = _ibkr_spots() if settings.IBKR_SPOTS_ENABLED else {}
    if ib.get("xau"):
        return {
            "xauusd": ib["xau"], "xauusd_age": ib["xau_age"], "xauusd_source": "IBKR spot (live)",
            "xagusd": ib["xag"], "xagusd_age": ib["xag_age"], "xagusd_source": "IBKR spot (live)",
            "deriv_connected": bool(ib.get("connected")),
            "ibkr_connected": bool(ib.get("connected")),
            "usdinr": fx, "usdinr_age": fx_age, "usdinr_source": fx_source,
            "wti": ib["wti"], "wti_age": ib["wti_age"],
            "brent": ib["brent"], "brent_age": ib["brent_age"],
            "finnhub_connected": bool(ib.get("connected")),
            "mcx_gold": _mcx("gold"),
            "mcx_silver": _mcx("silver"),
            "server_time": now,
        }
    return {
        "xauusd": _state["xauusd"],
        "xauusd_age": round(now - _state["xauusd_ts"], 1) if _state["xauusd_ts"] else None,
        "xauusd_source": "Finnhub spot (live)",
        "xagusd": _state["xagusd"],
        "xagusd_age": round(now - _state["xagusd_ts"], 1) if _state["xagusd_ts"] else None,
        "xagusd_source": "Finnhub spot (live)",
        "deriv_connected": _state["finnhub_connected"],  # legacy key: UI 'spot feed connected' flag
        "ibkr_connected": _state["ibkr_connected"],
        "usdinr": fx, "usdinr_age": fx_age, "usdinr_source": fx_source,
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
    # No IBKR thread here — ibkr_feed owns the single IB connection (golden
    # rule: one connection per market source) and get_inputs() reads its dict.
    threading.Thread(target=_usdinr_thread, daemon=True, name="premium-usdinr").start()
    if settings.FINNHUB_ENABLED and settings.FINNHUB_API_KEY:
        threading.Thread(target=_finnhub_thread, daemon=True, name="premium-finnhub").start()
    log.info("Premium feed started (IBKR spots+crude via ibkr_feed, TwelveData USD/INR, Finnhub=%s)", settings.FINNHUB_ENABLED)
