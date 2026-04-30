"""In-memory live quote store. Updated by Dhan WebSocket worker."""
from dataclasses import dataclass
from threading import Lock


@dataclass
class Quote:
    bid: float = 0.0
    ask: float = 0.0
    ltp: float = 0.0
    timestamp: float = 0.0


class QuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._lock = Lock()

    def update(self, instrument: str, bid: float, ask: float, ltp: float, ts: float) -> None:
        with self._lock:
            self._quotes[instrument] = Quote(bid=bid, ask=ask, ltp=ltp, timestamp=ts)

    def get(self, instrument: str) -> Quote:
        with self._lock:
            return self._quotes.get(instrument, Quote())

    def all(self) -> dict[str, Quote]:
        with self._lock:
            return dict(self._quotes)


quote_store = QuoteStore()
