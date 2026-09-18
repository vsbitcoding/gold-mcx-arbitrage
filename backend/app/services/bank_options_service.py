"""BANKEX / BANKNIFTY monthly option comparison, using the shared live feed.

The BANKEX strike is the anchor: match the same distance from each index's
live ATM, CE above ATM and PE below. The earlier expiry is bought at ask;
the later expiry is sold at bid. The display divisor is NOT a contract lot
size or an execution rule. Actual lots come from the instrument master.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

from app.services.angel_master import INDEX_IDS
from app.services.instrument_resolver import _download_csv, _parse_expiry
from app.services.market_data import clean_sides, quote_store

log = logging.getLogger("bank_options")
IST = timezone(timedelta(hours=5, minutes=30))
INDICES = ("BANKEX", "BANKNIFTY")
EXCHANGES = {"BANKEX": "BFO", "BANKNIFTY": "NFO"}
FRESH_SECONDS = 60
SUBSCRIPTION_RADIUS = 6000
MAX_DISPLAY_RANGE = 3000
_lock = threading.RLock()
_state = {"contracts": {}, "expiries": {}, "anchors": {}, "subscribed": set(),
          "requested": 0, "capacity_limited": False, "refreshed": 0.0}
# Persisted quotes deliberately cannot pass as new ticks after a restart.
_live_seen: dict[str, float] = {}
_last_window_check = 0.0


def _now() -> datetime:
    return datetime.now(IST)


def note_live_tick(security_id: str, timestamp: float) -> None:
    with _lock:
        _live_seen[str(security_id)] = timestamp


def _positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def seed_spots(jwt: str, credentials: dict) -> None:
    """One startup quote with the feed's existing login; never mint a session.

    This centres subscriptions before the first index socket tick. All ongoing
    values come from that socket. Failure leaves an honest waiting state.
    """
    from app.services import angel_feed
    import requests
    try:
        with requests.Session() as session:
            rows = angel_feed._quote(session, credentials, jwt, {
                "BSE": [INDEX_IDS["BANKEX"]], "NSE": [INDEX_IDS["BANKNIFTY"]]})
        for index in INDICES:
            sid = INDEX_IDS[index]
            price = _positive((rows.get(sid) or {}).get("ltp"))
            if price:
                now = time.time()
                quote_store.update(sid, price, price, price, now)
                note_live_tick(sid, now)
    except Exception as exc:  # this page must never prevent other feeds starting
        log.warning("Bank index startup quotes unavailable: %s", exc)


def _monthly_expiry(expiries: list[str], now: datetime) -> str | None:
    # The last LISTED expiry in each calendar month is monthly. Read actual
    # exchange dates (including holiday changes), never assume a weekday.
    monthly = {}
    for expiry in expiries:
        monthly[expiry[:7]] = max(expiry, monthly.get(expiry[:7], ""))
    cutoff = now.date().isoformat()
    active = [e for e in monthly.values()
              if e > cutoff or (e == cutoff and (now.hour, now.minute) < (15, 30))]
    return min(active, default=None)


def refresh() -> None:
    """Resolve only the current monthly contracts, retaining real lot sizes."""
    candidates = {index: {} for index in INDICES}
    for row in csv.DictReader(io.StringIO(_download_csv())):
        index = (row.get("SEM_TRADING_SYMBOL") or "").split("-", 1)[0]
        if index not in INDICES or row.get("SEM_INSTRUMENT_NAME") != "OPTIDX":
            continue
        exchange = EXCHANGES[index]
        if row.get("SEM_EXM_EXCH_ID") != ("BSE" if exchange == "BFO" else "NSE"):
            continue
        expiry = _parse_expiry(row.get("SEM_EXPIRY_DATE", ""))
        side = row.get("SEM_OPTION_TYPE")
        strike = _positive(row.get("SEM_STRIKE_PRICE"))
        lot_size = _positive(row.get("SEM_LOT_UNITS"))
        token = str(row.get("SEM_SMST_SECURITY_ID") or "")
        if not expiry or side not in ("CE", "PE") or not strike or not lot_size or not token:
            continue
        if int(lot_size) != lot_size:
            continue
        day = expiry.date().isoformat()
        meta = {"index": index, "security_id": f"{exchange}:{token}", "token": token,
                "exchange": exchange, "exch": exchange, "kind": "bank_option",
                "trading_symbol": row["SEM_TRADING_SYMBOL"], "side": side,
                "strike": strike, "expiry": day, "lot_size": int(lot_size)}
        candidates[index].setdefault(day, {})[(strike, side)] = meta
    contracts, expiries, anchors = {}, {}, {}
    now = _now()
    for index, by_expiry in candidates.items():
        expiry = _monthly_expiry(list(by_expiry), now)
        expiries[index] = expiry
        contracts[index] = by_expiry.get(expiry, {})
        spot = _positive(quote_store.get(INDEX_IDS[index]).ltp)
        # A median can centre a bootstrap subscription, never a displayed ATM.
        strikes = sorted({key[0] for key in contracts[index]})
        anchors[index] = spot or (strikes[len(strikes) // 2] if strikes else None)
    with _lock:
        _state.update(contracts=contracts, expiries=expiries, anchors=anchors,
                      refreshed=time.time())


def get_subscription_meta() -> dict[str, dict]:
    with _lock:
        state = dict(_state)
    out = {INDEX_IDS[index]: {"kind": "index", "underlying": index,
            "trading_symbol": index, "exch": "BSE" if index == "BANKEX" else "NSE"}
           for index in INDICES}
    options = []
    for index in INDICES:
        anchor = state["anchors"].get(index)
        if not anchor:
            continue
        for meta in state["contracts"].get(index, {}).values():
            distance = abs(meta["strike"] - anchor)
            if distance <= SUBSCRIPTION_RADIUS:
                options.append((distance, meta["security_id"], meta))
    # Nearer contracts survive first if the shared feed has little capacity.
    for _distance, sid, meta in sorted(options, key=lambda item: (item[0], item[1])):
        out[sid] = meta
    with _lock:
        _state["requested"] = len(out)
    return out


def set_subscribed(subscriptions: dict[str, dict], capacity_limited: bool = False) -> None:
    with _lock:
        _state["subscribed"] = set(subscriptions)
        _state["capacity_limited"] = capacity_limited


def subscription_update_needed() -> bool:
    """Re-centre only after a large move or expiry, never on every ATM change.

    Called by the existing socket supervisor, with a five-minute debounce.
    An ordinary ATM move stays inside the wide, already-subscribed buffer.
    """
    global _last_window_check
    now_ts = time.time()
    if now_ts - _last_window_check < 300:
        return False
    with _lock:
        state = dict(_state)
        seen = dict(_live_seen)
    if not state["refreshed"] or now_ts - state["refreshed"] < 120:
        return False
    now = _now()
    for index in INDICES:
        expiry = state["expiries"].get(index)
        expired = expiry and (expiry < now.date().isoformat() or
            (expiry == now.date().isoformat() and (now.hour, now.minute) >= (15, 30)))
        spot = _positive(quote_store.get(INDEX_IDS[index]).ltp)
        fresh = now_ts - seen.get(INDEX_IDS[index], 0) <= FRESH_SECONDS
        anchor = state["anchors"].get(index)
        moved = fresh and spot and anchor and abs(spot - anchor) > SUBSCRIPTION_RADIUS - MAX_DISPLAY_RANGE
        if expired or moved:
            _last_window_check = now_ts
            return True
    return False


def market_is_open() -> bool:
    from app.services import market_calendar
    # The app shares the equity holiday calendar across NSE and BSE.
    return market_calendar.is_open("NSE")


def quote_leg(meta: dict) -> dict:
    q = quote_store.get(meta["security_id"])
    bid, ask = clean_sides(q)
    bid, ask = _positive(bid), _positive(ask)
    with _lock:
        seen = _live_seen.get(str(meta["security_id"]), 0)
    age = max(0.0, time.time() - seen) if seen else None
    fresh = age is not None and age <= FRESH_SECONDS
    return {**meta, "bid": bid, "ask": ask, "ltp": _positive(q.ltp),
            "volume": max(0, q.volume or 0), "oi": max(0, q.oi or 0),
            "age_seconds": round(age, 1) if age is not None else None,
            "fresh": fresh}


def _indices(state: dict) -> dict:
    out = {}
    for index in INDICES:
        spot_meta = quote_leg({"security_id": INDEX_IDS[index]})
        spot = spot_meta["ltp"]
        strikes = sorted({k[0] for k in state["contracts"].get(index, {})})
        # Match an actual listed strike, breaking a half-step tie upwards.
        atm = min(strikes, key=lambda k: (abs(k - spot), -k)) if strikes and spot else None
        first = next(iter(state["contracts"].get(index, {}).values()), {})
        out[index] = {"spot": spot, "atm": atm, "expiry": state["expiries"].get(index),
                      "lot_size": first.get("lot_size"),
                      "age_seconds": spot_meta["age_seconds"], "fresh": spot_meta["fresh"]}
    return out


def _direction(expiries: dict) -> tuple[str | None, str | None]:
    a, b = expiries.get("BANKEX"), expiries.get("BANKNIFTY")
    if not a or not b or a == b:
        return None, None
    return ("BANKEX", "BANKNIFTY") if a < b else ("BANKNIFTY", "BANKEX")


def _reason(pair: dict, indices: dict, subscribed: set) -> str | None:
    if not pair["buy_index"]:
        return "Both expiries are the same; there is no earlier-expiry buy leg."
    today = _now()
    for index in INDICES:
        leg = pair[index.lower()]
        if not leg or not leg.get("security_id"):
            return "Matching strike is not listed."
        if leg["expiry"] < today.date().isoformat() or (leg["expiry"] == today.date().isoformat()
                and (today.hour, today.minute) >= (15, 30)):
            return "Monthly contracts are rolling to the next expiry."
        if leg["security_id"] not in subscribed:
            return "Waiting for subscription coverage."
        if not indices[index]["fresh"]:
            return "Waiting for fresh index quotes."
        if not leg["fresh"]:
            return "Waiting for fresh option quotes."
        if not leg["bid"] or not leg["ask"]:
            return "Both legs need valid two-sided Bid/Ask quotes."
    if not market_is_open():
        return "Market closed; paper entries are available during market hours."
    return None


def _make_pair(bankex: dict, banknifty: dict, state: dict, indices: dict) -> dict:
    buy, sell = _direction(state["expiries"])
    pair = {"side": bankex["side"], "bankex": quote_leg(bankex),
            "banknifty": quote_leg(banknifty), "buy_index": buy, "sell_index": sell}
    reason = _reason(pair, indices, state["subscribed"])
    pair.update(tradable=reason is None, reason=reason, market_open=market_is_open())
    return pair


def get_entry_pair(bankex_security_id: str, banknifty_security_id: str, side: str) -> dict:
    with _lock:
        state = dict(_state)
    found = {}
    for index, sid in (("BANKEX", bankex_security_id), ("BANKNIFTY", banknifty_security_id)):
        found[index] = next((m for m in state["contracts"].get(index, {}).values()
                             if m["security_id"] == sid and m["side"] == side), None)
    if not all(found.values()):
        raise ValueError("The selected monthly pair is no longer available. Refresh the Live view.")
    indices = _indices(state)
    if any(indices[i]["atm"] is None for i in INDICES):
        raise ValueError("Waiting for both live index quotes.")
    offsets = [found[i]["strike"] - indices[i]["atm"] for i in INDICES]
    if offsets[0] != offsets[1] or (side == "CE" and offsets[0] < 0) or (side == "PE" and offsets[0] > 0):
        raise ValueError("ATM has changed. Select the matching pair from the refreshed Live view.")
    pair = _make_pair(found["BANKEX"], found["BANKNIFTY"], state, indices)
    if not pair["tradable"]:
        raise ValueError(pair["reason"])
    return pair


def get_live(*, side="both", range_points=2000, liquidity="liquid", min_volume=1,
             max_spread_pct=10.0, bankex_lots=1, banknifty_lots=1,
             metric="divided", divisor=30.0) -> dict:
    with _lock:
        state = dict(_state)
    indices = _indices(state)
    buy, sell = _direction(state["expiries"])
    market_open = market_is_open()
    message = None
    if any(not indices[i]["expiry"] for i in INDICES):
        message = "Waiting for current monthly BANKEX and BANKNIFTY contracts."
    elif any(indices[i]["atm"] is None for i in INDICES):
        message = "Waiting for live BANKEX and BANKNIFTY index quotes."
    elif not buy:
        message = "Both expiries are the same; an earlier-expiry buy leg cannot be selected."
    elif any(not indices[i]["fresh"] for i in INDICES):
        message = "Index quotes are stale; paper entries are paused."
    elif not market_open:
        message = "Market closed. Paper entry and square-off resume with fresh market quotes."
    if state["capacity_limited"]:
        message = (message + " " if message else "") + "Some bank strikes exceed the feed subscription capacity."
    formula = {"points": "Sell Bid − Buy Ask",
               "divided": f"(Sell Bid − Buy Ask) ÷ {divisor:g}",
               "rupees": "(Sell Bid × sell quantity) − (Buy Ask × buy quantity)"}[metric]
    out = {"server_time": datetime.now(timezone.utc).isoformat(), "market_open": market_open,
           "indices": indices, "buy_index": buy, "sell_index": sell,
           "status": {"ready": all(indices[i]["atm"] and indices[i]["fresh"] for i in INDICES),
                      "message": message, "subscribed_options": sum(":" in s for s in state["subscribed"])},
           "rows": [], "bankex_strikes": [], "counts": {"candidates": 0, "shown": 0, "filtered": 0},
           "formula": formula}
    if any(indices[i]["atm"] is None for i in INDICES):
        return out
    bankex_atm, nifty_atm = indices["BANKEX"]["atm"], indices["BANKNIFTY"]["atm"]
    candidates = []
    lots = {"BANKEX": bankex_lots, "BANKNIFTY": banknifty_lots}
    for (strike, option_type), be in state["contracts"].get("BANKEX", {}).items():
        offset = strike - bankex_atm
        if abs(offset) > range_points or (side != "both" and side != option_type):
            continue
        if (option_type == "CE" and offset < 0) or (option_type == "PE" and offset > 0):
            continue
        bn = state["contracts"].get("BANKNIFTY", {}).get((nifty_atm + offset, option_type))
        if not bn:
            continue  # never silently pair a different moneyness distance
        pair = _make_pair(be, bn, state, indices)
        beq = pair["bankex"]
        mid = (beq["bid"] + beq["ask"]) / 2 if beq["bid"] and beq["ask"] else None
        spread_pct = ((beq["ask"] - beq["bid"]) / mid * 100) if mid else None
        liquid = bool(mid and beq["fresh"] and beq["volume"] >= min_volume
                      and spread_pct <= max_spread_pct)
        pair.update(id=f"{option_type}:{be['security_id']}:{bn['security_id']}",
                    offset_points=offset, liquid=liquid, bankex_spread_pct=spread_pct)
        buy_leg = pair[buy.lower()] if buy else {}
        sell_leg = pair[sell.lower()] if sell else {}
        buy_px, sell_px = buy_leg.get("ask"), sell_leg.get("bid")
        priced = bool(buy_px and sell_px and buy_leg.get("fresh") and sell_leg.get("fresh")
                      and buy_leg.get("bid") and sell_leg.get("ask"))
        difference = sell_px - buy_px if priced else None
        value = (sell_px * sell_leg["lot_size"] * lots[sell]
                 - buy_px * buy_leg["lot_size"] * lots[buy]) if priced else None
        divided = difference / divisor if difference is not None else None
        values = {"points": difference, "divided": divided, "rupees": value}
        pair.update(buy_price=buy_px, sell_price=sell_px,
                    difference_points=round(difference, 4) if difference is not None else None,
                    difference_divided=round(divided, 4) if divided is not None else None,
                    value_rupees=round(value, 2) if value is not None else None,
                    display_value=round(values[metric], 4) if values[metric] is not None else None)
        candidates.append(pair)
    rows = [p for p in candidates if liquidity == "all" or p["liquid"]]
    rows.sort(key=lambda p: (p["side"] != "CE", abs(p["offset_points"])))
    out["rows"] = rows
    out["bankex_strikes"] = sorted({p["bankex"]["strike"] for p in candidates})
    out["counts"] = {"candidates": len(candidates), "shown": len(rows), "filtered": len(candidates) - len(rows)}
    if not rows and not message:
        out["status"]["message"] = "No BANKEX strikes currently meet the selected liquidity filters."
    return out
