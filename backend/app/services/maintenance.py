"""Background DB maintenance:
- Daily auto-clear of all ladder rules at MCX close (~23:35 IST = 18:05 UTC)
- 7-day rolling history retention
- Activity log: 30-day retention
- Occasional SQLite VACUUM
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.models import ActivityLog, LadderRule, TradeHistory
from app.services import activity

log = logging.getLogger("maintenance")

HISTORY_RETENTION_DAYS = 7
ACTIVITY_RETENTION_DAYS = 30

# Daily auto-clear runs at 23:35 IST (= 18:05 UTC). MCX non-agri commodities
# session closes at 23:30 IST.
CLEAR_HOUR_UTC = 18
CLEAR_MINUTE_UTC = 5
TICK_SECONDS = 60


def _prune_history() -> int:
    cutoff = datetime.utcnow() - timedelta(days=HISTORY_RETENTION_DAYS)
    db = SessionLocal()
    try:
        n = db.query(TradeHistory).filter(TradeHistory.exit_time < cutoff).delete()
        if n > 0:
            activity.log(
                db, "history_purged",
                actor="system",
                summary=f"Auto-purged {n} history records older than {HISTORY_RETENTION_DAYS} days",
                details={"deleted": n, "retention_days": HISTORY_RETENTION_DAYS},
            )
        db.commit()
        return n
    finally:
        db.close()


def _prune_activity() -> int:
    cutoff = datetime.utcnow() - timedelta(days=ACTIVITY_RETENTION_DAYS)
    db = SessionLocal()
    try:
        n = db.query(ActivityLog).filter(ActivityLog.timestamp < cutoff).delete()
        db.commit()
        return n
    finally:
        db.close()


def _daily_clear_ladders() -> int:
    """Delete all ladder rules. Open positions are left as-is (per client spec)."""
    db = SessionLocal()
    try:
        n = db.query(LadderRule).delete()
        if n > 0:
            activity.log(
                db, "daily_clear",
                actor="system",
                summary=f"Daily auto-clear: deleted {n} ladders at MCX close",
                details={"deleted": n},
            )
        db.commit()
        return n
    finally:
        db.close()


def _vacuum() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        conn.execute(text("VACUUM"))


def _loop() -> None:
    # Track which day we last ran the daily clear (UTC date) to avoid double-fire
    last_clear_date: str | None = None
    time.sleep(15)
    while True:
        try:
            now = datetime.utcnow()
            today_str = now.date().isoformat()
            # Daily auto-clear window: at or after 18:05 UTC on a fresh date
            if (
                last_clear_date != today_str
                and (now.hour, now.minute) >= (CLEAR_HOUR_UTC, CLEAR_MINUTE_UTC)
            ):
                cleared = _daily_clear_ladders()
                pruned = _prune_history()
                act_pruned = _prune_activity()
                log.info(
                    "Daily auto-clear: %d ladders, %d history rows, %d activity rows.",
                    cleared, pruned, act_pruned,
                )
                if pruned > 0 or cleared > 0:
                    _vacuum()
                last_clear_date = today_str
        except Exception as e:
            log.exception("Maintenance error: %s", e)
        time.sleep(TICK_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="maintenance")
    t.start()
    return t
