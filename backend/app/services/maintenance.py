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
from app.services import (activity, crude_iv_history, dhan_feed, extra_instruments,
                          mcxccl_service, nse_mcx_history, options_history_service,
                          span_service)

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
    """Re-resolve Full Gold + Full Silver and note when the contract moves.

    A restart is no longer needed for this - the 08:40 roll above rebuilds every
    subscription daily - so the note is now a record of what changed rather than
    a job for somebody. Kept per-day so it is logged once, not every minute.
    """
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
                log.info(
                    "Calculator rollover: %s moved %s -> %s (the 08:40 roll "
                    "picks up the new subscription).",
                    label, prev["trading_symbol"], new["trading_symbol"],
                )
                # Persist a system activity row so the user sees it on the Activity tab
                db = SessionLocal()
                try:
                    activity.log(
                        db, "rollover_due",
                        actor="system",
                        summary=f"{label} rolled: {prev['trading_symbol']} to {new['trading_symbol']}",
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
    last_roll: str | None = None
    last_expiry_roll: str | None = None
    last_mcxccl_attempt: datetime | None = None
    last_optsnap: dict[str, str | None] = {s: None for s in options_history_service._SLOTS}
    last_nmsnap: dict[str, str | None] = {s: None for s in nse_mcx_history.SLOTS}
    last_civsnap: dict[str, str | None] = {s: None for s in crude_iv_history.SLOTS}
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
                snap_pruned = options_history_service.prune()
                nm_pruned = nse_mcx_history.prune()
                civ_pruned = crude_iv_history.prune()
                log.info(
                    "Nightly prune: %d history rows, %d activity rows, %d option snapshots, "
                    "%d NSE/MCX snapshots, %d crude IV snapshots.",
                    pruned, act_pruned, snap_pruned, nm_pruned, civ_pruned,
                )
                if pruned > 0:
                    _vacuum()
                last_clear_date = today_str

            # Daily rollover check (calculator MCX contracts) — once per IST day at 09:00 IST.
            if last_rollover_check != today_str and now.hour >= 9:
                _check_calculator_rollover(rollover_logged)
                last_rollover_check = today_str

            # Nifty/Sensex options-board snapshot (10:00, 15:00, 15:16 & 15:35 IST)
            # — replaces the client's manual screenshots. In-memory read + one tiny
            # INSERT; the service itself skips weekends / cold feed / missed windows
            # (so a late restart can never store mislabelled data). The slot list
            # lives in the service so the two can never drift apart.
            for _slot, (_h, _m) in options_history_service._SLOTS.items():
                if last_optsnap[_slot] != today_str and (now.hour, now.minute) >= (_h, _m):
                    try:
                        msg = options_history_service.snapshot(_slot)
                        log.info("Options snapshot %s: %s", _slot, msg)
                    except Exception as e:
                        log.warning("Options snapshot %s raised: %s", _slot, e)
                    last_optsnap[_slot] = today_str

            # NSE-vs-MCX board snapshot, nine slots 10:00-23:15 IST — the client
            # wants the whole table stored so the drift between the two
            # exchanges can be read back later. No exchange sells NSE-commodity
            # history, so a missed capture is gone for good; the service still
            # refuses to store a cold or mislabelled board.
            for _slot in nse_mcx_history.SLOTS:
                _h, _m = nse_mcx_history.SLOTS[_slot]
                if last_nmsnap[_slot] != today_str and (now.hour, now.minute) >= (_h, _m):
                    try:
                        res = nse_mcx_history.snapshot_all(_slot)
                        log.info("NSE/MCX snapshot %s: %s", _slot, res)
                        # A restart INSIDE the capture window leaves the feeds
                        # cold for a few seconds. Retiring the slot on that
                        # first tick would burn it for the whole day, so retry
                        # next minute while the only failures are transient.
                        # The service itself stops us at the window edge by
                        # answering "outside capture window", which is final.
                        if not any(v.startswith("no live") or v == "busy"
                                   for v in res.values()):
                            last_nmsnap[_slot] = today_str
                    except Exception as e:
                        log.warning("NSE/MCX snapshot %s raised: %s", _slot, e)
                        last_nmsnap[_slot] = today_str

            # MCX-vs-US option board, every half hour 09:00-23:30 IST, both
            # commodities and both expiry months (client, 19-Aug). US crude
            # trades nearly round the clock and its one daily break falls
            # outside MCX hours, so the overlap is simply MCX's session - but
            # the service still tests the DATA rather than the clock and skips a
            # slot where either side has stopped quoting two-way.
            for _slot in crude_iv_history.SLOTS:
                _h, _m = crude_iv_history.SLOTS[_slot]
                if last_civsnap[_slot] != today_str and (now.hour, now.minute) >= (_h, _m):
                    try:
                        res = crude_iv_history.snapshot_all(_slot)
                        stored = sum(1 for v in res.values() if v == "snapped")
                        if stored or any(v.startswith("outside") for v in res.values()):
                            log.info("crude IV snapshot %s: %s", _slot, res)
                        # Retry next minute while failures are transient - a
                        # restart inside the window leaves the feeds cold for a
                        # few seconds and burning the slot would lose the half
                        # hour. "outside capture window" is the service's own
                        # final answer and retires it.
                        if not any(v == "busy" or v.startswith("one side")
                                   for v in res.values()):
                            last_civsnap[_slot] = today_str
                    except Exception as e:                    # noqa: BLE001
                        log.warning("crude IV snapshot %s raised: %s", _slot, e)
                        last_civsnap[_slot] = today_str

            # Daily contract roll, 08:40 IST - after the SPAN refresh and twenty
            # minutes before MCX opens, so the gap falls where nobody is
            # watching. Every MCX instrument list (option spreads, metal and
            # other-commodity calendars, the NSE-vs-MCX strikes, the pair legs)
            # is resolved only when the socket connects, so a feed that stays
            # up serves an expired contract until something knocks it over.
            # This is one reconnect a day at a quiet hour, which is nothing
            # like the six-in-45-minutes that once cooled us down for 15 min.
            # Expiry-day roll (client, 31-Aug-2026): contracts stay current
            # until 23:00 of their own expiry day, so on a day when something
            # on the socket expires, one resubscribe at 23:00 walks the whole
            # board onto the next month. Other days: no resubscribe, no cost.
            if last_expiry_roll != today_str and (now.hour, now.minute) >= (23, 0):
                last_expiry_roll = today_str
                try:
                    if dhan_feed.has_expiring_today():
                        log.info("maintenance: 23:00 expiry-day roll -> resubscribe")
                        dhan_feed.request_resubscribe("expiry-day 23:00 roll")
                except Exception as e:  # noqa: BLE001
                    log.warning("maintenance: expiry roll failed: %s", e)

            if last_roll != today_str and (now.hour, now.minute) >= (8, 40):
                try:
                    log.info("Daily contract roll: %s",
                             dhan_feed.request_resubscribe("daily contract roll"))
                except Exception as e:
                    log.warning("Daily contract roll raised: %s", e)
                last_roll = today_str

            # Daily SPAN margin refresh — once per IST day at 08:30 IST (before market open).
            if last_span_refresh != today_str and (now.hour, now.minute) >= (8, 30):
                ok = span_service.refresh()
                last_span_refresh = today_str
                if ok:
                    log.info("SPAN margin feed refreshed for %s", today_str)

            # MCXCCL bullion warehouse-stock scrape + spread snapshot. MCXCCL
            # posts the daily PDF with an irregular lag, so a single fixed-time
            # run can silently miss data for days. Instead, from the morning
            # start hour we retry every MCXCCL_RETRY_HOURS until the stored data
            # has caught up to yesterday. refresh() walks back and backfills any
            # gap in one go. Isolated subprocess + fully wrapped → can never
            # affect the live feed/signals.
            if settings.BULLION_STOCK_ENABLED and (now.hour, now.minute) >= (
                settings.MCXCCL_FETCH_HOUR_IST, settings.MCXCCL_FETCH_MINUTE_IST
            ):
                target = (now.date() - timedelta(days=1)).isoformat()
                latest = mcxccl_service.latest_stored_date()
                caught_up = latest is not None and latest >= target
                due = (
                    last_mcxccl_attempt is None
                    or (now - last_mcxccl_attempt) >= timedelta(hours=settings.MCXCCL_RETRY_HOURS)
                )
                if not caught_up and due:
                    try:
                        mcxccl_service.refresh()
                    except Exception as e:
                        log.warning("MCXCCL refresh raised: %s", e)
                    last_mcxccl_attempt = now
        except Exception as e:
            log.exception("Maintenance error: %s", e)
        time.sleep(TICK_SECONDS)


def start_in_background() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="maintenance")
    t.start()
    return t
