"""Offline contract, quote and API checks for the bank-index board."""
import copy
import os
import unittest
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ANGEL_ENABLED"] = "false"
os.environ["IBKR_ENABLED"] = "false"
os.environ["IBKR_FEED_ENABLED"] = "false"
os.environ["PREMIUM_FEED_ENABLED"] = "false"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.security import get_current_user
from app.services import angel_master, bank_options_service as live
from app.services.market_data import Quote, QuoteStore
from app.routes import bank_options


def master_contract(index, strike, side, expiry="24SEP2026", token=None, lot=30):
    return {"name": index, "exch_seg": "BFO" if index == "BANKEX" else "NFO",
            "instrumenttype": "OPTIDX", "token": token or f"{index}-{strike}-{side}-{expiry}",
            "symbol": f"{index}{strike}{side}", "strike": str(strike * 100),
            "lotsize": str(lot), "expiry": expiry}


class BankOptionsLiveTests(unittest.TestCase):
    def setUp(self):
        self.old_state = copy.deepcopy(live._state)
        self.old_seen = dict(live._live_seen)
        self.addCleanup(lambda: (live._state.clear(), live._state.update(self.old_state),
                                 live._live_seen.clear(), live._live_seen.update(self.old_seen)))
        live._live_seen.clear()
        self.now = datetime(2026, 9, 18, 10, 30, tzinfo=live.IST)
        self.epoch = self.now.timestamp()
        self.quotes = QuoteStore()
        self.quotes._writer_started = True
        for name, value in (("quote_store", self.quotes),):
            p = patch.object(live, name, value)
            p.start(); self.addCleanup(p.stop)
        for target, kw in (("_now", {"side_effect": lambda: self.now}),
                           ("market_is_open", {"return_value": True})):
            p = patch.object(live, target, **kw)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(live.time, "time", side_effect=lambda: self.epoch)
        p.start(); self.addCleanup(p.stop)
        self.master = []
        for index, base, expiry in (("BANKEX", 63500, "24SEP2026"),
                                     ("BANKNIFTY", 56200, "29SEP2026")):
            for offset in range(-5000, 5100, 100):
                for side in ("CE", "PE"):
                    self.master.append(master_contract(index, base + offset, side, expiry))
            self.tick(live.INDEX_IDS[index], base, base, base)
        self.reload()
        for index, contracts in live._state["contracts"].items():
            for meta in contracts.values():
                self.tick(meta["security_id"], 99 if index == "BANKEX" else 130,
                          100 if index == "BANKEX" else 132, volume=100)

    def reload(self):
        csv_text, _ = angel_master.build_csv(self.master)
        with patch.object(live, "_download_csv", return_value=csv_text):
            live.refresh()
        live.set_subscribed(live.get_subscription_meta())

    def tick(self, sid, bid, ask, ltp=9999, volume=0, age=0, live_tick=True):
        self.quotes.update(sid, bid, ask, ltp, self.epoch - age, volume=volume, oi=100)
        if live_tick:
            live.note_live_tick(sid, self.epoch - age)

    def row(self, side, offset, **kwargs):
        return next(r for r in live.get_live(**kwargs)["rows"]
                    if r["side"] == side and r["offset_points"] == offset)

    def test_handwritten_ce_and_pe_pairing(self):
        expected = [("CE", 500, 64000, 56700), ("CE", 1000, 64500, 57200),
                    ("PE", -500, 63000, 55700), ("PE", -1000, 62500, 55200)]
        for side, offset, be, bn in expected:
            with self.subTest(side=side, offset=offset):
                row = self.row(side, offset)
                self.assertEqual((row["bankex"]["strike"], row["banknifty"]["strike"]), (be, bn))
                # BANKEX (24-Sep) expires first: it is SOLD at bid, BANKNIFTY bought at ask
                self.assertEqual(row["buy_index"], "BANKNIFTY")
                self.assertEqual(row["buy_price"], 132)
                self.assertEqual(row["sell_price"], 99)
                self.assertTrue(row["tradable"])

    def test_fixed_fifteen_strikes_offer_ce_and_pe_on_both_sides(self):
        expected_strikes = [60000, 60500, 61000, 61500, 62000, 62500, 63000, 63500,
                            64000, 64500, 65000, 65500, 66000, 66500, 67000]
        expected_offsets = [-3500, -3000, -2500, -2000, -1500, -1000, -500, 0,
                            500, 1000, 1500, 2000, 2500, 3000, 3500]
        # Legacy ranges cannot add 100-point strikes or resize the client window.
        for legacy_range in (100, 1000, 2000, 3000, 3500):
            with self.subTest(range_points=legacy_range):
                result = live.get_live(range_points=legacy_range)
                self.assertEqual(result["bankex_strikes"], expected_strikes)
                self.assertEqual(len(result["rows"]), 30)
                self.assertEqual(result["counts"], {"candidates": 30, "shown": 30, "filtered": 0})
                self.assertEqual(len({row["id"] for row in result["rows"]}), 30)
                self.assertEqual(result["window"], {"strike_step": 500,
                                                   "strikes_each_side": 7, "strike_count": 15})
                for side in ("CE", "PE"):
                    rows = [row for row in result["rows"] if row["side"] == side]
                    self.assertEqual([row["offset_points"] for row in rows], expected_offsets)
                    self.assertEqual([row["bankex"]["strike"] for row in rows], expected_strikes)
                    self.assertEqual([row["banknifty"]["strike"] for row in rows],
                                     [56200 + offset for offset in expected_offsets])
        for side in ("CE", "PE"):
            result = live.get_live(side=side)
            self.assertEqual(len(result["rows"]), 15)
            self.assertEqual({row["side"] for row in result["rows"]}, {side})
            self.assertEqual(result["bankex_strikes"], expected_strikes)

    def test_missing_contract_keeps_its_exact_slot_unpriced(self):
        original = live.get_live()
        for index, strike, side in (("BANKEX", 64500, "CE"), ("BANKNIFTY", 55200, "PE")):
            del live._state["contracts"][index][(strike, side)]
        result = live.get_live()
        self.assertEqual(result["bankex_strikes"], original["bankex_strikes"])
        self.assertEqual([row["id"] for row in result["rows"]],
                         [row["id"] for row in original["rows"]])
        self.assertEqual(len(result["rows"]), 30)
        for index, strike, side, offset in (("BANKEX", 64500, "CE", 1000),
                                           ("BANKNIFTY", 55200, "PE", -1000)):
            with self.subTest(index=index):
                row = self.row(side, offset)
                leg = row[index.lower()]
                self.assertEqual((leg["strike"], leg["side"]), (strike, side))
                self.assertIsNone(leg["security_id"])
                self.assertIsNone(leg["lot_size"])
                self.assertIsNone(leg["bid"])
                self.assertIsNone(leg["ask"])
                self.assertFalse(row["tradable"])
                self.assertIn(f"Matching {index} strike is not listed", row["reason"])
                self.assertIsNone(row["display_value"])
                self.assertIsNone(row["value_rupees"])
                old_row = next(r for r in original["rows"]
                               if r["side"] == side and r["offset_points"] == offset)
                with self.assertRaisesRegex(ValueError, "no longer available"):
                    live.get_entry_pair(old_row["bankex"]["security_id"],
                                        old_row["banknifty"]["security_id"], side)

    def test_divisor_does_not_change_lots_or_rupee_credit(self):
        row = self.row("CE", 500, bankex_lots=2, banknifty_lots=3)
        # sell BANKEX bid 99, buy BANKNIFTY ask 132: 99 - 132; rupees 99*30*2 - 132*30*3
        self.assertEqual(row["difference_points"], -33)
        self.assertEqual(row["difference_divided"], -1.1)
        self.assertEqual(row["value_rupees"], -5940)
        self.assertEqual(row["display_value"], -1.1)
        changed = self.row("CE", 500, divisor=15, bankex_lots=2, banknifty_lots=3)
        self.assertEqual(changed["display_value"], -2.2)
        self.assertEqual(changed["value_rupees"], -5940)
        rupees = self.row("CE", 500, metric="rupees", bankex_lots=2, banknifty_lots=3)
        self.assertEqual(rupees["display_value"], -5940)

    def test_reverse_expiry_reverses_prices(self):
        for meta in live._state["contracts"]["BANKEX"].values():
            meta["expiry"] = "2026-10-29"
        live._state["expiries"]["BANKEX"] = "2026-10-29"
        row = self.row("CE", 500)
        # BANKNIFTY (29-Sep) now expires first: sold at bid 130, BANKEX bought at ask 100
        self.assertEqual((row["buy_index"], row["sell_index"]), ("BANKEX", "BANKNIFTY"))
        self.assertEqual((row["buy_price"], row["sell_price"]), (100, 130))
        self.assertEqual(row["difference_points"], 30)

    def test_atm_moves_from_real_spots_and_old_clicked_pair_revalidates(self):
        old = self.row("CE", 500)
        self.tick(live.INDEX_IDS["BANKEX"], 63610, 63610, 63610)
        latest = self.row("CE", 500)
        self.assertEqual(latest["bankex"]["strike"], 64000)
        # 64000 is 390 above BANKEX spot 63610 -> BANKNIFTY 56200 + 390 = 56590 -> 56600
        self.assertEqual(latest["banknifty"]["strike"], 56600)
        self.assertEqual(live.get_live()["indices"]["BANKEX"]["atm"], 63500)
        # the pair clicked at spot 63500 (56700) no longer matches by points
        with self.assertRaisesRegex(ValueError, "matching BANKNIFTY strike changed"):
            live.get_entry_pair(old["bankex"]["security_id"], old["banknifty"]["security_id"], "CE")
        self.assertTrue(live.get_entry_pair(latest["bankex"]["security_id"],
                                            latest["banknifty"]["security_id"], "CE")["tradable"])
        self.tick(live.INDEX_IDS["BANKEX"], 63750, 63750, 63750)
        self.assertEqual(live.get_live()["indices"]["BANKEX"]["atm"], 64000)
        self.assertEqual(self.row("CE", 500)["bankex"]["strike"], 64500)
        with self.assertRaisesRegex(ValueError, "matching BANKNIFTY strike changed"):
            live.get_entry_pair(old["bankex"]["security_id"], old["banknifty"]["security_id"], "CE")

    def test_banknifty_keeps_its_own_100_point_atm(self):
        self.tick(live.INDEX_IDS["BANKNIFTY"], 56250, 56250, 56250)
        result = live.get_live()
        self.assertEqual(result["indices"]["BANKEX"]["atm"], 63500)
        self.assertEqual(result["indices"]["BANKNIFTY"]["atm"], 56300)
        self.assertEqual(self.row("CE", -500)["banknifty"]["strike"], 55800)
        self.assertEqual(self.row("PE", 500)["banknifty"]["strike"], 56800)

    def test_atm_uses_an_actual_listed_eligible_strike(self):
        for side in ("CE", "PE"):
            del live._state["contracts"]["BANKEX"][(63500, side)]
        # 63400/63600 are listed, but cannot serve as this board's BANKEX ATM.
        result = live.get_live()
        self.assertEqual(result["indices"]["BANKEX"]["atm"], 64000)
        missing = self.row("CE", -500)
        self.assertEqual(missing["bankex"]["strike"], 63500)
        self.assertIsNone(missing["bankex"]["security_id"])

    def test_entry_accepts_both_option_types_on_both_sides_but_enforces_grid(self):
        for side, offset in (("CE", -500), ("PE", 500), ("CE", 3500), ("PE", -3500)):
            row = self.row(side, offset)
            self.assertTrue(live.get_entry_pair(row["bankex"]["security_id"],
                                                row["banknifty"]["security_id"], side)["tradable"])
        for offset, message in ((100, "500-point strike"), (4000, "fifteen-strike ATM window"),
                                (-4000, "fifteen-strike ATM window")):
            with self.subTest(offset=offset):
                be = live._state["contracts"]["BANKEX"][(63500 + offset, "CE")]
                bn = live._state["contracts"]["BANKNIFTY"][(56200 + offset, "CE")]
                with self.assertRaisesRegex(ValueError, message):
                    live.get_entry_pair(be["security_id"], bn["security_id"], "CE")

    def test_never_guess_missing_spot(self):
        self.quotes._quotes.pop(live.INDEX_IDS["BANKEX"])
        result = live.get_live()
        self.assertIsNone(result["indices"]["BANKEX"]["atm"])
        self.assertEqual(result["rows"], [])
        self.assertFalse(result["status"]["ready"])

    def test_liquidity_flags_quotes_without_hiding_default_window(self):
        row = self.row("CE", 500)
        self.assertTrue(row["liquid"])
        sid = row["bankex"]["security_id"]
        self.tick(sid, 50, 100, volume=1000)
        self.assertEqual(len(live.get_live()["rows"]), 30)
        all_row = self.row("CE", 500)
        self.assertFalse(all_row["liquid"])
        self.assertGreater(all_row["bankex_spread_pct"], 10)
        self.assertIn("spread", all_row["liquidity_reason"])
        self.assertFalse(any(r["id"] == row["id"] for r in live.get_live(liquidity="liquid")["rows"]))
        self.tick(sid, 99, 100, volume=0)
        self.assertFalse(self.row("CE", 500)["liquid"])
        self.assertIn("volume", self.row("CE", 500)["liquidity_reason"])
        self.tick(sid, 99, 100, volume=100, age=61)
        stale = self.row("CE", 500)
        self.assertEqual(len(live.get_live()["rows"]), 30)
        self.assertFalse(stale["liquid"])
        self.assertFalse(stale["tradable"])
        self.assertIsNone(stale["display_value"])

    def test_stale_missing_crossed_books_never_create_spread_or_position(self):
        row = self.row("CE", 500)
        sid = row["banknifty"]["security_id"]
        for bid, ask, age in ((130, 132, 61), (0, 132, 0), (140, 132, 0)):
            with self.subTest(bid=bid, ask=ask, age=age):
                self.tick(sid, bid, ask, volume=100, age=age)
                changed = self.row("CE", 500, liquidity="all")
                self.assertFalse(changed["tradable"])
                self.assertIsNone(changed["display_value"])
                with self.assertRaises(ValueError):
                    live.get_entry_pair(row["bankex"]["security_id"], sid, "CE")

    def test_restored_quotes_cannot_be_fresh_or_executable(self):
        row = self.row("CE", 500)
        live._live_seen.pop(row["bankex"]["security_id"])
        changed = self.row("CE", 500, liquidity="all")
        self.assertFalse(changed["bankex"]["fresh"])
        self.assertFalse(changed["tradable"])
        self.assertIsNone(changed["difference_points"])

    def test_closed_market_equal_expiry_or_missing_subscription_blocks_entries(self):
        with patch.object(live, "market_is_open", return_value=False):
            self.assertFalse(self.row("CE", 500)["tradable"])
        live._state["expiries"]["BANKEX"] = live._state["expiries"]["BANKNIFTY"]
        self.assertIsNone(self.row("CE", 500)["buy_index"])
        self.assertIsNone(self.row("CE", 500)["difference_points"])
        live._state["expiries"]["BANKEX"] = "2026-09-24"
        sid = self.row("CE", 500)["banknifty"]["security_id"]
        live._state["subscribed"].remove(sid)
        self.assertFalse(self.row("CE", 500)["tradable"])

    def test_monthly_expiry_uses_actual_date_and_rolls_after_close(self):
        dates = ["2026-09-17", "2026-09-24", "2026-10-29", "2026-11-26"]
        self.assertEqual(live._monthly_expiry(dates, self.now), "2026-09-24")
        self.assertEqual(live._monthly_expiry(dates, datetime(2026, 9, 24, 15, 29, tzinfo=live.IST)), "2026-09-24")
        self.assertEqual(live._monthly_expiry(dates, datetime(2026, 9, 24, 15, 30, tzinfo=live.IST)), "2026-10-29")
        self.assertEqual(live._monthly_expiry(["2026-11-23", "2026-12-29"],
                         datetime(2026, 11, 1, tzinfo=live.IST)), "2026-11-23")

    def test_master_accepts_banks_and_preserves_other_indices(self):
        fixtures = [master_contract(i, 50000, "CE", token=str(n), lot=30 + n)
                    for n, i in enumerate(("BANKEX", "BANKNIFTY", "NIFTY", "SENSEX"), 1)]
        rows, segments = angel_master._rows_from_master(fixtures)
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["name"] for r in rows}, {"BANKEX", "BANKNIFTY", "NIFTY", "SENSEX"})
        self.assertEqual(segments["BFO:1"], "BFO")
        self.assertEqual(segments["NFO:2"], "NFO")
        self.assertEqual(rows[0]["lot"], "31")
        fixtures.append({"name": "GOLD", "exch_seg": "MCX", "instrumenttype": "FUTCOM",
                         "token": "1", "symbol": "GOLD30SEP26FUT", "expiry": "30SEP2026"})
        _, segments = angel_master._rows_from_master(fixtures)
        self.assertEqual(segments["1"], "MCX")
        self.assertEqual(segments["BFO:1"], "BFO")

    def test_live_api_to_persistent_position_to_realised_close(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.models import BankOptionPosition, User
        from app.services import bank_options_positions as ledger
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        BankOptionPosition.__table__.create(engine)
        User.__table__.create(engine)
        with sessionmaker(bind=engine)() as db:
            db.add_all([User(username=n, password_hash="x", role="admin") for n in ("alice", "bob")]); db.commit()
        app = FastAPI()
        app.include_router(bank_options.router)
        app.dependency_overrides[get_current_user] = lambda: "alice"
        with patch.object(ledger, "SessionLocal", sessionmaker(bind=engine)), \
             patch.object(ledger, "_now", return_value=self.now), TestClient(app) as client:
            row = next(r for r in client.get("/api/bank-options/live").json()["rows"]
                       if r["side"] == "CE" and r["offset_points"] == 500)
            self.assertEqual(row["display_value"], -1.1)
            body = {"bankex_security_id": row["bankex"]["security_id"],
                    "banknifty_security_id": row["banknifty"]["security_id"],
                    "side": "CE", "bankex_lots": 1, "banknifty_lots": 1, "request_id": "integration-1"}
            response = client.post("/api/bank-options/positions", json=body)
            self.assertEqual(response.status_code, 201, response.text)
            position = response.json()
            # sold BANKEX 99 x 30 = 2970, bought BANKNIFTY 132 x 30 = 3960
            self.assertEqual(position["entry_credit_rupees"], -990)
            self.assertEqual(position["pnl_rupees"], -90)
            self.assertEqual(client.post("/api/bank-options/positions", json=body).json()["id"], position["id"])
            app.dependency_overrides[get_current_user] = lambda: "bob"
            self.assertEqual(client.get("/api/bank-options/positions").json()["positions"], [])
            self.assertEqual(client.post(f"/api/bank-options/positions/{position['id']}/close").status_code, 404)
            app.dependency_overrides[get_current_user] = lambda: "alice"
            self.tick(body["bankex_security_id"], 120, 121, volume=100)
            self.tick(body["banknifty_security_id"], 122, 123, volume=100)
            closed = client.post(f"/api/bank-options/positions/{position['id']}/close")
            self.assertEqual(closed.status_code, 200, closed.text)
            # BANKEX bought back at 121 (-22 x 30), BANKNIFTY sold at 122 (-10 x 30)
            self.assertEqual(closed.json()["pnl_rupees"], -960)
            summary = client.get("/api/bank-options/positions").json()["summary"]
            self.assertEqual((summary["open"], summary["closed"], summary["realised_pnl_rupees"]), (0, 1, -960))

    def test_saved_legacy_strikes_remain_pinned_markable_and_closable(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.models import BankOptionPosition, User
        from app.services import bank_options_positions as ledger
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        BankOptionPosition.__table__.create(engine)
        User.__table__.create(engine)
        with sessionmaker(bind=engine)() as db:
            db.add_all([User(username=n, password_hash="x", role="admin") for n in ("alice", "bob")]); db.commit()
        with patch.object(ledger, "SessionLocal", sessionmaker(bind=engine)), \
             patch.object(ledger, "_now", return_value=self.now):
            for offset in (100, 4000):
                with self.subTest(offset=offset):
                    be = live._state["contracts"]["BANKEX"][(63500 + offset, "CE")]
                    bn = live._state["contracts"]["BANKNIFTY"][(56200 + offset, "CE")]
                    # Simulate a position saved when these strikes were offered.
                    legacy_pair = live._make_pair(be, bn, live._state, live._indices(live._state))
                    with patch.object(live, "get_entry_pair", return_value=legacy_pair):
                        position = ledger.create_position("alice", be["security_id"], bn["security_id"],
                                                          "CE", 1, 1, f"legacy-{offset}")
                    with self.assertRaises(ValueError):
                        live.get_entry_pair(be["security_id"], bn["security_id"], "CE")
                    # Even removal from the current master must not discard a saved leg.
                    del live._state["contracts"]["BANKEX"][(be["strike"], "CE")]
                    del live._state["contracts"]["BANKNIFTY"][(bn["strike"], "CE")]
                    pinned = ledger.get_subscription_meta()
                    self.assertEqual(pinned[be["security_id"]]["strike"], be["strike"])
                    self.assertEqual(pinned[bn["security_id"]]["strike"], bn["strike"])
                    self.tick(be["security_id"], 119, 120, volume=100)
                    self.tick(bn["security_id"], 125, 127, volume=100)
                    saved = next(p for p in ledger.list_positions("alice")["positions"]
                                 if p["id"] == position["id"])
                    self.assertTrue(saved["can_close"])
                    # BANKEX sold 99 -> ask 120 (-21 x 30); BANKNIFTY bought 132 -> bid 125 (-7 x 30)
                    self.assertEqual(saved["pnl_rupees"], -840)
                    closed = ledger.close_position("alice", position["id"])
                    self.assertEqual((closed["status"], closed["pnl_rupees"]), ("closed", -840))

    def test_shared_capacity_keeps_existing_screens_spots_and_pinned_contracts(self):
        from app.services import (subscriptions, pair_registry, bank_options_positions,
            elec_service, extra_instruments, goldopt_service, mcx_opt_stream,
            metals_service, options_service, othercomm_service, paper_trades, price_service)
        existing = {str(n): {"exch": "MCX"} for n in range(2996)}
        pinned = {"BFO:pinned": {"exch": "BFO", "kind": "bank_option"},
                  "NFO:pinned": {"exch": "NFO", "kind": "bank_option"}}
        with ExitStack() as stack:
            stack.enter_context(patch.object(pair_registry, "refresh", return_value=1))
            stack.enter_context(patch.object(pair_registry, "get_subscriptions", return_value=existing))
            for service in (elec_service, extra_instruments, goldopt_service, mcx_opt_stream,
                            metals_service, options_service, othercomm_service, paper_trades):
                stack.enter_context(patch.object(service, "refresh"))
                stack.enter_context(patch.object(service, "get_subscription_meta", return_value={}))
            stack.enter_context(patch.object(price_service, "refresh"))
            stack.enter_context(patch.object(live, "refresh"))
            stack.enter_context(patch.object(bank_options_positions, "get_subscription_meta", return_value=pinned))
            result, _ = subscriptions.build()
        self.assertEqual(len(result), 3000)
        self.assertTrue(set(existing).issubset(result))
        self.assertTrue(set(pinned).issubset(result))
        self.assertTrue({live.INDEX_IDS[i] for i in live.INDICES}.issubset(result))
        self.assertTrue(live._state["capacity_limited"])
        from app.services import angel_ws_feed
        plans = angel_ws_feed._plan(result)
        self.assertEqual(len(plans), 3)
        self.assertTrue(all(sum(len(tokens) for group in plan for tokens in group.values()) <= 1000
                            for plan in plans))


class BankOptionsRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(bank_options.router)
        self.app.dependency_overrides[get_current_user] = lambda: "alice"
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_query_validation_rejects_invalid_calculations(self):
        with patch.object(live, "get_live", return_value={}) as read:
            for query in ("divisor=0", "divisor=nan", "divisor=inf", "max_spread_pct=nan",
                          "range_points=9000", "bankex_lots=0", "metric=unknown", "side=call"):
                with self.subTest(query=query):
                    self.assertEqual(self.client.get("/api/bank-options/live?" + query).status_code, 422)
            read.assert_not_called()
            self.assertEqual(self.client.get("/api/bank-options/live?divisor=30&side=PE").status_code, 200)
            self.assertEqual(read.call_args.kwargs["range_points"], 3500)
            self.assertEqual(read.call_args.kwargs["liquidity"], "all")
            self.assertEqual(self.client.get("/api/bank-options/live?range_points=3500").status_code, 200)
            self.assertEqual(read.call_args.kwargs["range_points"], 3500)

    def test_positions_require_auth_and_do_not_accept_client_fill_prices(self):
        body = {"bankex_security_id": "BFO:1", "banknifty_security_id": "NFO:2",
                "side": "CE", "request_id": "test", "buy_price": 1}
        self.assertEqual(self.client.post("/api/bank-options/positions", json=body).status_code, 422)
        self.app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/api/bank-options/positions").status_code, 401)

    def test_page_permission_surface(self):
        from app import security
        with patch.object(security, "perms_of", return_value={"active": True, "role": "user", "pages": ["bankoptions"]}):
            self.assertTrue(security.may("alice", "/api/bank-options/live"))
            self.assertTrue(security.may("alice", "/api/bank-options/positions/1/close"))
            self.assertFalse(security.may("alice", "/api/nse-mcx"))
        with patch.object(security, "perms_of", return_value={"active": True, "role": "user", "pages": ["options"]}):
            self.assertFalse(security.may("alice", "/api/bank-options/live"))


class BankOptionWireTests(unittest.TestCase):
    def test_socket_subscriptions_do_not_share_sdk_class_cache_or_mutate_plans(self):
        from app.services import angel_ws_feed as feed
        class SDK:
            # Reproduce the real SDK's shared cache and retained list references.
            input_request_dict = {}
            RESUBSCRIBE_FLAG = False
            def __init__(self, *args, **kwargs):
                pass
            def subscribe(self, correlation, mode, groups):
                cache = self.input_request_dict.setdefault(mode, {})
                for group in groups:
                    if group["exchangeType"] in cache:
                        cache[group["exchangeType"]].extend(group["tokens"])
                    else:
                        cache[group["exchangeType"]] = group["tokens"]
                self.RESUBSCRIBE_FLAG = True
        auth = ("test", "test", {"ANGEL_API_KEY": "test", "ANGEL_CLIENT_CODE": "test"})
        first = feed._Conn(0, {4: ["100", "101"]}, {}, auth, {})
        second = feed._Conn(1, {4: ["102"]}, {}, auth, {})
        with patch('SmartApi.smartWebSocketV2.SmartWebSocketV2', SDK), patch.object(feed.threading, 'Thread'):
            first.start()
            second.start()
            first._on_open(None)
            second._on_open(None)
            self.assertIsNot(first.ws.input_request_dict, second.ws.input_request_dict)
            self.assertEqual(first.ws.input_request_dict[3][4], ["100", "101"])
            self.assertEqual(second.ws.input_request_dict[3][4], ["102"])
            self.assertEqual((first.n_tokens, second.n_tokens), (2, 1))
            first.ws.input_request_dict[3][4].append("SDK-internal")
            self.assertEqual(first.n_tokens, 2)
            first.start()  # replacement connection must start with an empty cache
            self.assertEqual(first.ws.input_request_dict, {})
            self.assertFalse(first.ws.RESUBSCRIBE_FLAG)
            first._on_open(None)
            self.assertEqual(first.ws.input_request_dict[3][4], ["100", "101"])

    def test_exchange_qualified_tokens_on_wire_and_in_quote_store(self):
        from app.services import angel_ws_feed as feed
        subs = {"NFO:123": {"exch": "NFO", "token": "123", "kind": "bank_option"},
                "BFO:123": {"exch": "BFO", "token": "123", "kind": "bank_option"},
                "99919012": {"exch": "BSE", "kind": "index"}}
        plans = feed._plan(subs)
        wire = {ex: tokens for groups, indices in plans for ex, tokens in {**groups, **indices}.items()}
        self.assertEqual(wire[2], ["123"])
        self.assertEqual(wire[4], ["123"])
        conn = feed._Conn(0, plans[0][0], plans[0][1], ("", "", {}), subs)
        with patch.object(feed.quote_store, "update") as update, patch.object(feed, "_set_state"), \
             patch.object(feed, "_eval_and_broadcast"), patch.object(live, "note_live_tick"):
            for exchange in (2, 4):
                conn._on_data(None, {"token": "123", "exchange_type": exchange,
                    "subscription_mode": 3, "last_traded_price": 10000,
                    "volume_trade_for_the_day": 20, "last_traded_timestamp": 1,
                    "best_5_buy_data": [{"flag": 1, "price": 9900}],
                    "best_5_sell_data": [{"flag": 0, "price": 10100}]})
            self.assertEqual([call.args[0] for call in update.call_args_list], ["NFO:123", "BFO:123"])
            self.assertEqual(update.call_args.kwargs["bid"], 99)
            self.assertEqual(update.call_args.kwargs["ask"], 101)


if __name__ == "__main__":
    unittest.main()
