"""Backtester for the MCX-vs-NYMEX option volatility trade (client's note,
23-Sep-2026), run on the half-hourly boards crude_iv_history stores.

  entry   on any MCX strike of the 100-point ladder (CE or PE), when the
          implied volatility of the MCX option and of the NYMEX option at the
          matching strike differ by `entry_diff` points or more: SELL the
          option whose IV is higher, BUY the other, one lot each (1:1, the
          client's choice - barrel sizes are ignored). The NYMEX strike is the
          one nearest MCX strike / USD-INR at that moment; both the strike and
          the USD-INR rate stay FIXED for the life of the trade.
  exit    the first later board where the same two options' IV gap has
          narrowed to `exit_diff` points or less; else `exit_days` calendar
          days before the first of the two option expiries; else the end of
          the data (marked at the last board). An optional stop in points.
  prices  per the client's rule a bought leg trades at its bid and a sold leg
          at its ask ("client"); "mid" and "market" (buy at ask, sell at bid)
          are there for a fair and a conservative reading. The NYMEX leg is
          dollars per barrel, restated in rupees at the trade's fixed rate.
  p&l     rupees per barrel (points) x `lot_size` barrels.

Everything is a parameter; the client tests scenarios himself. The boards
start on 19-Aug-2026 (no exchange sells NYMEX option history), so the test
covers whatever the capture job has stored - it grows every half hour.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import CrudeIvSnapshot

log = logging.getLogger("crude_iv_backtest")

DEFAULTS = {
    "commodity": "crude",
    "month": 0,                     # 0 = front expiry, 1 = the one after
    "start": None, "end": None,     # YYYY-MM-DD, blank = all stored boards
    "entry_diff": 5.0,              # |MCX IV - NYMEX IV| points to enter
    "exit_diff": 3.0,               # gap at or below which the trade closes
    "direction": "both",            # both | mcx_high (sell MCX, buy NYMEX) | us_high
    "sides": "both",                # both | CE | PE
    "otm_min": 0.0, "otm_max": 0.0, # MCX points from ATM (0 = no limit on that side)
    "strike_step": 100.0,           # MCX ladder
    "exit_days": 5,                 # square off this many calendar days before the first expiry
    "stop_loss": 0.0,               # points per barrel, 0 = off
    "price_rule": "mid",            # mid | client (buy at bid, sell at ask) | market (buy at ask, sell at bid)
    "lot_size": 100.0,              # barrels per lot, both legs (1:1)
    "max_positions": 0,             # open trades at once, 0 = no cap
    "exclude_wide": True,           # skip legs the board flagged as too wide to deal
}
_US_STEP = 0.5


@dataclass
class Trade:
    entry_ts: str
    side: str
    mcx_strike: float
    us_strike: float
    usdinr: float
    sell_exch: str                  # MCX | NYMEX (the higher-IV option)
    buy_exch: str
    sell_px: float                  # rupees per barrel
    buy_px: float
    sell_px_native: float           # as quoted (dollars for NYMEX)
    buy_px_native: float
    mcx_iv: float
    us_iv: float
    diff: float                     # MCX IV - NYMEX IV at entry
    atm_offset: float
    mcx_expiry: str
    us_expiry: str
    path: list = field(default_factory=list)    # per board: ts, mcx_iv, us_iv, diff, pnl
    exit_ts: str | None = None
    exit_reason: str | None = None
    sell_exit: float | None = None
    buy_exit: float | None = None
    exit_diff: float | None = None
    pnl_points: float | None = None
    mark: float | None = None
    last_mark_ts: str | None = None     # the last board that priced both legs


_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_SECONDS = 300


def _iso_expiry(v) -> str | None:
    if not v:
        return None
    s = str(v)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10]


def _boards(commodity: str, month: int) -> list[dict]:
    """Every stored board of the commodity/month, oldest first, unpacked to
    {ts, date, usdinr, mcx_expiry, us_expiry, atm, mcx: {strike: {CE: leg, PE: leg}}, us: {...}}
    where leg = (bid, ask, iv, wide). Cached for five minutes."""
    from sqlalchemy import func
    key = (commodity, month)
    db = SessionLocal()
    try:
        newest = db.query(func.max(CrudeIvSnapshot.id)).filter(
            CrudeIvSnapshot.commodity == commodity, CrudeIvSnapshot.month == month).scalar()
        with _cache_lock:
            hit = _cache.get(key)
            if hit and hit["newest"] == newest and time.time() - hit["at"] < _CACHE_SECONDS:
                return hit["boards"]
        rows = db.query(CrudeIvSnapshot.snap_date, CrudeIvSnapshot.slot, CrudeIvSnapshot.usdinr,
                        CrudeIvSnapshot.payload_json).filter(
            CrudeIvSnapshot.commodity == commodity, CrudeIvSnapshot.month == month).order_by(
            CrudeIvSnapshot.snap_date, CrudeIvSnapshot.slot).all()
    finally:
        db.close()
    boards = []
    for snap_date, slot, usdinr, payload in rows:
        try:
            p = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        rate = p.get("usdinr") or usdinr
        if not rate:
            continue
        m_cols, u_cols = p.get("cols_mcx") or [], p.get("cols_us") or []

        def legs(chain_rows, cols):
            ix = {c: i for i, c in enumerate(cols)}
            out, atm = {}, None
            for r in chain_rows:
                k = r[ix["strike"]]
                if k is None:
                    continue
                if r[ix["atm"]]:
                    atm = float(k)
                out[float(k)] = {
                    "CE": (r[ix["ce_bid"]], r[ix["ce_ask"]], r[ix["ce_iv"]], bool(r[ix["ce_wide"]])),
                    "PE": (r[ix["pe_bid"]], r[ix["pe_ask"]], r[ix["pe_iv"]], bool(r[ix["pe_wide"]])),
                }
            return out, atm
        mcx, m_atm = legs((p.get("mcx") or {}).get("rows") or [], m_cols)
        us, _u_atm = legs((p.get("us") or {}).get("rows") or [], u_cols)
        if not mcx or not us:
            continue
        m_exp, u_exp = _iso_expiry((p.get("mcx") or {}).get("expiry")), _iso_expiry((p.get("us") or {}).get("expiry"))
        # Both option months must be the same calendar month. On 03-Sep-2026 the
        # US chain wore October's expiry for 18 boards while MCX still showed
        # September's - that board compares two different contracts, so it is
        # dropped rather than read as a roll or a signal.
        if m_exp and u_exp and m_exp[:7] != u_exp[:7]:
            continue
        boards.append({
            "ts": f"{snap_date}T{slot}", "date": snap_date, "slot": slot, "usdinr": float(rate),
            "mcx_expiry": m_exp,
            "us_expiry": u_exp,
            "atm": m_atm, "mcx_future": (p.get("mcx") or {}).get("forward") or (p.get("mcx") or {}).get("future"),
            "us_future": (p.get("us") or {}).get("future"),
            "mcx": mcx, "us": us,
        })
    with _cache_lock:
        _cache[key] = {"newest": newest, "at": time.time(), "boards": boards}
    return boards


def _match_us_strike(mcx_strike: float, usdinr: float, us_chain: dict) -> float | None:
    """The NYMEX strike nearest to the MCX strike restated in dollars - only if
    one is listed within half a rung; a strike beyond the stored chain's edge
    is not a match."""
    if not us_chain:
        return None
    want = mcx_strike / usdinr
    k = min(us_chain, key=lambda key: (abs(key - want), key))
    return k if abs(k - want) <= _US_STEP / 2 + 1e-9 else None


def _dealable(leg, exclude_wide: bool) -> bool:
    """Two-way quote with an implied volatility: what an ENTRY needs."""
    bid, ask, iv, wide = leg
    return bool(bid and ask and iv and bid > 0 and ask > 0 and bid <= ask and not (exclude_wide and wide))


def _priced(leg) -> bool:
    """Two-way quote, IV or not: enough to mark or close a leg."""
    bid, ask, _iv, _wide = leg
    return bool(bid and ask and bid > 0 and ask > 0 and bid <= ask)


def _px(leg, action: str, rule: str) -> float:
    """Price for one leg as quoted: action = buy | sell."""
    bid, ask, _iv, _w = leg
    if rule == "mid":
        return (bid + ask) / 2
    if rule == "market":
        return ask if action == "buy" else bid
    return bid if action == "buy" else ask          # client: buy at bid, sell at ask


def _legs(board: dict, t: Trade):
    m = board["mcx"].get(t.mcx_strike, {}).get(t.side)
    u = board["us"].get(t.us_strike, {}).get(t.side)
    return m, u


def _mark(board: dict, t: Trade, p: dict, exit_rule: bool = False):
    """(pnl_points, sell_exit_rupees, buy_exit_rupees, mcx_iv, us_iv) at this board, or None."""
    m, u = _legs(board, t)
    if not m or not u or not _priced(m) or not _priced(u):
        return None
    rule = p["price_rule"]
    # closing: the sold leg is bought back, the bought leg is sold
    sell_leg, buy_leg = (m, u) if t.sell_exch == "MCX" else (u, m)
    sell_exit = _px(sell_leg, "buy", rule) * (1 if t.sell_exch == "MCX" else t.usdinr)
    buy_exit = _px(buy_leg, "sell", rule) * (1 if t.buy_exch == "MCX" else t.usdinr)
    pnl = (t.sell_px - sell_exit) + (buy_exit - t.buy_px)
    return round(pnl, 2), round(sell_exit, 2), round(buy_exit, 2), m[2], u[2]


def _close(t: Trade, board: dict, p: dict, reason: str) -> bool:
    mk = _mark(board, t, p)
    if mk is None:
        return False
    pnl, sell_exit, buy_exit, m_iv, u_iv = mk
    t.exit_ts, t.exit_reason, t.sell_exit, t.buy_exit = board["ts"], reason, sell_exit, buy_exit
    t.exit_diff = round(m_iv - u_iv, 2) if (m_iv and u_iv) else None
    t.pnl_points, t.mark = pnl, pnl
    t.path.append({"ts": board["ts"], "mcx_iv": m_iv, "us_iv": u_iv, "diff": t.exit_diff, "pnl": pnl, "note": reason})
    return True


def _clean(params: dict | None) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None and v != "" and k in DEFAULTS}}
    for k in ("entry_diff", "exit_diff", "otm_min", "otm_max", "strike_step", "stop_loss", "lot_size"):
        p[k] = float(p[k])
    for k in ("month", "exit_days", "max_positions"):
        p[k] = max(0, int(float(p[k])))
    p["month"] = 1 if p["month"] else 0
    p["commodity"] = p["commodity"] if p["commodity"] in ("crude", "natgas") else "crude"
    p["direction"] = p["direction"] if p["direction"] in ("both", "mcx_high", "us_high") else "both"
    p["sides"] = p["sides"] if p["sides"] in ("both", "CE", "PE") else "both"
    p["price_rule"] = p["price_rule"] if p["price_rule"] in ("client", "mid", "market") else "mid"
    p["exclude_wide"] = bool(p["exclude_wide"])
    return p


def _shift(iso: str, days: int) -> str:
    return (datetime.strptime(iso, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def run(params: dict | None) -> dict:
    p = _clean(params)
    boards = _boards(p["commodity"], p["month"])
    if p["start"]:
        boards = [b for b in boards if b["date"] >= p["start"]]
    if p["end"]:
        boards = [b for b in boards if b["date"] <= p["end"]]
    sides = ["CE", "PE"] if p["sides"] == "both" else [p["sides"]]
    open_t: list[Trade] = []
    closed: list[Trade] = []
    for b in boards:
        first_exp = min(x for x in (b["mcx_expiry"], b["us_expiry"]) if x) if (b["mcx_expiry"] or b["us_expiry"]) else None
        sq_date = _shift(first_exp, p["exit_days"]) if first_exp else None
        # 1. what is open: mark, exit on the gap, the stop, the square-off day, a rolled board
        for t in list(open_t):
            rolled = t.mcx_expiry != b["mcx_expiry"]         # the board moved to the next contract month
            if rolled:
                # the board moved to the next contract: settle at the last mark we have
                t.exit_ts, t.exit_reason = b["ts"], "contract rolled"
                t.pnl_points = t.mark
                t.path.append({"ts": b["ts"], "mcx_iv": None, "us_iv": None, "diff": None, "pnl": t.mark, "note": f"contract rolled, last mark ({t.last_mark_ts})"})
                open_t.remove(t); closed.append(t)
                continue
            mk = _mark(b, t, p)
            if mk is None:
                # no two-way price on a leg this board; the square-off day still ends the trade at its last mark
                if sq_date and b["date"] >= sq_date:
                    t.exit_ts, t.exit_reason, t.pnl_points = b["ts"], "square off", t.mark
                    t.path.append({"ts": b["ts"], "mcx_iv": None, "us_iv": None, "diff": None, "pnl": t.mark, "note": f"square off at the last mark ({t.last_mark_ts}), no quote on this board"})
                    open_t.remove(t); closed.append(t)
                continue
            pnl, _se, _be, m_iv, u_iv = mk
            gap = round(m_iv - u_iv, 2) if (m_iv and u_iv) else None
            t.mark, t.last_mark_ts = pnl, b["ts"]
            t.path.append({"ts": b["ts"], "mcx_iv": m_iv, "us_iv": u_iv, "diff": gap, "pnl": pnl, "note": None})
            reason = None
            if gap is not None and abs(gap) <= p["exit_diff"]:
                reason = "gap closed"
            elif p["stop_loss"] > 0 and pnl <= -p["stop_loss"]:
                reason = "stop loss"
            elif sq_date and b["date"] >= sq_date:
                reason = "square off"
            if reason:
                t.path.pop()
                if _close(t, b, p, reason):
                    open_t.remove(t); closed.append(t)
        # 2. new entries (not on or after the square-off day)
        if sq_date and b["date"] >= sq_date:
            continue
        if not b["atm"]:
            continue
        for k in sorted(b["mcx"]):
            if k % p["strike_step"] != 0:
                continue
            dist = abs(k - b["atm"])
            if (p["otm_min"] and dist < p["otm_min"]) or (p["otm_max"] and dist > p["otm_max"]):
                continue
            us_k = _match_us_strike(k, b["usdinr"], b["us"])
            if us_k is None:
                continue
            for side in sides:
                if p["max_positions"] and len(open_t) >= p["max_positions"]:
                    break
                if any(x.mcx_strike == k and x.side == side for x in open_t):
                    continue
                m, u = b["mcx"][k].get(side), b["us"][us_k].get(side)
                if not m or not u or not _dealable(m, p["exclude_wide"]) or not _dealable(u, p["exclude_wide"]):
                    continue
                gap = round(m[2] - u[2], 2)
                if abs(gap) < p["entry_diff"]:
                    continue
                if p["direction"] == "mcx_high" and gap < 0:
                    continue
                if p["direction"] == "us_high" and gap > 0:
                    continue
                sell_exch = "MCX" if gap > 0 else "NYMEX"
                buy_exch = "NYMEX" if gap > 0 else "MCX"
                sell_leg, buy_leg = (m, u) if sell_exch == "MCX" else (u, m)
                sell_native, buy_native = _px(sell_leg, "sell", p["price_rule"]), _px(buy_leg, "buy", p["price_rule"])
                sell_px = sell_native * (1 if sell_exch == "MCX" else b["usdinr"])
                buy_px = buy_native * (1 if buy_exch == "MCX" else b["usdinr"])
                t = Trade(entry_ts=b["ts"], side=side, mcx_strike=k, us_strike=us_k, usdinr=b["usdinr"],
                          sell_exch=sell_exch, buy_exch=buy_exch, sell_px=round(sell_px, 2), buy_px=round(buy_px, 2),
                          sell_px_native=round(sell_native, 2), buy_px_native=round(buy_native, 2),
                          mcx_iv=m[2], us_iv=u[2], diff=gap, atm_offset=k - b["atm"],
                          mcx_expiry=b["mcx_expiry"], us_expiry=b["us_expiry"], mark=0.0, last_mark_ts=b["ts"])
                t.path.append({"ts": b["ts"], "mcx_iv": m[2], "us_iv": u[2], "diff": gap, "pnl": 0.0, "note": "entry"})
                open_t.append(t)
    for t in open_t:                                    # still open at the end of the data
        t.exit_ts, t.exit_reason, t.pnl_points = boards[-1]["ts"] if boards else None, "data end", t.mark
        closed.append(t)
    trades = []
    for t in sorted(closed, key=lambda x: (x.entry_ts, x.side, x.mcx_strike)):
        d = asdict(t)
        d["pnl_rs"] = round(t.pnl_points * p["lot_size"], 0) if t.pnl_points is not None else None
        d["hours"] = None
        if t.exit_ts and t.entry_ts:
            try:
                d["hours"] = round((datetime.strptime(t.exit_ts, "%Y-%m-%dT%H:%M") - datetime.strptime(t.entry_ts, "%Y-%m-%dT%H:%M")).total_seconds() / 3600, 1)
            except ValueError:
                pass
        trades.append(d)
    pnl = [t["pnl_points"] or 0 for t in trades]
    wins = [x for x in pnl if x > 0]; losses = [x for x in pnl if x < 0]
    cum = peak = dd = 0.0; curve = []
    for t in sorted(trades, key=lambda t: (t["exit_ts"] or "", t["entry_ts"])):
        cum += t["pnl_points"] or 0
        peak = max(peak, cum); dd = min(dd, cum - peak)
        curve.append({"date": t["exit_ts"], "cum_points": round(cum, 2), "cum_rs": round(cum * p["lot_size"], 0)})
    from collections import Counter
    reasons = Counter(t["exit_reason"] for t in trades)
    return {
        "params": p,
        "coverage": {"boards": len(boards), "first": boards[0]["ts"] if boards else None, "last": boards[-1]["ts"] if boards else None,
                     "days": len({b["date"] for b in boards})},
        "summary": {
            "trades": len(trades), "wins": len(wins), "losses": len(losses), "flat": len(pnl) - len(wins) - len(losses),
            "win_rate": round(len(wins) / len(pnl) * 100, 1) if pnl else None,
            "pnl_points": round(sum(pnl), 2), "pnl_rs": round(sum(pnl) * p["lot_size"], 0),
            "avg_points": round(sum(pnl) / len(pnl), 2) if pnl else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "best": round(max(pnl), 2) if pnl else None, "worst": round(min(pnl), 2) if pnl else None,
            "max_drawdown_points": round(dd, 2), "max_drawdown_rs": round(dd * p["lot_size"], 0),
            "avg_hours": round(sum(t["hours"] or 0 for t in trades) / len(trades), 1) if trades else None,
            "exits": dict(reasons),
        },
        "trades": trades, "equity": curve,
    }
