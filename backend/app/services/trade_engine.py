"""Trigger detection + paper trade execution with multiple ladders per side.

Each pair-side can have many LadderRules. Each ladder fires and runs
INDEPENDENTLY:
  - Own entry threshold
  - Own exit threshold
  - Own weight cap (cumulative across ladder's open positions)
  - Own armed state (must leave + re-enter trigger zone after fill)

Cap semantics (per ladder):
  - On save → fire to current cap (back-to-back if spread in zone)
  - Cap full → no more fires until current ladder positions all square off
  - Cap mid-trade change → stored as PENDING, applies after square-off
"""
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.config import DEFAULT_MAX_WEIGHT_GRAMS, GRAMS_PER_LOT, PAIRS, cycle_grams
from app.models import LadderRule, Position, TradeHistory
from app.services.spread_engine import compute_pair


def _pair_def(name: str) -> dict | None:
    return next((p for p in PAIRS if p["name"] == name), None)


# Per-ladder armed state (in-memory)
_armed: dict[int, bool] = {}


def prime_armed_state(ladder_id: int) -> None:
    """Called when a ladder rule is saved/created so it fires immediately if
    spread is already in trigger zone."""
    _armed[ladder_id] = True


def effective_max_weight(rule: LadderRule | None) -> int:
    cap = rule.max_weight_grams if rule else None
    return cap if cap and cap > 0 else DEFAULT_MAX_WEIGHT_GRAMS


def open_positions_for_ladder(db: Session, ladder_id: int) -> List[Position]:
    return (
        db.query(Position)
        .filter(Position.ladder_rule_id == ladder_id, Position.status == "open")
        .all()
    )


def open_weight_grams_for_ladder(db: Session, ladder_id: int, big_instrument: str) -> int:
    g = GRAMS_PER_LOT.get(big_instrument, 0)
    rows = open_positions_for_ladder(db, ladder_id)
    return sum(r.big_lots * g for r in rows)


def can_open_new_cycle_for_ladder(
    db: Session, pair: dict, rule: LadderRule
) -> bool:
    cap = effective_max_weight(rule)
    current = open_weight_grams_for_ladder(db, rule.id, pair["big"])
    new_cycle = cycle_grams(pair)
    return (current + new_cycle) <= cap


def reconcile_pending_caps(db: Session) -> None:
    """Apply pending cap changes once a ladder has no open positions."""
    rules = db.query(LadderRule).filter(LadderRule.has_pending_cap == 1).all()
    for rule in rules:
        if not open_positions_for_ladder(db, rule.id):
            rule.max_weight_grams = rule.pending_max_weight_grams
            rule.pending_max_weight_grams = None
            rule.has_pending_cap = 0
            _armed[rule.id] = True  # re-prime for next round


def evaluate(db: Session) -> None:
    reconcile_pending_caps(db)

    # Group ladder rules by pair to avoid recomputing snapshots
    rules = db.query(LadderRule).filter(LadderRule.enabled == True).all()
    by_pair: dict[str, list[LadderRule]] = {}
    for r in rules:
        by_pair.setdefault(r.pair_name, []).append(r)

    for pair_name, ladders in by_pair.items():
        pair = _pair_def(pair_name)
        if not pair:
            continue
        snap = compute_pair(pair)
        dec_spread = snap["decrease_spread"]
        inc_spread = snap["increase_spread"]

        for rule in ladders:
            if rule.side == "decrease":
                _evaluate_decrease(db, pair, rule, snap, dec_spread, inc_spread)
            else:
                _evaluate_increase(db, pair, rule, snap, dec_spread, inc_spread)

    db.commit()


def _evaluate_decrease(db, pair, rule, snap, dec_spread, inc_spread):
    # Entry/firing logic
    if rule.entry is not None and dec_spread is not None:
        if dec_spread < rule.entry:
            _armed[rule.id] = True
        elif _armed.get(rule.id, False):
            if can_open_new_cycle_for_ladder(db, pair, rule):
                _open_trade(db, pair, "decrease", snap, rule.id)
                db.flush()
                if not can_open_new_cycle_for_ladder(db, pair, rule):
                    _armed[rule.id] = False
            else:
                _armed[rule.id] = False

    # Exit logic — close all open positions for this ladder when cover spread hits exit
    if rule.exit is not None and inc_spread is not None:
        for p in open_positions_for_ladder(db, rule.id):
            if inc_spread <= rule.exit:
                _close_trade(db, p, snap, closed_by="auto")


def _evaluate_increase(db, pair, rule, snap, dec_spread, inc_spread):
    if rule.entry is not None and inc_spread is not None:
        if inc_spread > rule.entry:
            _armed[rule.id] = True
        elif _armed.get(rule.id, False):
            if can_open_new_cycle_for_ladder(db, pair, rule):
                _open_trade(db, pair, "increase", snap, rule.id)
                db.flush()
                if not can_open_new_cycle_for_ladder(db, pair, rule):
                    _armed[rule.id] = False
            else:
                _armed[rule.id] = False

    if rule.exit is not None and dec_spread is not None:
        for p in open_positions_for_ladder(db, rule.id):
            if dec_spread >= rule.exit:
                _close_trade(db, p, snap, closed_by="auto")


def _open_trade(db: Session, pair: dict, mode: str, snap: dict, ladder_id: int) -> None:
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
        ladder_rule_id=ladder_id,
    )
    db.add(pos)


def _close_trade(db: Session, pos: Position, snap: dict, closed_by: str) -> None:
    if pos.mode == "decrease":
        exit_spread = snap["increase_spread"]
        big_exit = snap["big_ask"]
        small_exit = snap["small_bid"]
        pnl = (pos.entry_spread - exit_spread) * pos.big_lots
    else:
        exit_spread = snap["decrease_spread"]
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
    pair = _pair_def(pos.pair_name)
    if not pair:
        return 0.0
    snap = compute_pair(pair)
    if pos.mode == "decrease":
        cover = snap["increase_spread"]
        if cover is None:
            return 0.0
        return round((pos.entry_spread - cover) * pos.big_lots, 2)
    cover = snap["decrease_spread"]
    if cover is None:
        return 0.0
    return round((cover - pos.entry_spread) * pos.big_lots, 2)
