"""BANKEX / BANKNIFTY daily-close boards from the exchanges' bhavcopies.

The client asked (23-Sep-2026) for more history to test the BANKEX-vs-
BANKNIFTY pairs than the 10:00 / 15:30 snapshots can give, and the only past
data either exchange publishes is the daily bhavcopy: one row per contract
with close, settlement price, OI and volume. BSE and NSE both serve the
common "UDiFF" file (BhavCopy_<EXCH>_FO_0_0_0_YYYYMMDD_F_0000) back to
January 2024, free and without a login, so that is where this starts.

What is stored (bank_opt_daily): every option row the file has for the two
indices within 6,000 points of the day's underlying, every expiry. The files
list only contracts that saw activity, so a strike or an expiry nobody
traded is simply absent. The board for a date is then built the way the Live
view builds its own: the current contract per index (the nearest expiry
still ahead of that day's close - the monthly contract since 2025, when only
monthlies are listed, and the front weekly in 2024), BANKEX ATM on 500s, the
BANKNIFTY strike the same points from its spot, the earlier expiry sold and
the later bought. A leg is priced at its close when it traded and at the
exchange's settlement price when it did not, and says which.

Network: one small GET per index per day (BSE ~170 KB CSV, NSE ~1.1 MB zip),
paced at 0.4 s, in a background thread; idempotent over stored dates.
"""
from __future__ import annotations

import csv
import io
import logging
import threading
import time
import zipfile
from datetime import date, datetime, timedelta

import requests

from app.database import SessionLocal
from app.models import BankOptDaily
from app.services.bank_options_service import DISPLAY_OFFSETS, INDICES, STRIKE_STEPS

log = logging.getLogger("bank_daily_history")

SINCE = date(2024, 1, 1)
RADIUS = 6000                                   # points from the underlying; the live subscription radius
_PAUSE = 0.4
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
       "Accept": "*/*"}
_URLS = {
    "BANKNIFTY": "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d}_F_0000.csv.zip",
    "BANKEX": "https://www.bseindia.com/download/Bhavcopy/Derivative/BhavCopy_BSE_FO_0_0_0_{d}_F_0000.CSV",
}
_REFERER = {"BANKNIFTY": "https://www.nseindia.com/", "BANKEX": "https://www.bseindia.com/"}
_WEEKDAY_NAME = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_lock = threading.Lock()
_status = {"running": False, "msg": "", "days": 0, "rows": 0, "errors": 0, "at": None}
_no_file: set[tuple[str, str]] = set()          # (index, date) the exchange has no file for - a holiday
# A miss inside this many days is not remembered: BSE answered the 17-Sep-2026
# file with nothing on 23-Sep morning and served it an hour later, so a recent
# date is asked for again by the next 07:15 refresh instead of being written
# off for the life of the process.
_SETTLED_AFTER_DAYS = 10
_cache: dict = {}
_CACHE_TTL = 60.0


def _num(v) -> float | None:
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def parse(index_name: str, text: str, day: str | None = None) -> list[dict]:
    """The index's option rows out of a UDiFF bhavcopy, within RADIUS of the underlying."""
    rows: dict[tuple, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("TckrSymb") or "").strip() != index_name or (row.get("FinInstrmTp") or "").strip() != "IDO":
            continue
        side = (row.get("OptnTp") or "").strip()
        strike, under, expiry = _num(row.get("StrkPric")), _num(row.get("UndrlygPric")), (row.get("XpryDt") or "").strip()[:10]
        if side not in ("CE", "PE") or not strike or len(expiry) != 10:
            continue
        if under and abs(strike - under) > RADIUS:
            continue
        lot = _num(row.get("NewBrdLotQty"))
        # keyed so a contract printed twice cannot trip the unique index
        rows[(expiry, strike, side)] = {
            "index_name": index_name, "trade_date": day or (row.get("TradDt") or "").strip()[:10],
            "expiry": expiry, "strike": strike, "side": side,
            "close": _num(row.get("ClsPric")), "settle": _num(row.get("SttlmPric")),
            "last": _num(row.get("LastPric")), "prev_close": _num(row.get("PrvsClsgPric")),
            "volume": _num(row.get("TtlTradgVol")), "oi": _num(row.get("OpnIntrst")),
            "underlying": under, "lot_size": int(lot) if lot else None}
    return list(rows.values())


def fetch(index_name: str, day: str) -> list[dict] | None:
    """Download and parse one day's file; None when the exchange has none (holiday)."""
    url = _URLS[index_name].format(d=day.replace("-", ""))
    r = requests.get(url, headers={**_UA, "Referer": _REFERER[index_name]}, timeout=60)
    if r.status_code == 404:
        return None                             # no file: a holiday, or today's not published yet
    r.raise_for_status()                        # a 403 is a block, not a holiday: counted, retried later
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                return None
            text = z.read(names[0]).decode("utf-8", "replace")
    else:
        text = r.content.decode("utf-8", "replace")
        if text.lstrip()[:1] == "<":            # an HTML error page served with 200
            return None
    return parse(index_name, text, day)


def store(rows: list[dict], index_name: str, day: str) -> int:
    db = SessionLocal()
    try:
        db.query(BankOptDaily).filter(BankOptDaily.index_name == index_name, BankOptDaily.trade_date == day).delete()
        if rows:
            db.bulk_insert_mappings(BankOptDaily, rows)
        db.commit()
        _cache.clear()
        return len(rows)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def have_dates(index_name: str) -> set[str]:
    db = SessionLocal()
    try:
        return {d for (d,) in db.query(BankOptDaily.trade_date).filter(BankOptDaily.index_name == index_name).distinct()}
    finally:
        db.close()


def status() -> dict:
    out = dict(_status)
    try:
        dates = have_dates("BANKEX") & have_dates("BANKNIFTY")
        out.update(stored_days=len(dates), first=min(dates) if dates else None, last=max(dates) if dates else None)
    except Exception:  # noqa: BLE001
        pass
    return out


def backfill(since: date = SINCE, until: date | None = None, pause: float = _PAUSE) -> dict:
    """Every weekday from `since` to `until` (default today) that is not stored
    yet, both indices. Idempotent; a date the exchange has no file for is
    remembered for the process so it is not asked for again."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "msg": "already running"}
    today = date.today()
    until = until or today
    _status.update(running=True, msg="starting", days=0, rows=0, errors=0, at=datetime.now().isoformat(timespec="seconds"))
    try:
        from app.services import market_calendar
        have = {ix: have_dates(ix) for ix in INDICES}
        d, streak = since, 0
        while d <= until:
            ds = d.isoformat()
            if d.weekday() >= 5:
                d += timedelta(days=1)
                continue
            try:
                holiday = market_calendar.holiday("NSE", ds)
            except Exception:  # noqa: BLE001
                holiday = None
            for ix in INDICES:
                if ds in have[ix] or (ix, ds) in _no_file or holiday:
                    continue
                _status["msg"] = f"{ix} {ds}"
                try:
                    rows = fetch(ix, ds)
                except Exception as e:  # noqa: BLE001
                    _status["errors"] += 1
                    streak += 1
                    log.warning("bank bhavcopy %s %s: %s", ix, ds, e)
                    if streak >= 8:
                        _status["msg"] = f"stopped after repeated network errors at {ds}"
                        return {"ok": False, "msg": _status["msg"]}
                    time.sleep(pause)
                    continue
                streak = 0
                if not rows:
                    if d < today - timedelta(days=_SETTLED_AFTER_DAYS):
                        _no_file.add((ix, ds))    # an old miss is a holiday; a recent one is asked for again
                else:
                    try:
                        store(rows, ix, ds)
                    except Exception as e:  # noqa: BLE001
                        _status["errors"] += 1
                        log.warning("bank bhavcopy store %s %s: %s", ix, ds, e)
                    else:
                        have[ix].add(ds)
                        _status["days"] += 1
                        _status["rows"] += len(rows)
                time.sleep(pause)
            d += timedelta(days=1)
        _status["msg"] = f"complete: {_status['days']} index-days, {_status['rows']} rows, {_status['errors']} errors"
        log.info("bank daily history backfill %s", _status["msg"])
        return {"ok": True, "days": _status["days"], "rows": _status["rows"], "errors": _status["errors"]}
    finally:
        _status["running"] = False
        _lock.release()


def refresh_recent(days: int = 7) -> dict:
    return backfill(since=date.today() - timedelta(days=days))


def start_backfill(since: date = SINCE) -> bool:
    if _status["running"]:
        return False
    threading.Thread(target=backfill, args=(since,), daemon=True, name="bank-daily-backfill").start()
    return True


# --------------------------------------------------------------------------- #
# reads: one board per trade date, in the Live view's shape
# --------------------------------------------------------------------------- #
def current_expiry(expiries, day: str) -> str | None:
    """The current contract after `day`'s close: the nearest expiry still ahead
    of the day. Since 2025 only monthly BANKEX / BANKNIFTY contracts are listed,
    so this is the Live view's monthly; in 2024 it is the front weekly, which is
    also the only BANKEX contract that traded then (the bhavcopy lists a monthly
    only once somebody dealt in it)."""
    return min((e for e in expiries if e > day), default=None)


def _leg(row, strike: float, side: str) -> dict:
    if row is None:
        return {"strike": strike, "side": side, "listed": False, "expiry": None, "price": None, "close": None,
                "settle": None, "oi": None, "volume": None, "traded": False, "lot_size": None}
    traded = bool(row.volume and row.volume > 0)
    price = row.close if (traded and row.close) else (row.settle or row.close)
    return {"strike": row.strike, "side": side, "listed": True, "expiry": row.expiry, "price": price,
            "close": row.close, "settle": row.settle, "oi": row.oi, "volume": row.volume, "traded": traded,
            "lot_size": row.lot_size}


def build_board(day: str, rows: list) -> dict:
    """The day's board from its stored rows (both indices)."""
    by_index = {ix: [r for r in rows if r.index_name == ix] for ix in INDICES}
    indices, contracts = {}, {}
    for ix in INDICES:
        rs = by_index[ix]
        spot = next((r.underlying for r in rs if r.underlying), None)
        cur = current_expiry({r.expiry for r in rs}, day)
        contracts[ix] = {(r.strike, r.side): r for r in rs if r.expiry == cur}
        strikes = sorted({k[0] for k in contracts[ix] if k[0] % STRIKE_STEPS[ix] == 0})
        atm = min(strikes, key=lambda k: (abs(k - spot), -k)) if strikes and spot else None
        lot = next((r.lot_size for r in contracts[ix].values() if r.lot_size), None)
        indices[ix] = {"spot": spot, "atm": atm, "expiry": cur, "lot_size": lot}
    be, bn = indices["BANKEX"]["expiry"], indices["BANKNIFTY"]["expiry"]
    buy = sell = None
    if be and bn and be != bn:
        buy, sell = ("BANKNIFTY", "BANKEX") if be < bn else ("BANKEX", "BANKNIFTY")
    out_rows = []
    be_atm, be_spot, bn_spot = indices["BANKEX"]["atm"], indices["BANKEX"]["spot"], indices["BANKNIFTY"]["spot"]
    if be_atm and be_spot and bn_spot:
        step = STRIKE_STEPS["BANKNIFTY"]
        for offset in DISPLAY_OFFSETS:
            be_k = be_atm + offset
            bn_k = round((bn_spot + (be_k - be_spot)) / step) * step
            for side in ("CE", "PE"):
                legs = {"bankex": _leg(contracts["BANKEX"].get((be_k, side)), be_k, side),
                        "banknifty": _leg(contracts["BANKNIFTY"].get((bn_k, side)), bn_k, side)}
                buy_leg = legs[buy.lower()] if buy else None
                sell_leg = legs[sell.lower()] if sell else None
                buy_px = buy_leg["price"] if buy_leg else None
                sell_px = sell_leg["price"] if sell_leg else None
                priced = bool(buy_px and sell_px)
                out_rows.append({"side": side, "offset_points": offset, **legs,
                                 "buy_price": buy_px, "sell_price": sell_px,
                                 "difference_points": round(sell_px - buy_px, 2) if priced else None,
                                 "settled": bool(priced and not (buy_leg["traded"] and sell_leg["traded"]))})
    wd = datetime.strptime(day, "%Y-%m-%d").weekday()
    return {"date": day, "weekday": _WEEKDAY_NAME[wd], "slot": "close", "captured_at": None,
            "indices": indices, "buy_index": buy, "sell_index": sell, "rows": out_rows}


def get_history(weekday: int | None = None, days: int = 7, date_: str | None = None) -> dict:
    try:
        days = max(1, min(int(days), 120))
    except (TypeError, ValueError):
        days = 7
    key = (weekday, days, date_)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    db = SessionLocal()
    try:
        if date_:
            dates = [date_]
        else:
            q = db.query(BankOptDaily.trade_date).filter(BankOptDaily.index_name == "BANKEX").distinct()
            all_dates = sorted((d for (d,) in q), reverse=True)
            if weekday is not None:
                all_dates = [d for d in all_dates if datetime.strptime(d, "%Y-%m-%d").weekday() == weekday]
            dates = all_dates[:days]
        rows = db.query(BankOptDaily).filter(BankOptDaily.trade_date.in_(dates)).all() if dates else []
    finally:
        db.close()
    by_date: dict[str, list] = {}
    for r in rows:
        by_date.setdefault(r.trade_date, []).append(r)
    boards = [build_board(d, by_date[d]) for d in dates if d in by_date]
    data = {"source": "daily", "slot": "close", "weekday": _WEEKDAY_NAME[weekday] if weekday is not None else None,
            "days": days, "date": date_, "count": len(boards), "dates": [b["date"] for b in boards], "boards": boards,
            "note": "daily close from the BSE and NSE bhavcopy since January 2024; the nearest expiry after the "
                    "day is the current contract; a leg that did not trade is priced at the exchange's settlement price"}
    if len(_cache) > 32:
        _cache.clear()
    _cache[key] = (now, data)
    return data
