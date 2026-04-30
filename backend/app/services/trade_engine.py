"""Trigger detection + paper trade execution.

Decrease and Increase sides run INDEPENDENTLY per pair — both can have a
simultaneous open position (one for each side). Each side cycles on its own:
arm -> trigger -> open -> exit -> auto re-arm.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import PAIRS
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


def evaluate(db: Session) -> None:
    """Independently evaluate each side (decrease, increase) for every pair."""
    rules = db.query(PairRule).all()
    for rule in rules:
        pair = _pair_def(rule.pair_name)
        if not pair:
            continue
        snap = compute_pair(pair)

        # ----- Decrease side -----
        dec_pos = open_position_for_side(db, rule.pair_name, "decrease")
        if dec_pos is None:
            if (
                rule.decrease_entry is not None
                and snap["decrease_spread"] is not None
                and snap["decrease_spread"] >= rule.decrease_entry
            ):
                _open_trade(db, pair, "decrease", snap)
        else:
            if (
                rule.decrease_exit is not None
                and snap["decrease_spread"] is not None
                and snap["decrease_spread"] <= rule.decrease_exit
            ):
                _close_trade(db, dec_pos, snap, closed_by="auto")

        # ----- Increase side -----
        inc_pos = open_position_for_side(db, rule.pair_name, "increase")
        if inc_pos is None:
            if (
                rule.increase_entry is not None
                and snap["increase_spread"] is not None
                and snap["increase_spread"] <= rule.increase_entry
            ):
                _open_trade(db, pair, "increase", snap)
        else:
            if (
                rule.increase_exit is not None
                and snap["increase_spread"] is not None
                and snap["increase_spread"] >= rule.increase_exit
            ):
                _close_trade(db, inc_pos, snap, closed_by="auto")

    db.commit()


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
    if pos.mode == "decrease":
        exit_spread = snap["decrease_spread"]
        pnl = (pos.entry_spread - exit_spread) * pos.big_lots
    else:
        exit_spread = snap["increase_spread"]
        pnl = (exit_spread - pos.entry_spread) * pos.big_lots

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
    if pos.mode == "decrease" and snap["decrease_spread"] is not None:
        return round((pos.entry_spread - snap["decrease_spread"]) * pos.big_lots, 2)
    if pos.mode == "increase" and snap["increase_spread"] is not None:
        return round((snap["increase_spread"] - pos.entry_spread) * pos.big_lots, 2)
    return 0.0
