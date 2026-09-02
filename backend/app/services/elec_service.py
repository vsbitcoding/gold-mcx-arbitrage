"""NSE-vs-MCX electricity futures comparison (client's handwritten note, 02-Sep).

He wants the FUTURE price difference of electricity on both exchanges - MCX
trades it as ELECDMBL, NSE as ELECMBL, both monthly base load - with the
current numbers and hourly history.

Sides
-----
MCX comes off our own Dhan socket: this service resolves the first two
ELECDMBL months and hands them to the feed as extra subscriptions, the same
hook the paper trades use. NSE comes from the Angel poll, which learned an
"electricity" commodity for this (futures only - NSE lists no electricity
options, and the note asks for futures).

History
-------
Hourly, recorded by US from the live feeds at the top of each hour. It cannot
be backfilled: Dhan serves MCX hourly candles months back, but Angel's
historical API does not carry the NCO segment at all (probed 02-Sep: the same
request succeeds for MCX and answers HTTP 400 for NCO), and a difference with
one side missing is not a difference. So the series starts the day this
shipped, and each row is the pair of prices at that hour with ONE difference
value - the client's "single value" rule.

A row only writes when BOTH sides are live and fresh; a one-sided hour is
skipped honestly rather than stored half-blank.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from app.database import SessionLocal
from app.models import ElecHourly
from app.services.market_data import clean_sides, quote_store

log = logging.getLogger("elec_service")

_FRESH_SECONDS = 180.0

_lock = threading.Lock()
# [{security_id, trading_symbol, expiry}] for month 0..1, refreshed with the feed
_state: dict = {"mcx": []}


def refresh() -> None:
    """Resolve the first two MCX ELECDMBL months. Called on every feed
    (re)connect, so the expiry-day roll carries it like everything else."""
    from app.services.instrument_resolver import resolve_all_active
    try:
        contracts = resolve_all_active().get("elecmbl", [])[:2]
    except Exception as e:  # noqa: BLE001 - master download can fail; keep last
        log.warning("elec: resolve failed: %s", e)
        return
    _state["mcx"] = [{
        "security_id": str(c["security_id"]),
        "trading_symbol": c["trading_symbol"],
        "expiry": c["expiry"].strftime("%Y-%m-%d"),
    } for c in contracts]
    log.info("elec: MCX legs %s", [c["trading_symbol"] for c in _state["mcx"]])


def get_subscription_meta() -> dict:
    """{security_id: meta} merged into the Dhan feed's subscription list."""
    return {c["security_id"]: {
        "short": "elec_fut",
        "trading_symbol": c["trading_symbol"],
        "expiry": c["expiry"],
    } for c in _state["mcx"]}


def mcx_future(month: int = 0) -> dict | None:
    """Live MCX leg for the payload - bid/ask through the dead-book dash rule."""
    import time
    if month >= len(_state["mcx"]):
        return None
    c = _state["mcx"][month]
    q = quote_store.get(c["security_id"])
    bid, ask = clean_sides(q)
    age = (time.time() - q.timestamp) if q.timestamp else None
    return {
        "symbol": c["trading_symbol"], "expiry": c["expiry"],
        "bid": bid, "ask": ask, "ltp": q.ltp or None,
        "age": round(age, 1) if age is not None else None,
        "fresh": age is not None and age < _FRESH_SECONDS,
    }


def snapshot_hour() -> str:
    """Record this hour's pair of prices, once. Runs from maintenance at HH:00.

    The stored value is each side's traded price (LTP) at the top of the hour -
    the closest live thing to an hourly close - and one difference, MCX minus
    NSE, per the client's single-value rule.
    """
    now = datetime.now()
    hour_key = now.strftime("%Y-%m-%d %H:00")
    from app.services import angel_feed, dhan_feed
    if not dhan_feed.is_market_open():
        return "MCX closed; skipped"
    written = []
    with _lock:
        db = SessionLocal()
        try:
            for month in (0, 1):
                mcx = mcx_future(month)
                nse_board = angel_feed.get_data("electricity", month) or {}
                nse_fut = nse_board.get("future") or {}
                nse_ltp = nse_fut.get("ltp")
                age = nse_board.get("age")
                if not mcx or not mcx.get("fresh") or not mcx.get("ltp"):
                    continue
                if not nse_board.get("ok") or not nse_ltp or age is None or age > _FRESH_SECONDS:
                    continue
                if db.query(ElecHourly.id).filter(
                        ElecHourly.hour == hour_key,
                        ElecHourly.month == month).first():
                    continue
                diff = round(mcx["ltp"] - nse_ltp, 2)
                db.add(ElecHourly(
                    hour=hour_key, month=month,
                    nse_close=nse_ltp, mcx_close=mcx["ltp"], diff=diff,
                    pct=round(diff / nse_ltp * 100, 2) if nse_ltp else None,
                    nse_symbol=nse_fut.get("symbol"), mcx_symbol=mcx.get("symbol")))
                written.append(month)
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            return f"store error: {e}"
        finally:
            db.close()
    return f"snapped months {written}" if written else "one side not live; skipped"


def history(month: int = 0, days: int = 30) -> dict:
    """Stored hourly rows, newest first."""
    from datetime import timedelta
    days = max(1, min(int(days), 365))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:00")
    db = SessionLocal()
    try:
        rows = (db.query(ElecHourly)
                .filter(ElecHourly.month == (1 if month == 1 else 0),
                        ElecHourly.hour >= cutoff)
                .order_by(ElecHourly.hour.desc()).limit(2000).all())
        return {"month": month, "count": len(rows), "rows": [{
            "hour": r.hour, "nse": r.nse_close, "mcx": r.mcx_close,
            "diff": r.diff, "pct": r.pct,
        } for r in rows]}
    finally:
        db.close()
