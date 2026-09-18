"""Offline paper-ledger checks: no broker, socket, credentials or production DB.

Run from backend: python -m unittest discover -s tests -p 'test_bank_options_positions.py'
"""
import copy
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Import-time database configuration must never resolve a developer/server DB.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ANGEL_ENABLED"] = "false"
os.environ["IBKR_ENABLED"] = "false"
os.environ["IBKR_FEED_ENABLED"] = "false"
os.environ["PREMIUM_FEED_ENABLED"] = "false"

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models import BankOptionPosition, User  # noqa: E402
from app.services import bank_options_positions as positions  # noqa: E402


class BankOptionsPositionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bank-position-test-")
        self.addCleanup(self.temp.cleanup)
        self.engine = create_engine(f"sqlite:///{self.temp.name}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        BankOptionPosition.__table__.create(self.engine)
        # Positions belong to a permanent user id, not a name (review 18-Sep):
        # the ledger looks the owner up in the users table.
        User.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.Session() as db:
            db.add_all([User(username=name, password_hash="x", role="admin") for name in ("alice", "bob")])
            db.commit()
        self.patch_session = patch.object(positions, "SessionLocal", self.Session)
        self.patch_session.start()
        self.addCleanup(self.patch_session.stop)
        self.now = datetime(2026, 9, 18, 5, 0, tzinfo=timezone.utc)
        self.clock = patch.object(positions, "_now", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.bankex = {
            "security_id": "BFO:100", "exchange": "BFO", "trading_symbol": "BANKEX-64000-CE",
            "strike": 64000, "expiry": "2026-09-24", "lot_size": 30,
            "bid": 99.75, "ask": 101.25, "ltp": 99999, "age_seconds": 1,
            "volume": 50, "oi": 100, "fresh": True,
        }
        self.banknifty = {
            "security_id": "NFO:200", "exchange": "NFO", "trading_symbol": "BANKNIFTY-56700-CE",
            "strike": 56700, "expiry": "2026-09-29", "lot_size": 30,
            "bid": 121.1, "ask": 122.5, "ltp": 99999, "age_seconds": 1,
            "volume": 80, "oi": 200, "fresh": True,
        }
        self.quotes = {"BFO:100": self.bankex, "NFO:200": self.banknifty}
        self.live = SimpleNamespace(
            market_is_open=Mock(return_value=True),
            get_entry_pair=Mock(side_effect=lambda *args: {
                "side": args[2], "bankex": copy.deepcopy(self.bankex),
                "banknifty": copy.deepcopy(self.banknifty), "buy_index": "BANKEX",
                "sell_index": "BANKNIFTY", "market_open": True, "tradable": True, "reason": None,
            }),
            quote_leg=Mock(side_effect=lambda leg: copy.deepcopy(self.quotes.get(leg["security_id"], {}))),
        )
        self.patch_live = patch.object(positions, "_live", return_value=self.live)
        self.patch_live.start()
        self.addCleanup(self.patch_live.stop)

    def create(self, user="alice", request_id="request-1", **kwargs):
        values = {
            "username": user, "bankex_security_id": "BFO:100", "banknifty_security_id": "NFO:200",
            "side": "CE", "bankex_lots": 2, "banknifty_lots": 3, "request_id": request_id,
        }
        values.update(kwargs)
        return positions.create_position(**values)

    def test_entry_uses_ask_and_bid_and_marks_at_opposite_sides(self):
        p = self.create()
        self.assertEqual(p["buy_index"], "BANKEX")
        self.assertEqual(p["sell_index"], "BANKNIFTY")
        self.assertEqual(p["bankex"]["entry_price"], 101.25)
        self.assertEqual(p["banknifty"]["entry_price"], 121.1)
        self.assertEqual(p["bankex"]["quantity"], 60)
        self.assertEqual(p["banknifty"]["quantity"], 90)
        self.assertEqual(p["entry_credit_rupees"], 4824)
        self.assertEqual(p["pnl_rupees"], -216)
        self.assertEqual(p["bankex"]["current_price"], 99.75)
        self.assertEqual(p["banknifty"]["current_price"], 122.5)
        self.assertTrue(p["can_close"])
        self.assertTrue(p["created_at"].endswith("+00:00"))

    def test_direction_follows_expiry_and_contract_lot_sizes(self):
        self.bankex.update(expiry="2026-10-29", lot_size=20)
        self.banknifty.update(expiry="2026-10-27", lot_size=15)
        p = self.create(side="PE")
        self.assertEqual(p["buy_index"], "BANKNIFTY")
        self.assertEqual(p["sell_index"], "BANKEX")
        self.assertEqual(p["bankex"]["entry_price"], 99.75)
        self.assertEqual(p["banknifty"]["entry_price"], 122.5)
        self.assertEqual(p["bankex"]["quantity"], 40)
        self.assertEqual(p["banknifty"]["quantity"], 45)
        self.assertEqual(p["pnl_rupees"], -123)

    def test_saved_contract_and_quantities_survive_atm_and_master_changes(self):
        p = self.create()
        # Live quote dictionaries now contain a different strike/lot definition.
        self.bankex.update(strike=65000, lot_size=50, bid=110, ask=111)
        self.banknifty.update(strike=57700, lot_size=60, bid=114, ask=115)
        latest = positions.list_positions("alice")["positions"][0]
        self.assertEqual(latest["bankex"]["strike"], 64000)
        self.assertEqual(latest["banknifty"]["strike"], 56700)
        self.assertEqual(latest["bankex"]["quantity"], 60)
        self.assertEqual(latest["banknifty"]["quantity"], 90)
        self.assertEqual(latest["pnl_rupees"], 1074)
        subscriptions = positions.get_subscription_meta()
        self.assertEqual(set(subscriptions), {"BFO:100", "NFO:200"})
        self.assertEqual(subscriptions["BFO:100"]["strike"], 64000)
        self.assertEqual(subscriptions["NFO:200"]["exch"], "NFO")
        closed = positions.close_position("alice", p["id"])
        self.assertEqual(closed["pnl_rupees"], 1074)
        self.assertEqual(closed["bankex"]["exit_price"], 110)
        self.assertEqual(closed["banknifty"]["exit_price"], 115)
        self.assertEqual(positions.get_subscription_meta(), {})

    def test_entry_rejects_stale_missing_crossed_or_invalid_quotes(self):
        for change in ({"age_seconds": 60.001}, {"age_seconds": -1}, {"fresh": False},
                       {"bid": 0}, {"ask": None}, {"bid": 103, "ask": 102},
                       {"ask": float("nan")}, {"bid": True}, {"lot_size": 0}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.bankex)
                self.bankex.update(change)
                with self.assertRaises(ValueError):
                    self.create()
                self.bankex.clear()
                self.bankex.update(original)
        self.assertEqual(positions.list_positions("alice")["positions"], [])
        self.bankex["age_seconds"] = 60
        self.assertEqual(self.create()["status"], "open")

    def test_market_closed_or_equal_expiry_cannot_open(self):
        self.live.market_is_open.return_value = False
        with self.assertRaisesRegex(ValueError, "markets must be open"):
            self.create()
        self.live.market_is_open.return_value = True
        self.banknifty["expiry"] = self.bankex["expiry"]
        with self.assertRaisesRegex(ValueError, "Equal expiries"):
            self.create()

    def test_lots_bounds_and_request_id_validation(self):
        for value in (0, 101, 1.5, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.create(bankex_lots=value)
        for request_id in ("", "   ", "x" * 81):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                self.create(request_id=request_id)

    def test_idempotency_and_conflicting_reuse(self):
        first = self.create()
        self.live.market_is_open.return_value = False
        second = self.create()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.live.get_entry_pair.call_count, 1)
        with self.assertRaisesRegex(ValueError, "different position"):
            self.create(banknifty_lots=1)
        self.assertEqual(len(positions.list_positions("alice")["positions"]), 1)

    def test_ownership_and_request_ids_are_per_user(self):
        alice = self.create()
        bob = self.create(user="bob")
        self.assertNotEqual(alice["id"], bob["id"])
        self.assertEqual(len(positions.list_positions("alice")["positions"]), 1)
        self.assertEqual(len(positions.list_positions("bob")["positions"]), 1)
        with self.assertRaises(LookupError):
            positions.close_position("bob", alice["id"])
        with self.assertRaises(LookupError):
            positions.close_position("alice", 999)

    def test_stale_or_missing_marks_are_null_and_cannot_close(self):
        first = self.create()
        self.bankex["age_seconds"] = 61
        response = positions.list_positions("alice")
        self.assertIsNone(response["positions"][0]["pnl_rupees"])
        self.assertIsNone(response["summary"]["open_pnl_rupees"])
        self.assertFalse(response["positions"][0]["can_close"])
        with self.assertRaises(ValueError):
            positions.close_position("alice", first["id"])
        self.quotes.clear()
        self.assertIsNone(positions.list_positions("alice")["positions"][0]["pnl_rupees"])
        with self.assertRaises(ValueError):
            positions.close_position("alice", first["id"])

    def test_market_closed_cannot_close_even_with_fresh_quotes(self):
        first = self.create()
        self.live.market_is_open.return_value = False
        self.assertFalse(positions.list_positions("alice")["positions"][0]["can_close"])
        with self.assertRaises(ValueError):
            positions.close_position("alice", first["id"])

    def test_expiry_disables_trading_without_invented_settlement(self):
        first = self.create()
        self.now = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)  # 15:30 IST
        result = positions.list_positions("alice")
        expired = result["positions"][0]
        self.assertEqual(expired["status"], "expired")
        self.assertIsNone(expired["closed_at"])
        self.assertIsNone(expired["pnl_rupees"])
        self.assertFalse(expired["can_close"])
        self.assertEqual(result["summary"]["expired"], 1)
        self.assertEqual(result["summary"]["realised_pnl_rupees"], 0)
        self.assertEqual(positions.get_subscription_meta(), {})
        with self.assertRaises(ValueError):
            positions.close_position("alice", first["id"])
        with self.assertRaisesRegex(ValueError, "Expired contracts"):
            self.create(request_id="expired-attempt")

    def test_close_is_idempotent_and_realised_pnl_is_persisted(self):
        first = self.create()
        self.bankex.update(bid=110, ask=111)
        self.banknifty.update(bid=114, ask=115)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: positions.close_position("alice", first["id"]), range(4)))
        self.assertTrue(all(p["status"] == "closed" and p["pnl_rupees"] == 1074 for p in results))
        self.assertEqual(len({p["closed_at"] for p in results}), 1)
        self.bankex.update(bid=1, ask=2, fresh=False)
        self.live.market_is_open.return_value = False
        response = positions.list_positions("alice")
        self.assertEqual(response["positions"][0]["pnl_rupees"], 1074)
        self.assertEqual(response["summary"]["realised_pnl_rupees"], 1074)
        self.assertEqual(response["summary"]["open"], 0)
        self.assertEqual(response["summary"]["closed"], 1)

    def test_decimal_money_has_no_binary_float_artifacts(self):
        self.bankex.update(bid=0.09, ask=0.1)
        self.banknifty.update(bid=0.3, ask=0.31)
        p = self.create(bankex_lots=1, banknifty_lots=1)
        self.assertEqual(p["entry_credit_rupees"], 6)
        self.assertEqual(p["pnl_rupees"], -0.6)
        self.bankex.update(bid=0.2, ask=0.21)
        self.banknifty.update(bid=0.19, ask=0.2)
        self.assertEqual(positions.close_position("alice", p["id"])["pnl_rupees"], 6)


if __name__ == "__main__":
    unittest.main()
