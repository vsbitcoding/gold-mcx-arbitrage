"""One-shot migration: divide existing TradeHistory.pnl values by 10.

Idempotent via marker file: creates `.pnl_div10_done` next to the SQLite DB
once it has run, and refuses to run again. Safe to invoke multiple times.

Usage (on the server):
    cd /home/vs.bitcoding/gold-mcx-arbitrage/backend
    venv/bin/python -m scripts.migrate_pnl_divide_by_10
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure we can import the app package when run as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import TradeHistory  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate_pnl")


def _marker_path() -> Path:
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        return Path(db_path).with_suffix(".pnl_div10_done")
    # Non-sqlite — fallback to local cwd marker
    return Path(".pnl_div10_done")


def main() -> int:
    marker = _marker_path()
    if marker.exists():
        log.info("Marker exists at %s — migration already applied. Skipping.", marker)
        return 0

    db = SessionLocal()
    try:
        rows = db.query(TradeHistory).all()
        n = len(rows)
        log.info("Updating %d trade_history rows: pnl /= 10", n)
        for r in rows:
            if r.pnl is not None:
                r.pnl = round(r.pnl / 10.0, 2)
        db.commit()
    finally:
        db.close()

    marker.write_text("done\n", encoding="utf-8")
    log.info("Done. Wrote marker %s", marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
