import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import doors
from tests.synth import ohlc_from_closes


def eval_closes(closes, last=None):
    b = ohlc_from_closes(closes)
    return doors.evaluate("TEST", b["dates"], b["opens"], b["highs"], b["lows"], b["closes"], last=last)


class DoorTests(unittest.TestCase):
    def test_reclaim_day_0_below(self):
        closes = [10] * 8 + [9, 8.5]
        v = eval_closes(closes)
        self.assertEqual(v.reclaim_day, 0)

    def test_reclaim_day_1(self):
        closes = [10] * 6 + [8, 8, 12]
        v = eval_closes(closes)
        self.assertEqual(v.reclaim_day, 1)

    def test_reclaim_day_2(self):
        closes = [10] * 6 + [8, 8, 12, 12.2]
        v = eval_closes(closes)
        self.assertEqual(v.reclaim_day, 2)

    def test_reclaim_day_3_stale(self):
        closes = [10] * 6 + [8, 8, 12, 12.2, 12.4]
        v = eval_closes(closes)
        self.assertGreaterEqual(v.reclaim_day, 3)

    def test_slow_sto_20_low(self):
        closes = [20] * 8 + [5, 4, 3.5, 3.2, 3.0, 3.1, 18]
        b = ohlc_from_closes(closes, width=0.2)
        v = doors.evaluate("TEST", b["dates"], b["opens"], b["highs"], b["lows"], b["closes"])
        self.assertEqual(v.reclaim_day, 1)
        self.assertTrue(v.slow_sto_20_low)

    def test_exit_4ema_day1(self):
        closes = [10] * 10 + [12, 12, 12, 11.2]
        v = eval_closes(closes)
        self.assertEqual(v.exit_4ema, "day1_discretion")
        self.assertFalse(v.deep_break)

    def test_exit_4ema_day2_mandatory(self):
        closes = [10] * 10 + [12, 12, 8, 7.5]
        v = eval_closes(closes)
        self.assertEqual(v.exit_4ema, "day2_mandatory")

    def test_deep_break(self):
        closes = [10] * 12 + [12, 5]
        v = eval_closes(closes)
        self.assertTrue(v.deep_break)
        self.assertEqual(v.exit_4ema, "day1_discretion")

    def test_exit_21ema_warn_and_mandatory(self):
        up = [10 + i * 0.3 for i in range(30)]
        warn = eval_closes(up + [up[-1] - 8])
        self.assertEqual(warn.exit_21ema, "warn")
        mand = eval_closes(up + [up[-1] - 8, up[-1] - 9])
        self.assertEqual(mand.exit_21ema, "mandatory_2nd_close")

    def test_stop_from_current_price(self):
        closes = [100] * 20
        b = ohlc_from_closes(closes, width=2.0)
        v = doors.evaluate("TEST", b["dates"], b["opens"], b["highs"], b["lows"], b["closes"], last=100)
        self.assertIsNotNone(v.stop_price)
        self.assertLess(v.stop_price, 100)
        self.assertGreaterEqual(v.stop_pct, 0.08)
        self.assertIn(v.stop_binds, ("8%", "2xATR14"))

    def test_new_high(self):
        closes = list(range(1, 40))
        v = eval_closes(closes)
        self.assertTrue(v.new_high)


if __name__ == "__main__":
    unittest.main()
