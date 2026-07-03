"""Live premium-calc inputs — ISOLATED, in-memory, zero DB.

  XAU/USD  : Deriv public WebSocket  (real-time tick, free)
  USD/INR  : TwelveData spot         (polled every ~2 min, free — barely moves)
  MCX gold : read from the EXISTING Dhan quote_store (no new subscription)

Nothing here touches the Dhan feed, its subscriptions, or the database. Two tiny
daemon threads hold the latest values in memory; the route just reads them. If a
source drops it reconnects on its own — it can never affect the live feed.
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
    "xauusd": None, "xauusd_ts": 0.0, "deriv_connected": False,
    "usdinr": None, "usdinr_ts": 0.0,
}
_stop = threading.Event()

_DERIV_WSS = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"
_TD_URL = "https://api.twelvedata.com/price?symbol=USD/INR&apikey={key}"


# ── XAU/USD via Deriv WebSocket (real-time) ──────────────────────────────
async def _deriv_loop() -> None:
    import websockets  # lazy — a missing lib disables only this thread
    url = _DERIV_WSS.format(app_id=settings.DERIV_APP_ID or "1089")
    while not _stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                await ws.send(json.dumps({"ticks": "frxXAUUSD", "subscribe": 1}))
                log.info("Premium: Deriv WS connected (XAU/USD)")
                async for raw in ws:
                    if _stop.is_set():
                        break
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("msg_type") == "tick" and m.get("tick"):
                        q = m["tick"].get("quote")
                        if q:
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


# ── MCX gold from the existing quote_store (no new subscription) ─────────
def _mcx_gold() -> dict | None:
    try:
        from app.services import price_service
        from app.services.market_data import quote_store
        contracts = price_service._state.get("contracts", {}).get("gold", [])
        if not contracts:
            return None
        c = contracts[0]  # near month
        q = quote_store.get(c["security_id"])
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
        "xauusd_source": "Deriv (live)",
        "deriv_connected": _state["deriv_connected"],
        "usdinr": _state["usdinr"],
        "usdinr_age": round(now - _state["usdinr_ts"], 1) if _state["usdinr_ts"] else None,
        "usdinr_source": "TwelveData spot",
        "mcx_gold": _mcx_gold(),
        "server_time": now,
    }


def start_in_background() -> None:
    if not settings.PREMIUM_FEED_ENABLED:
        log.info("Premium feed disabled")
        return
    threading.Thread(target=_deriv_thread, daemon=True, name="premium-deriv").start()
    threading.Thread(target=_usdinr_thread, daemon=True, name="premium-usdinr").start()
    log.info("Premium feed started (Deriv XAU/USD + TwelveData USD/INR, in-memory)")
