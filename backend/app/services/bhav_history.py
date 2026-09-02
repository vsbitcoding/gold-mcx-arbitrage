"""Multi-year spread history from MCX's daily bhavcopy (client, 02-Sep-2026).

He wants the Spread History dialog to reach back to 2021, for every symbol,
for cross pairs as well as calendar ones, and in two shapes: month-wise (one
specific pair of contracts, day by day) and continuous (one unbroken line
across years, the current contracts on every day, rolled at expiry).

Source
------
MCX's own daily bhavcopy - every contract's official close and volume - but
not from mcxindia.com, which Akamai closes to scripts (403 on the page and
the API, from the server and from a desktop browser alike, probed 02-Sep).
Samco republishes the identical files, one CSV per trading day, from April
2016 onward, behind a plain form: POST a date range, get a list of links, GET
each link. A month per request is the practical unit - a whole year answers
nothing.

Only FUTCOM rows for the nine symbols the board trades are kept: about 45
contract-days per file, ~60,000 rows for 2021 to date. The download runs
once in the background (~1,400 files, paced), and a morning job appends the
newest day.

Maths
-----
Exactly the board's, on closes instead of bid/ask:
  calendar : far.close - near.close                     (same symbol)
  cross    : big.close x MULT[big] - small.close x MULT[small]
             with the template's month matching (same / next / same-or-next)
% is over the near or small leg. One value per day - the client's rule.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import func

from app.config import MULTIPLIERS
from app.database import SessionLocal
from app.models import McxDailyClose

log = logging.getLogger("bhav_history")

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
       "Referer": "https://www.samco.in/bhavcopy-nse-bse-mcx",
       "X-Requested-With": "XMLHttpRequest"}
_PAGE = "https://www.samco.in/bhavcopy-nse-bse-mcx"
_FORM = "https://www.samco.in/bse_nse_mcx/getBhavcopy"
_LINK_RE = re.compile(r'href="(https://www\.samco\.in/bse_nse_mcx/datacopy/[^"]+)"')
_PACE_SECONDS = 0.6

# short name (board vocabulary) -> MCX symbol in the bhavcopy
SYMBOLS = {
    "petal": "GOLDPETAL", "guinea": "GOLDGUINEA", "ten": "GOLDTEN", "mini": "GOLDM",
    "gold": "GOLD", "silver": "SILVER", "silverm": "SILVERM", "silvermic": "SILVERMIC",
    "silver100": "SILVER100",
}
_SHORT = {v: k for k, v in SYMBOLS.items()}
LABELS = {
    "petal": "PETAL", "guinea": "GUINEA", "ten": "TEN", "mini": "MINI", "gold": "GOLD",
    "silver": "SILVER", "silverm": "SILVER MINI", "silvermic": "SILVER MIC",
    "silver100": "SILVER 100",
}

_status: dict = {"running": False, "msg": "never run", "files": 0, "rows": 0, "at": None}
_lock = threading.Lock()


def status() -> dict:
    return dict(_status)


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def _session() -> requests.Session:
    s = requests.Session()
    s.get(_PAGE, headers=_UA, timeout=30)
    return s


def _links(s: requests.Session, start: date, end: date) -> list[str]:
    r = s.post(_FORM, headers=_UA, timeout=90, data={
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "bhavcopy_data[]": "MCX", "show_or_down": "1"})
    r.raise_for_status()
    return _LINK_RE.findall(r.text)


def _links_resilient(s: requests.Session, start: date, end: date) -> list[str]:
    """A month per request - except Samco answers HTTP 500 for whole months
    between Oct-2025 and Mar-2026 (probed 02-Sep) while half-months and weeks
    of the same span answer fine. So a failed window is split in two and
    retried, down to single days, and the pieces are joined."""
    try:
        return _links(s, start, end)
    except Exception as e:  # noqa: BLE001
        if start == end:
            log.warning("bhav links %s: %s", start, e)
            return []
        mid = start + (end - start) // 2
        time.sleep(_PACE_SECONDS)
        return (_links_resilient(s, start, mid)
                + _links_resilient(s, mid + timedelta(days=1), end))


def _parse_expiry(s: str) -> str | None:
    s = (s or "").strip()
    for fmt in ("%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_trade_date(s: str) -> str | None:
    return _parse_expiry(s)


def ingest_csv(text: str) -> int:
    """Upsert our symbols' FUTCOM rows from one bhavcopy CSV. Returns rows written."""
    rows = list(csv.DictReader(io.StringIO(text)))
    keep = []
    for r in rows:
        # Files before ~2017 carry no INSTRUMENTNAME at all - MCX had no
        # options then, so every row is a future; blank OPTIONTYPE and
        # STRIKEPRICE say the same thing. Later files name it FUTCOM.
        inst = (r.get("INSTRUMENTNAME") or "").strip()
        if inst and inst != "FUTCOM":
            continue
        if not inst and ((r.get("OPTIONTYPE") or "").strip() or (r.get("STRIKEPRICE") or "").strip()):
            continue
        sym = (r.get("SYMBOL") or "").strip().upper()
        if sym not in _SHORT:
            continue
        td = _parse_trade_date(r.get("DATE", ""))
        ex = _parse_expiry(r.get("EXPIRY_DATE", ""))
        if not td or not ex:
            continue
        try:
            close = float(r.get("CLOSE") or 0) or None
            vol = float(r.get("VOLUME_IN_LOTS") or 0)
        except ValueError:
            continue
        keep.append((td, sym, ex, close, vol))
    if not keep:
        return 0
    db = SessionLocal()
    try:
        td = keep[0][0]
        have = {(x.symbol, x.expiry): x for x in
                db.query(McxDailyClose).filter(McxDailyClose.trade_date == td).all()}
        n = 0
        for td, sym, ex, close, vol in keep:
            row = have.get((sym, ex))
            if row:
                row.close, row.volume = close, vol
            else:
                db.add(McxDailyClose(trade_date=td, symbol=sym, expiry=ex, close=close, volume=vol))
            n += 1
        db.commit()
        return n
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


def have_dates() -> set[str]:
    db = SessionLocal()
    try:
        return {d for (d,) in db.query(McxDailyClose.trade_date).distinct()}
    finally:
        db.close()


def backfill(start: date, end: date, skip_have: bool = True) -> dict:
    """Download every trading day in [start, end], one month per request.
    Safe to re-run: days already stored are skipped."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "msg": "already running"}
    _status.update(running=True, msg="starting", files=0, rows=0, at=time.time())
    try:
        s = _session()
        done = have_dates() if skip_have else set()
        cur = date(start.year, start.month, 1)
        while cur <= end:
            nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            m_end = min(nxt - timedelta(days=1), end)
            m_start = max(cur, start)
            links = _links_resilient(s, m_start, m_end)
            for url in links:
                m = re.search(r"(\d{8})_MCX", _decode_name(url))
                day = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None
                if day and day in done:
                    continue
                try:
                    f = s.get(url, headers=_UA, timeout=90)
                    if f.status_code != 200 or len(f.content) < 200:
                        continue
                    n = ingest_csv(f.content.decode("utf-8", "ignore"))
                    _status["files"] += 1
                    _status["rows"] += n
                except Exception as e:  # noqa: BLE001
                    log.warning("bhav file %s: %s", day, e)
                time.sleep(_PACE_SECONDS)
            _status["msg"] = f"{cur.strftime('%Y-%m')} done ({_status['files']} files)"
            log.info("bhav backfill: %s", _status["msg"])
            cur = nxt
        _status["msg"] = f"complete: {_status['files']} files, {_status['rows']} rows"
        return {"ok": True, **_status}
    finally:
        _status["running"] = False
        _lock.release()


def _decode_name(url: str) -> str:
    """Samco encodes the server path in base64 after /datacopy/."""
    import base64
    try:
        return base64.b64decode(url.rsplit("/", 1)[-1] + "==").decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return url


def refresh_recent(days: int = 4) -> dict:
    """Morning job: pull the last few days (idempotent)."""
    end = date.today() - timedelta(days=1)
    return backfill(end - timedelta(days=days), end)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _closes(symbol_short: str, start: str, end: str) -> dict[str, dict[str, float]]:
    """{trade_date: {expiry: close}} for one symbol in a date range."""
    db = SessionLocal()
    try:
        q = (db.query(McxDailyClose.trade_date, McxDailyClose.expiry, McxDailyClose.close)
             .filter(McxDailyClose.symbol == SYMBOLS[symbol_short],
                     McxDailyClose.trade_date >= start, McxDailyClose.trade_date <= end,
                     McxDailyClose.close.isnot(None)))
        out: dict[str, dict[str, float]] = {}
        for td, ex, cl in q:
            out.setdefault(td, {})[ex] = cl
        return out
    finally:
        db.close()


def expiries(symbol_short: str) -> list[str]:
    db = SessionLocal()
    try:
        return sorted(e for (e,) in db.query(McxDailyClose.expiry)
                      .filter(McxDailyClose.symbol == SYMBOLS[symbol_short]).distinct())
    finally:
        db.close()


def coverage() -> dict:
    db = SessionLocal()
    try:
        lo, hi, n = db.query(func.min(McxDailyClose.trade_date),
                             func.max(McxDailyClose.trade_date),
                             func.count(McxDailyClose.id)).one()
        return {"from": lo, "to": hi, "rows": n}
    finally:
        db.close()


def _rate(px: float, short: str) -> float:
    return px * MULTIPLIERS.get(short, 1.0)


def _current_months(by_exp: dict[str, float], day: str) -> list[str]:
    """Expiries still current on `day`, nearest first (expiry-day counts)."""
    return sorted(e for e in by_exp if e >= day)


def _match(small_exps: list[str], big_exp: str, mode: str) -> str | None:
    """The board's cross-pair month matching, on expiry strings."""
    same = [e for e in small_exps if e[:7] == big_exp[:7]]
    after = [e for e in small_exps if e > big_exp]
    if mode == "same":
        return same[0] if same else None
    if mode == "next":
        return after[0] if after else None
    return same[0] if same else (after[0] if after else None)     # sonext


def calendar_series(symbol: str, near_exp: str | None, far_exp: str | None,
                    start: str, end: str, continuous: bool = False, rank: int = 0) -> list[dict]:
    """Month-wise: the two named expiries. Continuous: on every day, the
    current month and the one after it (rank 0 = M1-M2, 1 = M2-M3)."""
    data = _closes(symbol, start, end)
    rows = []
    for td in sorted(data):
        by = data[td]
        if continuous:
            cur = _current_months(by, td)
            if len(cur) < rank + 2:
                continue
            n_e, f_e = cur[rank], cur[rank + 1]
        else:
            n_e, f_e = near_exp, far_exp
        n, f = by.get(n_e), by.get(f_e)
        if not n or not f:
            continue
        diff = round(f - n, 2)
        rows.append({"date": td, "near": n, "far": f, "diff": diff,
                     "pct": round(diff / n * 100, 3), "near_exp": n_e, "far_exp": f_e})
    return rows


def cross_series(big: str, small: str, mode: str, big_exp: str | None, small_exp: str | None,
                 start: str, end: str, continuous: bool = False) -> list[dict]:
    """Month-wise: the two named contracts. Continuous: on every day the
    big leg's current month, the small leg matched by the template's rule."""
    bd, sd = _closes(big, start, end), _closes(small, start, end)
    rows = []
    for td in sorted(set(bd) & set(sd)):
        if continuous:
            bcur = _current_months(bd[td], td)
            if not bcur:
                continue
            b_e = bcur[0]
            s_e = _match(_current_months(sd[td], td), b_e, mode)
        else:
            b_e, s_e = big_exp, small_exp
        if not s_e:
            continue
        b, s = bd[td].get(b_e), sd[td].get(s_e)
        if not b or not s:
            continue
        bv, sv = _rate(b, big), _rate(s, small)
        diff = round(bv - sv, 2)
        rows.append({"date": td, "big": b, "small": s, "big_rate": round(bv, 2),
                     "small_rate": round(sv, 2), "diff": diff,
                     "pct": round(diff / sv * 100, 3) if sv else None,
                     "big_exp": b_e, "small_exp": s_e})
    return rows
