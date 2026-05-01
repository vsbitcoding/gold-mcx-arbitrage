"""In-memory live quote store with DB persistence so the dashboard never goes
blank across service restarts or market holidays.
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


PERSIST_THROTTLE_SECONDS = 30  # write to DB at most every 30s per instrument


class QuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._last_persist: dict[str, float] = {}
        self._lock = Lock()

    def update(self, instrument: str, bid: float, ask: float, ltp: float, ts: float) -> None:
        with self._lock:
            self._quotes[instrument] = Quote(bid=bid, ask=ask, ltp=ltp, timestamp=ts)
        # Persist throttled — only save non-zero quotes (don't overwrite good data with 0)
        if (bid or ask or ltp) and self._should_persist(instrument):
            self._persist(instrument, bid, ask, ltp)

    def _should_persist(self, instrument: str) -> bool:
        now = time.time()
        last = self._last_persist.get(instrument, 0)
        if now - last >= PERSIST_THROTTLE_SECONDS:
            self._last_persist[instrument] = now
            return True
        return False

    def _persist(self, instrument: str, bid: float, ask: float, ltp: float) -> None:
        try:
            from app.database import SessionLocal
            from app.models import LastQuote
            db = SessionLocal()
            try:
                row = db.query(LastQuote).filter(LastQuote.instrument == instrument).first()
                if row:
                    row.bid = bid
                    row.ask = ask
                    row.ltp = ltp
                else:
                    db.add(LastQuote(instrument=instrument, bid=bid, ask=ask, ltp=ltp))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            log.debug("persist failed: %s", e)

    def get(self, instrument: str) -> Quote:
        with self._lock:
            return self._quotes.get(instrument, Quote())

    def all(self) -> dict[str, Quote]:
        with self._lock:
            return dict(self._quotes)

    def restore_from_db(self) -> int:
        """Load last known quotes from DB into memory (called on startup)."""
        try:
            from app.database import SessionLocal
            from app.models import LastQuote
            db = SessionLocal()
            try:
                rows = db.query(LastQuote).all()
                with self._lock:
                    for r in rows:
                        self._quotes[r.instrument] = Quote(
                            bid=r.bid or 0,
                            ask=r.ask or 0,
                            ltp=r.ltp or 0,
                            timestamp=time.time(),
                        )
                return len(rows)
            finally:
                db.close()
        except Exception as e:
            log.warning("restore_from_db failed: %s", e)
            return 0


quote_store = QuoteStore()
