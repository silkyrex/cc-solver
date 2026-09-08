import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExposureTests(unittest.TestCase):
    def test_verbatim_under_cap(self):
        payload = {
            "positions": [
                {"asset_class": "STK", "contract_description": "AAPL", "market_value": 20000},
                {"asset_class": "STK", "contract_description": "SPY", "market_value": 50000},
            ]
        }
        proc = subprocess.run(
            [sys.executable, str(ROOT / "exposure.py"), json.dumps(payload), "100000"],
            capture_output=True,
            text=True,
            check=True,
        )
        line = proc.stdout.strip()
        self.assertIn("gross 20%", line)
        self.assertIn("net 20%", line)
        self.assertNotIn("BREACH", line)

    def test_verbatim_breach(self):
        payload = {
            "positions": [
                {"asset_class": "STK", "contract_description": "NVDA", "market_value": 160000},
            ]
        }
        proc = subprocess.run(
            [sys.executable, str(ROOT / "exposure.py"), json.dumps(payload), "100000"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("BREACH", proc.stdout)
        self.assertIn("GROSS OVER", proc.stdout)


if __name__ == "__main__":
    unittest.main()
