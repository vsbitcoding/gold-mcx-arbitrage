"""BANKEX / BANKNIFTY board history: 10:00 and 15:30 IST snapshots + read side.

The client asked (23-Sep-2026) for the page's data "Morning 10:00 AM,
Afternoon 15:30 PM", the way the Nifty/Sensex board is kept. Same load
profile as that one:

  capture  : twice a trading day, reads ONLY the in-memory quote store through
             bank_options_service.get_live() - no network, no new
             subscriptions - then one ~12 KB INSERT. Skips holidays (exchange
             calendar), a cold feed and a missed window, so a late restart can
             never file 16:00 quotes under "10:00".
  read     : on demand, one indexed SELECT behind a 60 s cache.
  retention: nightly prune keeps ~370 days.

The 15:30 board is the close: option trading ends at 15:30 and the quotes keep
ticking through the 15:30-15:40 closing session, so the capture window is
kept short (8 min) and inside the NSE session the calendar knows about.

A history row prices a pair from each leg's LAST two-way quote as long as it
is under fifteen minutes old, and records the leg's age and the Live page's
60-second "fresh" flag beside it. The live board only prices a row whose legs
both ticked in the last minute, which is right for a paper entry but leaves a
saved 10:00 board full of dashes on the far strikes, whose standing bid/ask
simply do not change every minute.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import BankOptionsSnapshot

log = logging.getLogger("bank_options_history")

SLOTS = {"10:00": (10, 0), "15:30": (15, 30)}
# Minutes after the slot in which a capture is still honest. 15:30 must not
# slip past the 15:40 close, when the last quotes stop moving.
_WINDOW_MIN = {"10:00": 45, "15:30": 8}
_MAX_QUOTE_AGE = 900.0          # seconds; a standing quote older than this does not price a history row
# The index level may be up to five minutes old at capture: BSE stops the BANKEX
# ticks at 15:30 and prints the final value around 15:33, while the option
# quotes keep ticking, and the Live page's 60-second bar would skip the close.
_MAX_INDEX_AGE = 300.0
_WEEKDAY_NUM = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_NAME = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_lock = threading.Lock()
_cache: dict = {}
_CACHE_TTL = 60.0


def _usable(leg: dict) -> bool:
    age = leg.get("age")
    return bool(leg.get("bid") and leg.get("ask") and age is not None and age <= _MAX_QUOTE_AGE)


def _index_ok(ix: dict) -> bool:
    age = ix.get("age_seconds")
    return bool(ix.get("atm") and ix.get("spot") and age is not None and age <= _MAX_INDEX_AGE)


def compact(board: dict, captured_at: str) -> dict:
    """The stored shape of a live board: index cards + rows with both legs' quotes
    and the difference (sell bid minus buy ask) priced from the last quotes."""
    indices = {}
    for name, ix in (board.get("indices") or {}).items():
        indices[name] = {"spot": ix.get("spot"), "atm": ix.get("atm"), "expiry": ix.get("expiry"),
                         "lot_size": ix.get("lot_size"), "age": ix.get("age_seconds"), "fresh": bool(ix.get("fresh"))}
    buy, sell = board.get("buy_index"), board.get("sell_index")
    rows = []
    for r in board.get("rows") or []:
        legs = {}
        for name in ("bankex", "banknifty"):
            leg = r.get(name) or {}
            legs[name] = {"strike": leg.get("strike"), "expiry": leg.get("expiry"), "bid": leg.get("bid"),
                          "ask": leg.get("ask"), "ltp": leg.get("ltp"), "oi": leg.get("oi"), "volume": leg.get("volume"),
                          "age": leg.get("age_seconds"), "fresh": bool(leg.get("fresh")), "lot_size": leg.get("lot_size"),
                          "listed": bool(leg.get("security_id"))}
        buy_leg = legs.get((buy or "").lower()) if buy else None
        sell_leg = legs.get((sell or "").lower()) if sell else None
        buy_px = buy_leg.get("ask") if buy_leg else None
        sell_px = sell_leg.get("bid") if sell_leg else None
        priced = bool(buy_leg and sell_leg and _usable(buy_leg) and _usable(sell_leg))
        rows.append({"side": r.get("side"), "offset_points": r.get("offset_points"),
                     "bankex": legs["bankex"], "banknifty": legs["banknifty"],
                     "buy_price": buy_px, "sell_price": sell_px,
                     "difference_points": round(sell_px - buy_px, 2) if priced else None,
                     "stale": bool(priced and not (buy_leg["fresh"] and sell_leg["fresh"]))})
    return {"captured_at": captured_at, "indices": indices, "buy_index": buy, "sell_index": sell,
            "market_open": bool(board.get("market_open")), "rows": rows}


def snapshot(slot: str, now: datetime | None = None) -> str:
    """Store the current board for `slot`. Idempotent; returns a status string."""
    if slot not in SLOTS:
        return f"unknown slot {slot!r}"
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        from app.services import bank_options_service, market_calendar

        now = now or datetime.now()  # server runs in Asia/Kolkata -> IST
        hh, mm = SLOTS[slot]
        slot_start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < slot_start or now > slot_start + timedelta(minutes=_WINDOW_MIN[slot]):
            return "outside capture window; skipped"
        if not market_calendar.is_open("NSE"):
            return "market closed; skipped"
        board = bank_options_service.get_live(metric="points")
        indices = board.get("indices") or {}
        if not all(_index_ok(indices.get(name) or {}) for name in ("BANKEX", "BANKNIFTY")):
            return "no live index data; skipped"
        payload = compact(board, now.isoformat(timespec="seconds"))
        if not any(r["difference_points"] is not None for r in payload["rows"]):
            return "no live option quotes; skipped"
        today = now.date().isoformat()
        db = SessionLocal()
        try:
            if db.query(BankOptionsSnapshot.id).filter(BankOptionsSnapshot.snap_date == today,
                                                       BankOptionsSnapshot.slot == slot).first():
                return "already snapped this slot"
            ix = payload["indices"]
            db.add(BankOptionsSnapshot(
                snap_date=today, slot=slot, weekday=now.weekday(),
                bankex_spot=(ix.get("BANKEX") or {}).get("spot"), banknifty_spot=(ix.get("BANKNIFTY") or {}).get("spot"),
                bankex_atm=(ix.get("BANKEX") or {}).get("atm"), banknifty_atm=(ix.get("BANKNIFTY") or {}).get("atm"),
                bankex_expiry=(ix.get("BANKEX") or {}).get("expiry"), banknifty_expiry=(ix.get("BANKNIFTY") or {}).get("expiry"),
                payload_json=json.dumps(payload, separators=(",", ":"))))
            db.commit()
            _cache.clear()
            return "snapped"
        except Exception as e:  # noqa: BLE001 - unique-index race etc.; never raise into the loop
            db.rollback()
            return f"store error: {e}"
        finally:
            db.close()
    finally:
        _lock.release()


def parse_weekday(weekday) -> int | None:
    if weekday is None or weekday == "":
        return None
    w = str(weekday).strip().lower()
    if w.isdigit() and 0 <= int(w) <= 6:
        return int(w)
    return _WEEKDAY_NUM.get(w[:3])


def get_history(slot: str = "both", weekday=None, days: int = 7, date: str | None = None) -> dict:
    """The stored boards, newest first: the last `days` snapshot days (of the
    weekday, when one is given), or just `date`."""
    slot = slot if slot in SLOTS else "both"
    try:
        days = max(1, min(int(days), 120))
    except (TypeError, ValueError):
        days = 7
    wd = parse_weekday(weekday) if not date else None
    key = (slot, wd, days, date)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    db = SessionLocal()
    try:
        q = db.query(BankOptionsSnapshot)
        if date:
            q = q.filter(BankOptionsSnapshot.snap_date == date)
        elif wd is not None:
            q = q.filter(BankOptionsSnapshot.weekday == wd)
        if slot != "both":
            q = q.filter(BankOptionsSnapshot.slot == slot)
        limit = len(SLOTS) if date else days * (len(SLOTS) if slot == "both" else 1)
        rows = q.order_by(BankOptionsSnapshot.snap_date.desc(), BankOptionsSnapshot.slot.desc()).limit(limit).all()
    finally:
        db.close()
    boards, dates = [], []
    for r in rows:
        if r.snap_date not in dates:
            dates.append(r.snap_date)
        payload = json.loads(r.payload_json)
        boards.append({"date": r.snap_date, "weekday": _WEEKDAY_NAME[r.weekday], "slot": r.slot,
                       "captured_at": payload.get("captured_at"), "indices": payload.get("indices") or {},
                       "buy_index": payload.get("buy_index"), "sell_index": payload.get("sell_index"),
                       "rows": payload.get("rows") or []})
    data = {"source": "snapshot", "slot": slot, "weekday": _WEEKDAY_NAME[wd] if wd is not None else None,
            "days": days, "date": date, "count": len(boards), "dates": dates, "boards": boards,
            "note": "auto-captured 10:00 and 15:30 IST each trading day; holidays and weekends have no board"}
    if len(_cache) > 32:
        _cache.clear()
    _cache[key] = (now, data)
    return data


def prune(days: int = 370) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        n = db.query(BankOptionsSnapshot).filter(BankOptionsSnapshot.snap_date < cutoff).delete()
        db.commit()
        return int(n or 0)
    except Exception:  # noqa: BLE001
        db.rollback()
        return 0
    finally:
        db.close()
