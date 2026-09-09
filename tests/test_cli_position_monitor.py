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


def _falling_bars(n=45, start="2026-04-01"):
    """A window entirely under the 21 EMA: nothing in it can graduate anything."""
    d, ds = date.fromisoformat(start), []
    while len(ds) < n:
        if d.weekday() < 5:
            ds.append(d.isoformat())
        d += timedelta(days=1)
    closes = [100 * (0.99 ** i) for i in range(n)]
    return [{"date": ds[i], "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1}
            for i, c in enumerate(closes)], ds[-1]


def _inputs(tmp_path, held, bars):
    (tmp_path / "held.json").write_text(json.dumps(held))
    (tmp_path / "bars.json").write_text(json.dumps(bars))
    (tmp_path / "account.json").write_text(json.dumps({"net_liq": 100000}))
    (tmp_path / "positions.json").write_text(json.dumps({"positions": []}))


def test_position_monitor_reads_graduated_date_off_the_held_row(tmp_path):
    """The bug this closes: `graduated_date` was written everywhere and read nowhere.

    The Positions DB stores it as "Graduated on" and the prompt already maps it into held.json, but
    position_monitor never passed it down, so `exit_state` re-derived graduation from the 130 days
    of bars the harness pulls. A position held longer than that window loses the session it
    graduated on and gets demoted to the tight 4 EMA door -- an early forced exit on the
    longest-held position, which is where this system's return lives.
    """
    b, day = _falling_bars()
    row = {"ticker": "AAA", "entry": 200.0, "initial_stop": 180.0, "side": "long",
           "entry_door": "4ema", "entry_datetime": "2025-09-15T11:52:00-07:00"}

    _inputs(tmp_path, [row], {"AAA": b})
    demoted = cli.position_monitor(str(tmp_path), day)["positions"][0]
    assert demoted["active_door"] == "4ema"             # re-derivation alone cannot see the graduation

    _inputs(tmp_path, [dict(row, graduated_date="2025-11-04")], {"AAA": b})
    kept = cli.position_monitor(str(tmp_path), day)["positions"][0]
    assert kept["graduated"] and kept["active_door"] == "21ema"
    assert kept["graduated_source"] == "stored" and kept["graduated_date"] == "2025-11-04"


def test_a_derived_graduation_comes_back_as_a_payload_to_write(tmp_path):
    """Reading the field is only half the fix: something has to WRITE it the day it is derived.

    Until "Graduated on" is filled, the position is one long hold away from the same demotion, so
    the derived date leaves the solver as a payload EOD can put on the Positions DB row.
    """
    b, day = _rising_bars()
    _inputs(tmp_path, [{"ticker": "AAA", "entry": b[0]["close"], "initial_stop": b[0]["close"] * 0.9,
                        "side": "long", "entry_door": "4ema", "entry_datetime": b[0]["date"],
                        "graduated_date": None}], {"AAA": b})
    out = cli.position_monitor(str(tmp_path), day)
    row = out["positions"][0]
    assert row["graduated"] and row["graduated_source"] == "derived"
    assert out["graduated_payloads"] == [{"ticker": "AAA", "Graduated on": row["graduated_date"]}]

    # a graduation already on the row is already written; nothing to write again
    _inputs(tmp_path, [{"ticker": "AAA", "entry": b[0]["close"], "initial_stop": b[0]["close"] * 0.9,
                        "side": "long", "entry_door": "4ema", "entry_datetime": b[0]["date"],
                        "graduated_date": row["graduated_date"]}], {"AAA": b})
    assert cli.position_monitor(str(tmp_path), day)["graduated_payloads"] == []


def test_a_refused_graduated_date_pushes(tmp_path):
    """A "Graduated on" that predates the entry is a broken Positions DB row, and only Ray can say
    which half is wrong. The row is still answered off the tight door, and it pushes -- an
    unreported contradiction in the position record is how a leash silently ends up wrong."""
    b, day = _falling_bars()
    _inputs(tmp_path, [{"ticker": "AAA", "entry": 200.0, "initial_stop": 180.0, "side": "long",
                        "entry_door": "4ema", "entry_datetime": "2026-04-20T11:52:00-07:00",
                        "graduated_date": "2026-01-05"}], {"AAA": b})
    out = cli.position_monitor(str(tmp_path), day)
    assert "before entry" in out["positions"][0]["graduated_date_error"]
    assert out["positions"][0]["active_door"] == "4ema"
    assert out["push"] is True
