"""Angel One scrip master, served in the shape the rest of the app reads.

Every resolver in this app (pair registry, metals, other commodities, option
spreads, Nifty/Sensex, electricity, paper trades, crude IV) reads ONE thing:
a CSV with Dhan's SEM_* columns, through instrument_resolver._download_csv().
When the feed provider is Angel, that function hands out THIS module's CSV
instead - the same columns, filled from Angel's OpenAPIScripMaster.json - and
not one resolver changes.

Why that is safe: Dhan and Angel both key instruments by the EXCHANGE token
(GOLDPETAL 30-Sep-2026 is 568839 on both, GOLDBEES is 14428 on both, verified
07-Sep-2026 against both masters), so quote_store keys, pair names, paper
symbols and cached quotes all carry over. Only the three spot indices differ:
Dhan numbers them 13/51/21, Angel 99926000/99919000/99926017 - INDEX_IDS.

Trading symbols are rebuilt in Dhan's spelling ("GOLDPETAL-30Sep2026-FUT",
"CRUDEOIL-17Sep2026-7000-CE") because the UI, the paper-trade rows and the
pair labels all show that spelling; Angel's own "GOLDPETAL30SEP26FUT" would
have changed what the client sees for no reason.

What is emitted (only what the app subscribes, ~50k of Angel's 144k rows):
  MCX  FUTCOM + OPTFUT          exch MCX, segment M
  NFO  OPTIDX (NIFTY family)    exch NSE, segment D
  BFO  OPTIDX (SENSEX family)   exch BSE, segment D
  NSE  EQ (the two ETFs)        exch NSE, segment E
"""
from __future__ import annotations

import csv
import io
import logging
import threading
import time
from datetime import date, datetime

log = logging.getLogger("angel_master")

# Spot indices on Angel's socket (exchangeType 1 = NSE, 3 = BSE).
INDEX_IDS = {"NIFTY": "99926000", "SENSEX": "99919000", "INDIA VIX": "99926017"}
INDEX_EXCHANGE = {"99926000": "NSE", "99919000": "BSE", "99926017": "NSE"}

# Angel exchangeType codes for its WebSocket 2.0.
WS_EXCHANGE_TYPE = {"NSE": 1, "NFO": 2, "BSE": 3, "BFO": 4, "MCX": 5, "NCX": 7, "CDS": 13}

_ETF_SYMBOLS = {"GOLDBEES-EQ", "SILVERBEES-EQ"}
_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                       "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_CSV_TTL = 6 * 3600
_cache: dict = {"csv": "", "ts": 0.0, "segment": {}}
_lock = threading.Lock()


def parse_expiry(s: str) -> date | None:
    """Angel writes DDMMMYYYY ('30SEP2026'). Parsed, never string-sorted."""
    s = (s or "").strip().upper()
    try:
        return date(int(s[5:9]), _MONTHS[s[2:5]], int(s[:2]))
    except Exception:  # noqa: BLE001
        return None


def _dhan_expiry(d: date, hhmm: str) -> str:
    return f"{d.isoformat()} {hhmm}:00"


def _dhan_symbol_fut(name: str, d: date) -> str:
    return f"{name}-{d.strftime('%d%b%Y')}-FUT"


def _dhan_symbol_opt(name: str, d: date, strike: float, otype: str, weekly_index: bool) -> str:
    # Dhan spells index options by month only ("SENSEX-Oct2026-84600-PE") and
    # commodity options with the day ("CRUDEOIL-17Sep2026-7000-CE").
    when = d.strftime("%b%Y") if weekly_index else d.strftime("%d%b%Y")
    return f"{name}-{when}-{strike:g}-{otype}"


def _rows_from_master(master: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Dhan-shaped rows + {token: angel exchange segment}."""
    out: list[dict] = []
    segment: dict[str, str] = {}
    for r in master:
        seg = r.get("exch_seg")
        typ = r.get("instrumenttype") or ""
        name = r.get("name") or ""
        token = str(r.get("token") or "")
        if not token:
            continue
        if seg == "MCX" and typ in ("FUTCOM", "OPTFUT"):
            d = parse_expiry(r.get("expiry"))
            if not d:
                continue
            if typ == "FUTCOM":
                out.append({"exch": "MCX", "seg": "M", "sid": token, "inst": "FUTCOM",
                            "ts": _dhan_symbol_fut(name, d), "lot": "1.0",
                            "custom": f"{name} {d.strftime('%b').upper()} FUT",
                            "expiry": _dhan_expiry(d, "23:30"), "strike": "0.00000",
                            "otype": "XX", "tick": r.get("tick_size") or "", "name": name})
            else:
                sym = r.get("symbol") or ""
                otype = sym[-2:] if sym[-2:] in ("CE", "PE") else ""
                if not otype:
                    continue
                strike = float(r.get("strike") or 0) / 100.0
                out.append({"exch": "MCX", "seg": "M", "sid": token, "inst": "OPTFUT",
                            "ts": _dhan_symbol_opt(name, d, strike, otype, False), "lot": "1.0",
                            "custom": f"{name} {d.strftime('%d %b').upper()} {strike:g} {'CALL' if otype == 'CE' else 'PUT'}",
                            "expiry": _dhan_expiry(d, "23:30"), "strike": f"{strike:.5f}",
                            "otype": otype, "tick": r.get("tick_size") or "", "name": name})
            segment[token] = "MCX"
        elif seg in ("NFO", "BFO") and typ == "OPTIDX" and name in ("NIFTY", "SENSEX"):
            d = parse_expiry(r.get("expiry"))
            sym = r.get("symbol") or ""
            otype = sym[-2:] if sym[-2:] in ("CE", "PE") else ""
            if not d or not otype:
                continue
            strike = float(r.get("strike") or 0) / 100.0
            exch = "NSE" if seg == "NFO" else "BSE"
            out.append({"exch": exch, "seg": "D", "sid": token, "inst": "OPTIDX",
                        "ts": _dhan_symbol_opt(name, d, strike, otype, True),
                        "lot": r.get("lotsize") or "1",
                        "custom": f"{name} {d.strftime('%d %b').upper()} {strike:g} {'CALL' if otype == 'CE' else 'PUT'}",
                        "expiry": _dhan_expiry(d, "15:30"), "strike": f"{strike:.5f}",
                        "otype": otype, "tick": r.get("tick_size") or "", "name": name})
            segment[token] = seg
        elif seg == "NSE" and r.get("symbol") in _ETF_SYMBOLS:
            base = r["symbol"][:-3]
            out.append({"exch": "NSE", "seg": "E", "sid": token, "inst": "EQUITY",
                        "ts": base, "lot": "1.0", "custom": base, "expiry": "",
                        "strike": "", "otype": "", "tick": r.get("tick_size") or "", "name": name})
            segment[token] = "NSE"
    for tok, ex in INDEX_EXCHANGE.items():
        segment[tok] = ex
    return out, segment


_HEADER = ["SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID", "SEM_INSTRUMENT_NAME",
           "SEM_EXPIRY_CODE", "SEM_TRADING_SYMBOL", "SEM_LOT_UNITS", "SEM_CUSTOM_SYMBOL",
           "SEM_EXPIRY_DATE", "SEM_STRIKE_PRICE", "SEM_OPTION_TYPE", "SEM_TICK_SIZE",
           "SEM_EXPIRY_FLAG", "SEM_EXCH_INSTRUMENT_TYPE", "SEM_SERIES", "SM_SYMBOL_NAME"]


def build_csv(master: list[dict]) -> tuple[str, dict[str, str]]:
    rows, segment = _rows_from_master(master)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_HEADER)
    for r in rows:
        w.writerow([r["exch"], r["seg"], r["sid"], r["inst"], "0", r["ts"], r["lot"], r["custom"],
                    r["expiry"], r["strike"], r["otype"], r["tick"], "M", r["inst"], "", r["name"]])
    return buf.getvalue(), segment


def dhan_compat_csv(force: bool = False) -> str:
    """The Dhan-shaped CSV, rebuilt from Angel's master at most every 6 hours."""
    with _lock:
        if not force and _cache["csv"] and time.time() - _cache["ts"] < _CSV_TTL:
            return _cache["csv"]
        from app.services.angel_feed import _load_master
        t0 = time.time()
        master = _load_master()
        text, segment = build_csv(master)
        _cache.update(csv=text, ts=time.time(), segment=segment)
        log.info("Angel master -> compat CSV: %d rows in %.1fs (%d tokens mapped)",
                 text.count("\n") - 1, time.time() - t0, len(segment))
        return text


def segment_of(token: str) -> str | None:
    """Angel exchange segment ('MCX', 'NFO', 'BFO', 'NSE', 'BSE') for a token
    the compat CSV emitted, or None for one it never saw."""
    if not _cache["segment"]:
        dhan_compat_csv()
    return _cache["segment"].get(str(token))
