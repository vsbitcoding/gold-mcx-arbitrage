"""Public app API, part 2 (08-Oct-2026): every dashboard page the mobile app
did not have yet, read-only, behind the same API key as /api/v1 part 1.

Added for the app: Making Price, BANKEX / BANKNIFTY (live board + history),
MCX vs NYMEX history and backtest, NSE vs MCX daily closes, backtest, paper
trading view and electricity hours, multi-year Spread History, and the market
calendar.

Load rules, same as the rest of the app API:
  - live endpoints read the in-memory quote store only, behind a one-second
    cache, so any number of phones polling costs one computation a second;
  - history endpoints sit behind their services' own caches (60 s) plus a
    short cache here, and are meant to be fetched on a control change only;
  - backtests are CPU work: one at a time per kind (a second request while one
    runs gets 429 "busy, retry"), and an identical request within ten minutes
    is answered from the cache without recomputing.

Write actions stay on the web dashboard: paper positions, paper-trading
rules and start/stop, holiday edits.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.security import require_api_key
from app.services.live_feed import is_market_open

router = APIRouter(prefix="/api/v1", tags=["public-v1"])

# --------------------------------------------------------------------------- #
# small shared helpers
# --------------------------------------------------------------------------- #
_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 256


def _cached(key: tuple, ttl: float, fn):
    """Return fn() but compute it at most once per `ttl` seconds per key."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = (now, value)
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Making Price
# --------------------------------------------------------------------------- #
MAKING_DEFAULTS = {"factor": 0.00402,
                   "charges": {"petal": 325.0, "guinea": 1000.0, "ten": 1400.0, "silvermicro": 3500.0}}
# key, label, base instrument (price-table `short`), base label, charge multiplier, uses the gold factor
MAKING_ROWS = (
    ("petal", "Mini → Petal", "mini", "Gold Mini", 10.0, True),
    ("guinea", "Mini → Guinea", "mini", "Gold Mini", 1.25, True),
    ("ten", "Mini → Ten", "mini", "Gold Mini", 1.0, True),
    ("silvermicro", "Silver → Micro", None, None, None, False),
)


def making_price_payload(factor: float, charges: dict) -> dict:
    """The dashboard's Making Price cards, computed here.

    Gold rows : Gold Mini near-month Bid x factor + making charge x multiplier
    Silver row: the making charge alone (flat), as on the dashboard
    """
    from app.services import price_service
    table = price_service.get_table()
    group = next((g for g in table.get("groups", []) if g.get("short") == "mini"), None)
    near = (group or {}).get("contracts", [None])[0] if (group and group.get("contracts")) else None
    bid = near.get("buyer") if near else None
    rows = []
    for key, label, base, base_label, mult, factored in MAKING_ROWS:
        charge = charges[key]
        if factored:
            value = round(bid * factor + charge * mult, 2) if bid else None
            rows.append({"key": key, "label": label, "base": base_label,
                         "base_contract": near.get("contract") if near else None,
                         "base_bid": bid, "factor": factor, "making_charge": charge,
                         "multiplier": mult, "value": value})
        else:
            rows.append({"key": key, "label": label, "base": None, "base_contract": None,
                         "base_bid": None, "factor": None, "making_charge": charge,
                         "multiplier": None, "value": round(charge, 2)})
    return {"rows": rows, "defaults": MAKING_DEFAULTS,
            "formula": {"gold": "Gold Mini Bid x factor + making charge x multiplier",
                        "silver": "making charge (flat)"}}


@router.get("/making-price")
def public_making_price(
    factor: float | None = Query(None, ge=0, le=1, description="gold factor, default 0.00402"),
    petal: float | None = Query(None, ge=0, description="making charge, default 325"),
    guinea: float | None = Query(None, ge=0, description="making charge, default 1000"),
    ten: float | None = Query(None, ge=0, description="making charge, default 1400"),
    silvermicro: float | None = Query(None, ge=0, description="making charge, default 3500"),
    _key: str = Depends(require_api_key),
):
    """Live making-charge premium (Mini to Petal / Guinea / Ten from the Gold
    Mini Bid; Silver to Micro is a flat charge). Every input is optional and
    falls back to the dashboard default, so the app can keep the user's own
    factor and charges on the phone and pass them here. Poll every 2 s."""
    f = MAKING_DEFAULTS["factor"] if factor is None else factor
    charges = dict(MAKING_DEFAULTS["charges"])
    for k, v in (("petal", petal), ("guinea", guinea), ("ten", ten), ("silvermicro", silvermicro)):
        if v is not None:
            charges[k] = v
    key = ("making", f, tuple(sorted(charges.items())))
    body = _cached(key, 1.0, lambda: making_price_payload(f, charges))
    return {"server_time": _now_iso(), "market_open": is_market_open(), **body}


# --------------------------------------------------------------------------- #
# BANKEX / BANKNIFTY
# --------------------------------------------------------------------------- #
@router.get("/bank-options")
def public_bank_options(
    side: str = Query("both", pattern="^(both|CE|PE)$"),
    metric: str = Query("points", pattern="^(points|rupees)$",
                        description="points = Sell Bid - Buy Ask; rupees = net premium with lot sizes and lots"),
    bankex_lots: int = Query(1, ge=1, le=100),
    banknifty_lots: int = Query(1, ge=1, le=100),
    _key: str = Depends(require_api_key),
):
    """Live BANKEX vs BANKNIFTY monthly option board: 15 BANKEX strikes (ATM
    +/- 7 x 500), each matched to the BANKNIFTY strike the same points from its
    spot (rounded to 100), CE and PE. The EARLIER expiry is sold at Bid, the
    LATER bought at Ask; difference = Sell Bid - Buy Ask. Watch-only: paper
    positions stay on the dashboard. Poll every 2 s."""
    from app.services import bank_options_service
    key = ("bank", side, metric, bankex_lots, banknifty_lots)
    return _cached(key, 1.0, lambda: bank_options_service.get_live(
        side=side, metric=metric, bankex_lots=bankex_lots, banknifty_lots=banknifty_lots,
        liquidity="all"))


@router.get("/bank-options/history")
def public_bank_options_history(
    source: str = Query("snapshot", pattern="^(snapshot|daily)$",
                        description="snapshot = boards saved 10:00 and 15:30 IST; daily = one board a day from bhavcopy closes since Jan 2024"),
    slot: str = Query("both", pattern="^(both|10:00|15:30)$", description="snapshot only"),
    weekday: str | None = Query(None, description="mon..fri to keep one weekday"),
    days: int = Query(7, ge=1, le=120),
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _key: str = Depends(require_api_key),
):
    """Stored BANKEX / BANKNIFTY boards, newest first, in the live board's row
    shape. Static once written: fetch on a control change, never poll."""
    from app.services import bank_daily_history, bank_options_history
    if source == "daily":
        return bank_daily_history.get_history(weekday=bank_options_history.parse_weekday(weekday),
                                              days=days, date_=date)
    return bank_options_history.get_history(slot=slot, weekday=weekday, days=days, date=date)


# --------------------------------------------------------------------------- #
# MCX vs NYMEX: history + backtest
# --------------------------------------------------------------------------- #
@router.get("/crude-iv/history")
def public_crude_iv_history(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    month: int = Query(0, ge=0, le=1),
    slot: str = Query("all", description="all, or one half-hour 09:00 .. 23:30"),
    days: int = Query(3, ge=1, le=30),
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _key: str = Depends(require_api_key),
):
    """Stored MCX-vs-US option boards, every half hour 09:00 to 23:30 IST,
    newest first. Rows are flat lists; `cols_mcx` / `cols_us` name the columns
    in order. Fetch on a control change, never poll."""
    from app.services import crude_iv_history
    return crude_iv_history.get_history(commodity=commodity, month=month, slot=slot, days=days, date=date)


_bt_sem = {"crude_iv": threading.Semaphore(1), "nse_mcx": threading.Semaphore(1)}
_bt_cache: dict = {}
_BT_TTL = 600.0
_BT_MAX = 16


def _run_backtest(kind: str, params: dict, fn) -> dict:
    """One backtest per kind at a time; identical params within ten minutes
    are answered from the cache. Raises 429 when busy, 400 on bad rules."""
    key = (kind, json.dumps(params or {}, sort_keys=True, default=str))
    now = time.monotonic()
    with _cache_lock:
        hit = _bt_cache.get(key)
        if hit and now - hit[0] < _BT_TTL:
            return hit[1]
    sem = _bt_sem[kind]
    if not sem.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Another backtest is running. Retry in a few seconds.")
    try:
        result = fn(params or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        sem.release()
    with _cache_lock:
        if len(_bt_cache) >= _BT_MAX:
            oldest = min(_bt_cache, key=lambda k: _bt_cache[k][0])
            _bt_cache.pop(oldest, None)
        _bt_cache[key] = (time.monotonic(), result)
    return result


@router.post("/crude-iv/backtest")
def public_crude_iv_backtest(
    body: dict = Body(default_factory=dict),
    include_paths: bool = Query(False, description="true = every trade's board-by-board path (large, ~2-3 MB)"),
    _key: str = Depends(require_api_key),
):
    """MCX vs NYMEX implied-volatility gap backtest on the stored half-hourly
    boards (since 19-Aug-2026). Body = any rule (entry_diff, exit_diff,
    direction, sides, strike_step, otm_min, otm_max, exit_days, stop_loss,
    price_rule, lot_size, max_positions, exclude_wide, start, end, commodity,
    month); missing rules take the dashboard defaults, returned in `params`.
    Trades come without the per-board `path` unless include_paths=true."""
    from app.services import crude_iv_backtest
    result = _run_backtest("crude_iv", body, crude_iv_backtest.run)
    if include_paths:
        return result
    # a shallow copy, so the cached full result keeps its paths
    return {**result, "trades": [{k: v for k, v in t.items() if k != "path"} for t in result.get("trades", [])]}


# --------------------------------------------------------------------------- #
# NSE vs MCX: daily closes, backtest, paper trading, electricity hours
# --------------------------------------------------------------------------- #
@router.get("/nse-mcx/daily/expiries")
def public_nse_mcx_daily_expiries(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    _key: str = Depends(require_api_key),
):
    """NSE option expiries with stored daily closes since April 2024, each paired
    with its MCX expiry. Feeds the expiry picker of /nse-mcx/daily."""
    from app.services import nse_opt_history
    return _cached(("nmexp", commodity), 300.0,
                   lambda: {**nse_opt_history.expiries(commodity), "status": nse_opt_history.status()})


@router.get("/nse-mcx/daily")
def public_nse_mcx_daily(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    expiry: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="NSE expiry from /nse-mcx/daily/expiries"),
    mcx_expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    type: str | None = Query(None, pattern="^(CE|PE)$"),
    strike: float | None = Query(None),
    _key: str = Depends(require_api_key),
):
    """Daily closing premiums, NSE against MCX, per strike per day (close
    against close; an untraded NSE leg uses its settlement price)."""
    from app.services import nse_opt_history
    key = ("nmdaily", commodity, expiry, mcx_expiry, start, end, type, strike)
    return _cached(key, 300.0, lambda: nse_opt_history.compare(commodity, expiry, start, end, type, strike, mcx_expiry))


@router.post("/nse-mcx/backtest")
def public_nse_mcx_backtest(
    body: dict = Body(default_factory=dict),
    _key: str = Depends(require_api_key),
):
    """The NSE-vs-MCX premium-arbitrage backtest over the daily closes (since
    April 2024). Body = any rule of the dashboard's backtester; missing rules
    take the defaults (returned in `params`). One at a time; identical
    requests within ten minutes come from the cache."""
    from app.services import nse_mcx_backtest
    return _run_backtest("nse_mcx", body, nse_mcx_backtest.run)


@router.get("/nse-mcx/paper")
def public_nse_mcx_paper(
    commodity: str = Query("crude", pattern="^(crude|natgas)$"),
    _key: str = Depends(require_api_key),
):
    """Live paper trading of the NSE-vs-MCX premium arbitrage, read-only: the
    rules in force, open lots with live marks, closed trades, totals and the
    event log. Start/stop and rules stay on the dashboard. Poll every 10 s
    (the engine itself checks every 10 s)."""
    from app.services import nse_mcx_paper
    return _cached(("paper", commodity), 5.0, lambda: nse_mcx_paper.state(commodity))


@router.get("/nse-mcx/elec-hourly")
def public_nse_mcx_elec_hourly(
    month: int = Query(0, ge=0, le=1),
    days: int = Query(30, ge=1, le=365),
    _key: str = Depends(require_api_key),
):
    """Electricity NSE vs MCX, one stored difference per hour (since
    02-Sep-2026). Fetch on demand."""
    from app.services import elec_service
    return _cached(("elec", month, days), 60.0, lambda: elec_service.history(month=month, days=days))


# --------------------------------------------------------------------------- #
# Spread History (MCX bhavcopy closes, 2015 onward)
# --------------------------------------------------------------------------- #
@router.get("/spread-history/options")
def public_spread_history_options(_key: str = Depends(require_api_key)):
    """What Spread History can show: symbols with their stored expiries, the
    cross pairs, and the data coverage. Changes once a day."""
    from app.routes.pairs import bhav_options_payload
    return _cached(("bhavopt",), 300.0, bhav_options_payload)


@router.get("/spread-history")
def public_spread_history(
    kind: str = Query("calendar", pattern="^(calendar|cross)$"),
    big: str = Query(..., description="symbol key from /spread-history/options"),
    small: str | None = Query(None, description="cross only: the second leg"),
    big_exp: str | None = Query(None), small_exp: str | None = Query(None),
    mode: str = Query("continuous", pattern="^(continuous|month)$"),
    rank: int = Query(0, ge=0, le=4, description="continuous calendar: 0 = M1-M2, 1 = M2-M3 ..."),
    start: str = Query("2021-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _key: str = Depends(require_api_key),
):
    """One close-based spread value per trading day, newest first (the
    dashboard's Spread History dialog). Static data: fetch on a control change."""
    from app.routes.pairs import bhav_series_payload
    key = ("bhav", kind, big, small, big_exp, small_exp, mode, rank, start, end)
    return _cached(key, 300.0, lambda: bhav_series_payload(kind, big, small, big_exp, small_exp,
                                                            mode, rank, start, end))


# --------------------------------------------------------------------------- #
# Market calendar
# --------------------------------------------------------------------------- #
def market_status_payload() -> dict:
    from app.services import market_calendar
    today = date.today().isoformat()
    upto = (date.today() + timedelta(days=90)).isoformat()
    rows = market_calendar.list_year(date.today().year) + market_calendar.list_year(date.today().year + 1)
    upcoming = [{k: r[k] for k in ("date", "weekday", "exchange", "name", "morning_closed", "evening_closed")}
                for r in rows if today <= r["date"] <= upto]
    upcoming.sort(key=lambda r: (r["date"], r["exchange"]))
    return {"now": {"mcx": market_calendar.state("MCX"), "nse": market_calendar.state("NSE")},
            # the hours the server's own calendar uses for open / closed
            "sessions": {"nse": "09:15-15:40 IST", "mcx": "09:00-23:30 IST"},
            "upcoming_holidays": upcoming}


@router.get("/market-status")
def public_market_status(_key: str = Depends(require_api_key)):
    """Is each exchange open, closed or on holiday right now (the dashboard's
    LIVE / MARKET CLOSED / HOLIDAY badge), and the holidays of the next 90 days.
    For MCX a holiday can close only the morning or only the evening session."""
    return {"server_time": _now_iso(), **_cached(("market",), 30.0, market_status_payload)}
