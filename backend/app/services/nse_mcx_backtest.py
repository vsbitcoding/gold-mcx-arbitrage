"""Backtester for the NSE-vs-MCX option premium arbitrage (client's notebook,
09-Sep-2026).

The idea: the same option (strike, side) settles at different premiums on the
two exchanges. Buy it where it is cheap, sell it where it is dear, run to the
first expiry. Rules from the notebook, every number a parameter:

  entry   OTM strikes 300-800 points from the day's ATM (CE above, PE below),
          premium difference >= 25 when both expiries coincide, >= 60 when
          they are about a week apart. Buy on the cheaper exchange, sell on
          the dearer one, one lot each.
  exit    both legs squared at the closes of the FIRST expiry day (NSE's).
  modes   hold        - nothing between entry and expiry
          roll (b1)   - future moves `move_points` against a side (down hurts
                        the CE, up hurts the PE): close that strike, open the
                        strike that fits the new ATM
          add  (b2)   - same trigger, but the old strike stays and the new one
                        is added; all run to the first expiry
  p&l     points x point_value (100 rupees a point on crude).

Everything is closing prices from nse_mcx_opt_daily - the only history either
exchange publishes - so a trade is entered at the close of its signal day and
priced at closes throughout. Deterministic, in memory, a few milliseconds
per expiry.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

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
}


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
    reason: str = "signal"
    adjustments: int = 0
    exit_date: str | None = None
    buy_exit: float | None = None
    sell_exit: float | None = None
    pnl_points: float | None = None
    exit_reason: str | None = None
    parent: str | None = None         # the strike this one replaced or joined


def _num(v, d=2):
    return None if v is None else round(v, d)


_cache: dict = {}          # commodity -> {"rows": [...], "futs": {...}, "max_date": str, "at": float}
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
        opts: dict = {}          # (nse_exp|mcx_exp key by exchange) -> per-exchange rows
        futs: dict = {}          # (exchange, expiry) -> {date: close}
        by_exp: dict = {}        # (exchange, expiry) -> [(date, strike, side, px, vol)]
        for r in db.query(NseMcxOptDaily.exchange, NseMcxOptDaily.expiry, NseMcxOptDaily.trade_date, NseMcxOptDaily.strike,
                          NseMcxOptDaily.option_type, NseMcxOptDaily.close, NseMcxOptDaily.settle, NseMcxOptDaily.volume).filter(
                NseMcxOptDaily.commodity == commodity).yield_per(5000):
            exch, exp, td, k, side, close, settle, vol = r
            if side == "FUT":
                futs.setdefault((exch, exp), {})[td] = close or settle
            else:
                px = close if close else (settle if exch == "NSE" else None)
                by_exp.setdefault((exch, exp), []).append((td, k, side, px, vol or 0))
        hit = {"by_exp": by_exp, "futs": futs, "max_date": max_date, "at": time.time()}
        _cache[commodity] = hit
        return hit
    finally:
        db.close()


def _load(commodity: str, nse_exp: str, mcx_exp: str, start: str | None, end: str | None):
    """Per-day option closes for both exchanges of one expiry pairing, plus
    the underlying futures. Returns (opts, futs, days, nse_fut_exp, mcx_fut_exp)
    where opts[(date, strike, side)] = {nse, mcx, nse_vol, mcx_vol}."""
    ds = _dataset(commodity)

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


def _open(side, k, cell, day, fut, reason="signal", parent=None) -> Position:
    cheap, dear = ("NSE", "MCX") if cell["nse"] <= cell["mcx"] else ("MCX", "NSE")
    return Position(side=side, strike=k, entry_date=day, buy_exch=cheap, sell_exch=dear,
                    buy_px=cell[cheap.lower()], sell_px=cell[dear.lower()],
                    diff=round(cell["nse"] - cell["mcx"], 2), entry_future=fut, ref_future=fut,
                    reason=reason, parent=parent)


def _close(pos: Position, day: str, opts, reason: str) -> bool:
    """Square both legs at the day's closes; False if the day has no prices."""
    cell = opts.get((day, pos.strike, pos.side))
    if not cell or cell["nse"] is None or cell["mcx"] is None:
        return False
    pos.exit_date = day
    pos.buy_exit = cell[pos.buy_exch.lower()]
    pos.sell_exit = cell[pos.sell_exch.lower()]
    pos.pnl_points = round((pos.sell_px - pos.sell_exit) + (pos.buy_exit - pos.buy_px), 2)
    pos.exit_reason = reason
    return True


def run_expiry(commodity: str, nse_exp: str, mcx_exp: str, p: dict) -> dict:
    opts, futs, days, nse_fut_exp, mcx_fut_exp = _load(commodity, nse_exp, mcx_exp, p.get("start"), p.get("end"))
    first_exp = min(nse_exp, mcx_exp)
    days = [d for d in days if d <= first_exp]
    gap = abs((datetime.strptime(mcx_exp, "%Y-%m-%d") - datetime.strptime(nse_exp, "%Y-%m-%d")).days)
    threshold = p["threshold_same"] if gap == 0 else p["threshold_gap"]
    sides = ["CE", "PE"] if p["sides"] == "both" else [p["sides"]]
    strikes_all = sorted({k for key in opts if key != "_by_day" for k in [key[1]] if k % p["strike_step"] == 0})
    open_pos: list[Position] = []
    closed: list[Position] = []
    last_day = days[-1] if days else None
    for day in days:
        f = futs.get(day, {})
        fut = f.get("nse") if f.get("nse") is not None else f.get("mcx")
        atm = min(strikes_all, key=lambda k: abs(k - fut)) if (strikes_all and fut) else None
        if atm is None:
            continue
        # 1. adjustments on what is open (roll / add), measured from the reference future
        if p["mode"] in ("roll", "add") and fut is not None:
            for pos in list(open_pos):
                if pos.ref_future is None:
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
                    if _close(pos, day, opts, "adjusted"):
                        open_pos.remove(pos); closed.append(pos)
                else:
                    pos.ref_future = fut
                newp = _open(pos.side, k, cell, day, fut, reason="adjust", parent=f"{pos.strike:g}")
                newp.adjustments = pos.adjustments + 1
                open_pos.append(newp)
        # 2. fresh signals
        if day != first_exp:
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
                open_pos.append(_open(side, k, cell, day, fut))
        # 3. the first expiry: everything squares at its closes
        if day == first_exp or day == last_day:
            for pos in list(open_pos):
                if _close(pos, day, opts, "expiry" if day == first_exp else "data end"):
                    open_pos.remove(pos); closed.append(pos)
    # anything still open (no prices on the last day): close on the last day it had prices
    for pos in list(open_pos):
        for day in reversed(days):
            if _close(pos, day, opts, "last price"):
                break
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
            "pnl_points": t.pnl_points, "pnl_rs": _num(rs, 0),
            "days": (datetime.strptime(t.exit_date, "%Y-%m-%d") - datetime.strptime(t.entry_date, "%Y-%m-%d")).days if t.exit_date else None,
        })
    return {"nse_expiry": nse_exp, "mcx_expiry": mcx_exp, "gap_days": gap, "threshold": threshold,
            "nse_future_expiry": nse_fut_exp, "mcx_future_expiry": mcx_fut_exp,
            "days": len(days), "first_day": days[0] if days else None, "last_day": last_day, "trades": trades}


def run(params: dict) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None}}
    for k in ("threshold_same", "threshold_gap", "otm_min", "otm_max", "strike_step", "move_points", "point_value"):
        p[k] = float(p[k])
    p["multi"] = bool(p["multi"]); p["liquid_only"] = bool(p["liquid_only"])
    commodity = p["commodity"]
    pairs = hist.expiries(commodity)["expiries"]          # newest first
    chosen = [e for e in pairs if e["mcx"] and (not p["expiry"] or e["nse"] == p["expiry"])
              and (not p["start"] or e["nse"] >= p["start"]) and (not p["end"] or e["nse"] <= p["end"])]
    chosen.sort(key=lambda e: e["nse"])
    per_expiry = []
    trades: list[dict] = []
    for e in chosen:
        res = run_expiry(commodity, e["nse"], e["mcx"], p)
        pts = sum(t["pnl_points"] or 0 for t in res["trades"])
        wins = sum(1 for t in res["trades"] if (t["pnl_points"] or 0) > 0)
        per_expiry.append({"nse_expiry": e["nse"], "mcx_expiry": e["mcx"], "gap_days": res["gap_days"], "threshold": res["threshold"],
                           "days": res["days"], "trades": len(res["trades"]), "wins": wins,
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
        "expiries": len(per_expiry),
    }
    return {"params": p, "summary": summary, "by_expiry": per_expiry, "trades": trades, "equity": curve}
