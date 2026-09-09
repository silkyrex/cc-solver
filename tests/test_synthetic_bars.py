"""Padded bars are stripped before any door is read, and a thin real history is refused.

The feed returns one bar per session across the WHOLE requested range. Sessions before the
listing come back with OHLC all equal, volume 0, and `interpolated: true`, priced at the first
real bar's open. Verified live 2026-09-09: SKHY flat 149.00 before 2026-07-10, SPCX flat 150.00
before 2026-06-12. The task prompts map bars to {date, open, high, low, close, volume}, which
drops the flag, so these are identified by shape too.

The failure this pins is not "the number is slightly off". Left in, the padding also keeps the
bar COUNT above the 21 an EMA needs, so a three-week-old listing produced a confident 21 EMA and
an entry door bound against a price line that never traded -- in the LOOSE direction, because the
pad sits at the listing-day open below a name that has run.
"""
import json
from datetime import date, timedelta

from ccsolver import bars as barlib
from ccsolver import cli, doors, grader


def _sessions(n, start="2026-01-05"):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _real(dates, closes):
    return [{"date": d, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1_000_000}
            for d, c in zip(dates, closes)]


def _pad(dates, price, flag=False):
    """The feed's shape: flat OHLC at the first real open, volume 0."""
    b = [{"date": d, "open": price, "high": price, "low": price, "close": price, "volume": 0} for d in dates]
    if flag:
        for x in b:
            x["interpolated"] = True
    return b


def _listing(n_pad, n_real, base=149.0, step=1.01):
    """n_pad padded sessions at the listing open, then n_real real ones climbing."""
    ds = _sessions(n_pad + n_real)
    closes = [base * (step ** i) for i in range(n_real)]
    return _pad(ds[:n_pad], base) + _real(ds[n_pad:], closes), ds[-1]


def test_is_synthetic_by_shape_and_by_flag():
    assert barlib.is_synthetic({"open": 149.0, "high": 149.0, "low": 149.0, "close": 149.0, "volume": 0})
    assert barlib.is_synthetic({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 0, "interpolated": True})
    assert not barlib.is_synthetic({"open": 149.0, "high": 149.0, "low": 149.0, "close": 149.0, "volume": 12})
    assert not barlib.is_synthetic({"open": 148, "high": 150, "low": 147, "close": 149, "volume": 0})


def test_the_provisional_live_bar_is_never_stripped():
    """With no day_high/day_low in quotes, the live bar collapses to flat OHLC and volume 0.

    It is the bar the whole pre-MOC read depends on, and it sits at the END of the series where
    the trailing trim runs. Without the provisional guard the trim would eat it silently.
    """
    live = {"date": "live", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0,
            "volume": 0, "provisional": True}
    assert not barlib.is_synthetic(live)
    assert barlib.clean([live]) == [live]


def test_clean_trims_both_edges_and_keeps_an_interior_gap():
    ds = _sessions(9)
    b = _pad(ds[:3], 149.0) + _real(ds[3:5], [150, 151]) + _pad(ds[5:6], 151.0) \
        + _real(ds[6:8], [152, 153]) + _pad(ds[8:], 153.0)
    out = barlib.clean(b)
    assert [x["date"] for x in out] == ds[3:8]          # edges gone, interior halt kept
    assert barlib.real_count(out) == 4                   # the halt is not history
    assert barlib.clean(out) == out                      # idempotent


def test_padding_no_longer_changes_a_healthy_name_s_verdict():
    """The trim is a no-op on a name with real history, and proves what it used to change."""
    b, _ = _listing(n_pad=60, n_real=60)
    real_only = b[60:]
    padded = doors.entry_state(b)
    clean = doors.entry_state(real_only)
    assert padded == clean
    assert padded["thin_history"] is False
    assert padded["real_bars"] == 60
    assert padded["ema21"] is not None


def test_thin_history_withholds_the_21_ema_and_binds_the_tight_door():
    """18 real sessions. The padding used to supply the other 70 and a confident 21 EMA."""
    b, _ = _listing(n_pad=70, n_real=18)
    st = doors.entry_state(b)
    assert st["real_bars"] == 18
    assert st["thin_history"] is True
    assert st["ema21"] is None
    # same rule as a held row with no entry_door: unproven against the 21 EMA runs on the leash
    assert st["entry_door"] == "4ema"
    assert "THIN HISTORY" in st["reason"]
    # the 4 EMA read still works; only the unsupported half is withheld
    assert st["ema4"] is not None


def test_thirty_real_sessions_is_the_line():
    assert doors.entry_state(_listing(n_pad=70, n_real=29)[0])["thin_history"] is True
    assert doors.entry_state(_listing(n_pad=70, n_real=30)[0])["thin_history"] is False


def test_exit_state_reports_unknown_rather_than_zero_closes_against_the_21_ema():
    """A silent 0 reads as "no pressure against the door" -- the same lie the padding told."""
    b, _ = _listing(n_pad=70, n_real=18)
    ex = doors.exit_state(b, entry_door_="21ema")
    assert ex["thin_history"] is True
    assert ex["closes_against_21ema"] is None
    assert ex["door_21ema"] == "unknown"
    assert ex["mandatory_exit"] is False        # the test did not run; it did not "pass"
    assert ex["mandatory_reason"] is None
    assert "THIN HISTORY" in ex["note"]


def test_a_deep_break_is_still_mandatory_on_a_thin_history():
    """Deep break is a 4 EMA test, so it survives a withheld 21 EMA."""
    ds = _sessions(80)
    closes = [100.0] * 60 + [100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                             110, 111, 112, 113, 114, 115, 116, 117, 60.0]
    b = _pad(ds[:61], 100.0) + _real(ds[61:61 + len(closes) - 60], closes[60:])
    ex = doors.exit_state(b, entry_door_="21ema")
    assert ex["thin_history"] is True
    assert ex["deep_break_4ema"] is True
    assert ex["mandatory_exit"] is True


def test_position_monitor_pushes_a_thin_history_row(tmp_path):
    """An unreadable door is an unmonitored position, the same argument as SIDE UNKNOWN."""
    b, day = _listing(n_pad=70, n_real=18)
    (tmp_path / "held.json").write_text(json.dumps(
        [{"ticker": "NEW", "entry": 149.0, "initial_stop": 137.0, "side": "long", "entry_door": "21ema"}]))
    (tmp_path / "bars.json").write_text(json.dumps({"NEW": b}))
    (tmp_path / "account.json").write_text(json.dumps({"net_liq": 100000}))
    (tmp_path / "positions.json").write_text(json.dumps({"positions": []}))
    out = cli.position_monitor(str(tmp_path), day)
    assert out["positions"][0]["thin_history"] is True
    assert out["push"] is True


def test_miss_audit_measures_only_sessions_that_traded():
    """The pad sits at the listing-day open, so the SIZE of a spanning move looks about right.

    What it fabricates is the window: a 20-session move that really took five real sessions, dated
    from a day the stock did not trade. Both outputs matter -- window_start is what
    `flagged_before` compares the board's first_seen against, so a phantom start date can clear a
    genuine miss.
    """
    b, _ = _listing(n_pad=40, n_real=25, base=149.0, step=1.02)
    padded_dates = {x["date"] for x in b[:40]}
    for m in grader.miss_audit({"NEW": b}, {}):
        assert m["window_start"] not in padded_dates
        assert m["window_end"] not in padded_dates

    # Five real sessions is not a 20-session window. Before the trim the pad supplied the other
    # fifteen and this returned a confident miss row.
    assert grader.miss_audit({"NEW": _listing(n_pad=60, n_real=5)[0]}, {}) == []
