"""NSE vs MCX board history — thrice-daily snapshots at 10:00, 12:00 and 15:00 IST.

The client asked to track how the same strike drifts apart between the two
exchanges through the day, and chose the WHOLE table over an ATM-only summary,
so every strike is stored exactly as the live screen shows it.

This is the only record that will ever exist. Neither Angel, Dhan nor IBKR
serves NSE-commodity history, so nothing can be backfilled - the file can only
build forward from the first capture.

Load profile matches the rest of the app (client constraint: "no server / DB
load"):
  capture  : 3x/trading-day x 2 commodities, reads ONLY the in-memory feeds -
             no network, no new subscriptions - then one ~10 KB INSERT each.
             Skips weekends, cold feeds and missed windows, so it never stores
             an empty or mislabelled board.
  read     : on-demand only, one indexed SELECT behind a 60 s TTL cache.
  retention: nightly prune keeps ~370 days (~25 MB).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import NseMcxSnapshot

log = logging.getLogger("nse_mcx_history")

SLOTS = {"10:00": (10, 0), "12:00": (12, 0), "15:00": (15, 0)}
# Both months are captured even though the screen shows one at a time - the
# capture is the server's, not the viewer's, and a month nobody happened to be
# looking at would otherwise be lost for ever. Stored as "crude" / "crude_next"
# in the commodity column, which keeps the (date, slot, commodity) index doing
# its job without a schema change.
COMMODITIES = ("crude", "natgas")
MONTHS = (0, 1)


def _ckey(commodity: str, month: int) -> str:
    return commodity if month == 0 else f"{commodity}_next"


_WINDOW_MIN = 45          # minutes after the slot in which a capture is still honest
_WEEKDAY_NAME = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_lock = threading.Lock()               # serialises snapshot(); reads don't need it
_cache: dict = {}                      # (args) -> (ts, payload); tiny + bounded
_CACHE_TTL = 60.0


# --------------------------------------------------------------------------- #
# Capture (called from the maintenance loop)
# --------------------------------------------------------------------------- #
def _usable(board: dict) -> bool:
    """A board worth storing: both sides current, both futures priced, and at
    least one strike where both exchanges quote two-way. Anything less is a
    cold feed, not a market."""
    # `fresh` is false when either side has gone quiet. Storing then would file
    # one exchange's live prices against the other's last known ones - a
    # snapshot that looks ordinary for ever and is not a comparison at all.
    # Angel's session dies at midnight, so this is not hypothetical.
    if not board.get("fresh"):
        return False
    fut = board.get("future") or {}
    if (fut.get("nse") or {}).get("mid") is None or (fut.get("mcx") or {}).get("mid") is None:
        return False
    for r in (board.get("options") or {}).get("rows") or []:
        for side in ("ce", "pe"):
            leg = r.get(side) or {}
            if (leg.get("diff") or {}).get("rupees") is not None:
                return True
    return False


def snapshot(slot: str, commodity: str, month: int = 0) -> str:
    """Store the current board for `slot`. Idempotent; returns a status string."""
    if slot not in SLOTS:
        return f"unknown slot {slot!r}"
    if commodity not in COMMODITIES:
        return f"unknown commodity {commodity!r}"
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        from app.routes.nse_mcx import payload
        from app.services import dhan_feed

        now = datetime.now()  # server runs in Asia/Kolkata -> IST
        hh, mm = SLOTS[slot]
        slot_start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # A late run (a restart at 16:00 re-firing the 10:00 gate) must NOT store
        # 16:00 quotes labelled "10:00" - skip instead.
        if now < slot_start or now > slot_start + timedelta(minutes=_WINDOW_MIN):
            return "outside capture window; skipped"
        if not dhan_feed.is_market_open():
            return "market closed; skipped"

        board = payload(commodity, window=10, month=month)
        if not _usable(board):
            return "no live two-way market; skipped"

        today = now.date().isoformat()
        db = SessionLocal()
        try:
            ckey = _ckey(commodity, month)
            if db.query(NseMcxSnapshot.id).filter(
                    NseMcxSnapshot.snap_date == today,
                    NseMcxSnapshot.slot == slot,
                    NseMcxSnapshot.commodity == ckey).first():
                return "already snapped this slot"
            fut = board["future"]
            db.add(NseMcxSnapshot(
                snap_date=today,
                slot=slot,
                commodity=ckey,
                weekday=now.weekday(),
                nse_future=(fut.get("nse") or {}).get("mid"),
                mcx_future=(fut.get("mcx") or {}).get("mid"),
                future_diff=(fut.get("diff") or {}).get("rupees"),
                atm=(board.get("options") or {}).get("atm"),
                payload_json=json.dumps(
                    {"captured_at": now.isoformat(timespec="seconds"), "board": board},
                    separators=(",", ":")),
            ))
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


def snapshot_all(slot: str) -> dict:
    """Both commodities and both months for one slot."""
    return {_ckey(c, m): snapshot(slot, c, m) for c in COMMODITIES for m in MONTHS}


# --------------------------------------------------------------------------- #
# Read (dashboard + public app API)
# --------------------------------------------------------------------------- #
def get_history(commodity: str = "crude", slot: str = "all",
                days: int = 7, date: str | None = None, month: int = 0) -> dict:
    """Stored boards, newest first.

    date='YYYY-MM-DD' -> that day's snapshots only; otherwise the last `days`
    snapshot days. Each snapshot's `board` has exactly the live endpoint shape,
    so the History view renders with the same component as Live.
    """
    commodity = commodity if commodity in COMMODITIES else "crude"
    ckey = _ckey(commodity, 1 if month else 0)
    slot = slot if slot in SLOTS else "all"
    try:
        days = max(1, min(int(days), 60))
    except (TypeError, ValueError):
        days = 7

    key = (ckey, slot, days, date)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    db = SessionLocal()
    try:
        q = db.query(NseMcxSnapshot).filter(NseMcxSnapshot.commodity == ckey)
        if date:
            q = q.filter(NseMcxSnapshot.snap_date == date)
        if slot != "all":
            q = q.filter(NseMcxSnapshot.slot == slot)
        limit = len(SLOTS) if date else days * (len(SLOTS) if slot == "all" else 1)
        rows = (q.order_by(NseMcxSnapshot.snap_date.desc(), NseMcxSnapshot.slot.desc())
                 .limit(limit).all())
    finally:
        db.close()

    snapshots, dates_seen = [], []
    for r in rows:
        if r.snap_date not in dates_seen:
            if not date and len(dates_seen) >= days:
                break
            dates_seen.append(r.snap_date)
        stored = json.loads(r.payload_json)
        snapshots.append({
            "snap_date": r.snap_date,
            "weekday": _WEEKDAY_NAME[r.weekday],
            "slot": r.slot,
            "captured_at": stored.get("captured_at"),
            "nse_future": r.nse_future,
            "mcx_future": r.mcx_future,
            "future_diff": r.future_diff,
            "atm": r.atm,
            "board": stored.get("board") or {},
        })

    data = {
        "commodity": commodity,
        "month": 1 if month else 0,
        "slot": slot,
        "days_requested": days,
        "date": date,
        "slots": list(SLOTS),
        "count": len(snapshots),
        "dates": dates_seen,
        "snapshots": snapshots,
        "note": ("auto-captured 10:00, 12:00 and 15:00 IST each trading day; "
                 "weekends and holidays have no snapshot. No exchange serves NSE "
                 "commodity history, so nothing before the first capture exists."),
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
        n = db.query(NseMcxSnapshot).filter(NseMcxSnapshot.snap_date < cutoff).delete()
        db.commit()
        return int(n or 0)
    except Exception:  # noqa: BLE001
        db.rollback()
        return 0
    finally:
        db.close()
