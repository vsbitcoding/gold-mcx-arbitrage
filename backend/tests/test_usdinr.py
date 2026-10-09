"""USD/INR: the premium takes the NSE spot underlying, the MCX vs NYMEX screen
the front MONTHLY future; weekly futures (no market) are never picked."""
import os
import time
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-000")
os.environ.setdefault("ANGEL_ENABLED", "false")

from app.services import angel_feed, premium_feed  # noqa: E402


class FakeDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 9)


def fut(symbol, expiry, token):
    return {"exch_seg": "CDS", "name": "USDINR", "instrumenttype": "FUTCUR", "symbol": symbol,
            "expiry": expiry, "token": token}


MASTER = [
    fut("USDINR26O09FUT", "09OCT2026", "1752"),     # weekly, today
    fut("USDINR26O16FUT", "16OCT2026", "1084"),     # weekly
    fut("USDINR26OCTFUT", "28OCT2026", "1284"),     # monthly
    fut("USDINR26NOVFUT", "26NOV2026", "1584"),     # monthly
    fut("USDINR26SEPFUT", "28SEP2026", "999"),      # expired monthly
    {"exch_seg": "CDS", "name": "USDINR", "instrumenttype": "UNDCUR", "symbol": "USDINR", "expiry": "", "token": "1"},
    {"exch_seg": "CDS", "name": "USDINR", "instrumenttype": "UNDCUR", "symbol": "CCIL-USDINR", "expiry": "", "token": "16"},
]


class ResolveTests(unittest.TestCase):
    def resolve(self, today=FakeDate(2026, 10, 9)):
        class D(FakeDate):
            @classmethod
            def today(cls):
                return today
        with patch.object(angel_feed, "_load_master", return_value=MASTER), \
             patch.object(angel_feed, "_resolve_commodity", return_value=[]), \
             patch.object(angel_feed, "date", D):
            return angel_feed._resolve()

    def test_monthly_future_and_spot_never_a_weekly(self):
        out = self.resolve()
        self.assertEqual(out["usdinr"]["symbol"], "USDINR26OCTFUT")
        self.assertEqual(out["usdinr_spot"]["token"], "1")

    def test_monthly_rolls_on_its_expiry_day(self):
        self.assertEqual(self.resolve(FakeDate(2026, 10, 28))["usdinr"]["symbol"], "USDINR26NOVFUT")
        self.assertEqual(self.resolve(FakeDate(2026, 10, 27))["usdinr"]["symbol"], "USDINR26OCTFUT")

    def test_fx_leg_keeps_four_decimals_and_the_exchange_time(self):
        row = {"ltp": 96.71955, "tradeVolume": 0, "opnInterest": 0, "exchFeedTime": "09-Oct-2026 09:17:47",
               "depth": {"buy": [{"price": 96.7138}], "sell": [{"price": 96.7253}]}}
        leg = angel_feed._fx_leg(row)
        self.assertEqual((leg["bid"], leg["ask"], leg["mid"]), (96.7138, 96.7253, 96.71955))
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(leg["feed_ts"])), "2026-10-09 03:47:47")
        dead = angel_feed._fx_leg({"ltp": 97.145, "depth": {"buy": [{"price": 0.0}], "sell": [{"price": 0.0}]},
                                   "exchFeedTime": "01-Jan-1970 05:30:00"})
        self.assertEqual((dead["bid"], dead["ask"], dead["mid"], dead["feed_ts"]), (None, None, None, None))


class PremiumRateTests(unittest.TestCase):
    NOW = 1791517000.0

    def data(self, spot=True, future=True):
        d = {"age": 2.0}
        if spot:
            d["usdinr_spot"] = {"bid": 96.7138, "ask": 96.7253, "mid": 96.7196, "ltp": 96.7196, "feed_ts": self.NOW - 4}
        if future:
            d["usdinr"] = {"bid": 96.8875, "ask": 96.895, "mid": 96.8913, "ltp": 96.895, "feed_ts": self.NOW - 1,
                           "symbol": "USDINR26OCTFUT"}
        return d

    def rates(self, **kw):
        with patch.object(angel_feed, "get_data", return_value=self.data(**kw)), \
             patch.object(premium_feed.time, "time", return_value=self.NOW):
            return premium_feed._usdinr(), premium_feed._usdinr_future()

    def test_premium_takes_spot_and_mcx_nymex_the_future(self):
        (rate, age, src), (frate, fage, fsrc) = self.rates()
        self.assertEqual((rate, age), (96.7196, 4.0))
        self.assertIn("spot", src)
        self.assertEqual((frate, fage), (96.8913, 1.0))
        self.assertIn("monthly future", fsrc)

    def test_fallbacks(self):
        (rate, _a, src), (frate, _fa, fsrc) = self.rates(spot=False)
        self.assertEqual(rate, 96.8913)                   # no spot -> the monthly future, said so
        self.assertIn("spot unavailable", src)
        (rate, _a, src), (frate, _fa, fsrc) = self.rates(future=False)
        self.assertEqual((rate, frate), (96.7196, 96.7196))   # no future -> MCX vs NYMEX falls back to spot
        self.assertIn("future unavailable", fsrc)

    def test_a_rate_stopped_at_the_close_keeps_its_value_with_its_true_age(self):
        d = self.data()
        d["usdinr_spot"]["feed_ts"] = self.NOW - 6 * 3600
        with patch.object(angel_feed, "get_data", return_value=d), \
             patch.object(premium_feed.time, "time", return_value=self.NOW):
            rate, age, _src = premium_feed._usdinr()
        self.assertEqual((rate, age), (96.7196, 21600.0))


if __name__ == "__main__":
    unittest.main()
