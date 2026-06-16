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
from app.models import ActivityLog, TradeHistory
from app.services import activity, extra_instruments, span_service

log = logging.getLogger("maintenance")

HISTORY_RETENTION_DAYS = 7
ACTIVITY_RETENTION_DAYS = 30

# Daily auto-clear runs at 23:35 IST. MCX non-agri commodities
# session closes at 23:30 IST. Server timezone is Asia/Kolkata so
# datetime.now() is IST.
CLEAR_HOUR_IST = 23
CLEAR_MINUTE_IST = 35
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


def _vacuum() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        conn.execute(text("VACUUM"))


def _check_calculator_rollover(active: dict) -> None:
    """Re-resolve Full Gold + Full Silver. If 7-day-rollover would pick a new
    contract, log a clear warning so we know to restart the backend.
    Stores active per-day to avoid duplicate logs."""
    try:
        prev_gold = extra_instruments.get_full_gold()
        prev_silver = extra_instruments.get_full_silver()
        extra_instruments.refresh()
        new_gold = extra_instruments.get_full_gold()
        new_silver = extra_instruments.get_full_silver()

        for label, prev, new in (
            ("Full Gold", prev_gold, new_gold),
            ("Full Silver", prev_silver, new_silver),
        ):
            if not prev or not new:
                continue
            if prev["security_id"] != new["security_id"]:
                key = f"{label}:{new['security_id']}"
                if active.get(key):
                    continue
                active[key] = True
                log.warning(
                    "Calculator rollover due: %s should switch from %s → %s. "
                    "Restart backend to pick up the new subscription.",
                    label, prev["trading_symbol"], new["trading_symbol"],
                )
                # Persist a system activity row so the user sees it on the Activity tab
                db = SessionLocal()
                try:
                    activity.log(
                        db, "rollover_due",
                        actor="system",
                        summary=f"{label} rollover due: {prev['trading_symbol']} → {new['trading_symbol']} (restart backend)",
                        details={
                            "metal": label,
                            "from_symbol": prev["trading_symbol"],
                            "to_symbol": new["trading_symbol"],
                            "from_security_id": prev["security_id"],
                            "to_security_id": new["security_id"],
                        },
                        commit=True,
                    )
                finally:
                    db.close()
    except Exception as e:
        log.warning("Rollover check failed: %s", e)


def _loop() -> None:
    # Track which day we last ran the nightly pruning (IST date) to avoid double-fire
    last_clear_date: str | None = None
    last_rollover_check: str | None = None
    last_span_refresh: str | None = None
    rollover_logged: dict[str, bool] = {}
    # Initial SPAN refresh on startup so first ticks use live values (if feed configured)
    try:
        span_service.refresh()
    except Exception as e:
        log.warning("Initial SPAN refresh raised: %s", e)
    time.sleep(15)
    while True:
        try:
            now = datetime.now()  # server runs in Asia/Kolkata → IST
            today_str = now.date().isoformat()
            # Nightly retention prune: at or after 23:35 IST on a fresh date
            if (
                last_clear_date != today_str
                and (now.hour, now.minute) >= (CLEAR_HOUR_IST, CLEAR_MINUTE_IST)
            ):
                pruned = _prune_history()
                act_pruned = _prune_activity()
                log.info(
                    "Nightly prune: %d history rows, %d activity rows.",
                    pruned, act_pruned,
                )
                if pruned > 0:
                    _vacuum()
                last_clear_date = today_str

            # Daily rollover check (calculator MCX contracts) — once per IST day at 09:00 IST.
            if last_rollover_check != today_str and now.hour >= 9:
                _check_calculator_rollover(rollover_logged)
                last_rollover_check = today_str

            # Daily SPAN margin refresh — once per IST day at 08:30 IST (before market open).
            if last_span_refresh != today_str and (now.hour, now.minute) >= (8, 30):
                ok = span_service.refresh()
                last_span_refresh = today_str
                if ok:
                    log.info("SPAN margin feed refreshed for %s", today_str)
        except Exception as e:
            log.exception("Maintenance error: %s", e)
        time.sleep(TICK_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="maintenance")
    t.start()
    return t
