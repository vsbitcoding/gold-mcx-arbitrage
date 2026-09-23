"""MCX-vs-NYMEX volatility backtester on synthetic half-hourly boards.

Every expected number below is worked by hand from the fixture quotes, so a
change in the rules shows up as a wrong number, not as a moved constant.
"""
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

from app.models import CrudeIvSnapshot  # noqa: E402
from app.services import crude_iv_backtest as bt  # noqa: E402
from app.services import iv_calc  # noqa: E402

COLS_MCX = ["strike", "atm", "ce_bid", "ce_ask", "ce_iv", "ce_delta", "ce_wide", "ce_oi",
            "pe_bid", "pe_ask", "pe_iv", "pe_delta", "pe_wide", "pe_oi"]
COLS_US = ["strike", "atm", "ce_bid", "ce_ask", "ce_iv", "ce_delta", "ce_wide",
           "pe_bid", "pe_ask", "pe_iv", "pe_delta", "pe_wide"]


def mrow(strike, atm, ce, pe):
    """ce / pe = (bid, ask, iv) or None."""
    ce = ce or (None, None, None); pe = pe or (None, None, None)
    return [strike, 1 if atm else 0, ce[0], ce[1], ce[2], 0.5, 0, 10, pe[0], pe[1], pe[2], -0.5, 0, 10]


def urow(strike, atm, ce, pe):
    ce = ce or (None, None, None); pe = pe or (None, None, None)
    return [strike, 1 if atm else 0, ce[0], ce[1], ce[2], 0.5, 0, pe[0], pe[1], pe[2], -0.5, 0]


def board(mcx_rows, us_rows, us_expiry="20261015", usdinr=95.0):
    return {"cols_mcx": COLS_MCX, "cols_us": COLS_US,
            "mcx": {"rows": mcx_rows, "expiry": "2026-10-15", "forward": 8500.0, "future": 8500.0},
            "us": {"rows": us_rows, "expiry": us_expiry, "future": 89.5}, "us_currency": "USD", "usdinr": usdinr}


# A flat, even market at every strike except the ones a test pokes.
def base_mcx(over=None):
    over = over or {}
    rows = {8400: (None, None), 8500: (None, None), 8600: (None, None), 9000: (None, None)}
    out = []
    for k in (8400, 8500, 8600, 9000):
        ce, pe = over.get(k, ((50, 52, 45), (50, 52, 45)))
        out.append(mrow(float(k), k == 8500, ce, pe))
    return out


def base_us(over=None):
    over = over or {}
    out = []
    for k in (88.0, 88.5, 89.0, 89.5, 90.0, 90.5):
        ce, pe = over.get(k, ((0.5, 0.52, 45), (0.5, 0.52, 45)))
        out.append(urow(k, k == 89.5, ce, pe))
    return out


class CrudeIvBacktestTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        CrudeIvSnapshot.__table__.create(engine)
        self.Session = sessionmaker(bind=engine)
        p = patch.object(bt, "SessionLocal", self.Session); p.start(); self.addCleanup(p.stop)
        bt._cache.clear()
        # board 1: 8500 CE MCX IV 50 vs NYMEX 89.5 CE IV 44 -> gap +6 -> sell MCX, buy NYMEX
        #          9000 CE gap +10 but 9000/95 = 94.7 has no NYMEX strike within half a rung -> no trade
        b1 = board(base_mcx({8500: ((100, 102, 50), (50, 52, 45)), 9000: ((20, 22, 55), (50, 52, 45))}),
                   base_us({89.5: ((1.00, 1.04, 44), (0.5, 0.52, 44))}))
        # board 2 (12:00): the gap narrows to +2 -> exit "gap closed"
        b2 = board(base_mcx({8500: ((90, 92, 47), (50, 52, 45))}),
                   base_us({89.5: ((1.10, 1.14, 45), (0.5, 0.52, 44))}))
        # board 2b (12:30): NYMEX chain wearing NOVEMBER's expiry -> the board is dropped
        b2b = board(base_mcx({8500: ((10, 12, 80), (50, 52, 45))}), base_us(), us_expiry="20261115")
        # board 3 (next day): 8600 CE MCX IV 40 vs NYMEX 90.5 CE IV 46 -> gap -6 -> sell NYMEX, buy MCX
        b3 = board(base_mcx({8600: ((60, 62, 40), (50, 52, 45))}),
                   base_us({90.5: ((0.80, 0.84, 46), (0.5, 0.52, 45))}))
        # board 4: the 8600 CE has no MCX quote any more -> no mark
        b4 = board(base_mcx({8600: (None, (50, 52, 45))}), base_us({90.5: ((0.80, 0.84, 46), (0.5, 0.52, 45))}))
        # board 5 (12-Oct, on/after the square-off day 10-Oct): still no quote -> the trade waits; no new entries
        b5 = board(base_mcx({8600: (None, (50, 52, 45)), 8500: ((100, 102, 60), (50, 52, 45))}),
                   base_us({90.5: ((0.80, 0.84, 46), (0.5, 0.52, 45)), 89.5: ((1.00, 1.04, 44), (0.5, 0.52, 44))}))
        # board 6 (15-Oct, the expiry): still no quote -> ended at the last mark
        b6 = board(base_mcx({8600: (None, (50, 52, 45))}), base_us({90.5: ((0.80, 0.84, 46), (0.5, 0.52, 45))}))
        rows = [("2026-09-01", "09:00", b1), ("2026-09-01", "12:00", b2), ("2026-09-01", "12:30", b2b),
                ("2026-09-02", "09:00", b3), ("2026-09-03", "09:00", b4), ("2026-10-12", "09:00", b5),
                ("2026-10-15", "09:00", b6)]
        with self.Session() as db:
            for i, (d, slot, payload) in enumerate(rows, 1):
                db.add(CrudeIvSnapshot(id=i, snap_date=d, slot=slot, commodity="crude", month=0, weekday=1,
                                       mcx_forward=8500.0, mcx_future=8500.0, us_future=89.5, usdinr=95.0,
                                       mcx_atm_iv=50.0, us_atm_iv=44.0, iv_diff=6.0, payload_json=json.dumps(payload),
                                       created_at=datetime(2026, 9, 1, 9, 0)))
            db.commit()

    def run_bt(self, **kw):
        bt._cache.clear()
        return bt.run({"commodity": "crude", "month": 0, **kw})

    def test_boards_drop_the_month_mismatch(self):
        r = self.run_bt()
        self.assertEqual(r["coverage"]["boards"], 6)
        self.assertEqual(r["coverage"]["first"], "2026-09-01T09:00")

    def test_entry_and_gap_close_at_mid(self):
        r = self.run_bt()
        t = next(x for x in r["trades"] if x["mcx_strike"] == 8500)
        self.assertEqual((t["side"], t["us_strike"], t["sell_exch"], t["buy_exch"]), ("CE", 89.5, "MCX", "NYMEX"))
        self.assertEqual((t["mcx_iv"], t["us_iv"], t["diff"]), (50, 44, 6.0))
        self.assertEqual(t["sell_px"], 101.0)                      # MCX mid of 100 / 102
        self.assertEqual(t["buy_px"], 96.9)                        # NYMEX mid 1.02 x 95
        self.assertEqual((t["exit_ts"], t["exit_reason"], t["exit_diff"]), ("2026-09-01T12:00", "gap closed", 2.0))
        self.assertEqual(t["sell_exit"], 91.0)                     # bought back at MCX mid 90 / 92
        self.assertEqual(t["buy_exit"], 106.4)                     # sold at NYMEX mid 1.12 x 95
        self.assertEqual(t["pnl_points"], 19.5)                    # (101 - 91) + (106.4 - 96.9)
        self.assertEqual(t["pnl_rs"], 1950)                        # x 100 barrels
        self.assertEqual(t["hours"], 3.0)
        self.assertEqual([x["note"] for x in t["path"]], ["entry", "gap closed"])
        # 9000 CE had a 10-point gap but no NYMEX strike within half a rung of 94.7
        self.assertFalse(any(x["mcx_strike"] == 9000 for x in r["trades"]))

    def test_price_rules(self):
        client = next(x for x in self.run_bt(price_rule="client")["trades"] if x["mcx_strike"] == 8500)
        # sell MCX at ask 102, buy NYMEX at bid 1.00 x 95 = 95; exit: buy back at bid 90, sell at ask 1.14 x 95 = 108.3
        self.assertEqual((client["sell_px"], client["buy_px"], client["sell_exit"], client["buy_exit"]), (102.0, 95.0, 90.0, 108.3))
        self.assertEqual(client["pnl_points"], 25.3)
        market = next(x for x in self.run_bt(price_rule="market")["trades"] if x["mcx_strike"] == 8500)
        # sell MCX at bid 100, buy NYMEX at ask 1.04 x 95 = 98.8; exit: buy back at ask 92, sell at bid 1.10 x 95 = 104.5
        self.assertEqual((market["sell_px"], market["buy_px"], market["sell_exit"], market["buy_exit"]), (100.0, 98.8, 92.0, 104.5))
        self.assertEqual(market["pnl_points"], 13.7)

    def test_reverse_direction_square_off_at_last_mark_and_no_late_entries(self):
        r = self.run_bt()
        t = next(x for x in r["trades"] if x["mcx_strike"] == 8600)
        self.assertEqual((t["sell_exch"], t["buy_exch"], t["us_strike"], t["diff"]), ("NYMEX", "MCX", 90.5, -6.0))
        self.assertEqual(t["sell_px"], 77.9)                       # NYMEX mid 0.82 x 95
        self.assertEqual(t["buy_px"], 61.0)
        # no MCX quote after entry: the bought 8600 call is valued by Black-76 off the 8500 future at the NYMEX
        # 90.5 call's IV (46%) for the time left to 15-Oct; the sold NYMEX leg at mid 0.82 x 95 = 77.9. It squares
        # off on the first board on/after 10-Oct (12-Oct) and is flagged approx.
        model = iv_calc.price(8500.0, 8600.0, iv_calc.years_to("2026-10-15", now=datetime(2026, 10, 12, 9, 0)), 0.46, True)
        self.assertEqual((t["exit_ts"], t["exit_reason"]), ("2026-10-12T09:00", "square off"))
        self.assertEqual((t["sell_exit"], t["buy_exit"], t["approx"]), (77.9, round(model, 2), True))
        self.assertEqual(t["pnl_points"], round((77.9 - 77.9) + (model - 61.0), 2))
        self.assertEqual(t["last_mark_ts"], "2026-09-02T09:00")
        self.assertIn("model", t["path"][-1]["note"])
        self.assertEqual(t["path"][1]["note"], "model value")
        # 15-Oct board: the trade is already closed, nothing else opens
        self.assertTrue(all(x["entry_ts"] < "2026-10-10" for x in r["trades"]))
        # the 8500 CE showed a 16-point gap on the square-off board: no entry on or after that day
        self.assertEqual(len(r["trades"]), 2)
        self.assertEqual(r["summary"]["unpriced_exits"], 1)
        self.assertEqual(r["summary"]["pnl_points"], round(19.5 + t["pnl_points"], 2))

    def test_direction_filter_sides_and_band(self):
        us_high = self.run_bt(direction="us_high")["trades"]
        self.assertEqual([t["mcx_strike"] for t in us_high], [8600.0])
        mcx_high = self.run_bt(direction="mcx_high")["trades"]
        self.assertEqual([t["mcx_strike"] for t in mcx_high], [8500.0])
        self.assertEqual(self.run_bt(sides="PE")["trades"], [])
        self.assertEqual([t["mcx_strike"] for t in self.run_bt(otm_max=50)["trades"]], [8500.0])
        # liquid strikes (client, 23-Sep): 500-multiples only keeps 8500, drops the 8600 trade
        self.assertEqual([t["mcx_strike"] for t in self.run_bt(strike_step=500)["trades"]], [8500.0])
        self.assertEqual(self.run_bt(strike_step=1000)["trades"], [])
        self.assertEqual([t["mcx_strike"] for t in self.run_bt(strike_step=0)["trades"]], [8500.0, 8600.0])

    def test_stop_loss_and_validation(self):
        # client rule from the NYMEX-high trade's view: nothing moves, so no stop; a 1-point stop on the 8500 trade
        # cannot fire either because that trade only ever gains. The validation is what must hold.
        with self.assertRaisesRegex(ValueError, "smaller than the entry"):
            self.run_bt(exit_diff=5, entry_diff=5)
        with self.assertRaisesRegex(ValueError, "above zero"):
            self.run_bt(lot_size=0)
        with self.assertRaisesRegex(ValueError, "negative"):
            self.run_bt(strike_step=-100)
        self.assertEqual(self.run_bt(lot_size=1250)["trades"][0]["pnl_rs"], 24375)   # 19.5 x 1250


if __name__ == "__main__":
    unittest.main()
