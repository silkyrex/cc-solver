import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import calendar as calmod


class CalendarTests(unittest.TestCase):
    def test_early_close_nov_27_2026(self):
        s = calmod.session_status("2026-11-27")
        self.assertEqual(s["status"], "early_close")
        self.assertEqual(s["moc_deadline_pt"], "09:45")
        self.assertEqual(s["chain_shift_hours"], 3)

    def test_thanksgiving_closed(self):
        s = calmod.session_status("2026-11-26")
        self.assertEqual(s["status"], "closed")

    def test_regular_weekday(self):
        s = calmod.session_status("2026-09-08")
        self.assertEqual(s["status"], "normal")
        self.assertEqual(s["moc_deadline_pt"], "12:45")
        self.assertEqual(s["chain_shift_hours"], 0)

    def test_weekend(self):
        s = calmod.session_status("2026-09-12")
        self.assertEqual(s["status"], "closed")
        self.assertEqual(s["reason"], "weekend")

    def test_labor_day(self):
        s = calmod.session_status("2026-09-07")
        self.assertEqual(s["status"], "closed")


if __name__ == "__main__":
    unittest.main()
