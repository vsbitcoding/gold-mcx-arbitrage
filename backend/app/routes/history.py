from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TradeHistory
from app.security import get_current_user
from app.services import pair_registry

router = APIRouter(prefix="/api/history", tags=["history"])


def _pair_def(name: str) -> dict | None:
    return pair_registry.get_pair(name)


def _build_history_summaries(enriched: list[dict]) -> list[dict]:
    """Group closed trades by (pair_name, mode); compute weighted averages."""
    groups: dict[tuple, list[dict]] = {}
    for p in enriched:
        key = (p["pair_name"], p["mode"])
        groups.setdefault(key, []).append(p)

    out = []
    for (pair_name, mode), rows in groups.items():
        total_weight = sum(r["weight_grams"] or 0 for r in rows)
        if total_weight > 0:
            avg_entry = sum((r["entry_spread"] or 0) * (r["weight_grams"] or 0) for r in rows) / total_weight
            avg_exit = sum((r["exit_spread"] or 0) * (r["weight_grams"] or 0) for r in rows) / total_weight
        else:
            avg_entry = avg_exit = None
        pnl_total = sum(r["pnl"] or 0 for r in rows)
        out.append({
            "pair_name": pair_name,
            "mode": mode,
            "count": len(rows),
            "total_weight_grams": total_weight,
            "avg_entry_spread": round(avg_entry, 4) if avg_entry is not None else None,
            "avg_exit_spread": round(avg_exit, 4) if avg_exit is not None else None,
            "total_pnl": round(pnl_total, 2),
        })
    out.sort(key=lambda s: (s["pair_name"], s["mode"]))
    return out


@router.get("")
def list_history(
    days: int = Query(30, ge=1, le=365),
    pair_name: str | None = None,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(TradeHistory).filter(TradeHistory.exit_time >= since)
    if pair_name:
        q = q.filter(TradeHistory.pair_name == pair_name)
    rows = q.order_by(TradeHistory.exit_time.desc()).all()
    out = []
    for r in rows:
        pair_def = _pair_def(r.pair_name)
        big_inst = pair_def["big"] if pair_def else None
        small_inst = pair_def["small"] if pair_def else None
        big_action = "SELL" if r.mode == "decrease" else "BUY"
        small_action = "BUY" if r.mode == "decrease" else "SELL"
        duration = (r.exit_time - r.entry_time).total_seconds() if r.entry_time else 0
        out.append({
            "id": r.id,
            "pair_name": r.pair_name,
            "label": pair_def.get("label") if pair_def else r.pair_name,
            "expiry_label": pair_def.get("expiry_label") if pair_def else "",
            "mode": r.mode,
            "entry_spread": r.entry_spread,
            "exit_spread": r.exit_spread,
            "entry_time": r.entry_time.isoformat() if r.entry_time else None,
            "exit_time": r.exit_time.isoformat() if r.exit_time else None,
            "duration_seconds": duration,
            "big_instrument": big_inst,
            "big_action": big_action,
            "big_lots": r.big_lots,
            "big_entry_price": r.big_entry_price,
            "big_exit_price": r.big_exit_price,
            "small_instrument": small_inst,
            "small_action": small_action,
            "small_lots": r.small_lots,
            "small_entry_price": r.small_entry_price,
            "small_exit_price": r.small_exit_price,
            "weight_grams": r.weight_grams,
            "pnl": r.pnl,
            "is_paper": r.is_paper,
            "closed_by": r.closed_by,
        })
    return {
        "trades": out,
        "summaries": _build_history_summaries(out),
    }
