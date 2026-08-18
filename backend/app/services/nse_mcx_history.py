"""NSE vs MCX board history — nine snapshots a trading day, 10:00 to 23:15 IST.

The client asked to track how the same strike drifts apart between the two
exchanges through the day, and chose the WHOLE table over an ATM-only summary,
so every strike is stored exactly as the live screen shows it.

This is the only record that will ever exist. Neither Angel, Dhan nor IBKR
serves NSE-commodity history, so nothing can be backfilled - the file can only
build forward from the first capture.

Load profile matches the rest of the app (client constraint: "no server / DB
load"):
  capture  : 9x/trading-day x 2 commodities, reads ONLY the in-memory feeds -
             no network, no new subscriptions - then one ~10 KB INSERT each.
             Skips weekends, cold feeds and missed windows, so it never stores
             an empty or mislabelled board.
  read     : on-demand only, one indexed SELECT behind a 60 s TTL cache.
  retention: nightly prune keeps ~370 days (~65 MB at nine slots, measured at
             10 KB a board; the disk has 33 GB free).

Going from three slots to nine (client, 18-Aug) costs nothing that matters and
it was measured before it was done: 180 KB of writes a day, and a 30-day graph
request parses 32 ms of JSON once a minute behind the cache. Nothing here polls
- the 3 s poll on the live board reads memory and never touches this file.
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

# Client's list (18-Aug), every two hours through the evening session plus the
# 15:00 he already had six days of. 23:15 is deliberately 15 min before MCX
# closes at 23:30 - see _window_min(), which stops a late retry from labelling a
# 23:29 quote "23:15".
SLOTS = {"10:00": (10, 0), "12:00": (12, 0), "14:00": (14, 0), "15:00": (15, 0),
         "16:00": (16, 0), "18:00": (18, 0), "20:00": (20, 0), "22:00": (22, 0),
         "23:15": (23, 15)}
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
_MARKET_CLOSE = (23, 30)  # MCX evening close IST; nothing after this is that slot


def _window_min(slot: str) -> int:
    """How late a capture may still be filed under `slot`.

    45 minutes is fine when the next slot is two hours away. It is not fine at
    23:15, where the market shuts 15 minutes later and a retry at 23:50 would
    file a stale 23:29 quote as "23:15". Cap the window at whichever comes
    first: the next slot, the close, or 45 minutes.
    """
    hh, mm = SLOTS[slot]
    start = hh * 60 + mm
    later = [h * 60 + m for h, m in SLOTS.values() if h * 60 + m > start]
    limit = min([_MARKET_CLOSE[0] * 60 + _MARKET_CLOSE[1]] + later)
    return max(1, min(_WINDOW_MIN, limit - start))
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
        if now < slot_start or now > slot_start + timedelta(minutes=_window_min(slot)):
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


# Same threshold the live screen tints amber at: a mid between 0.05 and 16.85
# is not a price anyone can deal at.
_WIDE_SPREAD = 0.25


def _wide(leg: dict) -> bool:
    b, a = leg.get("bid"), leg.get("ask")
    if not (b and a):
        return False
    mid = (b + a) / 2
    return bool(mid and (a - b) / mid > _WIDE_SPREAD)


FUTURE = "future"          # the picker's first entry, in place of a strike


def _point(n: dict, m: dict) -> dict:
    """The two numbers the graph draws, from one NSE leg and one MCX leg.

    `diff` is what the trade actually nets, `mid_diff` is the headline gap
    between the exchanges. Both are MCX minus NSE so positive always means the
    same thing, and the distance between the lines is exactly what the two
    spreads cost - which is the point of showing them together (client, 18-Aug).
    """
    nse_ask, mcx_bid = n.get("ask"), m.get("bid")
    nse_mid, mcx_mid = n.get("mid"), m.get("mid")
    return {
        "nse_ask": nse_ask, "mcx_bid": mcx_bid,
        "nse_bid": n.get("bid"), "mcx_ask": m.get("ask"),
        "nse_mid": nse_mid, "mcx_mid": mcx_mid,
        # None, not 0, when either side had no quote - a gap in the line is
        # honest and a zero would read as "no edge today".
        "diff": round(mcx_bid - nse_ask, 2) if (nse_ask and mcx_bid) else None,
        "mid_diff": round(mcx_mid - nse_mid, 2) if (nse_mid and mcx_mid) else None,
        # Was either side quoted absurdly wide at that moment? The whole app
        # marks those rather than trusting them, and a graph needs it more
        # than a table does: one bad quote drags the axis and buries every
        # honest point. 14-Aug 10:00 on crude 7400 CE recorded an MCX bid of
        # 299.6 against 655.7 two hours later - a -267 spike that is a stale
        # quote, not an edge.
        "wide": _wide(n) or _wide(m),
    }


def series(commodity: str = "crude", strike: float | str | None = None,
           side: str = "ce", days: int = 30, month: int = 0) -> dict:
    """One strike's tradeable difference over time, for the graph.

    The client trades this pair by BUYING on NSE and SELLING on MCX, so the
    number that matters is what he actually nets:

        difference = MCX bid  -  NSE ask

    Not mid against mid. A mid is the midpoint of a spread nobody fills at; buy
    and you pay the ask, sell and you receive the bid. The mid version flatters
    the trade by roughly half of both spreads, which on a thin NSE strike is the
    whole number. Positive means opening the pair pays you.

    Returns the points oldest-first, so a chart can read them straight through,
    plus every strike seen in the window for the picker.
    """
    commodity = commodity if commodity in COMMODITIES else "crude"
    side = "pe" if str(side).lower() == "pe" else "ce"
    is_future = str(strike).lower() == FUTURE
    if is_future:
        strike = FUTURE
    hist = get_history(commodity=commodity, slot="all", days=days, month=month)

    # Count readings per strike, not just which strikes exist. 36 strikes have
    # appeared on some board or other but only 15 were ever quoted on both
    # sides, and the picker was defaulting to the middle of the 36 - landing on
    # one with nothing to draw and an empty page (18-Aug).
    seen: dict[float, int] = {}
    fut_seen = 0
    points = []
    for snap in hist["snapshots"]:
        rows = ((snap.get("board") or {}).get("options") or {}).get("rows") or []
        # Counted by the SAME rule as a strike - readings the tradeable line can
        # actually be drawn from. Counting every snapshot instead made the
        # future the best-covered entry in the picker, so the default landed on
        # the one contract whose main line has no history at all (18-Aug).
        _f = (snap.get("board") or {}).get("future") or {}
        if ((_f.get("nse") or {}).get("ask") and (_f.get("mcx") or {}).get("bid")):
            fut_seen += 1
        for r in rows:
            seen.setdefault(r["strike"], 0)
            for sd in ("ce", "pe"):
                leg = r.get(sd) or {}
                if (leg.get("nse") or {}).get("ask") and (leg.get("mcx") or {}).get("bid"):
                    seen[r["strike"]] += 1
                    break
        if strike is None:
            continue
        fut = (snap.get("board") or {}).get("future") or {}
        if is_future:
            n, m = fut.get("nse") or {}, fut.get("mcx") or {}
        else:
            row = next((r for r in rows if abs(r["strike"] - strike) < 1e-9), None)
            leg = (row or {}).get(side) or {}
            n, m = leg.get("nse") or {}, leg.get("mcx") or {}
        pt = _point(n, m)
        pt.update({
            "date": snap["snap_date"], "slot": snap["slot"],
            "captured_at": snap.get("captured_at"),
            # Where the underlying stood at that moment - the client asked for
            # it beside every reading, because +30 on a 7,400 call means one
            # thing with the future at 8,100 and another at 7,500.
            "mcx_future": (m.get("mid") if is_future else (fut.get("mcx") or {}).get("mid")),
        })
        points.append(pt)

    points.reverse()          # get_history returns newest first; a chart reads forward
    usable = sorted(k for k, n in seen.items() if n)
    # The future leads the picker. It is the one line that is always drawable -
    # both exchanges quote it two-way all session, unlike the thin far strikes.
    opts = [{"strike": FUTURE, "label": "Future", "readings": fut_seen,
             "mid_readings": len(hist["snapshots"])}]
    opts += [{"strike": k, "readings": seen[k]} for k in usable]
    return {
        "commodity": commodity, "month": month, "side": side,
        "strike": strike,
        "is_future": is_future,
        "formula": "MCX bid - NSE ask",
        "mid_formula": "MCX mid - NSE mid",
        # Only strikes with something to draw, newest count alongside, so the
        # picker cannot offer a dead one and can say how much is behind each.
        "strikes": usable,
        "strike_options": opts,
        "count": sum(1 for p in points if p["diff"] is not None),
        "mid_count": sum(1 for p in points if p["mid_diff"] is not None),
        "points": points,
        "slots": list(SLOTS),
        "note": ("Buy on NSE at the ask, sell on MCX at the bid. Positive means "
                 "opening the pair pays you. The mid line is the plain gap "
                 "between the two exchanges; the space between the lines is "
                 "what both spreads cost. Captured at "
                 + ", ".join(SLOTS) + " IST."),
    }


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
