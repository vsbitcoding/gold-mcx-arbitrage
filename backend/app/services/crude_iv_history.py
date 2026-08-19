"""MCX-vs-US option comparison history - half-hourly, both months (client, 19-Aug).

He asked for the whole table stored every 30 minutes "only while both markets
are open", plus the next expiry month alongside.

On "both open"
--------------
US crude trades nearly around the clock: Sunday 6 PM to Friday 5 PM ET with one
60-minute break a day, and that break lands at 02:30-03:30 IST, when MCX is shut
anyway. Measured at 16:45 IST, well before the US session, the US ATM was quoted
0.9% wide - a real market, not a placeholder. So the overlap is simply all of
MCX's hours, and the client picked 09:00 to 23:30 when that was put to him.

A clock is still the wrong test, though. `_usable()` demands both sides live and
some strike quoting two-way on both exchanges, so a thin hour stores nothing
rather than storing something misleading. No exchange sells this history back,
which cuts both ways: a missed capture is gone for good, and so is a bad one.

Load
----
Measured before it was written, since "no DB or server load" is standing:
  capture  : 30 slots x 2 commodities x 2 months = 120 rows a day, all read from
             the in-memory feeds - no upstream call, no new subscription.
  size     : the live board serialises to 14.8 KB, which would be 433 MB a year.
             Every column the table SHOWS - strike, bid, ask, IV, delta, and OI
             on the MCX side - packs into about 3 KB. The front month carries 31
             strikes and the next 15 (19-Aug), which averages out near where it
             was at 21 apiece, so roughly 390 KB a day and 95 MB a year, beside
             the 65 MB the NSE-vs-MCX history already uses.
  read     : on demand, one indexed SELECT behind a 60 s cache. Nothing polls it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import CrudeIvSnapshot

log = logging.getLogger("crude_iv_history")

# Every half hour through MCX's session. 23:30 is the close itself, so it gets a
# short window - see _window_min().
SLOTS = {f"{h:02d}:{m:02d}": (h, m)
         for h in range(9, 24) for m in (0, 30)
         if (h, m) >= (9, 0) and (h, m) <= (23, 30)}
COMMODITIES = ("crude", "natgas")
MONTHS = (0, 1)

_MARKET_CLOSE = (23, 30)
_WINDOW_MIN = 25          # under the 30-minute gap, so a late run cannot bleed
                          # into the next slot and be filed under this one

_lock = threading.Lock()
_cache: dict = {}
_CACHE_TTL = 60.0


def _window_min(slot: str) -> int:
    """How late a capture may still be filed under `slot`.

    Slots are 30 minutes apart, so 25 keeps a retry inside its own half hour.
    23:30 is the close: nothing after it belongs to that slot at all.
    """
    hh, mm = SLOTS[slot]
    start = hh * 60 + mm
    later = [h * 60 + m for h, m in SLOTS.values() if h * 60 + m > start]
    limit = min([_MARKET_CLOSE[0] * 60 + _MARKET_CLOSE[1] + 5] + later)
    return max(1, min(_WINDOW_MIN, limit - start))


def _atm_iv(rows: list) -> float | None:
    """The ATM row's volatility, averaging the two legs where both are quoted.

    They agree to a fraction of a point now that the forward is right - the
    average is belt and braces, and it keeps a number on screen when one leg
    happens to be one-sided.
    """
    row = next((r for r in rows if r.get("atm")), None)
    if not row:
        return None
    vals = [(row.get(s) or {}).get("iv") for s in ("ce", "pe")]
    vals = [v for v in vals if v]
    return round(sum(vals) / len(vals), 2) if vals else None


def _pack(board: dict) -> dict:
    """Everything the table shows, and nothing else.

    Keeping the live board would cost 433 MB a year to store symbols and volumes
    that no one reads back. Rows go out as flat lists rather than dicts: the key
    names repeat on every strike and would be most of the file.
    """
    def rows(chain, oi):
        out = []
        for r in chain.get("rows") or []:
            row = [r.get("strike"), 1 if r.get("atm") else 0]
            for side in ("ce", "pe"):
                leg = r.get(side) or {}
                row += [leg.get("bid"), leg.get("ask"), leg.get("iv"), leg.get("delta"),
                        1 if leg.get("wide") else 0]
                if oi:
                    row.append(leg.get("oi"))
            out.append(row)
        return out

    m, u = board["mcx"], board["us"]
    return {
        # field order, so a reader never has to guess what column 4 is
        "cols_mcx": ["strike", "atm",
                     "ce_bid", "ce_ask", "ce_iv", "ce_delta", "ce_wide", "ce_oi",
                     "pe_bid", "pe_ask", "pe_iv", "pe_delta", "pe_wide", "pe_oi"],
        "cols_us": ["strike", "atm",
                    "ce_bid", "ce_ask", "ce_iv", "ce_delta", "ce_wide",
                    "pe_bid", "pe_ask", "pe_iv", "pe_delta", "pe_wide"],
        "mcx": {"rows": rows(m, True), "expiry": m.get("expiry"), "symbol": m.get("symbol"),
                "forward": m.get("forward"), "future": m.get("future_price"),
                "fwd_strikes": m.get("fwd_strikes"), "decimals": m.get("decimals")},
        "us": {"rows": rows(u, False), "expiry": u.get("expiry"), "symbol": u.get("symbol"),
               "future": u.get("future_price"), "trading_class": u.get("trading_class")},
        # The US side is stored in DOLLARS, always, and the rupee tab converts at
        # read time using this rate - the one that applied at capture, not
        # today's. Storing both currencies would double the file to hold one
        # fact twice, and converting with a later rate would quietly restate a
        # six o'clock board at eight o'clock's exchange rate.
        "us_currency": "USD",
        "usdinr": (board.get("usdinr") or {}).get("price"),
    }


def _usable(board: dict) -> bool:
    """Both exchanges live, both futures priced, and some strike two-way on both.

    The clock says the markets overlap; this says the data does. A capture that
    fails here is skipped rather than stored half-blank, because a board with one
    side frozen looks ordinary for ever afterwards.
    """
    m, u = board.get("mcx") or {}, board.get("us") or {}
    if not m.get("rows") or not u.get("rows"):
        return False
    if not u.get("connected") or u.get("delayed"):
        return False
    if not m.get("forward") or not u.get("future_price"):
        return False

    def two_way(chain):
        for r in chain["rows"]:
            for side in ("ce", "pe"):
                leg = r.get(side) or {}
                if leg.get("bid") and leg.get("ask"):
                    return True
        return False

    return two_way(m) and two_way(u)


def snapshot(slot: str, commodity: str, month: int = 0) -> str:
    """Store the current board for `slot`. Idempotent; returns a status string."""
    if slot not in SLOTS:
        return f"unknown slot {slot!r}"
    if commodity not in COMMODITIES:
        return f"unknown commodity {commodity!r}"
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        from app.routes.crude_iv import _payload
        from app.services import dhan_feed

        now = datetime.now()                       # server runs in IST
        hh, mm = SLOTS[slot]
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < start or now > start + timedelta(minutes=_window_min(slot)):
            return "outside capture window; skipped"
        if not dhan_feed.is_market_open():
            return "MCX closed; skipped"

        # None, not 10 - the route's own per-month default (15 front, 7 next) is
        # what the screen renders, and history has to be the same board or the
        # stored one is ten strikes narrower than the live one it claims to be.
        board = _payload(window=None, commodity=commodity, month=month)
        if not _usable(board):
            return "one side not live or not quoting two-way; skipped"

        today = now.date().isoformat()
        db = SessionLocal()
        try:
            if db.query(CrudeIvSnapshot.id).filter(
                    CrudeIvSnapshot.snap_date == today,
                    CrudeIvSnapshot.slot == slot,
                    CrudeIvSnapshot.commodity == commodity,
                    CrudeIvSnapshot.month == month).first():
                return "already snapped this slot"
            m, u = board["mcx"], board["us"]
            m_iv, u_iv = _atm_iv(m.get("rows") or []), _atm_iv(u.get("rows") or [])
            db.add(CrudeIvSnapshot(
                snap_date=today, slot=slot, commodity=commodity, month=month,
                weekday=now.weekday(),
                mcx_forward=m.get("forward"), mcx_future=m.get("future_price"),
                us_future=u.get("future_price"),
                usdinr=(board.get("usdinr") or {}).get("price"),
                mcx_atm_iv=m_iv, us_atm_iv=u_iv,
                iv_diff=round(m_iv - u_iv, 2) if (m_iv and u_iv) else None,
                payload_json=json.dumps(
                    {"captured_at": now.isoformat(timespec="seconds"), **_pack(board)},
                    separators=(",", ":")),
            ))
            db.commit()
            _cache.clear()
            return "snapped"
        except Exception as e:                     # noqa: BLE001 - unique race etc.
            db.rollback()
            return f"store error: {e}"
        finally:
            db.close()
    finally:
        _lock.release()


def snapshot_all(slot: str) -> dict:
    """Both commodities and both months for one slot."""
    return {f"{c}_{m}": snapshot(slot, c, m) for c in COMMODITIES for m in MONTHS}


def get_history(commodity: str = "crude", month: int = 0, slot: str = "all",
                days: int = 3, date: str | None = None) -> dict:
    """Stored boards, newest first. Static once written - fetch, do not poll."""
    commodity = commodity if commodity in COMMODITIES else "crude"
    month = 1 if month == 1 else 0
    slot = slot if slot in SLOTS else "all"
    try:
        days = max(1, min(int(days), 30))
    except (TypeError, ValueError):
        days = 3

    key = (commodity, month, slot, days, date)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    db = SessionLocal()
    try:
        q = db.query(CrudeIvSnapshot).filter(
            CrudeIvSnapshot.commodity == commodity,
            CrudeIvSnapshot.month == month)
        if slot != "all":
            q = q.filter(CrudeIvSnapshot.slot == slot)
        if date:
            q = q.filter(CrudeIvSnapshot.snap_date == date)
        else:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            q = q.filter(CrudeIvSnapshot.snap_date >= cutoff)
        rows = q.order_by(CrudeIvSnapshot.snap_date.desc(),
                          CrudeIvSnapshot.slot.desc()).limit(400).all()
        snaps = []
        for r in rows:
            try:
                body = json.loads(r.payload_json)
            except ValueError:
                continue
            snaps.append({
                "snap_date": r.snap_date, "slot": r.slot, "weekday": r.weekday,
                "mcx_forward": r.mcx_forward, "mcx_future": r.mcx_future,
                "us_future": r.us_future, "usdinr": r.usdinr,
                "mcx_atm_iv": r.mcx_atm_iv, "us_atm_iv": r.us_atm_iv,
                "iv_diff": r.iv_diff,
                "captured_at": body.pop("captured_at", None),
                "board": body,
            })
        data = {"commodity": commodity, "month": month, "slot": slot,
                "slots": list(SLOTS), "count": len(snaps), "snapshots": snaps}
    finally:
        db.close()

    if len(_cache) > 32:
        _cache.clear()
    _cache[key] = (now, data)
    return data


def prune(days: int = 370) -> int:
    """Nightly retention. Returns rows removed."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        n = db.query(CrudeIvSnapshot).filter(CrudeIvSnapshot.snap_date < cutoff).delete()
        db.commit()
        return int(n or 0)
    except Exception:                              # noqa: BLE001
        db.rollback()
        return 0
    finally:
        db.close()
