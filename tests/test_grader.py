import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import grader


class GraderTests(unittest.TestCase):
    def test_forward_returns(self):
        bars = {"AAA": [{"date": f"2026-01-{d:02d}", "close": 100 + d} for d in range(1, 32)]}
        rows = [{"ticker": "AAA", "first_seen": "2026-01-01"}]
        out = grader.grade_rows(rows, bars)
        self.assertIsNotNone(out[0]["ret_5d"])
        self.assertGreater(out[0]["ret_5d"], 0)

    def test_miss_audit_does_not_edit_rules(self):
        moves = [{"ticker": "MISS", "move_20d": 0.22, "class": "universe gap"}]
        props = grader.miss_audit(moves, discovery_tickers=set())
        self.assertEqual(len(props), 1)
        self.assertIn("Do not edit a rule", props[0]["proposal"])


if __name__ == "__main__":
    unittest.main()
