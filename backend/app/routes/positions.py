from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import GRAMS_PER_LOT
from app.database import get_db
from app.models import LadderRule, Position
from app.security import get_current_user
from app.services import activity, pair_registry
from app.services.spread_engine import compute_pair
from app.services.trade_engine import live_pnl, manual_close

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _enrich(p: Position, live_ladder_ids: set[int]) -> dict:
    pair_def = pair_registry.get_pair(p.pair_name)
    snap = compute_pair(pair_def) if pair_def else None
    big_inst = pair_def["big"] if pair_def else None
    small_inst = pair_def["small"] if pair_def else None

    big_live = small_live = None
    cover_spread = None
    if snap:
        if p.mode == "decrease":
            # Closed by buying big at ask + selling small at bid
            big_live = snap["big_ask"]
            small_live = snap["small_bid"]
            cover_spread = snap["increase_spread"]
        else:
            big_live = snap["big_bid"]
            small_live = snap["small_ask"]
            cover_spread = snap["decrease_spread"]

    big_g = GRAMS_PER_LOT.get(big_inst, 0) if big_inst else 0
    weight_g = p.big_lots * big_g

    big_action = "SELL" if p.mode == "decrease" else "BUY"
    small_action = "BUY" if p.mode == "decrease" else "SELL"

    # Pair label for friendlier display in summary
    label = pair_def.get("label") if pair_def else p.pair_name
    expiry = pair_def.get("expiry_label") if pair_def else ""

    # Orphaned = parent ladder no longer exists (e.g. after daily auto-clear or manual delete).
    # Such positions cannot auto-exit — user must square off manually.
    orphaned = p.ladder_rule_id is None or p.ladder_rule_id not in live_ladder_ids

    return {
        "id": p.id,
        "orphaned": orphaned,
        "pair_name": p.pair_name,
        "label": label,
        "expiry_label": expiry,
        "mode": p.mode,
        "entry_spread": p.entry_spread,
        "cover_spread": cover_spread,
        "entry_time": p.entry_time.isoformat() + "Z",
        "is_paper": p.is_paper,
        "live_pnl": live_pnl(p),
        "weight_grams": weight_g,
        # Big leg
        "big_instrument": big_inst,
        "big_action": big_action,
        "big_lots": p.big_lots,
        "big_entry_price": p.big_price,
        "big_live_price": big_live,
        # Small leg
        "small_instrument": small_inst,
        "small_action": small_action,
        "small_lots": p.small_lots,
        "small_entry_price": p.small_price,
        "small_live_price": small_live,
    }


def _build_summaries(enriched: list[dict]) -> list[dict]:
    """Group enriched positions by (pair_name, mode) and compute weighted averages."""
    groups: dict[tuple, list[dict]] = {}
    for p in enriched:
        key = (p["pair_name"], p["mode"])
        groups.setdefault(key, []).append(p)

    out = []
    for (pair_name, mode), rows in groups.items():
        total_weight = sum(r["weight_grams"] or 0 for r in rows)
        if total_weight > 0:
            avg_entry = sum((r["entry_spread"] or 0) * (r["weight_grams"] or 0) for r in rows) / total_weight
        else:
            avg_entry = None
        live_pnl_total = sum(r["live_pnl"] or 0 for r in rows)
        cover = next((r["cover_spread"] for r in rows if r["cover_spread"] is not None), None)
        out.append({
            "pair_name": pair_name,
            "label": rows[0].get("label") or pair_name,
            "expiry_label": rows[0].get("expiry_label") or "",
            "mode": mode,
            "count": len(rows),
            "total_weight_grams": total_weight,
            "avg_entry_spread": round(avg_entry, 4) if avg_entry is not None else None,
            "cover_spread": cover,
            "live_pnl": round(live_pnl_total, 2),
        })
    out.sort(key=lambda s: (s["pair_name"], s["mode"]))
    return out


@router.get("")
def list_open(
    pair_name: str | None = None,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    q = db.query(Position).filter(Position.status == "open")
    if pair_name:
        q = q.filter(Position.pair_name == pair_name)
    rows = q.order_by(Position.id.desc()).all()
    live_ladder_ids = {lid for (lid,) in db.query(LadderRule.id).all()}
    enriched = [_enrich(p, live_ladder_ids) for p in rows]
    orphaned_count = sum(1 for r in enriched if r["orphaned"])
    orphaned_weight = sum((r["weight_grams"] or 0) for r in enriched if r["orphaned"])
    return {
        "positions": enriched,
        "summaries": _build_summaries(enriched),
        "orphaned_count": orphaned_count,
        "orphaned_weight_grams": orphaned_weight,
    }


@router.post("/{position_id}/close")
def close(position_id: int, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    closed = manual_close(db, position_id)
    if not closed:
        raise HTTPException(400, "Position not found or quote unavailable")
    return {"ok": True, "history_id": closed.id, "pnl": closed.pnl}


class SquareOffRequest(BaseModel):
    pair_name: str
    mode: str | None = Field(None, pattern="^(decrease|increase)$")
    weight_grams: int = Field(..., gt=0)


@router.post("/square-off")
def square_off(
    body: SquareOffRequest,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    """Manual square-off by weight (FIFO — oldest trades close first).

    Closes the oldest open trades for `pair_name` (and optional `mode`)
    until cumulative weight ≥ `weight_grams`. Returns count + total weight
    + PnL of trades closed.
    """
    pair_def = pair_registry.get_pair(body.pair_name)
    if not pair_def:
        raise HTTPException(404, "Unknown pair")
    big_g = GRAMS_PER_LOT.get(pair_def["big"], 0)
    if big_g <= 0:
        raise HTTPException(400, "Pair has no per-lot weight defined")

    q = db.query(Position).filter(
        Position.status == "open",
        Position.pair_name == body.pair_name,
    )
    if body.mode:
        q = q.filter(Position.mode == body.mode)
    rows = q.order_by(Position.entry_time.asc(), Position.id.asc()).all()
    if not rows:
        raise HTTPException(400, "No open positions for this pair")

    closed_ids: list[int] = []
    total_weight = 0
    total_pnl = 0.0
    for p in rows:
        if total_weight >= body.weight_grams:
            break
        result = manual_close(db, p.id)
        if not result:
            raise HTTPException(400, "Live quote unavailable — try again in a moment")
        closed_ids.append(result.id)
        total_weight += p.big_lots * big_g
        total_pnl += result.pnl or 0.0

    if not closed_ids:
        raise HTTPException(400, "Nothing closed — invalid request")

    activity.log(
        db, "square_off",
        pair_name=body.pair_name, side=body.mode, actor="user",
        summary=f"Manual square-off: closed {len(closed_ids)} trade(s), {total_weight}g, PnL {total_pnl:+.2f}",
        details={
            "requested_weight_grams": body.weight_grams,
            "closed_count": len(closed_ids),
            "actual_weight_grams": total_weight,
            "total_pnl": round(total_pnl, 2),
            "history_ids": closed_ids,
            "order": "fifo",
        },
        commit=True,
    )

    return {
        "ok": True,
        "closed_count": len(closed_ids),
        "actual_weight_grams": total_weight,
        "total_pnl": round(total_pnl, 2),
        "history_ids": closed_ids,
    }
