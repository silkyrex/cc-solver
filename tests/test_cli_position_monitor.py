"""position_monitor: a held row with no entry_door must run on the TIGHT 4 EMA door.

The Positions DB starts empty, so the first Position monitor run backfills every held name with
Entry door EMPTY, and the prompt omits empty keys from held.json. If the missing key defaulted to
the loose 21 EMA door, every live position would silently get the loose leash on that first run.
Ray ruled 2026-09-08: a position that cannot prove it was ever on the favourable side of the 21 EMA
runs on the 4 EMA door until it graduates.
"""
import json
from datetime import date, timedelta

from ccsolver import cli


def _rising_bars(n=45, start="2025-10-01"):
    d, ds = date.fromisoformat(start), []
    while len(ds) < n:
        if d.weekday() < 5:
            ds.append(d.isoformat())
        d += timedelta(days=1)
    closes = [100 * (1.01 ** i) for i in range(n)]
    return [{"date": ds[i], "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1}
            for i, c in enumerate(closes)], ds[-1]


def test_held_row_without_entry_door_gets_the_tight_4ema_door(tmp_path):
    b, day = _rising_bars()
    # deliberately NO entry_door and NO entry_datetime on the row -- the backfilled shape
    (tmp_path / "held.json").write_text(json.dumps(
        [{"ticker": "AAA", "entry": b[0]["close"], "initial_stop": b[0]["close"] * 0.9, "side": "long"}]))
    (tmp_path / "bars.json").write_text(json.dumps({"AAA": b}))
    (tmp_path / "account.json").write_text(json.dumps({"net_liq": 100000}))
    (tmp_path / "positions.json").write_text(json.dumps({"positions": []}))

    out = cli.position_monitor(str(tmp_path), day)
    row = out["positions"][0]
    assert row["ticker"] == "AAA"
    assert row["entry_door"] == "4ema"
    assert row["active_door"] == "4ema"
    assert row["graduated"] is False
