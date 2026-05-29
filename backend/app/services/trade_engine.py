"""Trigger detection + paper trade execution with multiple ladders per side.

Each pair-side can have many LadderRules. Each ladder fires and runs
INDEPENDENTLY:
  - Own entry threshold
  - Own exit threshold
  - Own weight cap (LIFETIME — total grams ever fired on this ladder)
  - Own armed state (must leave + re-enter trigger zone after fill)

Cap semantics (per ladder, lifetime):
  - Fired counter = sum of (big_lots × grams_per_lot) across ALL positions
    ever opened on this ladder (status = open OR closed). It never resets.
  - Spread in trigger zone + fired_g + new_cycle_g ≤ cap → fire
  - fired_g ≥ cap → ladder is LOCKED (no fires) until cap is RAISED
  - Cap is one-way only: validation in routes/ladders.py disallows decrease
"""
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.config import DEFAULT_MAX_WEIGHT_GRAMS, GRAMS_PER_LOT, cycle_grams
from app.models import AccountConfig, LadderRule, Position, TradeHistory
from app.services import activity, margin_service, pair_registry
from app.services.spread_engine import compute_pair


def _pair_def(name: str) -> dict | None:
    return pair_registry.get_pair(name)


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


def fired_weight_grams_for_ladder(db: Session, ladder_id: int, big_instrument: str) -> int:
    """LIFETIME fired weight for a ladder — sum across open + closed positions.

    This counter never decreases on its own. To 'unlock', the user must
    raise the ladder's cap (handled in routes/ladders.py).
    """
    g = GRAMS_PER_LOT.get(big_instrument, 0)
    open_rows = (
        db.query(Position.big_lots)
        .filter(Position.ladder_rule_id == ladder_id, Position.status == "open")
        .all()
    )
    closed_rows = (
        db.query(TradeHistory.big_lots)
        .filter(TradeHistory.ladder_rule_id == ladder_id)
        .all()
    )
    return sum(r[0] for r in open_rows) * g + sum(r[0] for r in closed_rows) * g


def can_open_new_cycle_for_ladder(
    db: Session, pair: dict, rule: LadderRule
) -> bool:
    cap = effective_max_weight(rule)
    fired = fired_weight_grams_for_ladder(db, rule.id, pair["big"])
    new_cycle = cycle_grams(pair)
    return (fired + new_cycle) <= cap


# In-memory flag so we don't log "fire blocked: account cap" every tick.
_account_cap_blocked_logged: set[int] = set()


def _account_cap_allows_new_fire(db: Session, pair: dict) -> tuple[bool, dict | None]:
    """Check the global account-margin cap for a candidate fire of `pair`.

    Margin is computed per pair via margin_service (live LTPs × instrument %).
    Returns (allowed, snapshot).
    """
    cfg = db.query(AccountConfig).first()
    if not cfg or not cfg.balance or not cfg.max_usage_percent:
        return True, None  # cap not configured → no enforcement

    # Enforcement counts ONLY positions that belong to a currently-live ladder.
    # Orphan positions (their ladder was removed by the daily auto-clear) must
    # NOT permanently consume the cap — otherwise the next day's fresh ladders
    # could never fire. Orphan exposure is still shown in Settings as info.
    live_ladder_ids = {lid for (lid,) in db.query(LadderRule.id).all()}
    open_positions = db.query(Position).filter(Position.status == "open").all()
    active_positions = [
        p for p in open_positions
        if p.ladder_rule_id is not None and p.ladder_rule_id in live_ladder_ids
    ]
    used = sum(margin_service.margin_for_position(p) for p in active_positions)
    this_fire = margin_service.estimated_margin_for_fire(pair)
    cap_rupees = cfg.balance * cfg.max_usage_percent / 100.0

    snap = {
        "open_count": len(active_positions),
        "total_open_count": len(open_positions),
        "this_fire": round(this_fire, 2),
        "used": round(used, 2),
        "cap": round(cap_rupees, 2),
        "balance": cfg.balance,
        "max_usage_percent": cfg.max_usage_percent,
        "pair_name": pair.get("name"),
    }
    return (used + this_fire) <= cap_rupees, snap


def _log_account_cap_block(db: Session, rule_id: int, pair_name: str, side: str, snap: dict) -> bool:
    """Log a fire-blocked event once per ladder. Returns True if a row was added."""
    if rule_id in _account_cap_blocked_logged:
        return False
    _account_cap_blocked_logged.add(rule_id)
    activity.log(
        db, "fire_blocked",
        pair_name=pair_name, side=side, ladder_id=rule_id, actor="system",
        summary=(
            f"Fire blocked: account cap reached "
            f"(used ₹{snap['used']:.0f} + this fire ₹{snap['this_fire']:.0f} > cap ₹{snap['cap']:.0f})"
        ),
        details=snap,
    )
    return True


def evaluate(db: Session) -> None:
    """Two-pass evaluation, runs up to ~2 Hz from the feed.

    Pass 1 (entries): may open new positions and flush them.
    Pass 2 (exits):   fetch ALL open positions ONCE (after entry flushes, so a
                      same-tick fill is still visible) and close from that dict.

    Avoids the old N+1 of one open-positions SELECT per ladder per tick, and
    only commits when something actually changed.
    """
    rules = db.query(LadderRule).filter(LadderRule.enabled == True).all()
    if not rules:
        return  # nothing armed → no work, no commit, no WAL churn

    by_pair: dict[str, list[LadderRule]] = {}
    for r in rules:
        by_pair.setdefault(r.pair_name, []).append(r)

    dirty = False
    # pair_name -> (pair, snap, ladders, dec_spread, inc_spread)
    resolved: dict[str, tuple] = {}

    # ── Pass 1: entries (may flush new positions) ──
    for pair_name, ladders in by_pair.items():
        pair = _pair_def(pair_name)
        if not pair:
            continue
        snap = compute_pair(pair)
        dec_spread = snap["decrease_spread"]
        inc_spread = snap["increase_spread"]
        resolved[pair_name] = (pair, snap, ladders, dec_spread, inc_spread)

        for rule in ladders:
            if rule.side == "decrease":
                if _entry_decrease(db, pair, rule, snap, dec_spread, inc_spread):
                    dirty = True
            else:
                if _entry_increase(db, pair, rule, snap, dec_spread, inc_spread):
                    dirty = True

    # ── Pass 2: exits — one query for all open positions, grouped by ladder ──
    needs_exit = any(
        any(r.exit is not None for r in ladders)
        for (_pair, _snap, ladders, _dec, _inc) in resolved.values()
    )
    if needs_exit:
        open_by_ladder: dict[int, list[Position]] = {}
        for p in db.query(Position).filter(Position.status == "open").all():
            if p.ladder_rule_id is not None:
                open_by_ladder.setdefault(p.ladder_rule_id, []).append(p)

        for pair_name, (pair, snap, ladders, dec_spread, inc_spread) in resolved.items():
            for rule in ladders:
                if rule.exit is None:
                    continue
                positions = open_by_ladder.get(rule.id)
                if not positions:
                    continue
                # decrease ladders cover on increase_spread; increase ladders on decrease_spread
                if rule.side == "decrease":
                    if inc_spread is not None and inc_spread <= rule.exit:
                        for p in positions:
                            _close_trade(db, p, snap, closed_by="auto")
                            dirty = True
                else:
                    if dec_spread is not None and dec_spread >= rule.exit:
                        for p in positions:
                            _close_trade(db, p, snap, closed_by="auto")
                            dirty = True

    if dirty:
        db.commit()


def _entry_decrease(db, pair, rule, snap, dec_spread, inc_spread) -> bool:
    """Entry/firing logic for a decrease ladder. Returns True if it wrote."""
    dirty = False
    if rule.entry is not None and dec_spread is not None:
        if dec_spread < rule.entry:
            _armed[rule.id] = True
        elif _armed.get(rule.id, False):
            allowed_acct, acct_snap = _account_cap_allows_new_fire(db, pair)
            if not allowed_acct:
                if _log_account_cap_block(db, rule.id, pair["name"], "decrease", acct_snap):
                    dirty = True
                _armed[rule.id] = False
            elif can_open_new_cycle_for_ladder(db, pair, rule):
                _open_trade(db, pair, "decrease", snap, rule.id)
                db.flush()
                dirty = True
                _account_cap_blocked_logged.discard(rule.id)
                if not can_open_new_cycle_for_ladder(db, pair, rule):
                    _armed[rule.id] = False
            else:
                _armed[rule.id] = False
    return dirty


def _entry_increase(db, pair, rule, snap, dec_spread, inc_spread) -> bool:
    """Entry/firing logic for an increase ladder. Returns True if it wrote."""
    dirty = False
    if rule.entry is not None and inc_spread is not None:
        if inc_spread > rule.entry:
            _armed[rule.id] = True
        elif _armed.get(rule.id, False):
            allowed_acct, acct_snap = _account_cap_allows_new_fire(db, pair)
            if not allowed_acct:
                if _log_account_cap_block(db, rule.id, pair["name"], "increase", acct_snap):
                    dirty = True
                _armed[rule.id] = False
            elif can_open_new_cycle_for_ladder(db, pair, rule):
                _open_trade(db, pair, "increase", snap, rule.id)
                db.flush()
                dirty = True
                _account_cap_blocked_logged.discard(rule.id)
                if not can_open_new_cycle_for_ladder(db, pair, rule):
                    _armed[rule.id] = False
            else:
                _armed[rule.id] = False
    return dirty


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
    weight = pair["big_lots"] * GRAMS_PER_LOT.get(pair["big"], 0)
    activity.log(
        db, "fire",
        pair_name=pair["name"], side=mode, ladder_id=ladder_id, actor="auto",
        summary=f"Fire {mode} @ {spread:.2f} · {weight}g",
        details={"spread": spread, "weight_grams": weight, "big_lots": pair["big_lots"]},
    )


def _close_trade(db: Session, pos: Position, snap: dict, closed_by: str) -> None:
    if pos.mode == "decrease":
        exit_spread = snap["increase_spread"]
        big_exit = snap["big_ask"]
        small_exit = snap["small_bid"]
        pnl = (pos.entry_spread - exit_spread) * pos.big_lots / 10
    else:
        exit_spread = snap["decrease_spread"]
        big_exit = snap["big_bid"]
        small_exit = snap["small_ask"]
        pnl = (exit_spread - pos.entry_spread) * pos.big_lots / 10

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
        ladder_rule_id=pos.ladder_rule_id,
    )
    db.add(history)
    pos.status = "closed"
    activity.log(
        db, "exit",
        pair_name=pos.pair_name, side=pos.mode, ladder_id=pos.ladder_rule_id,
        actor=("auto" if closed_by == "auto" else "user"),
        summary=f"Exit {pos.mode} @ {exit_spread:.2f} · PnL {pnl:+.2f}",
        details={"entry_spread": pos.entry_spread, "exit_spread": exit_spread, "pnl": round(pnl, 2), "weight_grams": weight, "closed_by": closed_by},
    )


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
        return round((pos.entry_spread - cover) * pos.big_lots / 10, 2)
    cover = snap["decrease_spread"]
    if cover is None:
        return 0.0
    return round((cover - pos.entry_spread) * pos.big_lots / 10, 2)
