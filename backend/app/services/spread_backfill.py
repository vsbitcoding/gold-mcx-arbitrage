"""One-time spread-history backfill from daily closes (bullion pairs).

Client logic: % spread = spread ÷ small/near-leg value × 100, over the last
~6 months. There is no external source for our live bid/ask spread, so history
is reconstructed from each leg contract's DAILY CLOSE:

    spread(d) = close_big(d) × mult_big − close_small(d) × mult_small
    pct(d)    = spread(d) ÷ (close_small(d) × mult_small) × 100

Closes come from Angel's candle API (ONE_DAY), paced, on the feed's own
daily session.

Load profile: ONE run of ~10-20 REST calls (one per unique contract, paced),
then a single DB transaction. Existing live-snapshot rows are only "healed"
(pct filled in); their bid/ask point spreads are never touched. Today's date is
left to the normal 18:00 live snapshot.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from app.config import MULTIPLIERS
from app.database import SessionLocal
from app.models import DailySpread

log = logging.getLogger("spread_backfill")

_lock = threading.Lock()
_status: dict = {"running": False, "msg": "never run", "at": None}

_BULLION_KEYS = ("gold", "silver")


def status() -> dict:
    return dict(_status)


def _is_bullion(pair: dict) -> bool:
    blob = f"{pair.get('big', '')} {pair.get('small', '')}".lower()
    return any(k in blob for k in _BULLION_KEYS)


def _hist_closes(sid: str, token: str, days: int) -> tuple[dict[str, float] | None, str | None]:
    """date('YYYY-MM-DD') -> daily close for one MCX contract. A late-listed far
    month simply returns the days it has."""
    from app.services import angel_history
    try:
        rows = angel_history.candles(sid, days + 7, "ONE_DAY")
    except Exception as e:  # noqa: BLE001
        return None, f"request error: {e}"
    out: dict[str, float] = {}
    for row in rows:
        try:
            if row[4]:
                out[str(row[0])[:10]] = float(row[4])
        except (TypeError, ValueError, IndexError):
            continue
    return (out, None) if out else (None, "empty response")


def run(days: int = 185) -> None:
    """Fetch leg closes and upsert DailySpread rows. Sets _status; never raises."""
    from app.services import live_feed, mcxccl_service
    from app.services.pair_registry import get_pairs

    if not _lock.acquire(blocking=False):
        return
    _status.update(running=True, msg="running...", at=datetime.now().isoformat(timespec="seconds"))
    try:
        token = live_feed.history_token()
        if not token:
            _status.update(running=False, msg="no live session yet (feed not authenticated) - retry in a minute")
            return

        pairs = [p for p in get_pairs() if _is_bullion(p)]
        if not pairs:
            _status.update(running=False, msg="no bullion pairs resolved")
            return

        # 1) fetch closes once per unique contract (paced - tiny, one-time)
        sids = {p["big_security_id"] for p in pairs} | {p["small_security_id"] for p in pairs}
        closes: dict[str, dict[str, float]] = {}
        errs: list[str] = []
        for sid in sids:
            data, err = _hist_closes(sid, token, days)
            if data:
                closes[sid] = data
            else:
                errs.append(f"{sid}:{err}")
            time.sleep(0.4)

        # 2) build per-pair daily spread% and upsert
        today = datetime.now().date().isoformat()
        names = [p["name"] for p in pairs]
        db = SessionLocal()
        inserted = healed = 0
        try:
            existing = {
                (r.snap_date, r.pair_name): r
                for r in db.query(DailySpread).filter(DailySpread.pair_name.in_(names)).all()
            }
            for p in pairs:
                cb = closes.get(p["big_security_id"]) or {}
                cs = closes.get(p["small_security_id"]) or {}
                mb = MULTIPLIERS.get(p["big"], 1.0)
                ms = MULTIPLIERS.get(p["small"], 1.0)
                for d in sorted(set(cb) & set(cs)):
                    if d >= today:      # today belongs to the live 18:00 snapshot
                        continue
                    small_v = cs[d] * ms
                    if not small_v:
                        continue
                    spread = round(cb[d] * mb - small_v, 4)
                    pct = round(spread / small_v * 100, 4)
                    row = existing.get((d, p["name"]))
                    if row is not None:
                        if row.decrease_pct is None and row.increase_pct is None:
                            row.decrease_pct = pct   # heal old point-only rows
                            healed += 1
                    else:
                        db.add(DailySpread(snap_date=d, pair_name=p["name"],
                                           decrease_spread=spread, decrease_pct=pct))
                        inserted += 1
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            _status.update(running=False, msg=f"store error: {e}")
            return
        finally:
            db.close()

        mcxccl_service._report_cache["data"] = None  # dashboard picks up new history
        msg = (f"done: {len(pairs)} pairs, {len(closes)}/{len(sids)} contracts, "
               f"+{inserted} rows, {healed} healed" + (f", errors: {errs[:3]}" if errs else ""))
        _status.update(running=False, msg=msg)
        log.info("Spread backfill %s", msg)
    finally:
        _lock.release()


def start(days: int = 185) -> bool:
    """Spawn the backfill in a daemon thread (no-op if already running)."""
    if _status["running"]:
        return False
    threading.Thread(target=run, args=(days,), daemon=True, name="spread-backfill").start()
    return True
