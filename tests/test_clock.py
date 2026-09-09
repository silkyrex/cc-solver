"""The clock guard. Nothing time-dependent may run before this passes.

The bug it exists to stop: a scheduled task hands the solver a pt_time that is actually UTC, or a
stale one from a retry, and pace RVOL plus every provisional exit read is silently wrong.
"""
from datetime import datetime, timedelta

import pytest

from ccsolver import clock


def test_pt_offset_is_resolved_per_date_not_hardcoded():
    assert clock.iso("2026-09-08", "11:50 AM") == "2026-09-08T11:50:00-07:00"   # PDT
    assert clock.iso("2026-12-15", "11:50 AM") == "2026-12-15T11:50:00-08:00"   # PST


def test_both_clocks_parse_and_humans_get_12_hour():
    assert clock.parse_clock("11:50 AM") == clock.parse_clock("11:50") == 710
    assert clock.parse_clock("1:10 PM") == clock.parse_clock("13:10") == 790
    assert clock.parse_clock("12:05 AM") == 5 and clock.parse_clock("12:05 PM") == 725
    assert clock.render(790) == "1:10 PM" and clock.render(710) == "11:50 AM"
    assert clock.render(725) == "12:05 PM" and clock.render(5) == "12:05 AM"


def _now(h, m):
    return datetime(2026, 9, 8, h, m, tzinfo=clock.PT)


def test_on_time_is_clean():
    r = clock.check("2026-09-08", "11:50 AM", now=_now(11, 52))
    assert r["ok"] and not r["warnings"] and abs(r["drift_minutes"]) <= 2


def test_utc_sent_as_pt_is_an_error_not_a_warning():
    """11:50 AM PT is 18:50 UTC. If that lands in pt_time it is 420 minutes off."""
    r = clock.check("2026-09-08", "18:50", now=_now(11, 50))
    assert not r["ok"] and r["drift_minutes"] == 420
    assert "UTC time was sent" in r["errors"][0]


def test_stale_retry_warns_but_proceeds():
    r = clock.check("2026-09-08", "11:50 AM", now=_now(12, 20))
    assert r["ok"] and r["warnings"] and "stale retry" in r["warnings"][0]


def test_future_date_is_refused():
    r = clock.check("2026-09-09", "11:50 AM", now=_now(11, 50))
    assert not r["ok"] and "FUTURE" in r["errors"][0]


def test_replay_warns_and_says_why_live_reads_are_meaningless():
    r = clock.check("2026-09-01", "11:50 AM", now=_now(11, 50))
    assert r["ok"] and "replay" in r["warnings"][0]
    assert r["drift_minutes"] is None      # no clock drift check on a past session


def test_garbage_input_never_raises():
    assert not clock.check("not-a-date", "11:50 AM", now=_now(11, 50))["ok"]
    assert not clock.check("2026-09-08", "half past noon", now=_now(11, 50))["ok"]


def test_live_task_refuses_on_a_bad_clock(tmp_path, capsys):
    import json
    from ccsolver import cli
    (tmp_path / "account.json").write_text(json.dumps({"net_liq": 100000.0, "pt_time": "18:50"}))
    (tmp_path / "calendar.json").write_text(json.dumps({"closed": [], "early": []}))
    rc = cli.main(["take_action", "--inputs", str(tmp_path), "--date", "2026-09-08"])
    out = json.loads(capsys.readouterr().out)
    # Either the clock is genuinely off right now (refused) or the test date is a replay (allowed).
    if rc == 2:
        assert out["status"] == "refused" and out["time_check"]["errors"]
    else:
        assert out["time_check"]["warnings"]      # a past date always warns


def test_every_task_carries_its_time_check(tmp_path, capsys):
    import json
    from ccsolver import cli
    (tmp_path / "calendar.json").write_text(json.dumps({"closed": [], "early": []}))
    cli.main(["calendar", "--inputs", str(tmp_path), "--date", "2026-09-08"])
    out = json.loads(capsys.readouterr().out)
    assert "time_check" in out and out["time_check"]["now_pt"].endswith(("AM", "PM"))
