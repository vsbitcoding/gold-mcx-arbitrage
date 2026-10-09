"""The app's spread boards in the dashboard's shape: card order, calendar expiry
text, legs and months for the Hist button, the bracketed plain difference, the
signal flash, the Signals order and IBKR's competing-session flag."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-that-is-long-enough-000")
os.environ.setdefault("ANGEL_ENABLED", "false")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.routes import public_v1  # noqa: E402

KEY = {"X-API-Key": "test-app-key"}


def snap(name, label, group, type_, expiry, dec, inc, big, small, big_expiry):
    return {"name": name, "label": label, "group_label": group, "type": type_, "expiry_label": expiry,
            "decrease_spread": dec, "increase_spread": inc, "decrease_pct": 0.5, "increase_pct": 0.6,
            "big": big, "small": small, "big_expiry": big_expiry}


SNAPS = [
    snap("Guinea-Mini@2026-10-30", "GUINEA / MINI", "GUINEA / MINI", "cross", "30 Oct 2026", 902.5, 944.0, "guinea", "mini", "2026-10-30"),
    snap("Petal-Guinea@2026-11-30", "PETAL / GUINEA", "PETAL / GUINEA", "cross", "30 Nov 2026", -150.0, -91.25, "petal", "guinea", "2026-11-30"),
    snap("Petal-Guinea@2026-10-30", "PETAL / GUINEA", "PETAL / GUINEA", "cross", "30 Oct 2026", -140.0, -91.25, "petal", "guinea", "2026-10-30"),
    snap("Silver100-Silvermic@2026-11-30", "SILVER 100 / SILVER MIC", "SILVER 100 / SILVER MIC", "cross", "30 Nov 2026", 1.0, 2.0, "silver100", "silvermic", "2026-11-30"),
    snap("Gold@2026-12-04/2027-02-05", "GOLD 05FEB27-04DEC26", "GOLD", "calendar", "Far 5 Feb 2027 − Near 4 Dec 2026", 2026.0, 2183.0, "gold", "gold", "2027-02-05"),
    snap("Petal@2026-10-30/2026-11-30", "PETAL 30NOV26-30OCT26", "PETAL", "calendar", "Far 30 Nov 2026 − Near 30 Oct 2026", 1270.0, 1300.0, "petal", "petal", "2026-11-30"),
]
SIG = {"id": 7, "name": "Petal-Guinea@2026-10-30", "label": "PETAL / GUINEA", "direction": "narrow",
       "entry": -140.0, "target": -160.0, "stop": -130.0, "current": -141.0, "probability": 70}


class ParityTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(public_v1.router)
        self.client = TestClient(app)
        for target, value in ((settings, ("PUBLIC_API_KEYS", "test-app-key")),):
            p = patch.object(target, *value); p.start(); self.addCleanup(p.stop)
        p = patch.object(public_v1, "compute_all", return_value=[dict(s) for s in SNAPS]); p.start(); self.addCleanup(p.stop)
        p = patch.object(public_v1.signal_service, "evaluate_all", return_value={SIG["name"]: SIG}); p.start(); self.addCleanup(p.stop)
        p = patch.object(public_v1, "is_market_open", return_value=True); p.start(); self.addCleanup(p.stop)

    def test_cross_cards_in_dashboard_order_with_signal_and_legs(self):
        g = self.client.get("/api/v1/spread-groups?type=cross", headers=KEY).json()["groups"]
        self.assertEqual([x["group"] for x in g], ["PETAL / GUINEA", "GUINEA / MINI", "SILVER 100 / SILVER MIC"])
        pg = g[0]
        self.assertEqual([r["expiry_display"] for r in pg["expiries"]], ["30 Oct 2026", "30 Nov 2026"])   # front first
        front = pg["expiries"][0]
        self.assertEqual((front["big"], front["small"], front["expiry_date"]), ("petal", "guinea", "2026-10-30"))
        self.assertEqual(front["signal"]["direction"], "narrow")
        self.assertTrue(pg["has_signal"])
        self.assertIsNone(pg["expiries"][1]["signal"])
        self.assertIsNone(front["decrease_raw"])                 # brackets are a calendar-only thing
        self.assertTrue(g[2]["silver"])
        self.assertFalse(pg["silver"])

    def test_calendar_cards_order_expiry_text_and_plain_difference(self):
        g = self.client.get("/api/v1/spread-groups?type=calendar", headers=KEY).json()["groups"]
        self.assertEqual([x["group"] for x in g], ["PETAL", "GOLD"])
        petal = g[0]["expiries"][0]
        self.assertEqual(petal["expiry_display"], "30 Oct 2026 − 30 Nov 2026")              # near − far
        self.assertEqual((petal["near_expiry"], petal["far_expiry"]), ("2026-10-30", "2026-11-30"))
        self.assertEqual((petal["decrease_raw"], petal["increase_raw"]), (127.0, 130.0))    # / 10
        gold = g[1]["expiries"][0]
        self.assertEqual(gold["expiry_display"], "4 Dec 2026 − 5 Feb 2027")
        self.assertIsNone(gold["decrease_raw"])
        self.assertEqual(gold["expiry"], "Far 5 Feb 2027 − Near 4 Dec 2026")              # old field untouched

    def test_stream_digest_and_flat_list_carry_the_signal(self):
        payload, digest = public_v1._build_groups_payload("cross")
        flat = self.client.get("/api/v1/spreads?type=cross", headers=KEY).json()["spreads"]
        self.assertEqual(sum(1 for r in flat if r["signal"]), 1)
        with patch.object(public_v1.signal_service, "evaluate_all", return_value={}):
            _p2, digest2 = public_v1._build_groups_payload("cross")
        self.assertNotEqual(digest, digest2)                     # a signal appearing re-pushes the stream

    def test_signals_in_the_signals_tab_order(self):
        sigs = [{"label": "TEN / MINI", "probability": 90}, {"label": "GUINEA / TEN", "probability": 10},
                {"label": "PETAL / GUINEA", "probability": 50}]
        with patch.object(public_v1.signal_service, "get_active_signals", return_value=sigs), \
             patch.object(public_v1.signal_service, "status", return_value={}):
            out = self.client.get("/api/v1/signals", headers=KEY).json()["signals"]
        self.assertEqual([s["label"] for s in out], ["GUINEA / TEN", "PETAL / GUINEA", "TEN / MINI"])

    def test_international_says_when_ibkr_is_logged_in_elsewhere(self):
        with patch.object(public_v1.ibkr_feed, "get_data", return_value={"connected": True, "competing_session": True}):
            d = self.client.get("/api/v1/international", headers=KEY).json()
        self.assertTrue(d["competing_session"])


if __name__ == "__main__":
    unittest.main()
