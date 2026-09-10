"""Live PAPER trading of the NSE-vs-MCX option premium arbitrage (client,
10-Sep-2026: "now it's time to paper trade in live market").

The backtester's rules, run on the live quotes of both exchanges instead of
daily closes. Never a real order. Per commodity (crude, natgas) the engine
polls the NSE vs MCX live board every few seconds during market hours and:

  entry     a strike on the ladder, OTM by `otm_min`..`otm_max` from the day's
            ATM (MCX future), quoted two-sided and fresh on both exchanges,
            whose difference is at least the rule. Prices per the client: the
            cheaper exchange's leg is BOUGHT at its bid, the dearer one SOLD at
            its ask, and the difference is ask(dear) - bid(cheap). Only inside
            the entry window (`entry_days` before the first expiry) and before
            the square-off day. One open strike per side unless `multi`.
  add lot   while the strike is still OTM and the same difference has widened
            by `add_step` (crude 20, gas 0.2) since the last lot, one more lot
            at the current prices (a separate trade row, reason "add lot"),
            up to `max_lots` (0 = no cap).
  take      the open profit of a lot reaches `take_profit` points: closed.
  square    `exit_days` before the first expiry: a profitable lot closes, a
            losing one is carried when `loss_roll` allows.
  shift     `roll_days` before a leg's own expiry a losing lot shifts that leg
            to the next expiry at the current prices (NSE first, MCX later).
  adjust    modes roll / add on a `move_points` move of the MCX future.
  p&l       points x point_value per lot; buy leg marked at bid, sell leg at
            ask, all the way through.

State survives restarts (tables nse_mcx_paper_*). Everything the engine does
is written to the event log the page shows.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import NseMcxPaperEvent, NseMcxPaperSetting, NseMcxPaperTrade
from app.services.angel_ws_feed import IST, is_market_open

log = logging.getLogger("nse_mcx_paper")

COMMODITIES = ("crude", "natgas")
POLL_SECONDS = 10
WINDOW = 40                   # strikes each side of the ATM read off the live board

# The client's conditions of 09-Sep-2026 (his backtest screenshots).
DEFAULTS = {
    "crude": {
        "sides": "both", "mode": "roll", "move_points": 500.0,
        "threshold_same": 10.0, "threshold_gap": 70.0, "otm_min": 200.0, "otm_max": 900.0, "strike_step": 500.0,
        "point_value": 100.0, "pick": "max", "multi": False,
        "entry_days": 30, "take_profit": 40.0, "exit_days": 10,
        "loss_roll": True, "roll_days": 1, "roll_legs": "both", "max_rolls": 0,
        "add_step": 20.0, "max_lots": 0,
    },
    "natgas": {
        "sides": "both", "mode": "hold", "move_points": 40.0,
        "threshold_same": 0.25, "threshold_gap": 1.25, "otm_min": 20.0, "otm_max": 60.0, "strike_step": 10.0,
        "point_value": 1250.0, "pick": "max", "multi": False,
        "entry_days": 30, "take_profit": 0.75, "exit_days": 10,
        "loss_roll": False, "roll_days": 1, "roll_legs": "both", "max_rolls": 0,
        "add_step": 0.2, "max_lots": 0,
    },
}
_FLOATS = ("move_points", "threshold_same", "threshold_gap", "otm_min", "otm_max", "strike_step", "point_value",
           "take_profit", "add_step")
_INTS = ("entry_days", "exit_days", "roll_days", "max_rolls", "max_lots")


def clean_params(commodity: str, raw: dict | None) -> dict:
    p = {**DEFAULTS[commodity], **{k: v for k, v in (raw or {}).items() if v is not None and v != "" and k in DEFAULTS[commodity]}}
    for k in _FLOATS:
        p[k] = float(p[k])
    for k in _INTS:
        p[k] = max(0, int(float(p[k])))
    p["multi"] = bool(p["multi"]); p["loss_roll"] = bool(p["loss_roll"])
    p["sides"] = p["sides"] if p["sides"] in ("both", "CE", "PE") else "both"
    p["mode"] = p["mode"] if p["mode"] in ("hold", "roll", "add") else "hold"
    p["pick"] = p["pick"] if p["pick"] in ("max", "near") else "max"
    p["roll_legs"] = p["roll_legs"] if p["roll_legs"] in ("both", "NSE", "MCX") else "both"
    return p


@dataclass
class Leg:
    exch: str
    exp: str
    dir: str                  # buy | sell
    px: float


@dataclass
class Trade:
    id: int | None
    commodity: str
    side: str
    strike: float
    entry_time: str           # IST iso
    entry_date: str
    nse_expiry: str
    mcx_expiry: str
    buy_exch: str
    sell_exch: str
    buy_px: float
    sell_px: float
    diff: float
    entry_future: float | None
    ref_future: float | None
    reason: str = "signal"    # signal | add lot | adjust
    parent: int | None = None
    legs: dict = field(default_factory=dict)     # exch -> Leg (as dict when loaded)
    realised: float = 0.0
    rolls: int = 0
    roll_log: list = field(default_factory=list)
    last_add_diff: float | None = None
    lots_added: int = 0
    sq_done: bool = False
    status: str = "open"
    mark: float | None = None
    mark_time: str | None = None
    mark_prices: dict = field(default_factory=dict)
    daily: list = field(default_factory=list)
    exit_time: str | None = None
    exit_date: str | None = None
    exit_reason: str | None = None
    buy_exit: float | None = None
    sell_exit: float | None = None
    pnl_points: float | None = None
    point_value: float = 100.0

    def first_exp(self) -> str:
        return min(l["exp"] if isinstance(l, dict) else l.exp for l in self.legs.values())

    def leg(self, exch: str) -> Leg:
        l = self.legs[exch]
        return l if isinstance(l, Leg) else Leg(**l)

    def set_leg(self, exch: str, leg: Leg):
        self.legs[exch] = asdict(leg)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["legs"] = {k: (asdict(v) if isinstance(v, Leg) else v) for k, v in self.legs.items()}
        d["pnl_rs"] = round(self.pnl_points * self.point_value, 0) if self.pnl_points is not None else None
        d["mark_rs"] = round(self.mark * self.point_value, 0) if self.mark is not None else None
        return d


_lock = threading.RLock()
_state: dict = {c: {"enabled": False, "params": dict(DEFAULTS[c]), "open": [], "last_check": None,
                    "last_error": None, "book": {}, "checks": 0} for c in COMMODITIES}
_events: list[dict] = []          # newest last, capped
_loaded = False


def _now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def _shift(iso: str, days: int) -> str:
    return (datetime.strptime(iso, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- persistence
def _load():
    global _loaded
    db = SessionLocal()
    try:
        for c in COMMODITIES:
            row = db.query(NseMcxPaperSetting).filter(NseMcxPaperSetting.commodity == c).first()
            if row:
                _state[c]["enabled"] = bool(row.enabled)
                try:
                    _state[c]["params"] = clean_params(c, json.loads(row.params or "{}"))
                except Exception:  # noqa: BLE001
                    _state[c]["params"] = dict(DEFAULTS[c])
            opens = []
            for t in db.query(NseMcxPaperTrade).filter(NseMcxPaperTrade.commodity == c, NseMcxPaperTrade.status == "open").all():
                try:
                    d = json.loads(t.data); d["id"] = t.id
                    d.pop("pnl_rs", None); d.pop("mark_rs", None)
                    opens.append(Trade(**d))
                except Exception as e:  # noqa: BLE001
                    log.warning("paper trade %s unreadable: %s", t.id, e)
            _state[c]["open"] = opens
        for e in db.query(NseMcxPaperEvent).order_by(NseMcxPaperEvent.id.desc()).limit(60).all()[::-1]:
            _events.append({"id": e.id, "time": _iso(e.time), "commodity": e.commodity, "trade_id": e.trade_id, "kind": e.kind, "text": e.text})
        _loaded = True
        log.info("paper: loaded %s", {c: (len(_state[c]["open"]), _state[c]["enabled"]) for c in COMMODITIES})
    finally:
        db.close()


def _save(trade: Trade, db=None):
    own = db is None
    db = db or SessionLocal()
    try:
        d = trade.to_dict(); d.pop("id", None)
        if trade.id is None:
            row = NseMcxPaperTrade(commodity=trade.commodity, status=trade.status, side=trade.side, strike=trade.strike,
                                   entry_time=datetime.fromisoformat(trade.entry_time), data="{}")
            db.add(row); db.flush()
            trade.id = row.id
            d = trade.to_dict(); d.pop("id", None)
        else:
            row = db.get(NseMcxPaperTrade, trade.id)
            if row is None:
                row = NseMcxPaperTrade(id=trade.id, commodity=trade.commodity, side=trade.side, strike=trade.strike,
                                       entry_time=datetime.fromisoformat(trade.entry_time))
                db.add(row)
        row.status = trade.status
        row.exit_time = datetime.fromisoformat(trade.exit_time) if trade.exit_time else None
        row.pnl_points = trade.pnl_points
        row.data = json.dumps(d)
        if own:
            db.commit()
    finally:
        if own:
            db.close()


def _event(commodity: str, kind: str, text: str, trade_id: int | None = None):
    now = _now()
    db = SessionLocal()
    try:
        e = NseMcxPaperEvent(time=now, commodity=commodity, trade_id=trade_id, kind=kind, text=text[:240])
        db.add(e); db.commit()
        _events.append({"id": e.id, "time": _iso(now), "commodity": commodity, "trade_id": trade_id, "kind": kind, "text": text[:240]})
        del _events[:-80]
    finally:
        db.close()
    log.info("paper %s %s: %s", commodity, kind, text)


def _save_setting(commodity: str, username: str | None):
    db = SessionLocal()
    try:
        row = db.query(NseMcxPaperSetting).filter(NseMcxPaperSetting.commodity == commodity).first()
        if row is None:
            row = NseMcxPaperSetting(commodity=commodity); db.add(row)
        row.enabled = _state[commodity]["enabled"]
        row.params = json.dumps(_state[commodity]["params"])
        row.updated_at = _now(); row.updated_by = username
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------- the live book
class Book:
    """The live board of one commodity: quotes keyed by (exchange, expiry,
    strike, side), both months, plus the futures and the freshness flags."""

    def __init__(self, commodity: str):
        from app.routes.nse_mcx import payload
        self.commodity = commodity
        self.quotes: dict = {}
        self.exp: dict = {}          # month -> {"NSE": exp, "MCX": exp}
        self.fresh: dict = {}
        self.fut = None
        self.atm = None
        self.strikes: list = []
        for month in (0, 1):
            try:
                d = payload(commodity, window=WINDOW, month=month)
            except Exception as e:  # noqa: BLE001
                log.debug("paper book %s month %s: %s", commodity, month, e)
                continue
            opts = d.get("options") or {}
            nse_exp, mcx_exp = opts.get("nse_expiry"), opts.get("mcx_expiry")
            if not nse_exp or not mcx_exp:
                continue
            self.exp[month] = {"NSE": nse_exp, "MCX": mcx_exp}
            self.fresh[month] = bool(d.get("fresh"))
            for r in opts.get("rows") or []:
                for side in ("ce", "pe"):
                    cell = r.get(side) or {}
                    self.quotes[("NSE", nse_exp, float(r["strike"]), side.upper())] = cell.get("nse") or {}
                    self.quotes[("MCX", mcx_exp, float(r["strike"]), side.upper())] = cell.get("mcx") or {}
            if month == 0:
                f = d.get("future") or {}
                self.fut = (f.get("mcx") or {}).get("mid") or (f.get("nse") or {}).get("mid")
                self.strikes = sorted({float(r["strike"]) for r in opts.get("rows") or []})
                if self.fut and self.strikes:
                    self.atm = min(self.strikes, key=lambda k: abs(k - self.fut))

    def ok(self) -> bool:
        return 0 in self.exp and self.fresh.get(0, False) and self.atm is not None

    def quote(self, exch: str, exp: str, strike: float, side: str) -> dict:
        return self.quotes.get((exch, exp, float(strike), side)) or {}

    @staticmethod
    def two_sided(q: dict) -> bool:
        return bool(q.get("bid") and q.get("ask")) and not q.get("wide")

    @staticmethod
    def leg_px(q: dict, direction: str) -> float | None:
        """The client's price rule: a bought leg at its bid, a sold leg at its ask."""
        v = q.get("bid") if direction == "buy" else q.get("ask")
        return float(v) if v else None

    def next_exp(self, exch: str) -> str | None:
        return (self.exp.get(1) or {}).get(exch)

    def summary(self) -> dict:
        return {"nse_expiry": (self.exp.get(0) or {}).get("NSE"), "mcx_expiry": (self.exp.get(0) or {}).get("MCX"),
                "next_nse_expiry": self.next_exp("NSE"), "next_mcx_expiry": self.next_exp("MCX"),
                "future": self.fut, "atm": self.atm, "fresh": self.fresh.get(0, False), "strikes": len(self.strikes)}


def _pair(book: Book, strike: float, side: str, nse_exp: str, mcx_exp: str):
    """Both legs of a strike priced per the rule. Returns
    (cheap_exch, dear_exch, buy_px, sell_px, diff) or None when either side is
    not a dealable two-way quote."""
    n = book.quote("NSE", nse_exp, strike, side); m = book.quote("MCX", mcx_exp, strike, side)
    if not (Book.two_sided(n) and Book.two_sided(m)):
        return None
    cheap, dear = ("NSE", "MCX") if n["mid"] <= m["mid"] else ("MCX", "NSE")
    qc, qd = (n, m) if cheap == "NSE" else (m, n)
    buy_px, sell_px = Book.leg_px(qc, "buy"), Book.leg_px(qd, "sell")
    if buy_px is None or sell_px is None:
        return None
    return cheap, dear, buy_px, sell_px, round(sell_px - buy_px, 2)


def _mark(t: Trade, book: Book) -> tuple[float, dict] | None:
    total = t.realised; prices = {}
    for exch in ("NSE", "MCX"):
        leg = t.leg(exch)
        now = Book.leg_px(book.quote(exch, leg.exp, t.strike, t.side), leg.dir)
        if now is None:
            return None
        prices[exch] = now
        total += (now - leg.px) if leg.dir == "buy" else (leg.px - now)
    return round(total, 2), prices


def _threshold(p: dict, nse_exp: str, mcx_exp: str) -> float:
    return p["threshold_same"] if nse_exp == mcx_exp else p["threshold_gap"]


def _candidates(book: Book, p: dict, side: str):
    nse_exp, mcx_exp = book.exp[0]["NSE"], book.exp[0]["MCX"]
    out = []
    for k in book.strikes:
        if k % p["strike_step"] != 0:
            continue
        dist = (k - book.atm) if side == "CE" else (book.atm - k)
        if dist < p["otm_min"] or dist > p["otm_max"]:
            continue
        pr = _pair(book, k, side, nse_exp, mcx_exp)
        if pr:
            out.append((k, pr))
    return out


def _best(cands, threshold: float, atm: float, pick: str):
    ok = [(k, pr) for k, pr in cands if pr[4] >= threshold]
    if not ok:
        return None
    return min(ok, key=lambda x: abs(x[0] - atm)) if pick == "near" else max(ok, key=lambda x: x[1][4])


def _open(commodity: str, p: dict, book: Book, side: str, k: float, pr, reason="signal", parent=None) -> Trade:
    cheap, dear, buy_px, sell_px, diff = pr
    now = _now()
    nse_exp, mcx_exp = book.exp[0]["NSE"], book.exp[0]["MCX"]
    t = Trade(id=None, commodity=commodity, side=side, strike=k, entry_time=_iso(now), entry_date=now.strftime("%Y-%m-%d"),
              nse_expiry=nse_exp, mcx_expiry=mcx_exp, buy_exch=cheap, sell_exch=dear, buy_px=buy_px, sell_px=sell_px,
              diff=diff, entry_future=book.fut, ref_future=book.fut, reason=reason, parent=parent,
              last_add_diff=diff, point_value=p["point_value"])
    t.set_leg("NSE", Leg("NSE", nse_exp, "buy" if cheap == "NSE" else "sell", buy_px if cheap == "NSE" else sell_px))
    t.set_leg("MCX", Leg("MCX", mcx_exp, "buy" if cheap == "MCX" else "sell", buy_px if cheap == "MCX" else sell_px))
    t.mark, t.mark_time, t.mark_prices = 0.0, _iso(now), {"NSE": t.leg("NSE").px, "MCX": t.leg("MCX").px}
    _record(t, now)
    _save(t)
    _event(commodity, reason, f"{reason}: {side} {k:g} buy {cheap} @ {buy_px} sell {dear} @ {sell_px} diff {diff}"
           + (f" (lot on #{parent})" if parent else ""), t.id)
    return t


def _close(t: Trade, book: Book, reason: str, prices: dict | None = None) -> bool:
    m = _mark(t, book)
    if m is None and prices is None:
        if t.mark is None or not t.mark_prices:
            return False
        pnl, prices = t.mark, t.mark_prices            # last known mark (a leg with no quote any more)
    elif m is not None:
        pnl, prices = m
    else:
        pnl = None
    now = _now()
    t.status, t.exit_time, t.exit_date, t.exit_reason = "closed", _iso(now), now.strftime("%Y-%m-%d"), reason
    t.buy_exit, t.sell_exit = prices.get(t.buy_exch), prices.get(t.sell_exch)
    t.pnl_points = pnl if pnl is not None else t.mark
    t.mark, t.mark_time, t.mark_prices = t.pnl_points, _iso(now), prices
    _record(t, now)
    _save(t)
    _event(t.commodity, "exit", f"{reason}: {t.side} {t.strike:g} closed at {t.buy_exch} {t.buy_exit} / {t.sell_exch} {t.sell_exit}, "
           f"{t.pnl_points:+.2f} pts", t.id)
    return True


def _record(t: Trade, now: datetime):
    d = now.strftime("%Y-%m-%d")
    row = {"date": d, "nse": t.mark_prices.get("NSE"), "mcx": t.mark_prices.get("MCX"), "pnl": t.mark, "time": now.strftime("%H:%M")}
    if t.daily and t.daily[-1]["date"] == d:
        t.daily[-1] = row
    else:
        t.daily.append(row)


def _roll_leg(t: Trade, exch: str, book: Book) -> bool:
    leg = t.leg(exch)
    nxt = book.next_exp(exch)
    if not nxt or nxt <= leg.exp:
        return False
    q_now = book.quote(exch, leg.exp, t.strike, t.side); q_new = book.quote(exch, nxt, t.strike, t.side)
    now_px = Book.leg_px(q_now, leg.dir)
    if now_px is None or not Book.two_sided(q_new):
        return False
    new_px = Book.leg_px(q_new, leg.dir)
    t.realised = round(t.realised + ((now_px - leg.px) if leg.dir == "buy" else (leg.px - now_px)), 2)
    t.set_leg(exch, Leg(exch, nxt, leg.dir, new_px))
    t.rolls += 1
    t.roll_log.append({"date": _now().strftime("%Y-%m-%d"), "time": _now().strftime("%H:%M"), "exch": exch,
                       "from": leg.exp, "to": nxt, "out": now_px, "in": new_px})
    _event(t.commodity, "shift", f"{t.side} {t.strike:g}: {exch} leg {leg.exp} closed @ {now_px}, {nxt} opened @ {new_px}", t.id)
    return True


def _manage(t: Trade, book: Book, p: dict, today: str) -> bool:
    """Take profit, square-off day, expiry shifts, forced closes for one open
    lot. True when it closed."""
    can_roll = p["loss_roll"] and t.rolls < p["max_rolls"]
    # a leg past its expiry: settle on the latest mark
    if any(t.leg(e).exp < today for e in ("NSE", "MCX")):
        return _close(t, book, "expiry")
    m = _mark(t, book)
    if m is None:
        return False
    pnl, prices = m
    t.mark, t.mark_time, t.mark_prices = pnl, _iso(_now()), prices
    _record(t, _now())
    if p["take_profit"] > 0 and pnl >= p["take_profit"]:
        return _close(t, book, "take profit")
    first_exp = t.first_exp()
    sq_target = _shift(first_exp, p["exit_days"])
    if not t.sq_done and today >= sq_target:
        if pnl >= 0 or not can_roll:
            return _close(t, book, "expiry" if (today >= first_exp or not p["exit_days"]) else "square off")
        t.sq_done = True
        _event(t.commodity, "carry", f"{t.side} {t.strike:g} in loss ({pnl:+.2f}) on the square-off day, carried", t.id)
    if not p["loss_roll"]:
        return False
    for exch in ("NSE", "MCX"):
        leg = t.leg(exch)
        if today < _shift(leg.exp, p["roll_days"]):
            continue
        m = _mark(t, book)
        if m is None:
            continue
        if m[0] >= 0:
            return _close(t, book, "expiry" if today >= leg.exp else "square off")
        allowed = can_roll and p["roll_legs"] in ("both", exch)
        if not allowed or not _roll_leg(t, exch, book):
            if today >= leg.exp:
                return _close(t, book, "expiry")
            continue
        due = _shift(t.first_exp(), p["exit_days"])
        if due > today:
            t.sq_done = False
        _save(t)
    return False


def _tick(commodity: str):
    st = _state[commodity]
    p = st["params"]
    book = Book(commodity)
    st["book"] = book.summary()
    st["checks"] += 1
    st["last_check"] = _iso(_now())
    if not book.ok():
        st["last_error"] = "live board not fresh"
        return
    st["last_error"] = None
    today = _now().strftime("%Y-%m-%d")
    nse_exp, mcx_exp = book.exp[0]["NSE"], book.exp[0]["MCX"]
    first_exp = min(nse_exp, mcx_exp)
    threshold = _threshold(p, nse_exp, mcx_exp)
    sq_day = _shift(first_exp, p["exit_days"])
    window_from = _shift(first_exp, p["entry_days"]) if p["entry_days"] else None
    open_t: list[Trade] = st["open"]
    # 1. manage what is open
    for t in list(open_t):
        if _manage(t, book, p, today):
            open_t.remove(t)
    # 2. add lots: the same difference widened by add_step while the strike is still OTM
    if p["add_step"] > 0:
        for t in list(open_t):
            if t.reason == "add lot" or t.rolls or t.status != "open":
                continue
            otm = (t.strike > book.atm) if t.side == "CE" else (t.strike < book.atm)
            if not otm:
                continue
            n = book.quote("NSE", nse_exp, t.strike, t.side); m = book.quote("MCX", mcx_exp, t.strike, t.side)
            if not (Book.two_sided(n) and Book.two_sided(m)):
                continue
            qb, qs = (n, m) if t.buy_exch == "NSE" else (m, n)
            buy_px, sell_px = Book.leg_px(qb, "buy"), Book.leg_px(qs, "sell")
            diff_now = round(sell_px - buy_px, 2)
            lots = 1 + sum(1 for x in open_t if x.parent == t.id and x.status == "open")
            if p["max_lots"] and lots >= p["max_lots"]:
                continue
            if diff_now >= (t.last_add_diff if t.last_add_diff is not None else t.diff) + p["add_step"]:
                pr = (t.buy_exch, t.sell_exch, buy_px, sell_px, diff_now)
                lot = _open(commodity, p, book, t.side, t.strike, pr, reason="add lot", parent=t.id)
                t.last_add_diff = diff_now; t.lots_added += 1
                _save(t)
                open_t.append(lot)
    # 3. move adjustments (roll / add) on the entry lots
    if p["mode"] in ("roll", "add") and book.fut:
        for t in list(open_t):
            if t.reason != "signal" or t.rolls or t.ref_future is None:
                continue
            move = book.fut - t.ref_future
            hurt = (t.side == "CE" and move <= -p["move_points"]) or (t.side == "PE" and move >= p["move_points"])
            if not hurt:
                continue
            cand = _best(_candidates(book, p, t.side), threshold, book.atm, p["pick"])
            if cand is None:
                continue
            k, pr = cand
            if k == t.strike:
                t.ref_future = book.fut; _save(t); continue
            if p["mode"] == "roll":
                if _close(t, book, "adjusted"):
                    open_t.remove(t)
            else:
                t.ref_future = book.fut; _save(t)
            newp = _open(commodity, p, book, t.side, k, pr, reason="adjust", parent=t.id)
            open_t.append(newp)
    # 4. fresh signals inside the entry window
    if today < sq_day and (window_from is None or today >= window_from):
        sides = ["CE", "PE"] if p["sides"] == "both" else [p["sides"]]
        for side in sides:
            have = [x for x in open_t if x.side == side]
            if have and not p["multi"]:
                continue
            cand = _best(_candidates(book, p, side), threshold, book.atm, p["pick"])
            if cand is None:
                continue
            k, pr = cand
            if any(x.strike == k for x in have):
                continue
            open_t.append(_open(commodity, p, book, side, k, pr))


def preview(commodity: str, book: Book | None = None) -> dict:
    """What the engine sees right now: the day's ATM, and per side the widest
    qualifying candidate against the rule - so a quiet screen is explainable."""
    p = _state[commodity]["params"]
    book = book or Book(commodity)
    out = {"book": book.summary(), "sides": {}}
    if not book.ok():
        return out
    nse_exp, mcx_exp = book.exp[0]["NSE"], book.exp[0]["MCX"]
    thr = _threshold(p, nse_exp, mcx_exp)
    first_exp = min(nse_exp, mcx_exp)
    today = _now().strftime("%Y-%m-%d")
    out["threshold"] = thr
    out["first_expiry"] = first_exp
    out["square_off_day"] = _shift(first_exp, p["exit_days"])
    out["window_from"] = _shift(first_exp, p["entry_days"]) if p["entry_days"] else None
    out["in_window"] = today < out["square_off_day"] and (out["window_from"] is None or today >= out["window_from"])
    for side in ("CE", "PE"):
        cands = _candidates(book, p, side)
        best = max(cands, key=lambda x: x[1][4]) if cands else None
        out["sides"][side] = {"candidates": len(cands),
                              "best": {"strike": best[0], "buy": best[1][0], "buy_px": best[1][2], "sell": best[1][1], "sell_px": best[1][3], "diff": best[1][4]} if best else None,
                              "fires": bool(best and best[1][4] >= thr)}
    return out


def _loop():
    time.sleep(20)                                  # let the feeds come up
    try:
        _load()
    except Exception as e:  # noqa: BLE001
        log.exception("paper: load failed: %s", e)
    while True:
        try:
            if is_market_open():
                for c in COMMODITIES:
                    if _state[c]["enabled"]:
                        with _lock:
                            _tick(c)
                    else:
                        _state[c]["book"] = Book(c).summary()
        except Exception as e:  # noqa: BLE001
            log.exception("paper tick: %s", e)
            for c in COMMODITIES:
                _state[c]["last_error"] = str(e)[:200]
        time.sleep(POLL_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="nse-mcx-paper")
    t.start()
    return t


# ---------------------------------------------------------------- API
def state(commodity: str) -> dict:
    with _lock:
        st = _state[commodity]
        opens = [t.to_dict() for t in st["open"]]
    db = SessionLocal()
    try:
        rows = db.query(NseMcxPaperTrade).filter(NseMcxPaperTrade.commodity == commodity, NseMcxPaperTrade.status == "closed").order_by(
            NseMcxPaperTrade.exit_time.desc()).limit(300).all()
        closed = []
        for r in rows:
            d = json.loads(r.data); d["id"] = r.id; closed.append(d)
    finally:
        db.close()
    pnl_closed = sum(t["pnl_points"] or 0 for t in closed)
    pnl_open = sum(t["mark"] or 0 for t in opens)
    pv = st["params"]["point_value"]
    wins = sum(1 for t in closed if (t["pnl_points"] or 0) > 0)
    return {
        "commodity": commodity, "enabled": st["enabled"], "params": st["params"], "market_open": is_market_open(),
        "last_check": st["last_check"], "last_error": st["last_error"], "checks": st["checks"], "book": st["book"],
        "open": opens, "closed": closed,
        "summary": {"open_lots": len(opens), "closed": len(closed), "wins": wins,
                    "win_rate": round(wins / len(closed) * 100, 1) if closed else None,
                    "open_points": round(pnl_open, 2), "open_rs": round(pnl_open * pv, 0),
                    "closed_points": round(pnl_closed, 2), "closed_rs": round(pnl_closed * pv, 0),
                    "total_points": round(pnl_open + pnl_closed, 2), "total_rs": round((pnl_open + pnl_closed) * pv, 0)},
        "events": [e for e in _events if e["commodity"] == commodity][-40:],
        "poll_seconds": POLL_SECONDS,
        "preview": preview(commodity) if is_market_open() else None,
    }


def set_params(commodity: str, raw: dict, username: str | None) -> dict:
    with _lock:
        _state[commodity]["params"] = clean_params(commodity, raw)
        _save_setting(commodity, username)
    _event(commodity, "settings", f"rules changed by {username or 'admin'}")
    return _state[commodity]["params"]


def set_enabled(commodity: str, on: bool, username: str | None) -> dict:
    with _lock:
        _state[commodity]["enabled"] = bool(on)
        _save_setting(commodity, username)
    _event(commodity, "start" if on else "stop", f"paper trading {'started' if on else 'stopped'} by {username or 'admin'}")
    return {"enabled": bool(on)}


def close_trade(commodity: str, trade_id: int, username: str | None) -> dict:
    with _lock:
        st = _state[commodity]
        t = next((x for x in st["open"] if x.id == trade_id), None)
        if t is None:
            raise ValueError("not an open paper trade")
        book = Book(commodity)
        if not _close(t, book, "manual"):
            raise ValueError("no price to close at right now")
        st["open"].remove(t)
    return t.to_dict()


def close_all(commodity: str, username: str | None) -> dict:
    n = 0
    with _lock:
        st = _state[commodity]
        book = Book(commodity)
        for t in list(st["open"]):
            if _close(t, book, "manual"):
                st["open"].remove(t); n += 1
    return {"closed": n}


def clear(commodity: str, username: str | None) -> dict:
    """Wipe the commodity's paper history (a fresh start for the trial)."""
    with _lock:
        _state[commodity]["open"] = []
        db = SessionLocal()
        try:
            n = db.query(NseMcxPaperTrade).filter(NseMcxPaperTrade.commodity == commodity).delete()
            db.query(NseMcxPaperEvent).filter(NseMcxPaperEvent.commodity == commodity).delete()
            db.commit()
        finally:
            db.close()
        _events[:] = [e for e in _events if e["commodity"] != commodity]
    _event(commodity, "clear", f"history cleared by {username or 'admin'} ({n} trades)")
    return {"deleted": n}
