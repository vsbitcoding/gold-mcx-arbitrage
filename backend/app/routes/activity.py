"""Activity log read-only endpoint with pagination + filters."""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog
from app.security import get_current_user

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_activity(
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    days: int = Query(7, ge=1, le=30),
    pair_name: str | None = None,
    action: str | None = None,
    db: Session = Depends(get_db),
    user: str = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(ActivityLog).filter(ActivityLog.timestamp >= since)
    if pair_name:
        q = q.filter(ActivityLog.pair_name == pair_name)
    if action:
        q = q.filter(ActivityLog.action == action)
    total = q.count()
    rows = q.order_by(ActivityLog.id.desc()).offset(offset).limit(limit).all()
    out = []
    for r in rows:
        details = None
        if r.details:
            try:
                details = json.loads(r.details)
            except Exception:
                details = None
        out.append({
            "id": r.id,
            "timestamp": (r.timestamp.isoformat() + "Z") if r.timestamp else None,
            "action": r.action,
            "pair_name": r.pair_name,
            "side": r.side,
            "ladder_id": r.ladder_id,
            "actor": r.actor,
            "summary": r.summary,
            "details": details,
        })
    return {"events": out, "total": total, "offset": offset, "limit": limit}
