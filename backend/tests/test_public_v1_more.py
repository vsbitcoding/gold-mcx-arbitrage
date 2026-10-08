"""App API part 2: key handling, Making Price arithmetic, the backtest guard
and cache, and that each new route reaches the service the dashboard uses."""
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-000")
os.environ.setdefault("ANGEL_ENABLED", "false")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.routes import public_v1, public_v1_more as more  # noqa: E402

KEY = {"X-API-Key": "test-app-key"}


def price_table(bid):
    return {"groups": [{"short": "gold", "contracts": [{"contract": "05 Dec 2026", "buyer": 1}]},
                       {"short": "mini", "contracts": [{"contract": "05 Nov 2026", "buyer": bid},
                                                       {"contract": "04 Dec 2026", "buyer": 999999}]}]}


class AppApiMoreTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(public_v1.router)
        app.include_router(more.router)
        self.client = TestClient(app)
        p = patch.object(settings, "PUBLIC_API_KEYS", "test-app-key"); p.start(); self.addCleanup(p.stop)
        p = patch.object(more, "is_market_open", return_value=True); p.start(); self.addCleanup(p.stop)
        more._cache.clear(); more._bt_cache.clear()

    def test_wrong_or_missing_key_is_401_not_500(self):
        self.assertEqual(self.client.get("/api/v1/market-status").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/market-status", headers={"X-API-Key": "nope"}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/making-price?api_key=nope").status_code, 401)

    def test_making_price_defaults_and_overrides(self):
        with patch("app.services.price_service.get_table", return_value=price_table(150000.0)):
            r = self.client.get("/api/v1/making-price", headers=KEY).json()
            rows = {x["key"]: x for x in r["rows"]}
            # near Gold Mini bid 150000 x 0.00402 = 603, + charge x multiplier
            self.assertEqual(rows["petal"]["value"], 3853.0)     # 603 + 325 x 10
            self.assertEqual(rows["guinea"]["value"], 1853.0)    # 603 + 1000 x 1.25
            self.assertEqual(rows["ten"]["value"], 2003.0)       # 603 + 1400 x 1
            self.assertEqual(rows["silvermicro"]["value"], 3500.0)
            self.assertEqual(rows["petal"]["base_contract"], "05 Nov 2026")
            more._cache.clear()
            r = self.client.get("/api/v1/making-price?factor=0.004&petal=300&silvermicro=3000", headers=KEY).json()
            rows = {x["key"]: x for x in r["rows"]}
            self.assertEqual(rows["petal"]["value"], 3600.0)     # 150000 x 0.004 + 300 x 10
            self.assertEqual(rows["guinea"]["value"], 1850.0)    # 600 + 1250
            self.assertEqual(rows["silvermicro"]["value"], 3000.0)
        more._cache.clear()
        with patch("app.services.price_service.get_table", return_value=price_table(None)):
            r = self.client.get("/api/v1/making-price", headers=KEY).json()
            self.assertIsNone({x["key"]: x for x in r["rows"]}["petal"]["value"])   # no bid -> no value, never 0

    def test_backtest_one_at_a_time_cached_and_paths_trimmed(self):
        calls, gate = [], threading.Event()

        def slow_run(params):
            calls.append(params)
            gate.wait(5)
            return {"params": params, "trades": [{"id": 1, "pnl_points": 2.5, "path": [{"ts": "x"}]}]}

        with patch("app.services.crude_iv_backtest.run", side_effect=slow_run):
            out = {}
            t = threading.Thread(target=lambda: out.setdefault("r", self.client.post(
                "/api/v1/crude-iv/backtest", json={"entry_diff": 5}, headers=KEY)))
            t.start()
            for _ in range(100):
                if calls:
                    break
                time.sleep(0.02)
            busy = self.client.post("/api/v1/crude-iv/backtest", json={"entry_diff": 4.5}, headers=KEY)
            self.assertEqual(busy.status_code, 429)
            gate.set(); t.join(5)
            first = out["r"].json()
            self.assertEqual(first["trades"], [{"id": 1, "pnl_points": 2.5}])          # path trimmed
            again = self.client.post("/api/v1/crude-iv/backtest", json={"entry_diff": 5}, headers=KEY)
            self.assertEqual(len(calls), 1)                                           # served from the cache
            self.assertEqual(again.json()["trades"][0].get("path"), None)
            full = self.client.post("/api/v1/crude-iv/backtest?include_paths=true", json={"entry_diff": 5}, headers=KEY).json()
            self.assertEqual(full["trades"][0]["path"], [{"ts": "x"}])                # cache kept the paths

    def test_backtest_bad_rules_are_400(self):
        with patch("app.services.nse_mcx_backtest.run", side_effect=ValueError("bad rule")):
            r = self.client.post("/api/v1/nse-mcx/backtest", json={}, headers=KEY)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "bad rule"))

    def test_routes_reach_the_dashboard_services(self):
        with patch("app.services.bank_options_service.get_live", return_value={"rows": []}) as live:
            self.assertEqual(self.client.get("/api/v1/bank-options", headers=KEY).status_code, 200)
            self.assertEqual(live.call_args.kwargs["metric"], "points")               # plain points by default
        with patch("app.services.bank_daily_history.get_history", return_value={"source": "daily"}) as daily:
            r = self.client.get("/api/v1/bank-options/history?source=daily&weekday=mon&days=20", headers=KEY).json()
            self.assertEqual(r["source"], "daily")
            self.assertEqual(daily.call_args.kwargs, {"weekday": 0, "days": 20, "date_": None})
        with patch("app.routes.pairs.bhav_series_payload", return_value={"rows": [1]}) as bhav:
            r = self.client.get("/api/v1/spread-history?kind=cross&big=petal&small=guinea", headers=KEY).json()
            self.assertEqual(r["rows"], [1])
            self.assertEqual(bhav.call_args.args[:3], ("cross", "petal", "guinea"))
        with patch("app.routes.nse_mcx._elec_payload", return_value={"commodity": "electricity"}) as elec:
            r = self.client.get("/api/v1/nse-mcx?commodity=electricity&month=1", headers=KEY).json()
            self.assertEqual(r["commodity"], "electricity")
            elec.assert_called_once_with(1)
        with patch("app.services.market_calendar.state", return_value={"state": "open"}), \
             patch("app.services.market_calendar.list_year", return_value=[
                 {"date": "2099-01-01", "weekday": "Thursday", "exchange": "NSE", "name": "Far", "morning_closed": True, "evening_closed": True, "id": 1},
                 {"date": "2000-01-01", "weekday": "Saturday", "exchange": "MCX", "name": "Past", "morning_closed": True, "evening_closed": True, "id": 2}]):
            r = self.client.get("/api/v1/market-status", headers=KEY).json()
            self.assertEqual(r["now"], {"mcx": {"state": "open"}, "nse": {"state": "open"}})
            self.assertEqual(r["upcoming_holidays"], [])      # past and far-future holidays are left out


if __name__ == "__main__":
    unittest.main()
