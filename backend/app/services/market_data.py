"""In-memory live quote store (keyed by security_id). Persists to DB so the
dashboard never goes blank across service restarts or market holidays.

Persistence is batched: live ticks only touch the in-memory dict (synchronous,
under lock) and mark the security_id dirty. A single daemon writer thread
flushes ALL dirty quotes in ONE transaction every 30s — keeping DB writes off
the hot Dhan feed thread and collapsing ~6 inline writes/sec into 1 tx/30s.
"""
from __future__ import annotations

import logging
import threading
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


# Previous-day close per security_id, from Dhan's one-shot "Previous Close"
# packet sent at (re)subscribe time. In-memory only; refreshed on every feed
# reconnect. Used for day-change / index-divergence displays.
prev_close_store: dict[str, float] = {}


PERSIST_INTERVAL_SECONDS = 30


class QuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._dirty: dict[str, tuple[float, float, float]] = {}  # sid -> (bid, ask, ltp) pending write
        self._lock = Lock()
        self._writer_started = False

    def update(self, security_id: str, bid: float, ask: float, ltp: float, ts: float) -> None:
        sid = str(security_id)
        with self._lock:
            self._quotes[sid] = Quote(bid=bid, ask=ask, ltp=ltp, timestamp=ts)
            if bid or ask or ltp:
                self._dirty[sid] = (bid, ask, ltp)  # newest value wins
        self._ensure_writer()

    # ── batched persistence ──────────────────────────────────────────────
    def _ensure_writer(self) -> None:
        if self._writer_started:
            return
        with self._lock:
            if self._writer_started:
                return
            self._writer_started = True
        t = threading.Thread(target=self._writer_loop, name="quote-persist", daemon=True)
        t.start()

    def _writer_loop(self) -> None:
        while True:
            time.sleep(PERSIST_INTERVAL_SECONDS)
            try:
                self._flush_dirty()
            except Exception as e:  # never let the writer thread die
                log.warning("quote persist flush failed: %s", e)

    def _flush_dirty(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            pending = dict(self._dirty)
            self._dirty.clear()

        from app.database import SessionLocal
        from app.models import LastQuote
        db = SessionLocal()
        try:
            sids = list(pending.keys())
            existing = {
                row.instrument: row
                for row in db.query(LastQuote).filter(LastQuote.instrument.in_(sids)).all()
            }
            for sid, (bid, ask, ltp) in pending.items():
                row = existing.get(sid)
                if row:
                    row.bid = bid
                    row.ask = ask
                    row.ltp = ltp
                else:
                    db.add(LastQuote(instrument=sid, bid=bid, ask=ask, ltp=ltp))
            db.commit()
        except Exception:
            db.rollback()
            # Re-queue the failed batch so the next cycle retries it (newer ticks win).
            with self._lock:
                for sid, v in pending.items():
                    self._dirty.setdefault(sid, v)
            raise
        finally:
            db.close()

    # ── reads ────────────────────────────────────────────────────────────
    # (clean_sides lives at module level below)
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


def clean_sides(q) -> tuple:
    """(buyer, seller) fit to show, or None where no real one exists.

    Client rule (Dharmesh Bhai, 31-Aug-2026): where there is no buyer or
    seller, show a dash - the far-month ghosts made that concrete when a
    restored bid from one era met an ask from another and the May-2027 silver
    printed buyer 253,682 over seller 251,846. A crossed book cannot exist on
    an exchange, and there is no telling which side is the lie, so a crossed
    pair blanks BOTH sides. Zeros were already dashes.
    """
    bid = q.bid or None
    ask = q.ask or None
    if bid and ask and bid > ask:
        return None, None
    return bid, ask
