"""Exchange calendar: is NSE / MCX open right now, and if not, why.

One source of truth for every clock in the app - the feed watchdog, the
paper engine, the snapshot jobs and the header badge (client, 14-Sep-2026:
the board read STALE all Ganesh Chaturthi morning and the watchdog rebuilt
the sockets 72 times for a market that was simply shut).

Holidays live in `market_holidays`, pulled from NSE's holiday master
(https://www.nseindia.com/api/holiday-master?type=trading): the FO segment
is the equity / F&O calendar (a listed day is closed all day) and the COM
segment carries the commodity sessions (morning closed / evening open), which
match MCX's own circular. The admin can add or edit a day on the Market
Holidays page; a manual row is never overwritten by a refresh.

Sessions (IST): NSE 09:15-15:30; MCX morning 09:00-17:00, evening 17:00-23:30.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import MarketHoliday

log = logging.getLogger("market_calendar")

IST = timezone(timedelta(hours=5, minutes=30))
EXCHANGES = ("NSE", "MCX")
SESSIONS = {
    "NSE": ((9, 15, 15, 30),),
    "MCX": ((9, 0, 17, 0), (17, 0, 23, 30)),
}
NSE_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"

_cache: dict = {"at": 0.0, "rows": {}}       # (date, exchange) -> row dict
_lock = threading.Lock()
_CACHE_SECONDS = 300


def _now() -> datetime:
    return datetime.now(IST)


def _rows() -> dict:
    with _lock:
        if time.time() - _cache["at"] < _CACHE_SECONDS:
            return _cache["rows"]
        db = SessionLocal()
        try:
            rows = {(h.date, h.exchange): _row(h) for h in db.query(MarketHoliday).all()}
        finally:
            db.close()
        _cache["rows"], _cache["at"] = rows, time.time()
        return rows


def _row(h: MarketHoliday) -> dict:
    return {"id": h.id, "date": h.date, "exchange": h.exchange, "name": h.name,
            "morning_closed": bool(h.morning_closed), "evening_closed": bool(h.evening_closed),
            "source": h.source, "updated_by": h.updated_by,
            "weekday": datetime.strptime(h.date, "%Y-%m-%d").strftime("%A")}


def invalidate():
    with _lock:
        _cache["at"] = 0.0


def holiday(exchange: str, day: str) -> dict | None:
    return _rows().get((day, exchange))


def state(exchange: str = "MCX", now: datetime | None = None) -> dict:
    """{"state": open|closed|holiday, "open": bool, "label": ..., "reason": ..., "holiday": name|None, "next_open": iso|None}"""
    n = now or _now()
    day = n.strftime("%Y-%m-%d")
    hol = holiday(exchange, day)
    if n.weekday() >= 5:
        return {"state": "closed", "open": False, "label": "Weekend", "reason": n.strftime("%A"), "holiday": None, "next_open": _next_open(exchange, n)}
    sessions = SESSIONS[exchange]
    closed_flags = []
    if hol:
        closed_flags = [hol["morning_closed"], hol["evening_closed"]] if exchange == "MCX" else [hol["morning_closed"] or hol["evening_closed"]]
    for i, (h1, m1, h2, m2) in enumerate(sessions):
        start = n.replace(hour=h1, minute=m1, second=0, microsecond=0)
        end = n.replace(hour=h2, minute=m2, second=0, microsecond=0)
        if start <= n <= end:
            if hol and closed_flags[min(i, len(closed_flags) - 1)]:
                which = "" if (exchange == "NSE" or all(closed_flags)) else (" (morning session)" if i == 0 else " (evening session)")
                return {"state": "holiday", "open": False, "label": "Holiday", "reason": f"{hol['name']}{which}",
                        "holiday": hol["name"], "next_open": _next_open(exchange, n)}
            return {"state": "open", "open": True, "label": "Open", "reason": None, "holiday": hol["name"] if hol else None, "next_open": None}
    # outside every session
    if hol and all(closed_flags):
        return {"state": "holiday", "open": False, "label": "Holiday", "reason": hol["name"], "holiday": hol["name"], "next_open": _next_open(exchange, n)}
    return {"state": "closed", "open": False, "label": "Market closed", "reason": "outside trading hours",
            "holiday": hol["name"] if hol else None, "next_open": _next_open(exchange, n)}


def is_open(exchange: str = "MCX", now: datetime | None = None) -> bool:
    return state(exchange, now)["open"]


def _next_open(exchange: str, n: datetime) -> str | None:
    """The next session start after `n`, up to two weeks out."""
    for d in range(0, 15):
        day = (n + timedelta(days=d)).replace(second=0, microsecond=0)
        if day.weekday() >= 5:
            continue
        hol = holiday(exchange, day.strftime("%Y-%m-%d"))
        for i, (h1, m1, _h2, _m2) in enumerate(SESSIONS[exchange]):
            start = day.replace(hour=h1, minute=m1)
            if start <= n:
                continue
            if hol:
                flag = (hol["morning_closed"] if i == 0 else hol["evening_closed"]) if exchange == "MCX" else (hol["morning_closed"] or hol["evening_closed"])
                if flag:
                    continue
            return start.isoformat()
    return None


# ------------------------------------------------------------------ admin API
def list_year(year: int) -> list[dict]:
    rows = [r for (d, _e), r in _rows().items() if d.startswith(str(year))]
    return sorted(rows, key=lambda r: (r["date"], r["exchange"]))


def years() -> list[int]:
    ys = {int(d[:4]) for (d, _e) in _rows()}
    ys.add(_now().year)
    return sorted(ys)


def upsert(data: dict, username: str | None) -> dict:
    day = str(data.get("date") or "")[:10]
    datetime.strptime(day, "%Y-%m-%d")
    exchange = str(data.get("exchange") or "").upper()
    if exchange not in EXCHANGES:
        raise ValueError("exchange must be NSE or MCX")
    db = SessionLocal()
    try:
        h = db.query(MarketHoliday).filter(MarketHoliday.date == day, MarketHoliday.exchange == exchange).first()
        if h is None:
            h = MarketHoliday(date=day, exchange=exchange); db.add(h)
        h.name = str(data.get("name") or "").strip()[:120] or "Holiday"
        h.morning_closed = bool(data.get("morning_closed", True))
        h.evening_closed = bool(data.get("evening_closed", True if exchange == "NSE" else False))
        h.source, h.updated_by = "manual", username
        db.commit()
        out = _row(h)
    finally:
        db.close()
    invalidate()
    return out


def delete(holiday_id: int) -> bool:
    db = SessionLocal()
    try:
        h = db.get(MarketHoliday, holiday_id)
        if h is None:
            return False
        db.delete(h); db.commit()
    finally:
        db.close()
    invalidate()
    return True


def refresh_from_nse(year: int | None = None) -> dict:
    """Pull the year's calendar from NSE's holiday master. FO -> NSE rows (all
    day), COM -> MCX rows (morning / evening flags). Manual rows are kept."""
    from app.services import nse_opt_history as h
    s = h._nse_session("CRUDEOIL")
    r = s.get(NSE_HOLIDAY_URL, headers=h._UA, timeout=30)
    r.raise_for_status()
    data = r.json()
    year = year or _now().year
    out = {"nse": 0, "mcx": 0, "kept_manual": 0}
    db = SessionLocal()
    try:
        def put(exchange, day, name, morning, evening):
            if not day.startswith(str(year)):
                return
            row = db.query(MarketHoliday).filter(MarketHoliday.date == day, MarketHoliday.exchange == exchange).first()
            if row and row.source == "manual":
                out["kept_manual"] += 1
                return
            if row is None:
                row = MarketHoliday(date=day, exchange=exchange); db.add(row)
            row.name, row.morning_closed, row.evening_closed, row.source = name, morning, evening, "nse"
            out[exchange.lower()] += 1
        for x in data.get("FO") or []:
            day = datetime.strptime(x["tradingDate"], "%d-%b-%Y").strftime("%Y-%m-%d")
            put("NSE", day, (x.get("description") or "").strip("* "), True, True)
        for x in data.get("COM") or []:
            day = datetime.strptime(x["tradingDate"], "%d-%b-%Y").strftime("%Y-%m-%d")
            put("MCX", day, (x.get("description") or "").strip("* "),
                (x.get("morning_session") or "").lower() == "closed", (x.get("evening_session") or "").lower() == "closed")
        db.commit()
    finally:
        db.close()
    invalidate()
    log.info("market calendar %s refreshed from NSE: %s", year, out)
    return out


def ensure_loaded() -> None:
    """On startup and once a day: fetch the current year if the table has none
    of it, and next year's list from December on."""
    try:
        y = _now().year
        have = {int(d[:4]) for (d, _e) in _rows()}
        if y not in have:
            refresh_from_nse(y)
        if _now().month == 12 and (y + 1) not in have:
            refresh_from_nse(y + 1)
    except Exception as e:  # noqa: BLE001
        log.warning("market calendar refresh: %s", e)
