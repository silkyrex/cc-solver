"""confirm_pass at 12:25 PM re-checks the 11:50 AM staged names against the 4 EMA.

Held names are NOT its job. position_monitor runs the same 12:25 PM slot and owns the provisional
exit read off the Positions DB (Ray, 2026-09-08); checking held names in both would push the same
name twice in the 20 minutes before the 12:45 PM MOC deadline. See test_cli_position_monitor.
"""
import json
from datetime import date, timedelta

import pytest

from ccsolver import cli


def _weekdays(n, start="2025-10-01"):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _rising_bars(n=45):
    """A clean uptrend, so the last settled close sits above the 4 EMA.

    The flip is then driven purely by the live price the test passes in, which is the only thing
    that changes between 11:50 AM and 12:25 PM.
    """
    closes = [100 * (1.01 ** i) for i in range(n)]
    ds = _weekdays(n)
    return [{"date": ds[i], "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1}
            for i, c in enumerate(closes)], ds[-1]


def _inputs(tmp_path, bars=None, quotes=None, staged=None):
    b, last_day = _rising_bars()
    files = {
        "staged": staged if staged is not None else [{"ticker": "AAA"}],
        "bars": {"AAA": b} if bars is None else bars,
        "quotes": quotes if quotes is not None else {},
        "calendar": {"closed": [], "early": []},
    }
    for name, obj in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(obj))
    return str(tmp_path), last_day


def test_flip_below_the_4ema_is_pushed(tmp_path):
    b, _ = _rising_bars()
    settled = b[-1]["close"]
    # 12% under yesterday's close drags the live bar decisively below the 4 EMA
    d, day = _inputs(tmp_path, quotes={"AAA": {"last": settled * 0.88}})
    out = cli.confirm_pass(d, day)
    assert out["moc_deadline_pt"] == "12:45"
    assert out["checked"] == 1
    assert len(out["flips"]) == 1
    assert out["flips"][0]["ticker"] == "AAA"
    assert out["flips"][0]["price"] < out["flips"][0]["ema4"]
    assert out["push"] is True                       # this has to reach Ray before 12:45 PM


def test_still_above_the_4ema_stays_quiet(tmp_path):
    b, _ = _rising_bars()
    d, day = _inputs(tmp_path, quotes={"AAA": {"last": b[-1]["close"] * 1.02}})
    out = cli.confirm_pass(d, day)
    assert out["flips"] == [] and out["skipped"] == [] and out["push"] is False


def test_held_names_are_not_read_here(tmp_path):
    """A held.json sitting in the input dir must not produce a verdict or a push.

    Guards the 2026-09-08 ruling: position_monitor owns held names at this slot.
    """
    b, _ = _rising_bars()
    d, day = _inputs(tmp_path, quotes={"AAA": {"last": b[-1]["close"] * 1.02}})
    (tmp_path / "held.json").write_text(json.dumps(
        [{"ticker": "ZZZ", "entry": 60.0, "initial_stop": 55.0, "side": "long",
          "entry_door": "4ema", "entry_datetime": "2025-11-03T11:50:00-07:00"}]))
    out = cli.confirm_pass(d, day)
    assert "pending_exits" not in out
    assert out["push"] is False
    assert [f["ticker"] for f in out["flips"]] == []


@pytest.mark.parametrize("bars,quotes,reason", [
    ({"AAA": []}, {"AAA": {"last": 100.0}}, "no bars"),
    (None, {}, "no live quote"),
])
def test_an_unusable_staged_name_is_reported_not_dropped(tmp_path, bars, quotes, reason):
    """Silence and a clean pass must never look the same.

    Empty bars additionally raised IndexError inside entry_state before this guard existed, which
    would have killed the whole 12:25 PM run over one bad ticker.
    """
    d, day = _inputs(tmp_path, bars=bars, quotes=quotes)
    out = cli.confirm_pass(d, day)
    assert out["skipped"] == [{"ticker": "AAA", "reason": reason}]
    assert out["flips"] == [] and out["push"] is False


def test_nothing_staged_is_a_clean_no_push(tmp_path):
    d, day = _inputs(tmp_path, staged=[])
    out = cli.confirm_pass(d, day)
    assert out["checked"] == 0 and out["flips"] == [] and out["push"] is False
