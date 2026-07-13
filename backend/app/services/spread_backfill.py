"""One-time spread-history backfill from Dhan daily closes (bullion pairs).

Client logic: % spread = spread ÷ small/near-leg value × 100, over the last
~6 months. There is no external source for our live bid/ask spread, so history
is reconstructed from each leg contract's DAILY CLOSE:

    spread(d) = close_big(d) × mult_big − close_small(d) × mult_small
    pct(d)    = spread(d) ÷ (close_small(d) × mult_small) × 100

Runs IN-PROCESS only — it reuses the live feed's token via
dhan_feed.get_live_token() (minting a standalone token would kill the feed).

Load profile: ONE run of ~10-20 REST calls (one per unique contract, paced),
then a single DB transaction. Existing live-snapshot rows are only "healed"
(pct filled in); their bid/ask point spreads are never touched. Today's date is
left to the normal 18:00 live snapshot.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import requests

from app.config import MULTIPLIERS, settings
from app.database import SessionLocal
from app.models import DailySpread

log = logging.getLogger("spread_backfill")

_lock = threading.Lock()
_status: dict = {"running": False, "msg": "never run", "at": None}

_HIST_URL = "https://api.dhan.co/v2/charts/historical"
_BULLION_KEYS = ("gold", "silver")


def status() -> dict:
    return dict(_status)


def _is_bullion(pair: dict) -> bool:
    blob = f"{pair.get('big', '')} {pair.get('small', '')}".lower()
    return any(k in blob for k in _BULLION_KEYS)


def _hist_closes(sid: str, token: str, days: int) -> tuple[dict[str, float] | None, str | None]:
    """date('YYYY-MM-DD') -> daily close for one MCX contract."""
    to = datetime.now().date()
    frm = to - timedelta(days=days + 7)
    try:
        r = requests.post(
            _HIST_URL,
            headers={"access-token": token, "client-id": settings.DHAN_CLIENT_ID,
                     "Content-Type": "application/json"},
            json={"securityId": str(sid), "exchangeSegment": "MCX_COMM",
                  "instrument": "FUTCOM",
                  "fromDate": frm.isoformat(), "toDate": to.isoformat()},
            timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"request error: {e}"
    if r.status_code != 200:
        return None, f"http {r.status_code}: {r.text[:120]}"
    d = r.json()
    out: dict[str, float] = {}
    for ts, close in zip(d.get("timestamp") or [], d.get("close") or []):
        try:
            if close:
                out[datetime.fromtimestamp(ts).date().isoformat()] = float(close)
        except (TypeError, ValueError, OSError):
            continue
    return out, None


def run(days: int = 185) -> None:
    """Fetch leg closes and upsert DailySpread rows. Sets _status; never raises."""
    from app.services import dhan_feed, mcxccl_service
    from app.services.pair_registry import get_pairs

    if not _lock.acquire(blocking=False):
        return
    _status.update(running=True, msg="running...", at=datetime.now().isoformat(timespec="seconds"))
    try:
        token = dhan_feed.get_live_token()
        if not token:
            _status.update(running=False, msg="no live token yet (feed not authenticated) - retry in a minute")
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
