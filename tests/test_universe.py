import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import universe


class UniverseTests(unittest.TestCase):
    def test_take_action_drops_scan_only_names(self):
        rows = universe.build_universe(
            roster=["SNDK"],
            discovery=[{"ticker": "BE"}],
            positions=["PSX"],
            rh_scan_rows=[{"ticker": "LABU"}, {"ticker": "ZZZZ"}],
        )
        tickers = {r["ticker"]: r for r in rows}
        self.assertIn("LABU", tickers)
        self.assertTrue(tickers["LABU"]["excluded"])
        action = universe.take_action_set(rows)
        action_t = {r["ticker"] for r in action}
        self.assertEqual(action_t, {"SNDK", "BE", "PSX"})
        self.assertNotIn("ZZZZ", action_t)

    def test_scan_cap_note_sample(self):
        sample = [{"ticker": f"T{i}"} for i in range(399)]
        rows = universe.build_universe(roster=["AA"], discovery=[], positions=[], rh_scan_rows=sample)
        self.assertTrue(any(r["sample_only"] for r in rows if r["ticker"] != "AA"))

    def test_massive_stub(self):
        with self.assertRaises(NotImplementedError):
            universe.massive_universe()


if __name__ == "__main__":
    unittest.main()
