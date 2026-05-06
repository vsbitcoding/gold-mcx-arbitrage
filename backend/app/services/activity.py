"""Activity log helper. Append-only audit trail for the dashboard."""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ActivityLog


def log(
    db: Session,
    action: str,
    *,
    pair_name: Optional[str] = None,
    side: Optional[str] = None,
    ladder_id: Optional[int] = None,
    actor: str = "user",
    summary: Optional[str] = None,
    details: Optional[dict] = None,
    commit: bool = False,
) -> ActivityLog:
    row = ActivityLog(
        timestamp=datetime.utcnow(),
        action=action,
        pair_name=pair_name,
        side=side,
        ladder_id=ladder_id,
        actor=actor,
        summary=summary,
        details=json.dumps(details) if details else None,
    )
    db.add(row)
    if commit:
        db.commit()
    return row
