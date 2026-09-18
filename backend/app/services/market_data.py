"""In-memory live quote store (keyed by security_id). Persists to DB so the
dashboard never goes blank across service restarts or market holidays.

Persistence is batched: live ticks only touch the in-memory dict (synchronous,
under lock) and mark the security_id dirty. A single daemon writer thread
flushes ALL dirty quotes in ONE transaction every 30s — keeping DB writes off
the hot feed thread and collapsing ~6 inline writes/sec into 1 tx/30s.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

log = logging.getLogger("market_data")


@dataclass
class Quote:
    bid: float = 0.0
    ask: float = 0.0
    ltp: float = 0.0
    timestamp: float = 0.0
    # From Angel's snap-quote packet. Read by the crude IV chain.
    volume: float = 0.0
    oi: float = 0.0
    # Cached prices may be displayed after restart, but cannot price a trade
    # until this process has received an actual update for the contract.
    restored: bool = False


# Previous-day close per security_id, from the feed's quote packets.
# In-memory only; refreshed on every feed reconnect. Used for day-change /
# index-divergence displays.
prev_close_store: dict[str, float] = {}


PERSIST_INTERVAL_SECONDS = 30


class QuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._dirty: dict[str, tuple[float, float, float, float]] = {}
        self._lock = Lock()
        self._writer_started = False

    def update(self, security_id: str, bid: float, ask: float, ltp: float, ts: float,
               volume: float | None = None, oi: float | None = None) -> None:
        sid = str(security_id)
        with self._lock:
            prev = self._quotes.get(sid)
            self._quotes[sid] = Quote(
                bid=bid, ask=ask, ltp=ltp, timestamp=ts,
                volume=volume if volume is not None else (prev.volume if prev else 0.0),
                oi=oi if oi is not None else (prev.oi if prev else 0.0))
            # Empty books must also replace their saved predecessor. Otherwise
            # a restart resurrects the last nonempty bid/ask.
            self._dirty[sid] = (bid, ask, ltp, ts)  # newest value wins
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
            for sid, (bid, ask, ltp, ts) in pending.items():
                # Store the quote's time, not the later batch-flush time.
                updated_at = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
                row = existing.get(sid)
                if row:
                    row.bid = bid
                    row.ask = ask
                    row.ltp = ltp
                    row.updated_at = updated_at
                else:
                    db.add(LastQuote(instrument=sid, bid=bid, ask=ask, ltp=ltp,
                                     updated_at=updated_at))
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
                        saved = r.updated_at
                        stamp = (saved.replace(tzinfo=timezone.utc) if saved and saved.tzinfo is None
                                 else saved)
                        self._quotes[r.instrument] = Quote(
                            bid=r.bid or 0, ask=r.ask or 0, ltp=r.ltp or 0,
                            timestamp=stamp.timestamp() if stamp else 0.0,
                            restored=True,
                        )
                return len(rows)
            finally:
                db.close()
        except Exception as e:
            log.warning("restore_from_db failed: %s", e)
            return 0


quote_store = QuoteStore()


def quote_age(q: Quote, now: float | None = None) -> float | None:
    """Age of an observed quote; restored/unknown clocks are not live quotes."""
    now = time.time() if now is None else now
    ts = q.timestamp
    if q.restored or not ts or not math.isfinite(ts) or ts > now + 5:
        return None
    return max(0.0, now - ts)


def clean_sides(q) -> tuple:
    """(buyer, seller) fit to show, or None where no real one exists.

    Client rule (Dharmesh Bhai, 31-Aug-2026): where there is no buyer or
    seller, show a dash - the far-month ghosts made that concrete when a
    restored bid from one era met an ask from another and the May-2027 silver
    printed buyer 253,682 over seller 251,846. A crossed book cannot exist on
    an exchange, and there is no telling which side is the lie, so a crossed
    pair blanks BOTH sides. Zeros were already dashes.
    """
    bid = q.bid if q.bid and math.isfinite(q.bid) and q.bid > 0 else None
    ask = q.ask if q.ask and math.isfinite(q.ask) and q.ask > 0 else None
    if bid and ask and bid > ask:
        return None, None
    return bid, ask
