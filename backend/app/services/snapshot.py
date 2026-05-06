"""Build live spread payload with multi-ladder rules per pair-side."""
from sqlalchemy.orm import Session

from app.config import DEFAULT_MAX_WEIGHT_GRAMS, GRAMS_PER_LOT, MAX_ALLOWED_WEIGHT_GRAMS, cycle_grams
from app.models import LadderRule, Position, TradeHistory
from app.services import pair_registry
from app.services.spread_engine import compute_all
from app.services.trade_engine import effective_max_weight


def _ladder_dict(r: LadderRule, open_weight: int, fired_weight: int, open_count: int) -> dict:
    cap = effective_max_weight(r)
    return {
        "id": r.id,
        "side": r.side,
        "entry": r.entry,
        "exit": r.exit,
        "max_weight_grams": r.max_weight_grams,
        "effective_max_weight": cap,
        "open_weight_grams": open_weight,         # currently-open weight (info only)
        "fired_weight_grams": fired_weight,       # LIFETIME fired (used for cap check)
        "headroom_grams": max(0, cap - fired_weight),
        "locked": fired_weight >= cap,
        "sort_order": r.sort_order or 0,
        "enabled": bool(r.enabled),
        "open_count": open_count,
    }


def build_live_payload(db: Session) -> list[dict]:
    ladders = db.query(LadderRule).order_by(LadderRule.sort_order, LadderRule.id).all()

    # Open positions by ladder
    open_positions = db.query(Position).filter(Position.status == "open").all()
    open_by_ladder: dict[int, list[Position]] = {}
    for p in open_positions:
        if p.ladder_rule_id is not None:
            open_by_ladder.setdefault(p.ladder_rule_id, []).append(p)

    # Closed-trade lots per ladder for lifetime counter
    closed_lots_by_ladder: dict[int, int] = {}
    for ladder_id, big_lots in db.query(TradeHistory.ladder_rule_id, TradeHistory.big_lots).filter(TradeHistory.ladder_rule_id.isnot(None)).all():
        closed_lots_by_ladder[ladder_id] = closed_lots_by_ladder.get(ladder_id, 0) + (big_lots or 0)

    pair_def_by_name = {p["name"]: p for p in pair_registry.get_pairs()}

    snaps = compute_all()
    out = []
    for s in snaps:
        pair_def = pair_def_by_name.get(s["name"])
        cycle_g = cycle_grams(pair_def) if pair_def else 0
        big_g = GRAMS_PER_LOT.get(pair_def["big"], 0) if pair_def else 0

        decrease_ladders = []
        increase_ladders = []
        any_decrease_open = False
        any_increase_open = False

        for r in ladders:
            if r.pair_name != s["name"]:
                continue
            opens = open_by_ladder.get(r.id, [])
            open_lots = sum(p.big_lots for p in opens)
            open_weight = open_lots * big_g
            fired_weight = (open_lots + closed_lots_by_ladder.get(r.id, 0)) * big_g
            d = _ladder_dict(r, open_weight, fired_weight, len(opens))
            if r.side == "decrease":
                decrease_ladders.append(d)
                if opens:
                    any_decrease_open = True
            else:
                increase_ladders.append(d)
                if opens:
                    any_increase_open = True

        if any_decrease_open or any_increase_open:
            status = "in_position"
        elif decrease_ladders or increase_ladders:
            status = "armed"
        else:
            status = "idle"

        out.append({
            **s,
            "decrease_ladders": decrease_ladders,
            "increase_ladders": increase_ladders,
            "decrease_open": any_decrease_open,
            "increase_open": any_increase_open,
            "cycle_grams": cycle_g,
            "default_max_weight": DEFAULT_MAX_WEIGHT_GRAMS,
            "max_allowed_weight": MAX_ALLOWED_WEIGHT_GRAMS,
            "status": status,
        })
    return out
