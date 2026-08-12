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
import json
import logging
import threading
import time
from pathlib import Path

from app.config import settings

log = logging.getLogger("ibkr_feed")

# How many strikes either side of the money to stream (each = 2 lines, C+P).
_WINDOW = 5
# The Crude Oil comparison tab wants 21 strikes on the MONTHLY contract with
# greeks - 10 calls above the money, the ATM row, 10 puts below (the client's
# own layout, same as his Commodity Options tab). Only one side is streamed per
# strike, so that is 22 lines rather than 42.
_IV_WINDOW = 10
# Commodities that carry an IV chain, and the future each one is priced off.
# The monthly option class is chosen as the one listing the most strikes: for
# crude that is LO (451 vs ~185 on the weeklies), for gas LNE (236 vs 61). The
# weeklies expire in days, so their IV is time-decay noise next to MCX.
_IV_SYMS = (("CL", "NYMEX", "cl"), ("NG", "NYMEX", "ng"))

_state: dict = {
    "xau": None, "xau_ts": 0.0,          # spot metals (CMDTY on SMART)
    "xag": None, "xag_ts": 0.0,
    "bz": None, "bz_ts": 0.0, "bz_symbol": None, "bz_expiry": None,
    "gc": None, "gc_ts": 0.0, "gc_symbol": None, "gc_expiry": None,
    "si": None, "si_ts": 0.0, "si_symbol": None, "si_expiry": None,
    "cl": None, "cl_ts": 0.0, "cl_symbol": None, "cl_expiry": None,
    "ng": None, "ng_ts": 0.0, "ng_symbol": None, "ng_expiry": None,
    "cl_options": [],            # [{strike, call:{bid,ask}, put:{bid,ask}}]
    "cl_options_expiry": None,
    "cl_options_ts": 0.0,
    # monthly chains with implied volatility, for the MCX-vs-US comparison
    "cl_iv_rows": [], "cl_iv_expiry": None, "cl_iv_class": None, "cl_iv_ts": 0.0,
    "ng_iv_rows": [], "ng_iv_expiry": None, "ng_iv_class": None, "ng_iv_ts": 0.0,
    "connected": False,
    "delayed": False,            # True if the gateway fell back to delayed data
    "stale": False,              # no price movement for a while (see the watchdog)
    "last_tick": 0.0,            # epoch of the last price CHANGE on any instrument
}

# If not a single instrument changes price for this long we assume the
# subscription died behind an open socket (IBKR error 1100 leaves ib.isConnected()
# True) and force a full reconnect.
#
# A closed market looks identical to a dead subscription from here, and on the
# night of 02-Aug that cost us: the market was shut, the watchdog fired every 11
# minutes for an hour. So the limit doubles after each silent reconnect (up to an
# hour) and resets the moment prices flow again - a genuinely dead feed is still
# caught within ten minutes, a weekend costs two or three reconnects.
_SILENCE_LIMIT = 600
_SILENCE_MAX = 3600
_silence_limit = _SILENCE_LIMIT
_stop = threading.Event()


def _px(t) -> dict:
    """bid/ask/last from a ticker, NaN-safe."""
    def v(x):
        return float(x) if (x == x and x is not None and x > 0) else None
    return {"bid": v(t.bid), "ask": v(t.ask), "last": v(t.last)}


def _leg(t) -> dict:
    """One option leg with greeks. IV is converted to PERCENT so it lines up
    with Dhan, which reports 64.89 where IBKR reports 0.6489."""
    def v(x):
        return float(x) if (x == x and x is not None and x > 0) else None
    def g(attr):
        for src in (t.modelGreeks, t.lastGreeks, t.bidGreeks, t.askGreeks):
            if src is not None:
                val = getattr(src, attr, None)
                if val is not None and val == val:
                    return float(val)
        return None
    bid, ask = v(t.bid), v(t.ask)
    iv = g("impliedVol")
    return {
        "bid": bid, "ask": ask, "last": v(t.last),
        "mid": round((bid + ask) / 2, 4) if (bid and ask) else (bid or ask),
        "iv": round(iv * 100, 2) if iv is not None else None,
        "delta": g("delta"), "theta": g("theta"),
        "gamma": g("gamma"), "vega": g("vega"),
    }


# sym -> (contract, volume, picked_at). Survives reconnects inside the process
# so a 3 a.m. reconnect cannot silently downgrade a good pick.
_front_cache: dict[str, tuple] = {}
_FRONT_TTL = 12 * 3600
# The chosen contract is written to disk as well. A restart during a data-farm
# outage cannot probe anything, and falling back to ContFuture then puts gold on
# the October contract - the exact $31 error the client reported on 03-Aug.
_FRONT_FILE = Path(__file__).resolve().parents[2] / ".ibkr_front_cache.json"


def _save_front_disk() -> None:
    try:
        _FRONT_FILE.write_text(json.dumps({
            sym: {"conId": c.conId, "localSymbol": c.localSymbol,
                  "expiry": c.lastTradeDateOrContractMonth, "vol": vol, "ts": ts}
            for sym, (c, vol, ts) in _front_cache.items()}))
    except Exception as e:  # noqa: BLE001
        log.debug("front-month cache not saved: %s", e)


async def _load_front_disk(ib) -> None:
    """Re-qualify yesterday's picks by conId so a cold start keeps the right
    month even when no probe is possible."""
    from ib_async import Contract
    try:
        saved = json.loads(_FRONT_FILE.read_text())
    except Exception:  # noqa: BLE001 — absent on first run
        return
    for sym, d in saved.items():
        if sym in _front_cache or not d.get("conId"):
            continue
        try:
            c = Contract(conId=d["conId"], exchange=d.get("exchange") or "")
            q = await asyncio.wait_for(ib.qualifyContractsAsync(c), timeout=_REQ_TIMEOUT)
            if q and q[0].lastTradeDateOrContractMonth >= time.strftime("%Y%m%d"):
                _front_cache[sym] = (q[0], d.get("vol", 0), d.get("ts", 0))
                log.info("IBKR: %s front month %s restored from disk", sym, q[0].localSymbol)
        except Exception as e:  # noqa: BLE001
            log.debug("could not restore %s front month: %s", sym, e)
# A contract has to trade at least this much in a day before it is allowed to
# displace ContFuture's choice.
_MIN_FRONT_VOL = 1000
# Every IB request gets a ceiling. IBKR's data farms go down independently of
# the socket (10-Aug: ushmds and cashfarm dropped while the connection stayed
# up), and an await with no timeout simply never returns - the feed hung for
# twenty minutes with no error and no reconnect.
_REQ_TIMEOUT = 15


async def _front_contract(ib, sym: str, exch: str, ctx: dict | None = None):
    """The contract the market is actually trading, judged on traded volume.

    ContFuture rolls to the NEAREST live expiry, which is not the same thing. On
    31-Jul-2026 it picked COMEX gold October (4103.8) while every terminal quoted
    December (4134.9) - a $31 gap the client spots instantly.

    Volume is read from the LAST DAILY BAR, not the live ticker. Live volume is
    zero whenever the market is shut, and that is exactly what broke it on 02-Aug:
    a reconnect at 1 a.m. saw zeros everywhere and fell back to October again.
    Daily bars answer the same question at any hour.
    """
    from ib_async import ContFuture, Future   # same lazy import as _loop

    cont = ContFuture(sym, exch)
    await asyncio.wait_for(ib.qualifyContractsAsync(cont), timeout=_REQ_TIMEOUT)

    cached = _front_cache.get(sym)
    if cached and (time.time() - cached[2]) < _FRONT_TTL:
        if cached[0].lastTradeDateOrContractMonth >= cont.lastTradeDateOrContractMonth:
            return cached[0]                      # still valid, skip the probe

    try:
        det = await asyncio.wait_for(
            ib.reqContractDetailsAsync(Future(sym, exchange=exch, currency="USD")),
            timeout=_REQ_TIMEOUT)
        # Use the contracts IBKR hands back - they are already qualified. Building
        # Future(sym, expiry) and re-qualifying is ambiguous on the active months
        # (silver returned nothing but November that way on 03-Aug), so match the
        # continuous contract's trading class and multiplier instead.
        cands = sorted(
            (d.contract for d in det
             if d.contract.lastTradeDateOrContractMonth >= cont.lastTradeDateOrContractMonth
             and d.contract.tradingClass == cont.tradingClass
             and d.contract.multiplier == cont.multiplier),
            key=lambda c: c.lastTradeDateOrContractMonth)[:5]
        vols: dict = {}
        for c in cands:
            if ctx is not None and not ctx.get("history_ok", True):
                break                      # farm is down; do not burn 15 s per strike
            try:
                bars = await asyncio.wait_for(
                    ib.reqHistoricalDataAsync(
                        c, endDateTime="", durationStr="5 D", barSizeSetting="1 day",
                        whatToShow="TRADES", useRTH=False, formatDate=1),
                    timeout=_REQ_TIMEOUT)
            except asyncio.TimeoutError:
                # One timeout means the farm is gone, not that this contract is
                # quiet. Give up on the whole probe rather than repeat it 25 times.
                log.warning("IBKR: history timed out for %s - skipping volume probe", c.localSymbol)
                if ctx is not None:
                    ctx["history_ok"] = False
                bars = []
                break
            vols[c] = max((float(b.volume) for b in bars if b.volume and b.volume > 0), default=0.0)
            await asyncio.sleep(0.3)          # stay inside IBKR's historical-data pacing
        log.info("IBKR: %s volumes %s", sym,
                 {c.localSymbol: int(v) for c, v in sorted(vols.items(), key=lambda kv: -kv[1])})

        cont_vol = next((v for c, v in vols.items() if c.localSymbol == cont.localSymbol), 0.0)
        best, best_vol = (None, 0.0)
        for c, v in vols.items():
            if v > best_vol:
                best, best_vol = c, v

        # Only overrule ContFuture for a contract that is genuinely the busy one.
        # Without this, a stray 8-lot print on silver November beat September,
        # whose history request had come back empty (03-Aug).
        if best is not None and best.localSymbol != cont.localSymbol:
            if best_vol < _MIN_FRONT_VOL or best_vol < cont_vol * 2:
                log.info("IBKR: %s keeping ContFuture %s (%s lots) - %s only had %s",
                         sym, cont.localSymbol, int(cont_vol), best.localSymbol, int(best_vol))
                best, best_vol = cont, cont_vol

        if best is not None and best_vol > 0:
            if best.localSymbol != cont.localSymbol:
                log.info("IBKR: %s front month = %s (%s lots/day) instead of ContFuture's %s",
                         sym, best.localSymbol, int(best_vol), cont.localSymbol)
            _front_cache[sym] = (best, best_vol, time.time())
            _save_front_disk()
            return best
        # History farm down? Fall back to LIVE volume, which is what the first
        # version used. It only works while the market is open, but that is
        # exactly when a wrong month would be visible to the client.
        if cands and not any(vols.values()):
            live = {}
            for c in cands:
                try:
                    live[c] = ib.reqMktData(c, "165", False, False)
                except Exception:  # noqa: BLE001
                    pass
            if live:
                await asyncio.sleep(6)
                for c, t in live.items():
                    v = float(t.volume) if (t.volume == t.volume and t.volume) else 0.0
                    vols[c] = max(vols.get(c, 0.0), v)
                    try:
                        ib.cancelMktData(c)
                    except Exception:  # noqa: BLE001
                        pass
                log.info("IBKR: %s live volumes %s", sym,
                         {c.localSymbol: int(v) for c, v in sorted(vols.items(), key=lambda kv: -kv[1])})
                best, best_vol = (None, 0.0)
                for c, v in vols.items():
                    if v > best_vol:
                        best, best_vol = c, v
                if best is not None and best.localSymbol != cont.localSymbol \
                        and best_vol >= _MIN_FRONT_VOL and best_vol >= cont_vol * 2:
                    log.info("IBKR: %s front month = %s (%s lots, live) instead of %s",
                             sym, best.localSymbol, int(best_vol), cont.localSymbol)
                    _front_cache[sym] = (best, best_vol, time.time())
                    _save_front_disk()
                    return best
        log.warning("IBKR: no volume found for any %s contract", sym)
    except Exception as e:  # noqa: BLE001 — never let this stop the feed
        log.warning("IBKR: volume probe for %s failed (%s)", sym, e)

    # Nothing usable from the probe: keep the last good pick rather than
    # silently dropping back to the wrong month.
    if cached and cached[0].lastTradeDateOrContractMonth >= cont.lastTradeDateOrContractMonth:
        log.info("IBKR: keeping cached %s front month %s", sym, cached[0].localSymbol)
        return cached[0]
    return cont


async def _loop() -> None:
    from ib_async import IB, Contract, ContFuture, Future, FuturesOption  # lazy — missing lib disables only this thread

    while not _stop.is_set():
        ib = IB()
        try:
            await ib.connectAsync(settings.IBKR_HOST, settings.IBKR_PORT,
                                  clientId=settings.IBKR_FEED_CLIENT_ID, timeout=20)
            ib.reqMarketDataType(1)  # real-time; gateway falls back to delayed on its own

            probe_ctx = {"history_ok": True}
            await _load_front_disk(ib)

            futs = {}
            for sym, exch, key in (("GC", "COMEX", "gc"), ("SI", "COMEX", "si"),
                                   ("CL", "NYMEX", "cl"), ("BZ", "NYMEX", "bz"),
                                   ("NG", "NYMEX", "ng")):
                try:
                    c = await asyncio.wait_for(_front_contract(ib, sym, exch, probe_ctx), timeout=120)
                except asyncio.TimeoutError:
                    log.warning("IBKR: %s front-month probe timed out, using ContFuture", sym)
                    c = ContFuture(sym, exch)
                    await asyncio.wait_for(ib.qualifyContractsAsync(c), timeout=_REQ_TIMEOUT)
                futs[key] = (c, ib.reqMktData(c, "", False, False))
                _state[key + "_symbol"] = c.localSymbol
                _state[key + "_expiry"] = c.lastTradeDateOrContractMonth

            # Spot metals — same feed that used to come from Finnhub.
            spots = {}
            for sym, key in (("XAUUSD", "xau"), ("XAGUSD", "xag")):
                c = Contract(secType="CMDTY", symbol=sym, exchange="SMART", currency="USD")
                await asyncio.wait_for(ib.qualifyContractsAsync(c), timeout=_REQ_TIMEOUT)
                spots[key] = (c, ib.reqMktData(c, "", False, False))

            # One monthly IV chain per commodity. The monthly is the class
            # listing the most strikes; the weeklies expire in days, so their IV
            # is time-decay noise and useless next to MCX's monthly.
            iv: dict = {}
            for sym, exch, key in _IV_SYMS:
                try:
                    ch = await asyncio.wait_for(
                        ib.reqSecDefOptParamsAsync(sym, exch, "FUT", futs[key][0].conId),
                        timeout=_REQ_TIMEOUT)
                    best = max((c for c in ch if c.exchange == exch), key=lambda c: len(c.strikes), default=None)
                except Exception as e:  # noqa: BLE001
                    log.warning("IBKR: no option classes for %s (%s)", sym, e)
                    best = None
                iv[key] = {
                    "sym": sym, "exch": exch, "chain": best,
                    "strikes": sorted(best.strikes) if best else [],
                    "expiry": sorted(best.expirations)[0] if best else None,
                    "tickers": {}, "window": [], "atm": None,
                }
                _state[key + "_iv_expiry"] = iv[key]["expiry"]
                _state[key + "_iv_class"] = best.tradingClass if best else None
                if best:
                    log.info("IBKR: %s IV class %s (%d strikes, exp %s)",
                             sym, best.tradingClass, len(best.strikes), iv[key]["expiry"])

            async def resubscribe_iv(key: str, centre: float) -> None:
                """21 monthly strikes around the money, one side each: calls
                above, puts below, both on the ATM row. Generic tick 106 asks
                IBKR for the implied volatility alongside the price."""
                d = iv[key]
                if not d["strikes"] or not d["expiry"]:
                    return
                atm = min(d["strikes"], key=lambda s: abs(s - centre))
                near = sorted(sorted(d["strikes"], key=lambda s: abs(s - atm))[: _IV_WINDOW * 2 + 1])
                if near == d["window"] and atm == d["atm"]:
                    return
                for strike in list(d["tickers"]):
                    for _right, tk in d["tickers"][strike].items():
                        try:
                            ib.cancelMktData(tk.contract)
                        except Exception:  # noqa: BLE001
                            pass
                d["tickers"].clear()
                for strike in near:
                    # Both sides on every strike. One side each was enough for the
                    # dashboard's calls-above/puts-below layout, but the client's
                    # own terminal renders a full chain and showed natural gas
                    # half empty (client, 12-Aug).
                    rights = ("C", "P")
                    legs = {}
                    for right in rights:
                        o = FuturesOption(d["sym"], d["expiry"], strike, right, d["exch"],
                                          tradingClass=d["chain"].tradingClass)
                        try:
                            q = await ib.qualifyContractsAsync(o)
                            if q:
                                legs[right] = ib.reqMktData(q[0], "106", False, False)
                        except Exception:  # noqa: BLE001 — one dead strike must not stop the rest
                            pass
                    if legs:
                        d["tickers"][strike] = legs
                d["window"], d["atm"] = near, atm
                log.info("IBKR: %s monthly IV window %s..%s (%d strikes, exp %s)",
                         d["sym"], near[0], near[-1], len(near), d["expiry"])

            log.info("IBKR feed connected (GC/SI/CL + monthly option chain + monthly IV chain)")
            last_window_check = 0.0
            last_iv_check = 0.0
            stale_since = time.time()
            rolled_at = time.time()

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
                global _silence_limit
                if moved:
                    stale_since = now
                    _state["last_tick"] = now
                    _state["stale"] = False
                    _silence_limit = _SILENCE_LIMIT      # prices flowing: back to 10 min
                elif now - stale_since > _silence_limit:
                    _state["stale"] = True
                    _silence_limit = min(_silence_limit * 2, _SILENCE_MAX)
                    raise RuntimeError(
                        f"no IBKR price change for {int(now - stale_since)}s - forcing reconnect "
                        f"(next check in {_silence_limit}s)")

                # Re-centre the option window at most once a minute, and only if
                # the underlying has actually walked out of it.
                cl_mid = None
                clp = _state.get("cl") or {}
                if clp.get("bid") and clp.get("ask"):
                    cl_mid = (clp["bid"] + clp["ask"]) / 2
                # Contracts roll; re-run the volume probe once a day by
                # reconnecting, which rebuilds every subscription cleanly.
                if now - rolled_at > 86400:
                    log.info("IBKR: daily front-month re-check")
                    raise RuntimeError("daily contract roll check")

                # The option chain is cached for the session, so on the day
                # after its expiry force the same reconnect path — the pick
                # above then rolls to the next month automatically instead of
                # streaming a dead contract until the daily check happens to
                # fire (that gap is how 06-AUG was still on screen on 07-Aug).
                if expiry and time.strftime("%Y%m%d", time.gmtime()) > expiry:
                    log.info("IBKR: CL option expiry %s passed - rolling to next month", expiry)
                    raise RuntimeError("CL option chain expired - rolling")


                # The IV windows re-centre on the ATM strike itself, so they
                # follow the market rather than only moving when price escapes
                # the edge. Tolerance scales with the strike step.
                if now - last_iv_check > 60:
                    last_iv_check = now
                    for key in iv:
                        p_ = _state.get(key) or {}
                        mid_ = ((p_["bid"] + p_["ask"]) / 2) if (p_.get("bid") and p_.get("ask")) else None
                        if mid_ is None:
                            continue
                        d = iv[key]
                        step = (d["strikes"][1] - d["strikes"][0]) if len(d["strikes"]) > 1 else 0.5
                        if not d["window"] or d["atm"] is None or abs(mid_ - d["atm"]) > step * 1.5:
                            await resubscribe_iv(key, mid_)


                for key, d in iv.items():
                    iv_rows = []
                    for strike in sorted(d["tickers"]):
                        legs = d["tickers"][strike]
                        is_atm = strike == d["atm"]
                        iv_rows.append({
                            "strike": strike,
                            "side": "ATM" if is_atm else ("CE" if strike > (d["atm"] or 0) else "PE"),
                            "atm": is_atm,
                            "ce": _leg(legs["C"]) if "C" in legs else None,
                            "pe": _leg(legs["P"]) if "P" in legs else None,
                        })
                    if iv_rows:
                        _state[key + "_iv_rows"] = iv_rows
                        _state[key + "_iv_ts"] = now
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


def _chain_block(key: str, age) -> dict:
    """The old crude_options shape - {strike, call, put} for every strike - so
    consumers that render a full chain keep working unchanged."""
    rows = []
    for r in _state.get(key + "_iv_rows", []):
        ce, pe = r.get("ce") or {}, r.get("pe") or {}
        pick = lambda d: {k: d.get(k) for k in ("bid", "ask", "last", "mid", "iv", "delta")}
        rows.append({"strike": r["strike"], "atm": r["atm"],
                     "call": pick(ce), "put": pick(pe)})
    return {
        "expiry": _state.get(key + "_iv_expiry"),
        "trading_class": _state.get(key + "_iv_class"),
        "age": age(key + "_iv"),
        "rows": rows,
    }


def _iv_block(key: str, age) -> dict:
    p = _state.get(key) or {}
    mid = ((p["bid"] + p["ask"]) / 2) if (p.get("bid") and p.get("ask")) else None
    return {
        "exchange": "NYMEX",
        "symbol": _state.get(key + "_symbol"),
        "trading_class": _state.get(key + "_iv_class"),
        "future_price": mid,
        "expiry": _state.get(key + "_iv_expiry"),
        "atm": next((r["strike"] for r in _state.get(key + "_iv_rows", []) if r["atm"]), None),
        "iv_unit": "percent",
        "age": age(key + "_iv"),
        "rows": _state.get(key + "_iv_rows", []),
    }


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
        "crude_iv": _iv_block("cl", age),
        "natgas_iv": _iv_block("ng", age),
        # Full chain view (both sides on every strike) over the same tickers the
        # IV blocks use - one subscription per commodity, not two.
        "crude_options": _chain_block("cl", age),
        "natgas_options": _chain_block("ng", age),
        "server_time": now,
    }


def start_in_background() -> None:
    if not settings.IBKR_FEED_ENABLED:
        log.info("IBKR feed disabled")
        return
    threading.Thread(target=_thread, daemon=True, name="ibkr-feed").start()
    log.info("IBKR feed starting (COMEX GC/SI + NYMEX CL + option chain, in-memory)")
