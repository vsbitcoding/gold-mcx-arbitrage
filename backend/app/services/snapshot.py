"""Build the same payload that GET /api/pairs/live returns, for WS broadcast."""
from sqlalchemy.orm import Session

from app.config import PAIRS
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
    snaps = compute_all()
    out = []
    for s in snaps:
        rule = rules.get(s["name"])
        dec_open = s["name"] in open_dec
        inc_open = s["name"] in open_inc
        out.append({
            **s,
            "decrease_entry": rule.decrease_entry if rule else None,
            "decrease_exit": rule.decrease_exit if rule else None,
            "increase_entry": rule.increase_entry if rule else None,
            "increase_exit": rule.increase_exit if rule else None,
            "decrease_open": dec_open,
            "increase_open": inc_open,
            "status": _row_status(rule, dec_open, inc_open),
        })
    return out
