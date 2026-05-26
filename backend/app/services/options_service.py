"""Nifty / Sensex PE-option spread service.

For each of the next THREE weekly expiries, subscribe to PUT options of
the two indices and compute a "spread per strike" row that the dashboard
displays as a single number.

Per-row formula (PE = put premium):
    nifty_value  = nifty_pe_ltp  * 325
    sensex_value = sensex_pe_ltp * 100
    spread       = nifty_value - sensex_value

The Nifty ATM strike is computed live from the spot index. The Sensex
strike paired with each Nifty strike is `nifty_strike × 3.2` rounded to
the nearest 100 (per client formula).

Each index shows ATM + 9 OTM-puts (strikes below ATM) per expiry → 10 rows
per expiry × 3 expiries = 30 rows total.

To avoid mid-day Dhan re-subscription churn (Dhan rate-limits hard) we
subscribe to a WIDER window at startup (ATM-15 ... ATM+5 for each index)
and only DISPLAY the rolling 10 that match the live ATM.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.services.instrument_resolver import _download_csv, _parse_expiry
from app.services.market_data import quote_store

log = logging.getLogger("options_service")

# Spot index security IDs (from Dhan scrip master)
NIFTY_SPOT_ID = "13"          # NSE IDX, "NIFTY"
SENSEX_SPOT_ID = "51"         # BSE IDX, "SENSEX"

# Strike step per index
NIFTY_STEP = 50
SENSEX_STEP = 100

# Sensex strike = Nifty strike × this, rounded to SENSEX_STEP
NIFTY_TO_SENSEX_RATIO = 3.2

# Premium multipliers per client (fixed)
NIFTY_MULT = 325
SENSEX_MULT = 100

# How many weekly expiries to track (current + next + next-next)
WEEK_COUNT = 3

# Display window: ATM + 9 OTM = 10 strikes per expiry
DISPLAY_STRIKES = 10
DISPLAY_BELOW = 9   # 9 strikes below ATM (OTM puts) + ATM itself = 10

# Subscription buffer (subscribe wider than display so dynamic ATM works
# without re-subscribing every time spot crosses a strike).
SUB_ABOVE = 5    # 5 strikes above ATM (cushion for upward spot move)
SUB_BELOW = 15   # 15 strikes below ATM (the displayed 9 + 6 cushion)


# ────────────────────────────────────────────────────────────────────────
# State (mutated at startup by refresh())
# ────────────────────────────────────────────────────────────────────────
_state: dict = {
    # {(underlying, week_index 0-2, strike, "PE"): {security_id, trading_symbol, expiry}}
    "options": {},
    # [(week_index, expiry_datetime)] ordered current → far
    "nifty_weeks": [],
    "sensex_weeks": [],
    # Anchor ATM strikes captured at refresh() (used to pick the subscription window)
    "nifty_anchor": None,
    "sensex_anchor": None,
}


def nifty_atm(spot: float) -> int:
    """Round Nifty spot to nearest 50."""
    return int(round(spot / NIFTY_STEP) * NIFTY_STEP)


def sensex_from_nifty(nifty_strike: int) -> int:
    """Equivalent Sensex strike per client formula (× 3.2, round to 100)."""
    return int(round(nifty_strike * NIFTY_TO_SENSEX_RATIO / SENSEX_STEP) * SENSEX_STEP)


def _live_spot(security_id: str) -> Optional[float]:
    q = quote_store.get(security_id)
    return q.ltp or None


def _resolve_index_pe_options(
    csv_text: str,
    underlying: str,           # "NIFTY" or "SENSEX"
    exchange: str,             # "NSE" or "BSE"
) -> dict[datetime, dict[int, dict]]:
    """Return {expiry_dt: {strike_int: {security_id, trading_symbol}}} for PE options
    of `underlying`. Filters out variants like BANKNIFTY / SENSEX50."""
    out: dict[datetime, dict[int, dict]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("SEM_EXM_EXCH_ID") != exchange:
            continue
        if row.get("SEM_INSTRUMENT_NAME") != "OPTIDX":
            continue
        if row.get("SEM_OPTION_TYPE") != "PE":
            continue
        ts = row.get("SEM_TRADING_SYMBOL", "")
        # Exact underlying: split on '-', first part must equal underlying
        if ts.split("-", 1)[0] != underlying:
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        if not expiry:
            continue
        try:
            strike = int(float(row.get("SEM_STRIKE_PRICE", "0")))
        except (TypeError, ValueError):
            continue
        out.setdefault(expiry, {})[strike] = {
            "security_id": str(row.get("SEM_SMST_SECURITY_ID")),
            "trading_symbol": ts,
        }
    return out


def _pick_weeklies(
    expiry_map: dict[datetime, dict[int, dict]],
    n: int,
) -> list[datetime]:
    """Pick the next `n` expiries that are <= 21 days away (filters monthly)."""
    today = datetime.now()
    near = sorted(e for e in expiry_map.keys() if e >= today and (e - today).days <= 28)
    return near[:n]


def refresh(min_days_ahead: int = 0) -> None:
    """Resolve weekly PE options for both indices and pick subscription window.

    Called once at feed startup. Stores everything in `_state`.
    """
    csv_text = _download_csv()
    nifty_map = _resolve_index_pe_options(csv_text, "NIFTY", "NSE")
    sensex_map = _resolve_index_pe_options(csv_text, "SENSEX", "BSE")

    nifty_weeks = _pick_weeklies(nifty_map, WEEK_COUNT)
    sensex_weeks = _pick_weeklies(sensex_map, WEEK_COUNT)

    if not nifty_weeks or not sensex_weeks:
        log.warning(
            "Options refresh: no weekly expiries — nifty=%d sensex=%d",
            len(nifty_weeks), len(sensex_weeks),
        )
        return

    # Anchor ATM from current spot (or fallback to median of available strikes).
    nifty_spot = _live_spot(NIFTY_SPOT_ID)
    sensex_spot = _live_spot(SENSEX_SPOT_ID)
    if not nifty_spot and nifty_weeks:
        strikes = sorted(nifty_map[nifty_weeks[0]].keys())
        nifty_spot = strikes[len(strikes) // 2] if strikes else 24000.0
    if not sensex_spot and sensex_weeks:
        strikes = sorted(sensex_map[sensex_weeks[0]].keys())
        sensex_spot = strikes[len(strikes) // 2] if strikes else 77000.0

    nifty_anchor = nifty_atm(nifty_spot)
    sensex_anchor = sensex_from_nifty(nifty_anchor)
    log.info(
        "Options anchor — Nifty spot=%.2f → ATM=%d ; Sensex paired ATM=%d",
        nifty_spot or 0, nifty_anchor, sensex_anchor,
    )

    # Build subscription windows: ATM-15 .. ATM+5 (21 strikes per index per week)
    options: dict = {}
    for wk_i, expiry in enumerate(nifty_weeks):
        strikes_map = nifty_map[expiry]
        for k in range(-SUB_BELOW, SUB_ABOVE + 1):
            strike = nifty_anchor + k * NIFTY_STEP
            if strike in strikes_map:
                options[("NIFTY", wk_i, strike, "PE")] = {
                    **strikes_map[strike],
                    "expiry": expiry.isoformat(),
                }
    for wk_i, expiry in enumerate(sensex_weeks):
        strikes_map = sensex_map[expiry]
        for k in range(-SUB_BELOW, SUB_ABOVE + 1):
            strike = sensex_anchor + k * SENSEX_STEP
            if strike in strikes_map:
                options[("SENSEX", wk_i, strike, "PE")] = {
                    **strikes_map[strike],
                    "expiry": expiry.isoformat(),
                }

    _state["options"] = options
    _state["nifty_weeks"] = nifty_weeks
    _state["sensex_weeks"] = sensex_weeks
    _state["nifty_anchor"] = nifty_anchor
    _state["sensex_anchor"] = sensex_anchor
    log.info(
        "Options subscribed: %d PE contracts across %d weeks × 2 indices",
        len(options), len(nifty_weeks),
    )


def get_extra_subscriptions() -> tuple[list[tuple], dict[str, dict]]:
    """Return (instruments, metadata) tuples for Dhan feed.

    Includes spot indices + all subscribed option contracts.
    """
    from dhanhq import marketfeed  # lazy import

    instruments: list[tuple] = []
    meta: dict[str, dict] = {}

    # Spot indices (Ticker request code — indices have no depth/OI, just LTP)
    instruments.append((marketfeed.MarketFeed.IDX, NIFTY_SPOT_ID, marketfeed.MarketFeed.Ticker))
    meta[NIFTY_SPOT_ID] = {"short": "nifty_spot", "trading_symbol": "NIFTY", "kind": "index"}
    instruments.append((marketfeed.MarketFeed.IDX, SENSEX_SPOT_ID, marketfeed.MarketFeed.Ticker))
    meta[SENSEX_SPOT_ID] = {"short": "sensex_spot", "trading_symbol": "SENSEX", "kind": "index"}

    # Option contracts
    for (idx, wk_i, strike, opt_type), info in _state["options"].items():
        sid = info["security_id"]
        exch = marketfeed.MarketFeed.NSE_FNO if idx == "NIFTY" else marketfeed.MarketFeed.BSE_FNO
        instruments.append((exch, sid, marketfeed.MarketFeed.Full))
        meta[sid] = {
            "short": f"{idx.lower()}_pe_{strike}_w{wk_i}",
            "trading_symbol": info["trading_symbol"],
            "kind": "option_pe",
            "underlying": idx,
            "week_index": wk_i,
            "strike": strike,
            "expiry": info["expiry"],
        }
    return instruments, meta


def get_spread_table() -> dict:
    """Compute the live spread table (3 weeks × 10 strikes) using current quotes.

    Returns:
      {
        "nifty_spot": float|None,
        "sensex_spot": float|None,
        "nifty_atm": int|None,
        "sensex_atm": int|None,
        "weeks": [
          {"week_index":0, "nifty_expiry":..., "sensex_expiry":..., "rows":[
              {"nifty_strike":24000, "sensex_strike":76800,
               "nifty_pe": 250.5, "sensex_pe": 820.0,
               "nifty_value": 81412.5, "sensex_value": 82000,
               "spread": -587.5}
              ...
          ]}, ...
        ]
      }
    """
    nifty_spot = _live_spot(NIFTY_SPOT_ID)
    sensex_spot = _live_spot(SENSEX_SPOT_ID)

    # Anchor falls back to startup anchor if no live spot yet.
    nifty_atm_live = nifty_atm(nifty_spot) if nifty_spot else _state.get("nifty_anchor")
    sensex_atm_live = sensex_from_nifty(nifty_atm_live) if nifty_atm_live else _state.get("sensex_anchor")

    weeks_out = []
    nifty_weeks = _state.get("nifty_weeks") or []
    sensex_weeks = _state.get("sensex_weeks") or []

    # Pair weeks by index (current week 0, next 1, next-next 2). Client said
    # ±1-2 day difference between Nifty & Sensex weekly is OK.
    for wk_i in range(min(len(nifty_weeks), len(sensex_weeks))):
        rows = []
        for offset in range(0, DISPLAY_STRIKES):  # 0..9, with 0=ATM, 1..9 below
            nifty_strike = nifty_atm_live - offset * NIFTY_STEP if nifty_atm_live else None
            sensex_strike = sensex_from_nifty(nifty_strike) if nifty_strike else None
            n_info = _state["options"].get(("NIFTY", wk_i, nifty_strike, "PE")) if nifty_strike else None
            s_info = _state["options"].get(("SENSEX", wk_i, sensex_strike, "PE")) if sensex_strike else None
            n_pe = _live_spot(n_info["security_id"]) if n_info else None
            s_pe = _live_spot(s_info["security_id"]) if s_info else None
            n_value = (n_pe * NIFTY_MULT) if n_pe else None
            s_value = (s_pe * SENSEX_MULT) if s_pe else None
            spread = (n_value - s_value) if (n_value is not None and s_value is not None) else None
            rows.append({
                "nifty_strike": nifty_strike,
                "sensex_strike": sensex_strike,
                "nifty_pe": n_pe,
                "sensex_pe": s_pe,
                "nifty_value": round(n_value, 2) if n_value is not None else None,
                "sensex_value": round(s_value, 2) if s_value is not None else None,
                "spread": round(spread, 2) if spread is not None else None,
            })
        weeks_out.append({
            "week_index": wk_i,
            "nifty_expiry": nifty_weeks[wk_i].isoformat() if wk_i < len(nifty_weeks) else None,
            "sensex_expiry": sensex_weeks[wk_i].isoformat() if wk_i < len(sensex_weeks) else None,
            "rows": rows,
        })

    return {
        "nifty_spot": nifty_spot,
        "sensex_spot": sensex_spot,
        "nifty_atm": nifty_atm_live,
        "sensex_atm": sensex_atm_live,
        "weeks": weeks_out,
    }


def status() -> dict:
    """Compact status info for UI/debug."""
    return {
        "subscribed_options": len(_state.get("options", {})),
        "nifty_weeks": [e.isoformat() for e in _state.get("nifty_weeks", [])],
        "sensex_weeks": [e.isoformat() for e in _state.get("sensex_weeks", [])],
        "nifty_anchor": _state.get("nifty_anchor"),
        "sensex_anchor": _state.get("sensex_anchor"),
    }
