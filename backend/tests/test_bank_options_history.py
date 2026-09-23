"""BANKEX / BANKNIFTY history: the 10:00 / 15:30 snapshot rules and the daily
boards built from bhavcopy rows. Expected numbers are worked by hand."""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-000")
os.environ.setdefault("ANGEL_ENABLED", "false")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.models import BankOptDaily, BankOptionsSnapshot  # noqa: E402
from app.services import bank_daily_history as daily  # noqa: E402
from app.services import bank_options_history as hist  # noqa: E402


def leg(bid, ask, age=5.0, fresh=True, sid="X"):
    return {"strike": 64000, "expiry": "2026-09-24", "bid": bid, "ask": ask, "ltp": bid, "oi": 10, "volume": 3,
            "age_seconds": age, "fresh": fresh, "lot_size": 30, "security_id": sid}


def live_board(rows, bankex_age=1):
    fresh = bankex_age is not None and bankex_age <= 60
    return {"market_open": True, "buy_index": "BANKNIFTY", "sell_index": "BANKEX",
            "indices": {"BANKEX": {"spot": 63644, "atm": 63500, "expiry": "2026-09-24", "lot_size": 30, "age_seconds": bankex_age, "fresh": fresh},
                        "BANKNIFTY": {"spot": 56327, "atm": 56300, "expiry": "2026-09-29", "lot_size": 35, "age_seconds": 1, "fresh": True}},
            "status": {"ready": fresh, "message": None}, "rows": rows}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        BankOptionsSnapshot.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        p = patch.object(hist, "SessionLocal", self.Session); p.start(); self.addCleanup(p.stop)
        hist._cache.clear()

    def test_compact_prices_from_last_quotes_and_flags_stale(self):
        rows = [
            # fresh both legs: sell BANKEX bid 99, buy BANKNIFTY ask 132 -> -33
            {"side": "CE", "offset_points": 0, "bankex": leg(99, 100), "banknifty": leg(130, 132)},
            # BANKEX leg 5 min old (not "fresh" on the live page) but still a standing two-way quote -> priced, stale
            {"side": "PE", "offset_points": 0, "bankex": leg(99, 100, age=300, fresh=False), "banknifty": leg(130, 132)},
            # a quote older than 15 min does not price a history row
            {"side": "CE", "offset_points": 500, "bankex": leg(99, 100, age=1000, fresh=False), "banknifty": leg(130, 132)},
            # a restored quote (never ticked today) has no age -> unpriced
            {"side": "PE", "offset_points": 500, "bankex": leg(99, 100, age=None, fresh=False), "banknifty": leg(130, 132)},
            # one-sided book -> unpriced
            {"side": "CE", "offset_points": -500, "bankex": leg(None, 100), "banknifty": leg(130, 132)},
        ]
        c = hist.compact(live_board(rows), "2026-09-23T10:00:05")
        got = [(r["side"], r["offset_points"], r["difference_points"], r["stale"]) for r in c["rows"]]
        self.assertEqual(got, [("CE", 0, -33.0, False), ("PE", 0, -33.0, True), ("CE", 500, None, False),
                               ("PE", 500, None, False), ("CE", -500, None, False)])
        self.assertEqual(c["indices"]["BANKNIFTY"]["lot_size"], 35)
        self.assertEqual((c["buy_index"], c["sell_index"]), ("BANKNIFTY", "BANKEX"))

    def test_snapshot_windows_calendar_and_idempotence(self):
        rows = [{"side": "CE", "offset_points": 0, "bankex": leg(99, 100), "banknifty": leg(130, 132)}]
        with patch("app.services.bank_options_service.get_live", return_value=live_board(rows)), \
             patch("app.services.market_calendar.is_open", return_value=True):
            self.assertEqual(hist.snapshot("10:00", now=datetime(2026, 9, 23, 9, 59)), "outside capture window; skipped")
            self.assertEqual(hist.snapshot("15:30", now=datetime(2026, 9, 23, 15, 39)), "outside capture window; skipped")
            self.assertEqual(hist.snapshot("10:00", now=datetime(2026, 9, 23, 10, 0, 30)), "snapped")
            self.assertEqual(hist.snapshot("10:00", now=datetime(2026, 9, 23, 10, 5)), "already snapped this slot")
            self.assertEqual(hist.snapshot("15:30", now=datetime(2026, 9, 23, 15, 30, 40)), "snapped")
        with patch("app.services.bank_options_service.get_live", return_value=live_board(rows)), \
             patch("app.services.market_calendar.is_open", return_value=False):
            self.assertEqual(hist.snapshot("10:00", now=datetime(2026, 9, 24, 10, 0, 30)), "market closed; skipped")
        # a restored index quote (no tick since restart) cannot make a board; a 3-minute-old one at the close can
        with patch("app.services.bank_options_service.get_live", return_value=live_board(rows, bankex_age=None)), \
             patch("app.services.market_calendar.is_open", return_value=True):
            self.assertEqual(hist.snapshot("10:00", now=datetime(2026, 9, 24, 10, 0, 30)), "no live index data; skipped")
        with patch("app.services.bank_options_service.get_live", return_value=live_board(rows, bankex_age=180)), \
             patch("app.services.market_calendar.is_open", return_value=True):
            self.assertEqual(hist.snapshot("15:30", now=datetime(2026, 9, 24, 15, 33, 10)), "snapped")
            self.assertFalse(hist.get_history(date="2026-09-24")["boards"][0]["indices"]["BANKEX"]["fresh"])
        h = hist.get_history(slot="both", days=7)
        self.assertEqual([(b["date"], b["slot"]) for b in h["boards"]],
                         [("2026-09-24", "15:30"), ("2026-09-23", "15:30"), ("2026-09-23", "10:00")])
        self.assertEqual(h["boards"][1]["rows"][0]["difference_points"], -33.0)
        self.assertEqual(h["boards"][1]["indices"]["BANKEX"]["spot"], 63644)
        self.assertEqual(h["dates"], ["2026-09-24", "2026-09-23"])
        hist._cache.clear()
        self.assertEqual(hist.get_history(slot="10:00", weekday="wed")["count"], 1)   # 23-Sep-2026 is a Wednesday
        hist._cache.clear()
        self.assertEqual(hist.get_history(weekday="mon")["count"], 0)


BHAV = """TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rs
2026-09-22,2026-09-22,FO,BSE,IDO,1,,BANKEX,,2026-09-24,2026-09-24,63500.00,CE,BANKEX26SEP63500CE,1,1,1,210.00,210,200,63529.21,209.50,100,0,50,1,1,F1,30,,,,,
2026-09-22,2026-09-22,FO,BSE,IDO,2,,BANKEX,,2026-09-24,2026-09-24,63500.00,PE,BANKEX26SEP63500PE,1,1,1,0.00,0,0,63529.21,180.25,100,0,0,0,0,F1,30,,,,,
2026-09-22,2026-09-22,FO,BSE,IDO,3,,BANKEX,,2026-09-24,2026-09-24,63600.00,CE,BANKEX26SEP63600CE,1,1,1,150.00,150,140,63529.21,150.00,100,0,50,1,1,F1,30,,,,,
2026-09-22,2026-09-22,FO,BSE,IDO,4,,BANKEX,,2026-10-29,2026-10-29,63500.00,CE,BANKEX26OCT63500CE,1,1,1,900.00,900,880,63529.21,899.00,10,0,5,1,1,F1,30,,,,,
2026-09-22,2026-09-22,FO,BSE,IDO,5,,BANKEX,,2026-09-24,2026-09-24,70500.00,CE,BANKEX26SEP70500CE,1,1,1,0.05,0.05,0.05,63529.21,0.05,0,0,0,0,0,F1,30,,,,,
2026-09-22,2026-09-22,FO,BSE,IDF,6,,BANKEX,,2026-09-24,2026-09-24,0.00,XX,BANKEX26SEPFUT,1,1,1,63550,63550,63400,63529.21,63550,100,0,50,1,1,F1,30,,,,,
2026-09-22,2026-09-22,FO,NSE,IDO,7,,BANKNIFTY,,2026-09-29,2026-09-29,56300.00,CE,BANKNIFTY26SEP56300CE,1,1,1,300.00,300,290,56327.40,300.00,100,0,50,1,1,F1,35,,,,,
2026-09-22,2026-09-22,FO,NSE,IDO,8,,BANKNIFTY,,2026-09-29,2026-09-29,56300.00,PE,BANKNIFTY26SEP56300PE,1,1,1,250.00,250,240,56327.40,250.00,100,0,50,1,1,F1,35,,,,,
2026-09-22,2026-09-22,FO,NSE,IDO,9,,BANKNIFTY,,2026-09-29,2026-09-29,56800.00,CE,BANKNIFTY26SEP56800CE,1,1,1,100.00,100,90,56327.40,100.00,100,0,50,1,1,F1,35,,,,,
2026-09-22,2026-09-22,FO,NSE,IDO,10,,BANKNIFTY,,2026-09-29,2026-09-29,56850.00,CE,BANKNIFTY26SEP56850CE,1,1,1,90.00,90,90,56327.40,90.00,100,0,50,1,1,F1,35,,,,,
2026-09-22,2026-09-22,FO,NSE,IDO,11,,NIFTY,,2026-09-29,2026-09-29,25000.00,CE,NIFTY26SEP25000CE,1,1,1,90.00,90,90,25000,90.00,100,0,50,1,1,F1,75,,,,,
"""


class DailyBoardTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        BankOptDaily.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        p = patch.object(daily, "SessionLocal", self.Session); p.start(); self.addCleanup(p.stop)
        daily._cache.clear()

    def test_parse_keeps_options_within_the_radius(self):
        be = daily.parse("BANKEX", BHAV, "2026-09-22")
        # 70500 is beyond 6,000 points, the future is not an option; 63600 (off the page's 500 ladder) is kept
        self.assertEqual([(r["expiry"], r["strike"], r["side"]) for r in be],
                         [("2026-09-24", 63500.0, "CE"), ("2026-09-24", 63500.0, "PE"), ("2026-09-24", 63600.0, "CE"),
                          ("2026-10-29", 63500.0, "CE")])
        self.assertEqual((be[0]["close"], be[0]["settle"], be[0]["volume"], be[0]["lot_size"], be[0]["underlying"]),
                         (210.0, 209.5, 50.0, 30, 63529.21))
        bn = daily.parse("BANKNIFTY", BHAV, "2026-09-22")
        self.assertEqual([r["strike"] for r in bn], [56300.0, 56300.0, 56800.0, 56850.0])   # NIFTY rows ignored

    def test_board_matches_the_live_rules_and_prices_untraded_at_settle(self):
        daily.store(daily.parse("BANKEX", BHAV, "2026-09-22"), "BANKEX", "2026-09-22")
        daily.store(daily.parse("BANKNIFTY", BHAV, "2026-09-22"), "BANKNIFTY", "2026-09-22")
        h = daily.get_history(days=7)
        self.assertEqual(h["count"], 1)
        b = h["boards"][0]
        self.assertEqual(b["weekday"], "tue")
        self.assertEqual(b["indices"]["BANKEX"], {"spot": 63529.21, "atm": 63500.0, "expiry": "2026-09-24", "lot_size": 30})
        self.assertEqual(b["indices"]["BANKNIFTY"], {"spot": 56327.4, "atm": 56300.0, "expiry": "2026-09-29", "lot_size": 35})
        # BANKEX (24-Sep) expires first: sold; BANKNIFTY (29-Sep) bought
        self.assertEqual((b["buy_index"], b["sell_index"]), ("BANKNIFTY", "BANKEX"))
        self.assertEqual(len(b["rows"]), 30)
        atm_ce = next(r for r in b["rows"] if r["side"] == "CE" and r["offset_points"] == 0)
        # BANKNIFTY strike = round100(56327.4 + (63500 - 63529.21)) = round100(56298.19) = 56300
        self.assertEqual((atm_ce["bankex"]["strike"], atm_ce["banknifty"]["strike"]), (63500.0, 56300.0))
        # sell BANKEX close 210, buy BANKNIFTY close 300 -> -90, both traded
        self.assertEqual((atm_ce["sell_price"], atm_ce["buy_price"], atm_ce["difference_points"], atm_ce["settled"]),
                         (210.0, 300.0, -90.0, False))
        atm_pe = next(r for r in b["rows"] if r["side"] == "PE" and r["offset_points"] == 0)
        # the BANKEX 63500 PE never traded (volume 0, close 0) -> settlement 180.25 is its price, flagged
        self.assertEqual((atm_pe["sell_price"], atm_pe["buy_price"], atm_pe["difference_points"], atm_pe["settled"]),
                         (180.25, 250.0, -69.75, True))
        self.assertFalse(atm_pe["bankex"]["traded"])
        # +500: BANKEX 64000 is not listed in the fixture -> unpriced, strike still shown
        up = next(r for r in b["rows"] if r["side"] == "CE" and r["offset_points"] == 500)
        self.assertEqual((up["bankex"]["listed"], up["bankex"]["strike"], up["banknifty"]["strike"], up["difference_points"]),
                         (False, 64000.0, 56800.0, None))
        daily._cache.clear()
        self.assertEqual(daily.get_history(weekday=0)["count"], 0)
        daily._cache.clear()
        self.assertEqual(daily.get_history(date_="2026-09-22")["count"], 1)

    def test_current_expiry_rolls_after_the_expiry_day(self):
        listed = {"2026-09-24", "2026-10-29", "2026-11-26"}
        self.assertEqual(daily.current_expiry(listed, "2026-09-22"), "2026-09-24")
        self.assertEqual(daily.current_expiry(listed, "2026-09-24"), "2026-10-29")   # the close of expiry day has rolled
        self.assertIsNone(daily.current_expiry({"2026-09-24"}, "2026-09-30"))
        # 2024, weekly era: the front weekly is the current contract
        self.assertEqual(daily.current_expiry({"2024-01-03", "2024-01-10", "2024-01-25", "2024-01-31"}, "2024-01-02"), "2024-01-03")


if __name__ == "__main__":
    unittest.main()
