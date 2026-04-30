"""Build the same payload that GET /api/pairs/live returns, for WS broadcast."""
from sqlalchemy.orm import Session

from app.config import GRAMS_PER_LOT, PAIRS, cycle_grams
from app.models import PairRule, Position
from app.services.spread_engine import compute_all


def _row_status(rule: PairRule | None, dec_open: bool, inc_open: bool) -> str:
    if dec_open or inc_open:
        return "in_position"
    if rule and (rule.decrease_entry is not None or rule.increase_entry is not None):
        return "armed"
    return "idle"


def build_live_payload(db: Session) -> list[dict]:
    rules = {r.pair_name: r for r in db.query(PairRule).all()}
    open_dec = {
        p.pair_name
        for p in db.query(Position)
        .filter(Position.status == "open", Position.mode == "decrease")
        .all()
    }
    open_inc = {
        p.pair_name
        for p in db.query(Position)
        .filter(Position.status == "open", Position.mode == "increase")
        .all()
    }
    # Open weight per pair (sum of big_lots × gram_per_big_lot)
    open_positions = (
        db.query(Position).filter(Position.status == "open").all()
    )
    weight_by_pair: dict[str, int] = {}
    for p in open_positions:
        # Match by pair name to its config to get big instrument
        pair_def = next((pd for pd in PAIRS if pd["name"] == p.pair_name), None)
        if not pair_def:
            continue
        g = GRAMS_PER_LOT.get(pair_def["big"], 0)
        weight_by_pair[p.pair_name] = weight_by_pair.get(p.pair_name, 0) + p.big_lots * g

    pair_def_by_name = {p["name"]: p for p in PAIRS}

    snaps = compute_all()
    out = []
    for s in snaps:
        rule = rules.get(s["name"])
        dec_open = s["name"] in open_dec
        inc_open = s["name"] in open_inc
        pair_def = pair_def_by_name.get(s["name"])
        cycle_g = cycle_grams(pair_def) if pair_def else 0
        out.append({
            **s,
            "decrease_entry": rule.decrease_entry if rule else None,
            "decrease_exit": rule.decrease_exit if rule else None,
            "increase_entry": rule.increase_entry if rule else None,
            "increase_exit": rule.increase_exit if rule else None,
            "max_weight_grams": rule.max_weight_grams if rule else None,
            "cycle_grams": cycle_g,
            "open_weight_grams": weight_by_pair.get(s["name"], 0),
            "decrease_open": dec_open,
            "increase_open": inc_open,
            "status": _row_status(rule, dec_open, inc_open),
        })
    return out
