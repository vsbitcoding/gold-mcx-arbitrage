"""In-memory live quote store (keyed by security_id). Persists to DB so the
dashboard never goes blank across service restarts or market holidays.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

log = logging.getLogger("market_data")


@dataclass
class Quote:
    bid: float = 0.0
    ask: float = 0.0
    ltp: float = 0.0
    timestamp: float = 0.0


PERSIST_THROTTLE_SECONDS = 30


class QuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._last_persist: dict[str, float] = {}
        self._lock = Lock()

    def update(self, security_id: str, bid: float, ask: float, ltp: float, ts: float) -> None:
        sid = str(security_id)
        with self._lock:
            self._quotes[sid] = Quote(bid=bid, ask=ask, ltp=ltp, timestamp=ts)
        if (bid or ask or ltp) and self._should_persist(sid):
            self._persist(sid, bid, ask, ltp)

    def _should_persist(self, sid: str) -> bool:
        now = time.time()
        last = self._last_persist.get(sid, 0)
        if now - last >= PERSIST_THROTTLE_SECONDS:
            self._last_persist[sid] = now
            return True
        return False

    def _persist(self, sid: str, bid: float, ask: float, ltp: float) -> None:
        try:
            from app.database import SessionLocal
            from app.models import LastQuote
            db = SessionLocal()
            try:
                row = db.query(LastQuote).filter(LastQuote.instrument == sid).first()
                if row:
                    row.bid = bid; row.ask = ask; row.ltp = ltp
                else:
                    db.add(LastQuote(instrument=sid, bid=bid, ask=ask, ltp=ltp))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            log.debug("persist failed: %s", e)

    def get(self, security_id: str) -> Quote:
        with self._lock:
            return self._quotes.get(str(security_id), Quote())

    def all(self) -> dict[str, Quote]:
        with self._lock:
            return dict(self._quotes)

    def restore_from_db(self) -> int:
        try:
            from app.database import SessionLocal
            from app.models import LastQuote
            db = SessionLocal()
            try:
                rows = db.query(LastQuote).all()
                with self._lock:
                    for r in rows:
                        self._quotes[r.instrument] = Quote(
                            bid=r.bid or 0, ask=r.ask or 0, ltp=r.ltp or 0,
                            timestamp=time.time(),
                        )
                return len(rows)
            finally:
                db.close()
        except Exception as e:
            log.warning("restore_from_db failed: %s", e)
            return 0


quote_store = QuoteStore()
