import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rvol


class RvolTests(unittest.TestCase):
    def test_u_shape_not_linear_at_105_minutes(self):
        frac = rvol.expected_fraction(105)
        linear = 105 / 390
        self.assertGreater(frac, linear)
        self.assertGreater(frac, 0.30)
        self.assertLess(frac, 0.70)

    def test_raw_vs_pace(self):
        avg = 1_000_000
        minutes = 105
        frac = rvol.expected_fraction(minutes)
        today = avg * frac
        out = rvol.pace_adjusted_rvol(today, avg, minutes)
        self.assertAlmostEqual(out["rvol_pace"], 1.0, places=2)
        self.assertLess(out["rvol_raw"], 0.75)

    def test_full_day(self):
        out = rvol.pace_adjusted_rvol(1_000_000, 1_000_000, 390)
        self.assertAlmostEqual(out["rvol_pace"], 1.0, places=4)
        self.assertAlmostEqual(out["rvol_raw"], 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
