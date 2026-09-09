"""NSE-vs-MCX daily option premiums since April 2024 (client, 08-Sep-2026).

Two sources, one table (NseMcxOptDaily):

  NSE  - the exchange's own historical data service behind the "All Historical
         Data" tab of nseindia.com/commodity-getquote. One call with csv=true
         per (expiry, CE|PE) returns every strike of every day of that contract
         (checked 08-Sep: CRUDEOIL 17-Apr-2024 CE = 2,236 rows). The JSON form
         of the same call caps at 70 rows, so only the CSV form is used.
  MCX  - the daily bhavcopy the Spread History already downloads (Samco
         mirror); its OPTFUT rows carry close, previous close, volume and OI.

Both are CLOSING figures - neither exchange publishes intraday history - so
the comparison here is close against close, per strike, per day. The pairing
of contracts follows the live screen: an NSE expiry against the MCX expiry
nearest to it.

Load: a one-time backfill (about 120 NSE calls, paced) plus a morning top-up
of the listed expiries; reads are indexed lookups.
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

from app.database import SessionLocal
from app.models import NseMcxOptDaily

log = logging.getLogger("nse_opt_history")

SYMBOLS = {"crude": "CRUDEOIL", "natgas": "NATURALGAS"}
# The client reads crude in round hundreds; gas steps 5 on both exchanges.
STEP = {"crude": 100.0, "natgas": 5.0}
SINCE = date(2024, 4, 1)

_NSE = "https://www.nseindia.com"
_API = _NSE + "/api/historicalOR/com/derivatives"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
       "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "X-Requested-With": "XMLHttpRequest"}
_PACE = 1.5
_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}

_lock = threading.Lock()
_status: dict = {"running": False, "msg": "never run", "nse_calls": 0, "rows": 0, "at": None}
# Only what the screen can show is stored: strikes on the client's ladder and
# contracts within four months of the day. That keeps two years of both
# exchanges near 300k rows instead of over a million.
_KEEP_DAYS = 120


def _keep(commodity: str, trade_date: str, expiry: str, strike: float) -> bool:
    if strike % STEP[commodity] != 0:
        return False
    try:
        gap = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.strptime(trade_date, "%Y-%m-%d")).days
    except ValueError:
        return False
    return -1 <= gap <= _KEEP_DAYS


def status() -> dict:
    return dict(_status)


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
def _iso(d: str) -> str | None:
    """'17-APR-2024' or '17 Apr 2024' -> '2024-04-17'."""
    s = (d or "").strip().upper().replace(" ", "-")
    m = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{4})$", s)
    if not m or m.group(2) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def _num(v) -> float | None:
    s = str(v or "").strip().replace(",", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _upsert(rows: list[dict]) -> int:
    """rows: dicts with the NseMcxOptDaily columns. Returns rows written."""
    if not rows:
        return 0
    db = SessionLocal()
    try:
        # One bhavcopy carries BOTH commodities, so the existing rows are
        # loaded per (exchange, commodity) - loading only the first batch's
        # commodity let the other one insert duplicates (08-Sep backfill).
        groups = {(r["exchange"], r["commodity"]) for r in rows}
        dates = {r["trade_date"] for r in rows}
        have = {}
        for exch, comm in groups:
            for x in db.query(NseMcxOptDaily).filter(
                    NseMcxOptDaily.exchange == exch, NseMcxOptDaily.commodity == comm,
                    NseMcxOptDaily.trade_date.in_(list(dates))).all():
                have[(x.exchange, x.commodity, x.trade_date, x.expiry, x.option_type, x.strike)] = x
        n = 0
        for r in rows:
            k = (r["exchange"], r["commodity"], r["trade_date"], r["expiry"], r["option_type"], r["strike"])
            row = have.get(k)
            if row is None:
                row = NseMcxOptDaily(**r)
                db.add(row)
                have[k] = row
            else:
                for f in ("close", "settle", "ltp", "prev_close", "volume", "oi"):
                    setattr(row, f, r.get(f))
            n += 1
        db.commit()
        return n
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# NSE
# --------------------------------------------------------------------------- #
def _nse_session(symbol: str) -> requests.Session:
    s = requests.Session()
    s.get(f"{_NSE}/commodity-getquote?symbol={symbol}",
          headers={**_UA, "Referer": f"{_NSE}/commodity-getquote?symbol={symbol}"}, timeout=25)
    return s


def _nse_get(s: requests.Session, symbol: str, params: dict, csv_form: bool = False) -> requests.Response:
    p = {**params, "symbol": symbol}
    if csv_form:
        p["csv"] = "true"
    r = s.get(_API, params=p, headers={**_UA, "Referer": f"{_NSE}/commodity-getquote?symbol={symbol}"}, timeout=90)
    _status["nse_calls"] += 1
    time.sleep(_PACE)
    return r


def nse_expiries_seen(s: requests.Session, symbol: str, since: date, until: date) -> set[str]:
    """Option expiries listed on NSE between two dates. The unfiltered call
    returns one day's board (capped), so it is asked on the first trading
    day of every month and the expiries on those boards are collected."""
    seen: set[str] = set()
    cur = date(since.year, since.month, 1)
    while cur <= until:
        for off in range(0, 6):                      # first weekday with a board
            d = cur + timedelta(days=off)
            if d > until or d.weekday() >= 5:
                continue
            try:
                r = _nse_get(s, symbol, {"from": d.strftime("%d-%m-%Y"), "to": d.strftime("%d-%m-%Y")})
                data = r.json().get("data") or []
            except Exception as e:  # noqa: BLE001
                log.warning("nse expiries %s %s: %s", symbol, d, e)
                data = []
            exps = {_iso(x.get("COM_EXPIRY_DT")) for x in data if x.get("COM_INSTRUMENT") == "OPTFUT"}
            exps.discard(None)
            if exps:
                seen |= exps
                break
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    try:                                              # today's listed ones too
        r = s.get(_API + "/meta", params={"symbol": symbol}, headers={**_UA, "Referer": f"{_NSE}/commodity-getquote?symbol={symbol}"}, timeout=30)
        for e in (r.json().get("data") or [[], [], []])[2]:
            iso = _iso(e)
            if iso:
                seen.add(iso)
    except Exception as e:  # noqa: BLE001
        log.debug("nse meta: %s", e)
    return {e for e in seen if e >= since.isoformat()}


def nse_pull_expiry(s: requests.Session, commodity: str, expiry: str, otype: str,
                    start: date | None = None) -> int:
    """Every strike of every day for one contract side, via the CSV form."""
    symbol = SYMBOLS[commodity]
    exp = datetime.strptime(expiry, "%Y-%m-%d").date()
    frm = start or (exp - timedelta(days=100))
    to = min(exp, date.today())
    if frm > to:
        return 0
    r = _nse_get(s, symbol, {"instrumentType": "OPTFUT", "year": str(exp.year),
                            "expiryDate": exp.strftime("%d-%b-%Y"), "optionType": otype,
                            "from": frm.strftime("%d-%m-%Y"), "to": to.strftime("%d-%m-%Y")}, csv_form=True)
    if r.status_code != 200 or "text/csv" not in (r.headers.get("content-type") or ""):
        raise RuntimeError(f"NSE {symbol} {expiry} {otype}: http {r.status_code} {r.text[:80]!r}")
    text = r.content.decode("utf-8-sig", "ignore")
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        rec = {k.strip(): v for k, v in rec.items() if k}
        td = _iso(rec.get("DATE")); ex = _iso(rec.get("EXPIRY DATE"))
        strike = _num(rec.get("STRIKE PRICE"))
        ot = (rec.get("OPTION TYPE") or "").strip().upper()
        if not td or not ex or strike is None or ot not in ("CE", "PE") or not _keep(commodity, td, ex, strike):
            continue
        rows.append({"exchange": "NSE", "commodity": commodity, "trade_date": td, "expiry": ex,
                     "option_type": ot, "strike": strike,
                     "close": _num(rec.get("CLOSE PRICE")), "settle": _num(rec.get("SETTLE PRICE")),
                     "ltp": _num(rec.get("LAST PRICE")), "prev_close": None,
                     "volume": _num(rec.get("Volume")), "oi": _num(rec.get("OPEN INTEREST"))})
    n = _upsert(rows)
    _status["rows"] += n
    return n


def nse_fut_expiries_seen(s: requests.Session, symbol: str, since: date, until: date) -> set[str]:
    """Futures expiries listed on NSE between two dates, from the monthly boards."""
    seen: set[str] = set()
    cur = date(since.year, since.month, 1)
    while cur <= until:
        for off in range(0, 6):
            d = cur + timedelta(days=off)
            if d > until or d.weekday() >= 5:
                continue
            try:
                r = _nse_get(s, symbol, {"instrumentType": "FUTENR", "from": d.strftime("%d-%m-%Y"), "to": d.strftime("%d-%m-%Y")})
                data = r.json().get("data") or []
            except Exception as e:  # noqa: BLE001
                log.warning("nse fut expiries %s %s: %s", symbol, d, e)
                data = []
            exps = {_iso(x.get("COM_EXPIRY_DT")) for x in data if x.get("COM_INSTRUMENT") == "FUTENR"}
            exps.discard(None)
            if exps:
                seen |= exps
                break
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {e for e in seen if e >= since.isoformat()}


def nse_pull_future(s: requests.Session, commodity: str, expiry: str, start: date | None = None) -> int:
    """One future contract's daily closes (option_type FUT, strike 0)."""
    symbol = SYMBOLS[commodity]
    exp = datetime.strptime(expiry, "%Y-%m-%d").date()
    frm = start or (exp - timedelta(days=130))
    to = min(exp, date.today())
    if frm > to:
        return 0
    r = _nse_get(s, symbol, {"instrumentType": "FUTENR", "year": str(exp.year), "expiryDate": exp.strftime("%d-%b-%Y"),
                            "from": frm.strftime("%d-%m-%Y"), "to": to.strftime("%d-%m-%Y")}, csv_form=True)
    if r.status_code != 200 or "text/csv" not in (r.headers.get("content-type") or ""):
        raise RuntimeError(f"NSE {symbol} FUT {expiry}: http {r.status_code} {r.text[:80]!r}")
    rows = []
    for rec in csv.DictReader(io.StringIO(r.content.decode("utf-8-sig", "ignore"))):
        rec = {k.strip(): v for k, v in rec.items() if k}
        td = _iso(rec.get("DATE")); ex = _iso(rec.get("EXPIRY DATE"))
        if not td or not ex or not _keep(commodity, td, ex, 0.0):
            continue
        rows.append({"exchange": "NSE", "commodity": commodity, "trade_date": td, "expiry": ex,
                     "option_type": "FUT", "strike": 0.0,
                     "close": _num(rec.get("CLOSE PRICE")), "settle": _num(rec.get("SETTLE PRICE")),
                     "ltp": _num(rec.get("LAST PRICE")), "prev_close": None,
                     "volume": _num(rec.get("Volume")), "oi": _num(rec.get("OPEN INTEREST"))})
    n = _upsert(rows)
    _status["rows"] += n
    return n


def _nse_stored_span(commodity: str, expiry: str, kind: str = "OPT") -> tuple[str | None, str | None]:
    from sqlalchemy import func
    db = SessionLocal()
    try:
        q = db.query(func.min(NseMcxOptDaily.trade_date), func.max(NseMcxOptDaily.trade_date)).filter(
            NseMcxOptDaily.exchange == "NSE", NseMcxOptDaily.commodity == commodity,
            NseMcxOptDaily.expiry == expiry)
        q = q.filter(NseMcxOptDaily.option_type == "FUT") if kind == "FUT" else q.filter(NseMcxOptDaily.option_type != "FUT")
        lo, hi = q.one()
        return lo, hi
    finally:
        db.close()


def backfill_nse(since: date = SINCE, commodities: tuple = ("crude", "natgas")) -> dict:
    """Every expiry since `since`, both sides. Expiries already stored to their
    last day are skipped, so a re-run only fetches what is missing."""
    today = date.today()
    out = {"expiries": 0, "rows": 0, "skipped": 0, "errors": []}
    for commodity in commodities:
        symbol = SYMBOLS[commodity]
        s = _nse_session(symbol)
        exps = sorted(nse_expiries_seen(s, symbol, since, today))
        log.info("nse backfill %s: %d expiries since %s", commodity, len(exps), since)
        for exp in exps:
            lo, hi = _nse_stored_span(commodity, exp)
            if hi and hi >= min(exp, today.isoformat()):
                out["skipped"] += 1
                continue
            for otype in ("CE", "PE"):
                for attempt in range(3):
                    try:
                        out["rows"] += nse_pull_expiry(s, commodity, exp, otype)
                        break
                    except Exception as e:  # noqa: BLE001
                        log.warning("nse %s %s %s attempt %d: %s", commodity, exp, otype, attempt + 1, e)
                        time.sleep(5 * (attempt + 1))
                        s = _nse_session(symbol)
                else:
                    out["errors"].append(f"{commodity} {exp} {otype}")
            out["expiries"] += 1
            _status["msg"] = f"NSE {commodity} {exp} done ({out['rows']} rows)"
        for fexp in sorted(nse_fut_expiries_seen(s, symbol, since, today)):
            lo, hi = _nse_stored_span(commodity, fexp, "FUT")
            if hi and hi >= min(fexp, today.isoformat()):
                continue
            for attempt in range(3):
                try:
                    out["rows"] += nse_pull_future(s, commodity, fexp)
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning("nse %s FUT %s attempt %d: %s", commodity, fexp, attempt + 1, e)
                    time.sleep(5 * (attempt + 1))
                    s = _nse_session(symbol)
            else:
                out["errors"].append(f"{commodity} FUT {fexp}")
            _status["msg"] = f"NSE {commodity} future {fexp} done ({out['rows']} rows)"
    return out


def refresh_nse_recent(days: int = 7) -> dict:
    """Morning top-up: the listed expiries, last few days."""
    today = date.today()
    out = {"rows": 0, "errors": []}
    for commodity, symbol in SYMBOLS.items():
        try:
            s = _nse_session(symbol)
            r = s.get(_API + "/meta", params={"symbol": symbol}, headers={**_UA, "Referer": f"{_NSE}/commodity-getquote?symbol={symbol}"}, timeout=30)
            exps = [_iso(e) for e in (r.json().get("data") or [[], [], []])[2]]
            exps = [e for e in exps if e and e >= (today - timedelta(days=days)).isoformat()]
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{commodity} meta: {e}")
            continue
        for exp in exps[:4]:                        # the near ones are the ones that trade
            for otype in ("CE", "PE"):
                try:
                    out["rows"] += nse_pull_expiry(s, commodity, exp, otype, start=today - timedelta(days=days))
                except Exception as e:  # noqa: BLE001
                    out["errors"].append(f"{commodity} {exp} {otype}: {e}")
        try:
            for fexp in sorted(nse_fut_expiries_seen(s, symbol, today - timedelta(days=days), today))[:3]:
                out["rows"] += nse_pull_future(s, commodity, fexp, start=today - timedelta(days=days))
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{commodity} futures: {e}")
    try:
        out["merged"] = merge_redated()
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"merge: {e}")
    return out


# --------------------------------------------------------------------------- #
# MCX (bhavcopy rows)
# --------------------------------------------------------------------------- #
_MCX_SYMBOLS = {v: k for k, v in SYMBOLS.items()}


def ingest_mcx_csv(text: str) -> int:
    """OPTFUT rows of one bhavcopy for our two commodities. Called by
    bhav_history.ingest_csv on every file it stores, and by the backfill."""
    from app.services.bhav_history import _parse_expiry, _parse_trade_date
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        inst = (r.get("INSTRUMENTNAME") or "").strip()
        if inst not in ("OPTFUT", "FUTCOM"):
            continue
        sym = (r.get("SYMBOL") or "").strip().upper()
        if sym not in _MCX_SYMBOLS:
            continue
        td = _parse_trade_date(r.get("DATE", "")); ex = _parse_expiry(r.get("EXPIRY_DATE", ""))
        if inst == "FUTCOM":
            # the underlying future's close, one row per contract-day (strike 0)
            ot, strike = "FUT", 0.0
        else:
            ot = (r.get("OPTIONTYPE") or "").strip().upper()
            strike = _num(r.get("STRIKEPRICE"))
        if ot not in ("CE", "PE", "FUT") or not td or not ex or strike is None or not _keep(_MCX_SYMBOLS[sym], td, ex, strike):
            continue
        rows.append({"exchange": "MCX", "commodity": _MCX_SYMBOLS[sym], "trade_date": td, "expiry": ex,
                     "option_type": ot, "strike": strike,
                     "close": _num(r.get("CLOSE")), "settle": None, "ltp": None,
                     "prev_close": _num(r.get("PREVIOUS_CLOSE")),
                     "volume": _num(r.get("VOLUME_IN_LOTS")), "oi": _num(r.get("OPEN_INTEREST_IN_LOTS"))})
    return _upsert(rows)


def mcx_have_dates(kind: str = "FUT") -> set[str]:
    """Days already holding MCX rows of `kind` (FUT = futures, the newer part;
    a day with futures stored has its options too)."""
    db = SessionLocal()
    try:
        q = db.query(NseMcxOptDaily.trade_date).filter(NseMcxOptDaily.exchange == "MCX")
        q = q.filter(NseMcxOptDaily.option_type == "FUT") if kind == "FUT" else q.filter(NseMcxOptDaily.option_type != "FUT")
        return {d for (d,) in q.distinct()}
    finally:
        db.close()


def backfill_mcx(since: date = SINCE) -> dict:
    """Walk the bhavcopy archive from `since`, one month per request, storing
    the option rows. Days already stored are skipped."""
    from app.services import bhav_history as bh
    s = bh._session()
    done = mcx_have_dates()
    end = date.today() - timedelta(days=1)
    out = {"files": 0, "rows": 0}
    cur = date(since.year, since.month, 1)
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        for url in bh._links_resilient(s, max(cur, since), min(nxt - timedelta(days=1), end)):
            m = re.search(r"(\d{8})_MCX", bh._decode_name(url))
            day = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None
            if day and day in done:
                continue
            try:
                f = s.get(url, headers=bh._UA, timeout=90)
                if f.status_code == 200 and len(f.content) > 200:
                    out["rows"] += ingest_mcx_csv(f.content.decode("utf-8", "ignore"))
                    out["files"] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("mcx opt file %s: %s", day, e)
            time.sleep(bh._PACE_SECONDS)
        _status["msg"] = f"MCX {cur.strftime('%Y-%m')} done ({out['files']} files)"
        log.info("mcx opt backfill: %s", _status["msg"])
        cur = nxt
    return out


def merge_redated(commodity: str | None = None) -> list[dict]:
    """NSE re-dates option expiries now and then (Nov-2025: crude's 16-Dec
    became 09-Dec, 14-Jan became 07-Jan; May-2026: gas). The same contract
    then sits under two expiry labels, the old one stopping dead mid-life.
    Relabel the old rows to the successor - the expiry whose data begins the
    trading day after the old one's ends, in the same month - so every reader
    sees one contract. Idempotent; runs after every NSE pull."""
    from sqlalchemy import func
    out = []
    db = SessionLocal()
    try:
        for comm in ([commodity] if commodity else list(SYMBOLS)):
            spans = db.query(NseMcxOptDaily.expiry, func.min(NseMcxOptDaily.trade_date), func.max(NseMcxOptDaily.trade_date)).filter(
                NseMcxOptDaily.commodity == comm, NseMcxOptDaily.exchange == "NSE",
                NseMcxOptDaily.option_type != "FUT").group_by(NseMcxOptDaily.expiry).all()
            by_exp = {e: (lo, hi) for e, lo, hi in spans}
            today = date.today().isoformat()
            for exp, (lo, hi) in sorted(by_exp.items()):
                e = datetime.strptime(exp, "%Y-%m-%d").date(); h = datetime.strptime(hi, "%Y-%m-%d").date()
                if exp >= today or (e - h).days <= 3:
                    continue                                    # lived to its expiry, or still live
                succ = [e2 for e2, (lo2, _hi2) in by_exp.items()
                        if e2 < exp and e2[:7] == exp[:7] and 0 < (datetime.strptime(lo2, "%Y-%m-%d").date() - h).days <= 7]
                if not succ:
                    continue
                new = min(succ)
                n = db.query(NseMcxOptDaily).filter(NseMcxOptDaily.commodity == comm, NseMcxOptDaily.exchange == "NSE",
                                                    NseMcxOptDaily.expiry == exp).update({"expiry": new}, synchronize_session=False)
                db.commit()
                out.append({"commodity": comm, "from": exp, "to": new, "rows": n})
                log.info("nse re-dated expiry merged: %s %s -> %s (%d rows)", comm, exp, new, n)
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()
    return out


def backfill_all(since: date = SINCE) -> dict:
    if not _lock.acquire(blocking=False):
        return {"ok": False, "msg": "already running"}
    _status.update(running=True, msg="starting", nse_calls=0, rows=0, at=datetime.now().isoformat(timespec="seconds"))
    try:
        mcx = backfill_mcx(since)
        nse = backfill_nse(since)
        merge_redated()
        _status["msg"] = f"complete: MCX {mcx['files']} files/{mcx['rows']} rows, NSE {nse['expiries']} expiries/{nse['rows']} rows, errors {len(nse['errors'])}"
        log.info("nse-mcx daily backfill %s", _status["msg"])
        return {"ok": True, "mcx": mcx, "nse": nse}
    finally:
        _status["running"] = False
        _lock.release()


def start_backfill(since: date = SINCE) -> bool:
    if _status["running"]:
        return False
    threading.Thread(target=backfill_all, args=(since,), daemon=True, name="nmopt-backfill").start()
    return True


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def _expiries(commodity: str, exchange: str, kind: str = "OPT") -> list[str]:
    db = SessionLocal()
    try:
        q = db.query(NseMcxOptDaily.expiry).filter(NseMcxOptDaily.commodity == commodity, NseMcxOptDaily.exchange == exchange)
        q = q.filter(NseMcxOptDaily.option_type == "FUT") if kind == "FUT" else q.filter(NseMcxOptDaily.option_type != "FUT")
        return sorted(e for (e,) in q.distinct())
    finally:
        db.close()


def _underlying_future(commodity: str, exchange: str, opt_expiry: str) -> str | None:
    """The future an option month rides: the first future expiring on or after
    the option's expiry (NSE crude 10-Sep option -> 21-Sep future; MCX 17-Sep
    option -> 21-Sep future)."""
    later = [e for e in _expiries(commodity, exchange, "FUT") if e >= opt_expiry]
    return later[0] if later else None


def _nearest(target: str, pool: list[str]) -> str | None:
    if not pool:
        return None
    t = datetime.strptime(target, "%Y-%m-%d")
    return min(pool, key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d") - t).days))


def expiries(commodity: str) -> dict:
    """NSE expiries with the MCX expiry each is compared against, newest first,
    plus the day span each pairing has data for."""
    nse = _expiries(commodity, "NSE", "OPT"); mcx = _expiries(commodity, "MCX", "OPT")
    out = []
    for e in sorted(nse, reverse=True):
        m = _nearest(e, mcx)
        out.append({"nse": e, "mcx": m,
                    "gap_days": abs((datetime.strptime(m, "%Y-%m-%d") - datetime.strptime(e, "%Y-%m-%d")).days) if m else None})
    return {"commodity": commodity, "step": STEP[commodity], "expiries": out}


def compare(commodity: str, nse_expiry: str, start: str | None = None, end: str | None = None,
            option_type: str | None = None, strike: float | None = None, mcx_expiry: str | None = None) -> dict:
    """Day-by-day, strike-by-strike closing premium on both exchanges.

    Only strikes on the client's ladder (round hundreds for crude) and only
    days both exchanges traded. A leg with no close on one side is left None
    and the difference with it; a dash is truer than a number from one side.
    """
    mcx_exp = mcx_expiry or _nearest(nse_expiry, _expiries(commodity, "MCX", "OPT"))
    step = STEP[commodity]
    db = SessionLocal()
    try:
        def fetch(exchange, exp):
            q = db.query(NseMcxOptDaily).filter(NseMcxOptDaily.commodity == commodity,
                                                 NseMcxOptDaily.exchange == exchange, NseMcxOptDaily.expiry == exp)
            if start:
                q = q.filter(NseMcxOptDaily.trade_date >= start)
            if end:
                q = q.filter(NseMcxOptDaily.trade_date <= end)
            if option_type in ("CE", "PE"):
                q = q.filter(NseMcxOptDaily.option_type == option_type)
            if strike is not None:
                q = q.filter(NseMcxOptDaily.strike == strike)
            return q.all()
        nse_rows = fetch("NSE", nse_expiry)
        mcx_rows = fetch("MCX", mcx_exp) if mcx_exp else []
        nse_fut_exp = _underlying_future(commodity, "NSE", nse_expiry)
        mcx_fut_exp = _underlying_future(commodity, "MCX", mcx_exp) if mcx_exp else None

        def fut(exchange, exp):
            if not exp:
                return {}
            q = db.query(NseMcxOptDaily).filter(NseMcxOptDaily.commodity == commodity, NseMcxOptDaily.exchange == exchange,
                                                 NseMcxOptDaily.expiry == exp, NseMcxOptDaily.option_type == "FUT")
            # NSE's future seldom trades: an untraded day's "close" is a stale print, the settlement is the level
            return {r.trade_date: (r.settle if (exchange == "NSE" and r.settle and not r.volume) else (r.close or r.settle)) for r in q.all()}
        nse_fut = fut("NSE", nse_fut_exp); mcx_fut = fut("MCX", mcx_fut_exp)
    finally:
        db.close()

    def px(r):
        # NSE: the close when the strike traded, else the settlement (NSE repeats a
        # stale last-traded close for weeks); MCX: the bhavcopy close.
        if r.exchange == "NSE" and r.settle and not r.volume:
            return r.settle
        return r.close if r.close else (r.settle if r.exchange == "NSE" else None)
    nse = {(r.trade_date, r.strike, r.option_type): r for r in nse_rows if r.option_type != "FUT" and r.strike % step == 0}
    mcx = {(r.trade_date, r.strike, r.option_type): r for r in mcx_rows if r.option_type != "FUT" and r.strike % step == 0}
    days = sorted({k[0] for k in nse} & {k[0] for k in mcx}, reverse=True)
    strikes = sorted({k[1] for k in nse} & {k[1] for k in mcx})
    rows = []
    futures = {}
    for d in days:
        nf, mf = nse_fut.get(d), mcx_fut.get(d)
        # The day's ATM: the ladder strike nearest the future's close (MCX's, the
        # traded market, else NSE's). The client reads the day-wise ATM premium off this row.
        ref = mf if mf is not None else nf
        atm = min(strikes, key=lambda k: abs(k - ref)) if (strikes and ref) else None
        futures[d] = {"nse": nf, "mcx": mf, "diff": round(nf - mf, 2) if (nf is not None and mf is not None) else None,
                      "diff_pct": round((nf - mf) / mf * 100, 2) if (nf is not None and mf) else None,
                      "atm": atm}
        for k in strikes:
            entry = {"date": d, "strike": k, "fut": futures[d], "atm": k == futures[d]["atm"]}
            any_leg = False
            for ot in ("CE", "PE"):
                n, m = nse.get((d, k, ot)), mcx.get((d, k, ot))
                np_, mp = (px(n) if n else None), (px(m) if m else None)
                entry[ot.lower()] = {
                    "nse": np_, "mcx": mp,
                    "diff": round(np_ - mp, 2) if (np_ is not None and mp is not None) else None,
                    "diff_pct": round((np_ - mp) / mp * 100, 2) if (np_ is not None and mp) else None,
                    "nse_vol": n.volume if n else None, "mcx_vol": m.volume if m else None,
                    "nse_oi": n.oi if n else None, "mcx_oi": m.oi if m else None,
                }
                any_leg = any_leg or np_ is not None or mp is not None
            if any_leg:
                rows.append(entry)
    return {"commodity": commodity, "nse_expiry": nse_expiry, "mcx_expiry": mcx_exp, "step": step,
            "nse_future_expiry": nse_fut_exp, "mcx_future_expiry": mcx_fut_exp, "futures": futures,
            "strikes": strikes, "days": len(days), "from": days[-1] if days else None, "to": days[0] if days else None,
            "rows": rows}
