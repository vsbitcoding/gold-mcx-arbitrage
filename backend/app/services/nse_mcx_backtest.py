"""Backtester for the NSE-vs-MCX option premium arbitrage (client's notebook,
09-Sep-2026, second page 10-Sep-2026).

The idea: the same option (strike, side) settles at different premiums on the
two exchanges. Buy it where it is cheap, sell it where it is dear, run to the
first expiry. Rules from the notebook, every number a parameter:

  entry   OTM strikes 300-800 points from the day's ATM (CE above, PE below),
          premium difference >= 25 when both expiries coincide, >= 60 when
          they are about a week apart. Buy on the cheaper exchange, sell on
          the dearer one, one lot each. Only inside the entry window: at most
          `entry_days` calendar days before the first expiry (0 = any day).
  exit    `exit_days` calendar days before the FIRST expiry (0 = on the expiry
          day itself) both legs are squared at that day's closes - if the trade
          is in profit. A losing trade is carried instead (`loss_roll`): each
          leg is shifted to its exchange's next expiry `roll_days` before its
          own expiry (NSE leg first when NSE expires first, MCX leg later), the
          same strike, and the check repeats at the new first expiry. `max_rolls`
          caps the shifts (0 = no cap); `roll_legs` limits which leg may shift.
  modes   hold        - nothing between entry and exit
          roll (b1)   - future moves `move_points` against a side (down hurts
                        the CE, up hurts the PE): close that strike, open the
                        strike that fits the new ATM
          add  (b2)   - same trigger, but the old strike stays and the new one
                        is added
  p&l     points x point_value (100 rupees a point on crude).

Everything is closing prices from nse_mcx_opt_daily - the only history either
exchange publishes - so a trade is entered at the close of its signal day and
priced at closes throughout. Deterministic, in memory, a few milliseconds
per expiry.
"""
from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import NseMcxOptDaily
from app.services import nse_opt_history as hist

log = logging.getLogger("nse_mcx_backtest")

DEFAULTS = {
    "commodity": "crude",
    "start": "2024-04-01", "end": None,
    "expiry": None,                 # one NSE expiry, or every expiry in range
    "sides": "both",                # both | CE | PE
    "threshold_same": 25.0,         # both expiries on the same day
    "threshold_gap": 60.0,          # expiries a week apart
    "otm_min": 300.0, "otm_max": 800.0,
    "strike_step": 100.0,           # ladder to consider (100 = every hundred, 500 = the round ones)
    "mode": "hold",                 # hold | roll | add
    "move_points": 500.0,
    "point_value": 100.0,
    "multi": False,                 # several open strikes per side per expiry
    "liquid_only": True,            # entry needs volume on BOTH exchanges that day
    "pick": "max",                  # max = widest difference among candidates, near = nearest to ATM
    "entry_days": 30,               # entries only this many calendar days before the first expiry (0 = any day)
    "exit_days": 10,                # square off this many calendar days before the first expiry (0 = on expiry)
    "loss_roll": True,              # a losing trade is not squared: each leg shifts to the next expiry
    "roll_days": 1,                 # shift a leg this many calendar days before its own expiry
    "roll_legs": "both",            # both | NSE | MCX
    "max_rolls": 0,                 # 0 = no cap
}


@dataclass
class Leg:
    exch: str
    exp: str
    dir: str                          # buy | sell
    px: float                         # entry price in the current contract
    exit_px: float | None = None


@dataclass
class Position:
    side: str
    strike: float
    entry_date: str
    buy_exch: str
    sell_exch: str
    buy_px: float
    sell_px: float
    diff: float
    entry_future: float | None
    ref_future: float | None          # the future the move is measured from
    legs: dict = field(default_factory=dict)      # exch -> Leg
    reason: str = "signal"
    adjustments: int = 0
    parent: str | None = None         # the strike this one replaced or joined
    realised: float = 0.0             # points banked by legs already shifted
    rolls: int = 0
    roll_log: list = field(default_factory=list)
    sq_due: str | None = None         # the square-off check date for the current legs
    sq_done: bool = False             # checked and carried (loss)
    exit_date: str | None = None
    buy_exit: float | None = None
    sell_exit: float | None = None
    pnl_points: float | None = None
    exit_reason: str | None = None

    def first_exp(self) -> str:
        return min(l.exp for l in self.legs.values())


def _num(v, d=2):
    return None if v is None else round(v, d)


def _shift(iso: str, days: int) -> str:
    return (datetime.strptime(iso, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def _last_on_or_before(days: list, iso: str) -> str | None:
    i = bisect_right(days, iso)
    return days[i - 1] if i else None


_cache: dict = {}          # commodity -> dataset
_CACHE_SECONDS = 600


def _dataset(commodity: str) -> dict:
    """Every option and future row of the commodity, read once and kept for
    ten minutes (the table changes once a day). One query instead of one per
    expiry took a full run from 13 s to well under a second."""
    import time
    from sqlalchemy import func
    db = SessionLocal()
    try:
        max_date = db.query(func.max(NseMcxOptDaily.trade_date)).filter(NseMcxOptDaily.commodity == commodity).scalar()
        hit = _cache.get(commodity)
        if hit and hit["max_date"] == max_date and time.time() - hit["at"] < _CACHE_SECONDS:
            return hit
        futs: dict = {}          # (exchange, expiry) -> {date: close}
        by_exp: dict = {}        # (exchange, expiry) -> [(date, strike, side, px, vol)]
        pxi: dict = {}           # (exchange, expiry) -> {(date, strike, side): (px, vol)}
        all_days: set = set()
        for r in db.query(NseMcxOptDaily.exchange, NseMcxOptDaily.expiry, NseMcxOptDaily.trade_date, NseMcxOptDaily.strike,
                          NseMcxOptDaily.option_type, NseMcxOptDaily.close, NseMcxOptDaily.settle, NseMcxOptDaily.volume).filter(
                NseMcxOptDaily.commodity == commodity).yield_per(5000):
            exch, exp, td, k, side, close, settle, vol = r
            if side == "FUT":
                futs.setdefault((exch, exp), {})[td] = close or settle
            else:
                # NSE repeats the last traded price as "close" for weeks when a
                # contract does not trade; its daily settlement is the real mark
                if exch == "NSE" and settle and not vol:
                    px = settle
                else:
                    px = close if close else (settle if exch == "NSE" else None)
                by_exp.setdefault((exch, exp), []).append((td, k, side, px, vol or 0))
                pxi.setdefault((exch, exp), {})[(td, k, side)] = (px, vol or 0)
                all_days.add(td)
        cdays = {key: sorted({row[0] for row in rows}) for key, rows in by_exp.items()}   # trading days per contract
        nxt: dict = {}           # (exchange, expiry) -> the exchange's next option expiry
        for exch in ("NSE", "MCX"):
            exps = sorted(e for (ex, e) in by_exp if ex == exch)
            for a, b in zip(exps, exps[1:]):
                nxt[(exch, a)] = b
        hit = {"by_exp": by_exp, "futs": futs, "pxi": pxi, "cdays": cdays, "next": nxt,
               "days": sorted(all_days), "max_date": max_date, "at": time.time()}
        _cache[commodity] = hit
        return hit
    finally:
        db.close()


def _load(ds: dict, nse_exp: str, mcx_exp: str, start: str | None, end: str | None):
    """Per-day option closes for both exchanges of one expiry pairing, plus
    the underlying futures. Returns (opts, futs, days, nse_fut_exp, mcx_fut_exp)
    where opts[(date, strike, side)] = {nse, mcx, nse_vol, mcx_vol}."""

    def underlying(exch, opt_exp):
        # first future expiring on or after the option's expiry, from the cache
        later = sorted(e for (ex, e) in ds["futs"] if ex == exch and e >= opt_exp)
        return later[0] if later else None
    nse_fut_exp = underlying("NSE", nse_exp)
    mcx_fut_exp = underlying("MCX", mcx_exp)
    futs: dict[str, dict] = {}
    for exch, fexp in (("NSE", nse_fut_exp), ("MCX", mcx_fut_exp)):
        for td, px in (ds["futs"].get((exch, fexp)) or {}).items():
            futs.setdefault(td, {})[exch.lower()] = px
    opts: dict = {}
    for exch, exp in (("NSE", nse_exp), ("MCX", mcx_exp)):
        for td, k, side, px, vol in ds["by_exp"].get((exch, exp), []):
            if (start and td < start) or (end and td > end):
                continue
            cell = opts.setdefault((td, k, side), {"nse": None, "mcx": None, "nse_vol": 0, "mcx_vol": 0})
            cell[exch.lower()] = px
            cell[exch.lower() + "_vol"] = vol
    nse_days = {k[0] for k, v in opts.items() if v["nse"] is not None}
    mcx_days = {k[0] for k, v in opts.items() if v["mcx"] is not None}
    days = sorted(nse_days & mcx_days)
    # the day index the scan walks, so a day costs its own strikes, not every day's
    by_day: dict = {}
    for (td, k, side), cell in opts.items():
        by_day.setdefault(td, []).append((k, side, cell))
    opts["_by_day"] = by_day
    return opts, futs, days, nse_fut_exp, mcx_fut_exp


def _candidates(opts, day, atm, side, p) -> list[tuple[float, dict]]:
    lo, hi = p["otm_min"], p["otm_max"]
    out = []
    for k, s, cell in opts["_by_day"].get(day, []):
        if s != side or cell["nse"] is None or cell["mcx"] is None:
            continue
        if k % p["strike_step"] != 0:
            continue
        dist = (k - atm) if side == "CE" else (atm - k)
        if dist < lo or dist > hi:
            continue
        if p["liquid_only"] and not (cell["nse_vol"] > 0 and cell["mcx_vol"] > 0):
            continue
        out.append((k, cell))
    return out


def _best(cands, threshold, atm, pick) -> tuple[float, dict] | None:
    ok = [(k, c) for k, c in cands if abs(c["nse"] - c["mcx"]) >= threshold]
    if not ok:
        return None
    if pick == "near":
        return min(ok, key=lambda x: abs(x[0] - atm))
    return max(ok, key=lambda x: abs(x[1]["nse"] - x[1]["mcx"]))


def _open(side, k, cell, day, fut, nse_exp, mcx_exp, reason="signal", parent=None) -> Position:
    cheap, dear = ("NSE", "MCX") if cell["nse"] <= cell["mcx"] else ("MCX", "NSE")
    pos = Position(side=side, strike=k, entry_date=day, buy_exch=cheap, sell_exch=dear,
                   buy_px=cell[cheap.lower()], sell_px=cell[dear.lower()],
                   diff=round(cell["nse"] - cell["mcx"], 2), entry_future=fut, ref_future=fut,
                   reason=reason, parent=parent)
    pos.legs = {"NSE": Leg("NSE", nse_exp, "buy" if cheap == "NSE" else "sell", cell["nse"]),
                "MCX": Leg("MCX", mcx_exp, "buy" if cheap == "MCX" else "sell", cell["mcx"])}
    return pos


class _Book:
    """Prices for any contract of the commodity, for legs that left the entry
    pairing (shifted to a later expiry)."""

    def __init__(self, ds: dict):
        self.ds = ds

    def px(self, leg: Leg, day: str, strike: float, side: str) -> float | None:
        cell = self.ds["pxi"].get((leg.exch, leg.exp), {}).get((day, strike, side))
        return cell[0] if cell else None

    def last_px(self, leg: Leg, day: str, strike: float, side: str) -> tuple[str, float] | None:
        """The leg's latest close on or before `day`, up to two weeks back."""
        cdays = self.ds["cdays"].get((leg.exch, leg.exp), [])
        i = bisect_right(cdays, day)
        for d in reversed(cdays[max(0, i - 10):i]):
            v = self.px(leg, d, strike, side)
            if v is not None:
                return d, v
        return None

    def roll_day(self, leg: Leg, roll_days: int) -> str | None:
        """The contract's last trading day on or before `roll_days` before its
        expiry; None while that date is still beyond the end of the data."""
        target = _shift(leg.exp, roll_days)
        if target > self.ds["days"][-1]:
            return None
        cdays = self.ds["cdays"].get((leg.exch, leg.exp), [])
        return _last_on_or_before(cdays, target)

    def next_exp(self, leg: Leg) -> str | None:
        return self.ds["next"].get((leg.exch, leg.exp))


def _leg_pnl(leg: Leg, now: float) -> float:
    return (now - leg.px) if leg.dir == "buy" else (leg.px - now)


def _mark(pos: Position, book: _Book, day: str) -> float | None:
    """Open P&L in points at the day's closes; None when a leg has no close."""
    total = pos.realised
    for leg in pos.legs.values():
        now = book.px(leg, day, pos.strike, pos.side)
        if now is None:
            return None
        total += _leg_pnl(leg, now)
    return round(total, 2)


def _close(pos: Position, book: _Book, day: str, reason: str, fallback: bool = False) -> bool:
    """Square both legs at the day's closes; with `fallback` a leg with no close
    that day uses its latest earlier close. False if a leg cannot be priced."""
    exits = {}
    for exch, leg in pos.legs.items():
        now = book.px(leg, day, pos.strike, pos.side)
        if now is None and fallback:
            hit = book.last_px(leg, day, pos.strike, pos.side)
            now = hit[1] if hit else None
        if now is None:
            return False
        exits[exch] = now
    for exch, leg in pos.legs.items():
        leg.exit_px = exits[exch]
    pos.exit_date = day
    pos.buy_exit = exits[pos.buy_exch]
    pos.sell_exit = exits[pos.sell_exch]
    pos.pnl_points = round(pos.realised + sum(_leg_pnl(l, exits[e]) for e, l in pos.legs.items()), 2)
    pos.exit_reason = reason
    return True


def _set_sq_due(pos: Position, book: _Book, exit_days: int, today: str | None = None):
    target = _shift(pos.first_exp(), exit_days)
    due = _last_on_or_before(book.ds["days"], target) if target <= book.ds["days"][-1] else None
    if today is None or due is None or due > today:
        pos.sq_due, pos.sq_done = due, False


def _roll_leg(pos: Position, leg: Leg, book: _Book, day: str) -> bool:
    """Shift one leg to its exchange's next expiry at the day's closes (the
    settlement price when the next contract did not trade that day)."""
    nxt = book.next_exp(leg)
    if not nxt:
        return False
    now = book.px(leg, day, pos.strike, pos.side)
    new_leg = Leg(leg.exch, nxt, leg.dir, 0.0)
    new_px = book.px(new_leg, day, pos.strike, pos.side)
    if now is None or new_px is None:
        return False
    leg.exit_px = now
    pos.realised = round(pos.realised + _leg_pnl(leg, now), 2)
    new_leg.px = new_px
    pos.legs[leg.exch] = new_leg
    pos.rolls += 1
    pos.roll_log.append({"date": day, "exch": leg.exch, "from": leg.exp, "to": nxt, "out": now, "in": new_px})
    return True


def _manage(pos: Position, book: _Book, day: str, p: dict) -> bool:
    """Square-off check, expiry shifts and forced closes for one open
    position on one day. True when the position closed."""
    # a contract expired without a close to act on: settle at the latest prices
    if any(leg.exp < day for leg in pos.legs.values()):
        return _close(pos, book, day, "last price", fallback=True)
    can_roll = p["loss_roll"] and (not p["max_rolls"] or pos.rolls < p["max_rolls"])
    # 1. the square-off date for the current legs: profit closes, loss carries
    if not pos.sq_done and pos.sq_due and day >= pos.sq_due:
        pnl = _mark(pos, book, day)
        if pnl is not None:
            at_expiry = day >= pos.first_exp() or not p["exit_days"]
            if pnl >= 0 or not can_roll:
                return _close(pos, book, day, "expiry" if at_expiry else "square off")
            pos.sq_done = True
    if not p["loss_roll"]:
        return False
    # 2. a leg close to its own expiry: profit closes, loss shifts the leg
    for exch in ("NSE", "MCX"):
        leg = pos.legs[exch]
        rd = book.roll_day(leg, p["roll_days"])
        if not rd or day < rd:
            continue
        pnl = _mark(pos, book, day)
        if pnl is None:
            continue
        if pnl >= 0:
            return _close(pos, book, day, "expiry" if day >= leg.exp else "square off")
        allowed = can_roll and p["roll_legs"] in ("both", exch)
        if not allowed or not _roll_leg(pos, leg, book, day):
            if day >= leg.exp:
                return _close(pos, book, day, "expiry")
            continue                       # try again tomorrow, up to the expiry day
        _set_sq_due(pos, book, p["exit_days"], today=day)
    return False


def run_expiry(ds: dict, nse_exp: str, mcx_exp: str, p: dict) -> dict:
    book = _Book(ds)
    opts, futs, days, nse_fut_exp, mcx_fut_exp = _load(ds, nse_exp, mcx_exp, p.get("start"), p.get("end"))
    first_exp = min(nse_exp, mcx_exp)
    days = [d for d in days if d <= first_exp]
    day_set = set(days)
    gap = abs((datetime.strptime(mcx_exp, "%Y-%m-%d") - datetime.strptime(nse_exp, "%Y-%m-%d")).days)
    threshold = p["threshold_same"] if gap == 0 else p["threshold_gap"]
    sides = ["CE", "PE"] if p["sides"] == "both" else [p["sides"]]
    strikes_all = sorted({k for key in opts if key != "_by_day" for k in [key[1]] if k % p["strike_step"] == 0})
    sq_day = _last_on_or_before(days, _shift(first_exp, p["exit_days"])) or first_exp
    window_from = _shift(first_exp, p["entry_days"]) if p["entry_days"] else None
    open_pos: list[Position] = []
    closed: list[Position] = []
    last_day = days[-1] if days else None
    if not days:
        return {"nse_expiry": nse_exp, "mcx_expiry": mcx_exp, "gap_days": gap, "threshold": threshold,
                "nse_future_expiry": nse_fut_exp, "mcx_future_expiry": mcx_fut_exp,
                "days": 0, "first_day": None, "last_day": None, "trades": []}
    walk = ds["days"][bisect_right(ds["days"], days[0]) - 1:]
    if p.get("end"):
        walk = [d for d in walk if d <= p["end"]]
    for day in walk:
        if day > first_exp and not open_pos:
            break
        if day in day_set:
            f = futs.get(day, {})
            fut = f.get("nse") if f.get("nse") is not None else f.get("mcx")
            atm = min(strikes_all, key=lambda k: abs(k - fut)) if (strikes_all and fut) else None
            if atm is not None:
                # 1. adjustments on what is open (roll / add), measured from the reference future
                if p["mode"] in ("roll", "add") and fut is not None:
                    for pos in list(open_pos):
                        if pos.ref_future is None or pos.rolls:
                            continue
                        move = fut - pos.ref_future
                        hurt = (pos.side == "CE" and move <= -p["move_points"]) or (pos.side == "PE" and move >= p["move_points"])
                        if not hurt:
                            continue
                        cand = _best(_candidates(opts, day, atm, pos.side, p), threshold, atm, p["pick"])
                        if cand is None:
                            continue                          # nothing fit today; try again tomorrow
                        k, cell = cand
                        if k == pos.strike:
                            pos.ref_future = fut
                            continue
                        if p["mode"] == "roll":
                            if _close(pos, book, day, "adjusted"):
                                open_pos.remove(pos); closed.append(pos)
                        else:
                            pos.ref_future = fut
                        newp = _open(pos.side, k, cell, day, fut, nse_exp, mcx_exp, reason="adjust", parent=f"{pos.strike:g}")
                        newp.adjustments = pos.adjustments + 1
                        _set_sq_due(newp, book, p["exit_days"])
                        open_pos.append(newp)
                # 2. fresh signals, inside the entry window and before the square-off day
                if day < sq_day and (window_from is None or day >= window_from):
                    for side in sides:
                        have = [x for x in open_pos if x.side == side]
                        if have and not p["multi"]:
                            continue
                        cand = _best(_candidates(opts, day, atm, side, p), threshold, atm, p["pick"])
                        if cand is None:
                            continue
                        k, cell = cand
                        if any(x.strike == k for x in have):
                            continue
                        pos = _open(side, k, cell, day, fut, nse_exp, mcx_exp)
                        _set_sq_due(pos, book, p["exit_days"])
                        open_pos.append(pos)
        # 3. square-off checks, expiry shifts, forced closes
        for pos in list(open_pos):
            if _manage(pos, book, day, p):
                open_pos.remove(pos); closed.append(pos)
    # anything still open at the end of the data: mark at the latest closes
    for pos in list(open_pos):
        _close(pos, book, walk[-1], "data end", fallback=True)
        closed.append(pos)
    trades = []
    for t in sorted(closed, key=lambda x: (x.entry_date, x.side, x.strike)):
        rs = t.pnl_points * p["point_value"] if t.pnl_points is not None else None
        trades.append({
            "nse_expiry": nse_exp, "mcx_expiry": mcx_exp, "gap_days": gap, "threshold": threshold,
            "side": t.side, "strike": t.strike, "entry_date": t.entry_date, "reason": t.reason, "parent": t.parent,
            "buy_exch": t.buy_exch, "buy_px": _num(t.buy_px), "sell_exch": t.sell_exch, "sell_px": _num(t.sell_px),
            "diff": t.diff, "entry_future": _num(t.entry_future),
            "exit_date": t.exit_date, "exit_reason": t.exit_reason, "buy_exit": _num(t.buy_exit), "sell_exit": _num(t.sell_exit),
            "exit_nse_expiry": t.legs["NSE"].exp, "exit_mcx_expiry": t.legs["MCX"].exp,
            "rolls": t.rolls, "roll_log": t.roll_log, "realised": _num(t.realised),
            "pnl_points": t.pnl_points, "pnl_rs": _num(rs, 0),
            "days": (datetime.strptime(t.exit_date, "%Y-%m-%d") - datetime.strptime(t.entry_date, "%Y-%m-%d")).days if t.exit_date else None,
        })
    return {"nse_expiry": nse_exp, "mcx_expiry": mcx_exp, "gap_days": gap, "threshold": threshold,
            "nse_future_expiry": nse_fut_exp, "mcx_future_expiry": mcx_fut_exp,
            "days": len(days), "first_day": days[0] if days else None, "last_day": last_day, "trades": trades}


def run(params: dict) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None and v != ""}}
    for k in ("threshold_same", "threshold_gap", "otm_min", "otm_max", "strike_step", "move_points", "point_value"):
        p[k] = float(p[k])
    for k in ("entry_days", "exit_days", "roll_days", "max_rolls"):
        p[k] = max(0, int(float(p[k])))
    p["multi"] = bool(p["multi"]); p["liquid_only"] = bool(p["liquid_only"]); p["loss_roll"] = bool(p["loss_roll"])
    if p["roll_legs"] not in ("both", "NSE", "MCX"):
        p["roll_legs"] = "both"
    commodity = p["commodity"]
    pairs = hist.expiries(commodity)["expiries"]          # newest first
    chosen = [e for e in pairs if e["mcx"] and (not p["expiry"] or e["nse"] == p["expiry"])
              and (not p["start"] or e["nse"] >= p["start"]) and (not p["end"] or e["nse"] <= p["end"])]
    chosen.sort(key=lambda e: e["nse"])
    ds = _dataset(commodity)
    per_expiry = []
    trades: list[dict] = []
    for e in chosen:
        res = run_expiry(ds, e["nse"], e["mcx"], p)
        pts = sum(t["pnl_points"] or 0 for t in res["trades"])
        wins = sum(1 for t in res["trades"] if (t["pnl_points"] or 0) > 0)
        per_expiry.append({"nse_expiry": e["nse"], "mcx_expiry": e["mcx"], "gap_days": res["gap_days"], "threshold": res["threshold"],
                           "days": res["days"], "trades": len(res["trades"]), "wins": wins,
                           "rolls": sum(t["rolls"] for t in res["trades"]),
                           "pnl_points": round(pts, 2), "pnl_rs": round(pts * p["point_value"], 0)})
        trades.extend(res["trades"])
    trades.sort(key=lambda t: (t["entry_date"], t["nse_expiry"], t["side"], t["strike"]))
    pnl = [t["pnl_points"] or 0 for t in trades]
    wins = [x for x in pnl if x > 0]; losses = [x for x in pnl if x < 0]
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    for t in sorted(trades, key=lambda t: (t["exit_date"] or "", t["entry_date"])):
        cum += t["pnl_points"] or 0
        peak = max(peak, cum); dd = min(dd, cum - peak)
        curve.append({"date": t["exit_date"], "cum_points": round(cum, 2), "cum_rs": round(cum * p["point_value"], 0)})
    summary = {
        "trades": len(trades), "wins": len(wins), "losses": len(losses), "flat": len(pnl) - len(wins) - len(losses),
        "win_rate": round(len(wins) / len(pnl) * 100, 1) if pnl else None,
        "pnl_points": round(sum(pnl), 2), "pnl_rs": round(sum(pnl) * p["point_value"], 0),
        "avg_points": round(sum(pnl) / len(pnl), 2) if pnl else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "best": round(max(pnl), 2) if pnl else None, "worst": round(min(pnl), 2) if pnl else None,
        "max_drawdown_points": round(dd, 2), "max_drawdown_rs": round(dd * p["point_value"], 0),
        "avg_days": round(sum(t["days"] or 0 for t in trades) / len(trades), 1) if trades else None,
        "rolls": sum(t["rolls"] for t in trades),
        "rolled_trades": sum(1 for t in trades if t["rolls"]),
        "expiries": len(per_expiry),
    }
    return {"params": p, "summary": summary, "by_expiry": per_expiry, "trades": trades, "equity": curve}
