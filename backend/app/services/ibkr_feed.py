"""International COMEX/NYMEX feed via the local IB Gateway — ISOLATED, in-memory.

Streams (real-time, subscription = COMEX L1 + NYMEX L1, USD 3.10/mo):
  XAUUSD / XAGUSD  spot metals (CMDTY on SMART — free with the account)
  GC  COMEX gold future
  SI  COMEX silver future
  CL  NYMEX crude future  + its OPTION CHAIN (ATM window, calls + puts)
  BZ  NYMEX Brent future

Design constraints (client's rules):
  * NOTHING touches the Dhan feed — separate thread, separate TCP connection to
    IB Gateway on localhost, its own clientId. Dhan cannot be affected.
  * ZERO database writes. All state is a small in-memory dict the route reads.
  * Only ~25 market-data lines are subscribed (3 futures + an ATM window of the
    option chain), never all 185 strikes — IBKR caps concurrent lines and each
    line is upstream bandwidth we don't need.
  * The ATM window re-centres only when the underlying leaves it (checked once a
    minute), so a normal day does zero re-subscribing.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from app.config import settings

log = logging.getLogger("ibkr_feed")

# How many strikes either side of the money to stream (each = 2 lines, C+P).
_WINDOW = 5

_state: dict = {
    "xau": None, "xau_ts": 0.0,          # spot metals (CMDTY on SMART)
    "xag": None, "xag_ts": 0.0,
    "bz": None, "bz_ts": 0.0, "bz_symbol": None, "bz_expiry": None,
    "gc": None, "gc_ts": 0.0, "gc_symbol": None, "gc_expiry": None,
    "si": None, "si_ts": 0.0, "si_symbol": None, "si_expiry": None,
    "cl": None, "cl_ts": 0.0, "cl_symbol": None, "cl_expiry": None,
    "cl_options": [],            # [{strike, call:{bid,ask}, put:{bid,ask}}]
    "cl_options_expiry": None,
    "cl_options_ts": 0.0,
    "connected": False,
    "delayed": False,            # True if the gateway fell back to delayed data
    "stale": False,              # no price movement for a while (see the watchdog)
    "last_tick": 0.0,            # epoch of the last price CHANGE on any instrument
}

# If not a single instrument changes price for this long we assume the
# subscription died behind an open socket (IBKR error 1100 leaves ib.isConnected()
# True) and force a full reconnect. COMEX/NYMEX trade ~23h a day, so real silence
# this long only happens in the daily maintenance break, where a reconnect is free.
_SILENCE_LIMIT = 600
_stop = threading.Event()


def _px(t) -> dict:
    """bid/ask/last from a ticker, NaN-safe."""
    def v(x):
        return float(x) if (x == x and x is not None and x > 0) else None
    return {"bid": v(t.bid), "ask": v(t.ask), "last": v(t.last)}


async def _loop() -> None:
    from ib_async import IB, Contract, ContFuture, FuturesOption  # lazy — missing lib disables only this thread

    while not _stop.is_set():
        ib = IB()
        try:
            await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT,
                                  clientId=settings.IBKR_FEED_CLIENT_ID, timeout=20)
            ib.reqMarketDataType(1)  # real-time; gateway falls back to delayed on its own

            futs = {}
            for sym, exch, key in (("GC", "COMEX", "gc"), ("SI", "COMEX", "si"),
                                   ("CL", "NYMEX", "cl"), ("BZ", "NYMEX", "bz")):
                c = ContFuture(sym, exch)
                await ib.qualifyContractsAsync(c)
                futs[key] = (c, ib.reqMktData(c, "", False, False))
                _state[key + "_symbol"] = c.localSymbol
                _state[key + "_expiry"] = c.lastTradeDateOrContractMonth

            # Spot metals — same feed that used to come from Finnhub.
            spots = {}
            for sym, key in (("XAUUSD", "xau"), ("XAGUSD", "xag")):
                c = Contract(secType="CMDTY", symbol=sym, exchange="SMART", currency="USD")
                await ib.qualifyContractsAsync(c)
                spots[key] = (c, ib.reqMktData(c, "", False, False))

            # Option chain metadata for CL (one call, cached for the session).
            cl_contract = futs["cl"][0]
            chains = await ib.reqSecDefOptParamsAsync("CL", "NYMEX", "FUT", cl_contract.conId)
            chain = next((c for c in chains if c.exchange == "NYMEX"), chains[0] if chains else None)
            all_strikes = sorted(chain.strikes) if chain else []
            expiry = sorted(chain.expirations)[0] if chain else None
            _state["cl_options_expiry"] = expiry

            opt_tickers: dict = {}   # strike -> {"C": ticker, "P": ticker}
            window: list[float] = []

            async def resubscribe(centre: float) -> None:
                """Stream only the ATM window; drop whatever left it."""
                nonlocal window
                if not all_strikes or not expiry:
                    return
                near = sorted(all_strikes, key=lambda s: abs(s - centre))[: _WINDOW * 2 + 1]
                new_window = sorted(near)
                if new_window == window:
                    return
                for strike in list(opt_tickers):
                    if strike not in new_window:
                        for right in ("C", "P"):
                            try:
                                ib.cancelMktData(opt_tickers[strike][right].contract)
                            except Exception:  # noqa: BLE001
                                pass
                        opt_tickers.pop(strike, None)
                for strike in new_window:
                    if strike in opt_tickers:
                        continue
                    pair = {}
                    for right in ("C", "P"):
                        o = FuturesOption("CL", expiry, strike, right, "NYMEX")
                        try:
                            await ib.qualifyContractsAsync(o)
                            pair[right] = ib.reqMktData(o, "", False, False)
                        except Exception:  # noqa: BLE001 — a dead strike must not kill the feed
                            pass
                    if len(pair) == 2:
                        opt_tickers[strike] = pair
                window = new_window
                log.info("IBKR: CL option window %s..%s (%d strikes)",
                         window[0], window[-1], len(window))

            log.info("IBKR feed connected (GC/SI/CL + CL option chain)")
            last_window_check = 0.0
            stale_since = time.time()

            while not _stop.is_set() and ib.isConnected():
                await asyncio.sleep(1)
                now = time.time()

                moved = False
                for key, (_c, t) in list(futs.items()) + list(spots.items()):
                    p = _px(t)
                    if p["bid"] or p["last"]:
                        if p != _state.get(key):
                            moved = True
                        _state[key] = p
                        _state[key + "_ts"] = now
                        _state["connected"] = True
                    _state["delayed"] = t.marketDataType in (3, 4)

                # Zombie guard. IBKR error 1100 ("connectivity lost") does NOT drop
                # the local socket, so isConnected() keeps saying True while every
                # price quietly freezes - exactly how the Deriv feed went unnoticed
                # for 4.8 days. Any price change resets the clock.
                if moved:
                    stale_since = now
                    _state["last_tick"] = now
                    _state["stale"] = False
                elif now - stale_since > _SILENCE_LIMIT:
                    _state["stale"] = True
                    raise RuntimeError(
                        f"no IBKR price change for {int(now - stale_since)}s - forcing reconnect")

                # Re-centre the option window at most once a minute, and only if
                # the underlying has actually walked out of it.
                cl_mid = None
                clp = _state.get("cl") or {}
                if clp.get("bid") and clp.get("ask"):
                    cl_mid = (clp["bid"] + clp["ask"]) / 2
                if cl_mid and now - last_window_check > 60:
                    last_window_check = now
                    if not window or cl_mid < window[0] or cl_mid > window[-1]:
                        await resubscribe(cl_mid)

                rows = []
                for strike in sorted(opt_tickers):
                    c_t, p_t = opt_tickers[strike]["C"], opt_tickers[strike]["P"]
                    rows.append({"strike": strike, "call": _px(c_t), "put": _px(p_t)})
                if rows:
                    _state["cl_options"] = rows
                    _state["cl_options_ts"] = now
        except Exception as e:  # noqa: BLE001
            _state["connected"] = False
            log.warning("IBKR feed error: %s (reconnect in 20s)", e)
            if _stop.wait(20):
                break
        finally:
            try:
                ib.disconnect()
            except Exception:  # noqa: BLE001
                pass


def _thread() -> None:
    try:
        asyncio.run(_loop())
    except Exception as e:  # noqa: BLE001
        log.error("IBKR feed thread stopped: %s", e)


def get_data() -> dict:
    now = time.time()

    def age(k):
        ts = _state.get(k + "_ts") or 0
        return round(now - ts, 1) if ts else None

    last = _state.get("last_tick") or 0
    return {
        "connected": _state["connected"],
        "delayed": _state["delayed"],
        "stale": bool(_state.get("stale")),
        "last_tick_age": round(now - last, 1) if last else None,
        "gold_future": {**(_state["gc"] or {}), "age": age("gc"),
                        "symbol": _state["gc_symbol"], "expiry": _state["gc_expiry"]},
        "silver_future": {**(_state["si"] or {}), "age": age("si"),
                          "symbol": _state["si_symbol"], "expiry": _state["si_expiry"]},
        "crude_future": {**(_state["cl"] or {}), "age": age("cl"),
                         "symbol": _state["cl_symbol"], "expiry": _state["cl_expiry"]},
        "brent_future": {**(_state["bz"] or {}), "age": age("bz"),
                         "symbol": _state["bz_symbol"], "expiry": _state["bz_expiry"]},
        "gold_spot": {**(_state["xau"] or {}), "age": age("xau")},
        "silver_spot": {**(_state["xag"] or {}), "age": age("xag")},
        "crude_options": {
            "expiry": _state["cl_options_expiry"],
            "age": age("cl_options"),
            "rows": _state["cl_options"],
        },
        "server_time": now,
    }


def start_in_background() -> None:
    if not settings.IBKR_FEED_ENABLED:
        log.info("IBKR feed disabled")
        return
    threading.Thread(target=_thread, daemon=True, name="ibkr-feed").start()
    log.info("IBKR feed starting (COMEX GC/SI + NYMEX CL + option chain, in-memory)")
