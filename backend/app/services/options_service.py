"""Nifty / Sensex PE-option spread service.

For each of the next THREE weekly expiries, subscribe to PUT options of
the two indices and compute a "spread per strike" row that the dashboard
displays as a single number.

Per-row formula (PE = put premium, executable convention per client):
    nifty_value  = nifty_pe_BID  * 325      # SELL Nifty PE  → receive at BID
    sensex_value = sensex_pe_ASK * 100      # BUY  Sensex PE → pay at ASK
    spread       = nifty_value - sensex_value
    (falls back to LTP for any leg where bid/ask isn't available)

The Nifty ATM strike is computed live from the spot index. The Sensex
strike paired with each Nifty strike preserves moneyness distance:

    ITM_value    = nifty_spot − nifty_strike            (positive for OTM PE)
    sensex_strike = round_to_100(sensex_spot − ITM × 3.2)

So the Sensex paired strike sits `ITM × 3.2` points away from Sensex spot,
in the same OTM direction — keeping both legs at equivalent moneyness.

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

# Distance-scaling factor: 1 Nifty point ≈ 3.2 Sensex points (per client)
NIFTY_TO_SENSEX_RATIO = 3.2

# Premium multipliers per client (fixed)
NIFTY_MULT = 325
SENSEX_MULT = 100

# How many weekly expiries to track (current + next + next-next)
WEEK_COUNT = 3

# Display window: ATM + 9 OTM = 10 strikes per expiry (the "below" tab)
DISPLAY_STRIKES = 10
DISPLAY_BELOW = 9   # 9 strikes below ATM (OTM puts) + ATM itself = 10
# "above" tab (positive side): ATM + 14 higher strikes = 15 rows
ABOVE_ROWS = 15

# Subscription buffer (subscribe wider than display so the dynamic ATM stays
# covered all day WITHOUT re-subscribing mid-session — Dhan rate-limits hard on
# reconnects, so we deliberately use ONE wide static window per day instead).
# The anchor is captured at the daily ~09:17 IST refresh; the window must cover
# a full day's index move in BOTH directions from that open level:
#   SUB_ABOVE = up-move room   (30 strikes → Sensex ~3000 pts / Nifty ~1500 pts)
#   SUB_BELOW = down-move room + the 9 displayed OTM puts
SUB_ABOVE = 30
SUB_BELOW_NIFTY = 35
SUB_BELOW_SENSEX = 35


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
    # Spot prices captured at refresh() — fallback when live spot isn't available
    "nifty_spot_at_refresh": None,
    "sensex_spot_at_refresh": None,
}


def nifty_atm(spot: float) -> int:
    """Round Nifty spot to nearest 50."""
    return int(round(spot / NIFTY_STEP) * NIFTY_STEP)


def sensex_atm(spot: float) -> int:
    """Round Sensex spot to nearest 100."""
    return int(round(spot / SENSEX_STEP) * SENSEX_STEP)


def pair_sensex_strike(nifty_strike: int, nifty_spot: float, sensex_spot: float) -> int:
    """Sensex strike paired with `nifty_strike` (distance-preserving, per client).

        ITM_value     = nifty_spot − nifty_strike      (positive ⇒ OTM PE)
        sensex_strike = round_to_100(sensex_spot − ITM_value × 3.2)

    So the Sensex strike sits the same moneyness distance away from its spot
    as the Nifty strike, scaled by the 3.2 ratio.
    """
    itm = nifty_spot - nifty_strike
    return int(round((sensex_spot - itm * NIFTY_TO_SENSEX_RATIO) / SENSEX_STEP) * SENSEX_STEP)


def _live_spot(security_id: str) -> Optional[float]:
    q = quote_store.get(security_id)
    return q.ltp or None


def _live_pe(security_id: Optional[str]):
    """Return (bid, ask, ltp) tuple for an option contract; (None, None, None) if unsubscribed."""
    if not security_id:
        return None, None, None
    q = quote_store.get(security_id)
    return (q.bid or None, q.ask or None, q.ltp or None)


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
    """Pick the next `n` weekly expiries (<= 28 days away — filters monthly+)."""
    today = datetime.now()
    near = sorted(e for e in expiry_map.keys() if e >= today and (e - today).days <= 28)
    return near[:n]


def _pair_sensex_with_nifty(
    nifty_weeks: list[datetime],
    sensex_map: dict[datetime, dict[int, dict]],
) -> list[datetime | None]:
    """For each Nifty expiry, find the Sensex expiry in the SAME WEEK.

    Nifty weeklies expire on Tuesday; Sensex weeklies on Thursday — so for each
    Nifty Tuesday we want the Sensex Thursday 2 days after (within 7 days, AFTER
    the Nifty date is preferred; fall back to nearest within ±7 days).
    """
    all_sensex = sorted(sensex_map.keys())
    out: list[datetime | None] = []
    for ne in nifty_weeks:
        match = next(
            (se for se in all_sensex if 0 <= (se - ne).days <= 7),
            None,
        )
        if not match:
            match = min(
                (se for se in all_sensex if abs((se - ne).days) <= 7),
                key=lambda se: abs((se - ne).days),
                default=None,
            )
        out.append(match)
    return out


def refresh(min_days_ahead: int = 0) -> None:
    """Resolve weekly PE options for both indices and pick subscription window.

    Called once at feed startup. Stores everything in `_state`.
    """
    csv_text = _download_csv()
    nifty_map = _resolve_index_pe_options(csv_text, "NIFTY", "NSE")
    sensex_map = _resolve_index_pe_options(csv_text, "SENSEX", "BSE")

    nifty_weeks = _pick_weeklies(nifty_map, WEEK_COUNT)
    sensex_weeks = _pair_sensex_with_nifty(nifty_weeks, sensex_map)

    if not nifty_weeks:
        log.warning("Options refresh: no Nifty weekly expiries found.")
        return
    # Drop any (nifty, sensex) pairs where Sensex match couldn't be found.
    paired = [(n, s) for n, s in zip(nifty_weeks, sensex_weeks) if s is not None]
    if not paired:
        log.warning("Options refresh: no Nifty↔Sensex same-week pairs found.")
        return
    nifty_weeks = [n for n, _ in paired]
    sensex_weeks = [s for _, s in paired]
    for i, (n, s) in enumerate(paired):
        log.info("Options week %d: Nifty %s ↔ Sensex %s", i + 1, n.date(), s.date())

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
    sensex_anchor = sensex_atm(sensex_spot)
    log.info(
        "Options anchor — Nifty spot=%.2f → ATM=%d ; Sensex spot=%.2f → ATM=%d",
        nifty_spot or 0, nifty_anchor, sensex_spot or 0, sensex_anchor,
    )

    # Build subscription windows around each index's own ATM.
    options: dict = {}
    for wk_i, expiry in enumerate(nifty_weeks):
        strikes_map = nifty_map[expiry]
        for k in range(-SUB_BELOW_NIFTY, SUB_ABOVE + 1):
            strike = nifty_anchor + k * NIFTY_STEP
            if strike in strikes_map:
                options[("NIFTY", wk_i, strike, "PE")] = {
                    **strikes_map[strike],
                    "expiry": expiry.isoformat(),
                }
    for wk_i, expiry in enumerate(sensex_weeks):
        strikes_map = sensex_map[expiry]
        for k in range(-SUB_BELOW_SENSEX, SUB_ABOVE + 1):
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
    _state["nifty_spot_at_refresh"] = nifty_spot
    _state["sensex_spot_at_refresh"] = sensex_spot
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


def get_spread_table(side: str = "below") -> dict:
    """Compute the live spread table (3 weeks) using current quotes.

    side="below" (default): ATM + 9 lower strikes  = 10 rows (OTM puts).
    side="above"          : ATM + 14 higher strikes = 15 rows (the positive side).

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

    # Fall back to spot snapshot captured at refresh() if live tick missing.
    nifty_spot_for_calc = nifty_spot or _state.get("nifty_spot_at_refresh")
    sensex_spot_for_calc = sensex_spot or _state.get("sensex_spot_at_refresh")

    nifty_atm_live = nifty_atm(nifty_spot_for_calc) if nifty_spot_for_calc else _state.get("nifty_anchor")
    sensex_atm_live = sensex_atm(sensex_spot_for_calc) if sensex_spot_for_calc else _state.get("sensex_anchor")

    above = side == "above"
    count = ABOVE_ROWS if above else DISPLAY_STRIKES   # 15 above (ATM+14) | 10 below (ATM+9)
    step_sign = 1 if above else -1                     # walk up for "above", down for "below"

    weeks_out = []
    nifty_weeks = _state.get("nifty_weeks") or []
    sensex_weeks = _state.get("sensex_weeks") or []

    # Pair weeks by index (current week 0, next 1, next-next 2). Client said
    # ±1-2 day difference between Nifty & Sensex weekly is OK.
    for wk_i in range(min(len(nifty_weeks), len(sensex_weeks))):
        rows = []
        for offset in range(0, count):  # 0=ATM, then up (above) or down (below)
            nifty_strike = nifty_atm_live + step_sign * offset * NIFTY_STEP if nifty_atm_live else None
            sensex_strike = (
                pair_sensex_strike(nifty_strike, nifty_spot_for_calc, sensex_spot_for_calc)
                if (nifty_strike and nifty_spot_for_calc and sensex_spot_for_calc)
                else None
            )
            n_info = _state["options"].get(("NIFTY", wk_i, nifty_strike, "PE")) if nifty_strike else None
            s_info = _state["options"].get(("SENSEX", wk_i, sensex_strike, "PE")) if sensex_strike else None
            n_bid, n_ask, n_ltp = _live_pe(n_info["security_id"] if n_info else None)
            s_bid, s_ask, s_ltp = _live_pe(s_info["security_id"] if s_info else None)
            # Executable spread per client: SELL Nifty PE at BID, BUY Sensex PE at ASK.
            # Fall back to LTP if bid/ask not present.
            n_price = n_bid if n_bid else n_ltp
            s_price = s_ask if s_ask else s_ltp
            n_value = (n_price * NIFTY_MULT) if n_price else None
            s_value = (s_price * SENSEX_MULT) if s_price else None
            spread = (n_value - s_value) if (n_value is not None and s_value is not None) else None
            rows.append({
                "nifty_strike": nifty_strike,
                "sensex_strike": sensex_strike,
                "nifty_pe": n_ltp,         # LTP (informational)
                "sensex_pe": s_ltp,
                "nifty_bid": n_bid,        # used for spread (sell side)
                "sensex_ask": s_ask,       # used for spread (buy side)
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
        "side": side,
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
