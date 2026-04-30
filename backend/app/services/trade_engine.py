"""Trigger detection + paper trade execution.

PnL & exit logic uses the COVER-SIDE spread (the side at which you'd actually
close the trade), per client's specification:

  Decrease trade  → opens at Decrease spread (sell big bid + buy small ask)
                  → closes at Increase spread (buy big ask + sell small bid)
                  → PnL = entry_decrease − current_increase

  Increase trade  → opens at Increase spread (buy big ask + sell small bid)
                  → closes at Decrease spread (sell big bid + buy small ask)
                  → PnL = current_decrease − entry_increase

Decrease and Increase sides run independently per pair — both can have a
simultaneous open position.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import DEFAULT_MAX_WEIGHT_GRAMS, GRAMS_PER_LOT, PAIRS, cycle_grams
from app.models import PairRule, Position, TradeHistory
from app.services.spread_engine import compute_pair


def _pair_def(name: str) -> dict | None:
    return next((p for p in PAIRS if p["name"] == name), None)


def open_position_for_side(db: Session, pair_name: str, mode: str) -> Position | None:
    return (
        db.query(Position)
        .filter(
            Position.pair_name == pair_name,
            Position.mode == mode,
            Position.status == "open",
        )
        .first()
    )


def open_positions_for_pair(db: Session, pair_name: str) -> list[Position]:
    return (
        db.query(Position)
        .filter(Position.pair_name == pair_name, Position.status == "open")
        .all()
    )


def open_weight_grams(db: Session, pair_name: str, big_instrument: str) -> int:
    """Sum of grams across all open positions for this pair."""
    g = GRAMS_PER_LOT.get(big_instrument, 0)
    rows = (
        db.query(Position)
        .filter(Position.pair_name == pair_name, Position.status == "open")
        .all()
    )
    return sum(r.big_lots * g for r in rows)


def effective_max_weight(rule: PairRule | None) -> int:
    """Return user-set cap, or default 1000g if not set."""
    cap = rule.max_weight_grams if rule else None
    return cap if cap and cap > 0 else DEFAULT_MAX_WEIGHT_GRAMS


def can_open_new_cycle(db: Session, pair: dict, rule: PairRule) -> bool:
    """Cumulative weight cap (Option B). Defaults to 1000g if unset."""
    cap = effective_max_weight(rule)
    current = open_weight_grams(db, pair["name"], pair["big"])
    new_cycle = cycle_grams(pair)
    return (current + new_cycle) <= cap


def evaluate(db: Session) -> None:
    """Independently evaluate each side. Cumulative weight cap (Option B):
    multiple simultaneous positions allowed per pair until total grams hits cap.

    Armed state machine (per pair-side) ensures we fire ONLY on a fresh
    threshold crossing — never while spread sits in trigger zone, never on a
    stale None tick, never on service restart unless spread is genuinely
    re-entering the zone.
    """
    rules = db.query(PairRule).all()
    for rule in rules:
        pair = _pair_def(rule.pair_name)
        if not pair:
            continue
        snap = compute_pair(pair)
        dec_spread = snap["decrease_spread"]
        inc_spread = snap["increase_spread"]

        # ----- Decrease side -----
        # Trigger zone: spread >= decrease_entry
        # Armed when last seen spread was OUTSIDE the trigger zone (< entry)
        if rule.decrease_entry is not None and dec_spread is not None:
            armed = _dec_armed.get(rule.pair_name, False)
            if dec_spread < rule.decrease_entry:
                # Outside zone → arm for next entry
                _dec_armed[rule.pair_name] = True
            elif armed and dec_spread >= rule.decrease_entry:
                # Crossed into zone with armed flag → fire
                if can_open_new_cycle(db, pair, rule):
                    _open_trade(db, pair, "decrease", snap)
                _dec_armed[rule.pair_name] = False  # disarm; must exit zone to re-arm

        # Auto-close every open Decrease pos when cover spread hits exit
        if rule.decrease_exit is not None and inc_spread is not None:
            for p in db.query(Position).filter(
                Position.pair_name == rule.pair_name,
                Position.mode == "decrease",
                Position.status == "open",
            ).all():
                if inc_spread <= rule.decrease_exit:
                    _close_trade(db, p, snap, closed_by="auto")

        # ----- Increase side -----
        # Trigger zone: spread <= increase_entry
        # Armed when last seen spread was OUTSIDE the trigger zone (> entry)
        if rule.increase_entry is not None and inc_spread is not None:
            armed = _inc_armed.get(rule.pair_name, False)
            if inc_spread > rule.increase_entry:
                _inc_armed[rule.pair_name] = True
            elif armed and inc_spread <= rule.increase_entry:
                if can_open_new_cycle(db, pair, rule):
                    _open_trade(db, pair, "increase", snap)
                _inc_armed[rule.pair_name] = False

        # Auto-close every open Increase pos when cover spread hits exit
        if rule.increase_exit is not None and dec_spread is not None:
            for p in db.query(Position).filter(
                Position.pair_name == rule.pair_name,
                Position.mode == "increase",
                Position.status == "open",
            ).all():
                if dec_spread >= rule.increase_exit:
                    _close_trade(db, p, snap, closed_by="auto")

    db.commit()


# Per pair-side armed state. After firing we disarm; next fire requires spread
# to leave the trigger zone first (prevents runaway loops).
_dec_armed: dict[str, bool] = {}
_inc_armed: dict[str, bool] = {}


def prime_armed_state(pair_name: str) -> None:
    """Call when client saves a new rule — primes both sides so the next valid
    tick fires immediately if spread is already inside the trigger zone."""
    _dec_armed[pair_name] = True
    _inc_armed[pair_name] = True


def _open_trade(db: Session, pair: dict, mode: str, snap: dict) -> None:
    if mode == "decrease":
        big_price = snap["big_bid"]
        small_price = snap["small_ask"]
        spread = snap["decrease_spread"]
    else:
        big_price = snap["big_ask"]
        small_price = snap["small_bid"]
        spread = snap["increase_spread"]

    pos = Position(
        pair_name=pair["name"],
        mode=mode,
        entry_spread=spread,
        big_lots=pair["big_lots"],
        small_lots=pair["small_lots"],
        big_price=big_price,
        small_price=small_price,
        is_paper=True,
        status="open",
    )
    db.add(pos)


def _close_trade(db: Session, pos: Position, snap: dict, closed_by: str) -> None:
    """Close uses the COVER-SIDE spread (opposite of entry)."""
    if pos.mode == "decrease":
        exit_spread = snap["increase_spread"]   # cover by buying big back
        big_exit = snap["big_ask"]
        small_exit = snap["small_bid"]
        pnl = (pos.entry_spread - exit_spread) * pos.big_lots
    else:
        exit_spread = snap["decrease_spread"]   # cover by selling big back
        big_exit = snap["big_bid"]
        small_exit = snap["small_ask"]
        pnl = (exit_spread - pos.entry_spread) * pos.big_lots

    pair_def = _pair_def(pos.pair_name)
    weight = pos.big_lots * GRAMS_PER_LOT.get(pair_def["big"], 0) if pair_def else 0

    history = TradeHistory(
        pair_name=pos.pair_name,
        mode=pos.mode,
        entry_spread=pos.entry_spread,
        exit_spread=exit_spread,
        entry_time=pos.entry_time,
        exit_time=datetime.utcnow(),
        big_lots=pos.big_lots,
        small_lots=pos.small_lots,
        pnl=round(pnl, 2),
        is_paper=pos.is_paper,
        closed_by=closed_by,
        big_entry_price=pos.big_price,
        small_entry_price=pos.small_price,
        big_exit_price=big_exit,
        small_exit_price=small_exit,
        weight_grams=weight,
    )
    db.add(history)
    pos.status = "closed"


def manual_close(db: Session, position_id: int) -> TradeHistory | None:
    pos = db.query(Position).filter(Position.id == position_id, Position.status == "open").first()
    if not pos:
        return None
    pair = _pair_def(pos.pair_name)
    if not pair:
        return None
    snap = compute_pair(pair)
    if snap["decrease_spread"] is None or snap["increase_spread"] is None:
        return None
    _close_trade(db, pos, snap, closed_by="manual")
    db.commit()
    return (
        db.query(TradeHistory)
        .filter(TradeHistory.pair_name == pos.pair_name)
        .order_by(TradeHistory.id.desc())
        .first()
    )


def live_pnl(pos: Position) -> float:
    """Live PnL using cover-side spread (the spread you'd actually close at)."""
    pair = _pair_def(pos.pair_name)
    if not pair:
        return 0.0
    snap = compute_pair(pair)
    if pos.mode == "decrease":
        cover = snap["increase_spread"]
        if cover is None:
            return 0.0
        return round((pos.entry_spread - cover) * pos.big_lots, 2)
    # increase
    cover = snap["decrease_spread"]
    if cover is None:
        return 0.0
    return round((cover - pos.entry_spread) * pos.big_lots, 2)
