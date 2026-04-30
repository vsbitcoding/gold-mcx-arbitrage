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
        # ENTRY uses Decrease spread (the price you sell big at).
        # EXIT  uses Increase spread (the price you cover/buy back big at).
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
                and snap["increase_spread"] is not None
                and snap["increase_spread"] <= rule.decrease_exit
            ):
                _close_trade(db, dec_pos, snap, closed_by="auto")

        # ----- Increase side -----
        # ENTRY uses Increase spread (the price you buy big at).
        # EXIT  uses Decrease spread (the price you sell big back at).
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
                and snap["decrease_spread"] is not None
                and snap["decrease_spread"] >= rule.increase_exit
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
    """Close uses the COVER-SIDE spread (opposite of entry)."""
    if pos.mode == "decrease":
        exit_spread = snap["increase_spread"]   # cover by buying big back
        pnl = (pos.entry_spread - exit_spread) * pos.big_lots
    else:
        exit_spread = snap["decrease_spread"]   # cover by selling big back
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
