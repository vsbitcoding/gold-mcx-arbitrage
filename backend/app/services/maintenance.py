"""Background DB maintenance: prune old history, VACUUM SQLite occasionally.

Runs in a daemon thread. No external schedulers required.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.models import TradeHistory

log = logging.getLogger("maintenance")

HISTORY_RETENTION_DAYS = 90
RUN_INTERVAL_SECONDS = 24 * 3600  # daily


def _prune_history() -> int:
    cutoff = datetime.utcnow() - timedelta(days=HISTORY_RETENTION_DAYS)
    db = SessionLocal()
    try:
        n = db.query(TradeHistory).filter(TradeHistory.exit_time < cutoff).delete()
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
    # First run after 60s (let app warm up); thereafter daily
    time.sleep(60)
    while True:
        try:
            n = _prune_history()
            log.info("Maintenance: pruned %d history rows older than %d days.", n, HISTORY_RETENTION_DAYS)
            if n > 0:
                _vacuum()
                log.info("Maintenance: VACUUM done.")
        except Exception as e:
            log.exception("Maintenance error: %s", e)
        time.sleep(RUN_INTERVAL_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="maintenance")
    t.start()
    return t
