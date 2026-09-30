"""Nifty/Sensex board history: the stored boards come back with both cards the
live screen shows - day change and the move since the previous day's 15:16."""
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-000")
os.environ.setdefault("ANGEL_ENABLED", "false")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.models import OptionsSnapshot  # noqa: E402
from app.services import options_history_service as hist  # noqa: E402

REF = {"ref_date": "2026-09-29", "ref_slot": "15:16", "nifty_ref": 22683.75, "sensex_ref": 72480.07,
       "nifty_change": -67.15, "sensex_change": -39.28, "sensex_expected_change": -214.88, "divergence": 175.6}


def board(ref=True):
    b = {"nifty_spot": 22616.6, "sensex_spot": 72440.79, "nifty_day_change": -99.6, "sensex_day_change": -88.3,
         "day_divergence": 230.4, "weeks": [{"week_index": 0, "rows": [{"nifty_strike": 22600, "sensex_strike": 72400,
                                                                        "nifty_ask": 120.0, "sensex_bid": 480.0}]}]}
    if ref:
        b["ref_divergence"] = dict(REF)
    return b


class OptionsHistoryTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        OptionsSnapshot.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        p = patch.object(hist, "SessionLocal", self.Session); p.start(); self.addCleanup(p.stop)
        hist._cache.clear()
        with self.Session() as db:
            db.add(OptionsSnapshot(snap_date="2026-09-30", slot="15:16", weekday=2, nifty_spot=22616.6, sensex_spot=72440.79,
                                   payload_json=json.dumps({"captured_at": "2026-09-30T15:16:04", "below": board(), "above": board()})))
            # a board from before 18-Aug-2026 never stored the reference
            db.add(OptionsSnapshot(snap_date="2026-08-10", slot="10:00", weekday=0, nifty_spot=24000.0, sensex_spot=79000.0,
                                   payload_json=json.dumps({"captured_at": "2026-08-10T10:00:04", "below": board(False), "above": board(False)})))
            db.commit()

    def test_both_cards_come_back_on_every_side(self):
        for side in ("below", "above", "squareoff"):
            with self.subTest(side=side):
                hist._cache.clear()
                s = hist.get_history(date="2026-09-30", side=side)["snapshots"][0]
                self.assertEqual(s["ref_divergence"], REF)
                self.assertEqual((s["day_divergence"], s["nifty_day_change"], s["sensex_day_change"]), (230.4, -99.6, -88.3))

    def test_old_board_has_no_reference_and_rows_are_unchanged(self):
        s = hist.get_history(date="2026-08-10")["snapshots"][0]
        self.assertIsNone(s["ref_divergence"])
        self.assertEqual(s["weeks"][0]["rows"][0]["nifty_strike"], 22600)
        hist._cache.clear()
        # the square-off board is still derived the same way (N ask x mult - S bid x mult)
        from app.services.options_service import NIFTY_MULT, SENSEX_MULT
        sq = hist.get_history(date="2026-09-30", side="squareoff")["snapshots"][0]["weeks"][0]["rows"][0]
        self.assertEqual((sq["nifty_leg"], sq["sensex_leg"]), (120.0, 480.0))
        self.assertEqual(sq["spread"], round(round(120.0 * NIFTY_MULT, 2) - round(480.0 * SENSEX_MULT, 2), 2))


if __name__ == "__main__":
    unittest.main()
