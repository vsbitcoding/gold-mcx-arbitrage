"""Nifty/Sensex options-board history — thrice-daily snapshots + weekday query.

Replaces the client's manual 10am/3pm screenshots. Load profile is deliberately
tiny (client constraint: "no server / DB load"):

  capture  : 2×/trading-day (10:00 & 15:00 IST), reads ONLY the in-memory
             quote_store via options_service.get_spread_table() — no network,
             no new Dhan subscriptions — then ONE ~40 KB INSERT. Skips
             weekends / cold feed / missed capture windows, so it never stores
             misleading or empty boards.
  read     : on-demand only (the dashboard fetches on control change — no
             polling); a single indexed SELECT of ≤ 2×weeks small rows behind
             a 60 s TTL cache.
  retention: nightly prune keeps ~370 days (a full year of weekday history,
             ~10 MB total).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import OptionsSnapshot

_SLOTS = {"10:00": (10, 0), "15:00": (15, 0), "15:25": (15, 25)}
_WINDOW_MIN = 45          # minutes after the slot in which a capture is still honest
# 15:25 sits five minutes before the index close, so its window has to be tight -
# a late run at 16:00 would otherwise store post-close numbers under that label.
_SLOT_WINDOW = {"15:25": 5}
_WEEKDAY_NUM = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_NAME = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_lock = threading.Lock()               # serialises snapshot(); reads don't need it
_cache: dict = {}                      # (args) -> (ts, payload); tiny + bounded
_CACHE_TTL = 60.0


# --------------------------------------------------------------------------- #
# Capture (called from the maintenance loop at 10:00 / 15:00 IST)
# --------------------------------------------------------------------------- #
def snapshot(slot: str) -> str:
    """Store the current board for `slot`. Idempotent; returns a status string."""
    if slot not in _SLOTS:
        return f"unknown slot {slot!r}"
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        from app.services import dhan_feed, options_service

        now = datetime.now()  # server runs in Asia/Kolkata → IST
        hh, mm = _SLOTS[slot]
        slot_start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        window = _SLOT_WINDOW.get(slot, _WINDOW_MIN)
        # A late run (e.g. server restart at 16:00 re-firing the 10:00 gate)
        # must NOT store 16:00 quotes labelled "10:00" — skip instead.
        if now < slot_start or now > slot_start + timedelta(minutes=window):
            return "outside capture window; skipped"
        if not dhan_feed.is_market_open():
            return "market closed; skipped"

        below = options_service.get_spread_table("below")
        above = options_service.get_spread_table("above")
        # Holiday / cold-feed guard: no live spot AND no anchor → nothing real to store.
        if below.get("nifty_spot") is None and below.get("nifty_atm") is None:
            return "no live index data; skipped"

        today = now.date().isoformat()
        db = SessionLocal()
        try:
            if db.query(OptionsSnapshot.id).filter(
                    OptionsSnapshot.snap_date == today,
                    OptionsSnapshot.slot == slot).first():
                return "already snapped this slot"
            payload = {
                "captured_at": now.isoformat(timespec="seconds"),
                "below": below,
                "above": above,
            }
            db.add(OptionsSnapshot(
                snap_date=today,
                slot=slot,
                weekday=now.weekday(),
                nifty_spot=below.get("nifty_spot"),
                sensex_spot=below.get("sensex_spot"),
                india_vix=below.get("india_vix"),
                nifty_atm=below.get("nifty_atm"),
                sensex_atm=below.get("sensex_atm"),
                payload_json=json.dumps(payload, separators=(",", ":")),
            ))
            db.commit()
            _cache.clear()
            return "snapped"
        except Exception as e:  # noqa: BLE001 — unique-index race etc.; never raise into the loop
            db.rollback()
            return f"store error: {e}"
        finally:
            db.close()
    finally:
        _lock.release()


# --------------------------------------------------------------------------- #
# Read (dashboard + public app API)
# --------------------------------------------------------------------------- #
def _squareoff_view(above: dict) -> dict:
    """Derive the square-off (exit) board from the stored 'above' raw depth:
    BUY back Nifty PE @ ASK, SELL Sensex PE @ BID (falls back to LTP)."""
    from app.services.options_service import NIFTY_MULT, SENSEX_MULT

    out = {**above, "side": "squareoff", "weeks": []}
    for wk in above.get("weeks", []):
        rows = []
        for r in wk.get("rows", []):
            n_price = r.get("nifty_ask") or r.get("nifty_pe")
            s_price = r.get("sensex_bid") or r.get("sensex_pe")
            n_value = round(n_price * NIFTY_MULT, 2) if n_price else None
            s_value = round(s_price * SENSEX_MULT, 2) if s_price else None
            spread = round(n_value - s_value, 2) if (n_value is not None and s_value is not None) else None
            rows.append({
                **r,
                "nifty_leg": round(n_price, 2) if n_price else None,
                "sensex_leg": round(s_price, 2) if s_price else None,
                "nifty_value": n_value,
                "sensex_value": s_value,
                "spread": spread,
            })
        out["weeks"].append({**wk, "rows": rows})
    return out


def _parse_weekday(weekday) -> int | None:
    if weekday is None:
        return None
    w = str(weekday).strip().lower()
    if w.isdigit() and 0 <= int(w) <= 6:
        return int(w)
    return _WEEKDAY_NUM.get(w[:3])


def get_history(weekday=None, slot: str = "both", side: str = "below",
                weeks: int = 7, date: str | None = None) -> dict:
    """Snapshots for the weekday-compare view.

    weekday mon..sun / 0..6 → the last `weeks` same-weekday boards (newest
    first); omit → the last `weeks` snapshot days of any weekday.
    date='YYYY-MM-DD' → just that day's snapshot(s). Each snapshot's
    weeks[].rows[] has exactly the live /options-spread row shape.
    """
    side = side if side in ("below", "above", "squareoff") else "below"
    slot = slot if slot in _SLOTS or slot == "both" else "both"
    try:
        weeks = max(1, min(int(weeks), 52))
    except (TypeError, ValueError):
        weeks = 7
    wd = _parse_weekday(weekday) if date is None else None

    key = (wd, slot, side, weeks, date)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    db = SessionLocal()
    try:
        q = db.query(OptionsSnapshot)
        if date:
            q = q.filter(OptionsSnapshot.snap_date == date)
        elif wd is not None:
            q = q.filter(OptionsSnapshot.weekday == wd)
        if slot != "both":
            q = q.filter(OptionsSnapshot.slot == slot)
        limit = len(_SLOTS) * 2 if date else weeks * (len(_SLOTS) if slot == "both" else 1)
        rows = (q.order_by(OptionsSnapshot.snap_date.desc(), OptionsSnapshot.slot.asc())
                 .limit(limit).all())
    finally:
        db.close()

    snapshots = []
    dates_seen: list[str] = []
    for r in rows:
        if r.snap_date not in dates_seen:
            if not date and len(dates_seen) >= weeks:
                break
            dates_seen.append(r.snap_date)
        payload = json.loads(r.payload_json)
        if side == "below":
            board = payload.get("below") or {}
        elif side == "above":
            board = payload.get("above") or {}
        else:
            board = _squareoff_view(payload.get("above") or {})
        snapshots.append({
            "snap_date": r.snap_date,
            "weekday": _WEEKDAY_NAME[r.weekday],
            "slot": r.slot,
            "captured_at": payload.get("captured_at"),
            "nifty_spot": r.nifty_spot,
            "sensex_spot": r.sensex_spot,
            "india_vix": r.india_vix,
            "nifty_atm": r.nifty_atm,
            "sensex_atm": r.sensex_atm,
            # day-change vs prev close + N×3.2 divergence (present in snapshots
            # taken after 2026-07-13; None for older ones)
            "nifty_day_change": board.get("nifty_day_change"),
            "sensex_day_change": board.get("sensex_day_change"),
            "day_divergence": board.get("day_divergence"),
            "side": side,
            "weeks": board.get("weeks", []),
        })

    data = {
        "weekday": _WEEKDAY_NAME[wd] if wd is not None else None,
        "slot": slot,
        "side": side,
        "weeks_requested": weeks,
        "date": date,
        "count": len(snapshots),
        "dates": dates_seen,
        "snapshots": snapshots,
        "note": "auto-captured 10:00, 15:00 & 15:25 IST each trading day; holidays/weekends have no snapshot",
    }
    if len(_cache) > 32:
        _cache.clear()
    _cache[key] = (now, data)
    return data


def prune(days: int = 370) -> int:
    """Nightly retention: drop snapshots older than ~a year. Returns rows removed."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        n = db.query(OptionsSnapshot).filter(OptionsSnapshot.snap_date < cutoff).delete()
        db.commit()
        return int(n or 0)
    except Exception:  # noqa: BLE001
        db.rollback()
        return 0
    finally:
        db.close()
