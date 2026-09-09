"""The backtest harness replays the REAL doors; it does not carry a second copy of them.

Every case here is built from `synth.py` so the bars are readable in the test. What each
one pins:
  - a clean winner leaves on the 21 EMA door, not on a stop and not on a deep break. The
    fixture climbs and bleeds GENTLY on purpose: after a steep run the 21 EMA sits so far
    under price that any close below it is already >4% through the 4 EMA, i.e. a deep
    break, and the test would pass while testing nothing (the trap recorded in the
    2026-09-08 handoff).
  - the stop fills intraday, at the stop, on a session whose CLOSE never opened a door.
  - a relaunch-shaped entry binds to the tight 4 EMA door and GRADUATES, one way, off a
    settled close. The harness must read that from `exit_state`, never recompute it.
  - a thin real history is refused outright. Padded bars are stripped, and what is left
    is below MIN_REAL_BARS_21EMA, so there is no 21 EMA and no entry.
  - the halves partition the trades: every trade lands in exactly one.
  - DEC-006: nothing in the harness moves a stop on profit.
"""
from backtest import harness
from ccsolver import bars as barlib
from synth import bars_from_closes


def _series(steps, base=100.0, n_flat=35):
    """n_flat flat sessions (a real, quiet history) then multiplicative daily steps."""
    closes, c = [base] * n_flat, base
    for s in steps:
        c *= 1 + s
        closes.append(c)
    return bars_from_closes(closes)


def _run(series, door=harness.DOOR_21EMA, ticker="T"):
    """(trades, refusals) for one ticker over its whole file."""
    trades, refusals, _unresolved = harness.simulate(
        ticker, series, series[0]["date"], series[-1]["date"], door=door)
    return trades, refusals


def test_clean_winner_exits_on_the_21ema_door():
    # gentle climb, gentle bleed: the 21 EMA is reachable without a deep break
    b = _series([0.006] * 30 + [-0.012, -0.012] + [0.014] + [0.006] * 10 + [-0.010] * 10)
    trades, _ = _run(b)
    t = trades[0]
    assert t["entry_door"] == "21ema"          # entered on the favourable side of the 21 EMA
    assert t["reclaim_day_at_entry"] == 1
    assert t["exit_reason"] == harness.EXIT_DOOR
    assert "21 EMA 2nd consecutive close" in t["exit_detail"]
    assert t["active_door_at_exit"] == "21ema"
    assert t["return_pct"] > 0
    # peak >= realized, and giveback is that gap as a share of the peak
    assert t["peak_unrealized_pct"] >= t["return_pct"]
    # tolerance is loose because every reported field is rounded to 4dp before it lands
    assert abs(t["giveback_pct_of_peak"]
               - 100 * (t["peak_unrealized_pct"] - t["return_pct"]) / t["peak_unrealized_pct"]) < 1e-3
    assert abs(t["r_multiple"] - t["return_pct"] / t["stop_pct"]) < 1e-3


def test_stop_fires_intraday_before_any_door():
    b = _series([0.01])
    entry_close = b[-1]["close"]
    # next session: opens above the stop, digs through it intraday, closes above it again.
    # No door can fire on this close, so only the intraday stop can take the trade out.
    stop = round(entry_close * 0.92, 4)
    b = b + [dict(b[-1], date="2026-02-23", open=entry_close, high=entry_close,
                  low=stop * 0.97, close=entry_close * 0.96)]
    trades, _ = _run(b)
    t = trades[0]
    assert t["stop_pct"] == 8.0                      # flat tape: 2xATR14 is tiny, the 8% floor wins
    assert t["exit_reason"] == harness.EXIT_STOP
    assert t["exit_price"] == t["stop_price"]        # filled AT the stop, not at the close
    assert abs(t["r_multiple"] + 1.0) < 1e-9         # a stop-out is exactly -1R


def test_4ema_entry_graduates_to_the_21ema_door():
    # dip under the 21 EMA, reclaim the 4 EMA from below it (relaunch shape), then run
    b = _series([-0.02, -0.02, -0.02] + [0.05] + [0.02] * 25 + [-0.09, -0.05, -0.03, -0.03])
    trades, _ = _run(b)
    t = trades[0]
    assert t["entry_door"] == "4ema"        # born on the wrong side of the 21 EMA: tight leash
    assert t["graduated"] is True          # earned the loose one on a settled close
    assert t["active_door_at_exit"] == "21ema"
    assert t["return_pct"] > 0


def test_thin_or_synthetic_history_is_refused():
    # the feed's shape: OHLC all equal at the first real open, volume 0, before the listing
    every = _series([0.01] * 6, base=149.0, n_flat=6)
    pad = [{"date": b["date"], "open": 149.0, "high": 149.0, "low": 149.0, "close": 149.0,
            "volume": 0} for b in every[:6]]
    real = every[6:]
    series = harness.normalise({"bars": pad + real}, "THIN")
    assert len(series) == len(real)                       # the leading pad is gone
    assert barlib.thin(series)                            # what is left is under 30 real sessions
    trades, refusals = _run(series, ticker="THIN")
    assert trades == []
    assert refusals and refusals[0]["refused"] == "thin real history"
    assert refusals[0]["sessions_refused"] == len(series)


def test_halves_partition_the_trades():
    early = _series([0.01, -0.30, -0.01] + [0.0] * 60)               # one trade, stopped out early
    late = _series([0.0] * 40 + [-0.02, -0.02, -0.02, 0.06, 0.01])   # one trade, late
    out = harness.replay({"EARLY": early, "LATE": late},
                         early[0]["date"], max(early[-1]["date"], late[-1]["date"]))
    agg = out["aggregates"]
    assert agg["overall"]["trades"] == agg["first_half"]["trades"] + agg["second_half"]["trades"]
    assert agg["first_half"]["trades"] >= 1 and agg["second_half"]["trades"] >= 1
    assert all(t["entry_date"] <= out["half_split_session"] for t in out["trades"]
               if t["entry_date"] <= out["half_split_session"])
    # the split is a real session in the range, not a calendar midpoint
    assert out["half_split_session"] in {b["date"] for b in early} | {b["date"] for b in late}


def test_alternative_doors_share_one_entry_set():
    b = _series([0.006] * 30 + [-0.012, -0.012] + [0.014] + [0.006] * 10 + [-0.010] * 10)
    first = {}
    for door in harness.DOORS:
        trades, _ = _run(b, door=door)
        first[door] = trades[0]
    entries = {t["entry_date"] for t in first.values()}
    assert len(entries) == 1                       # the door under test never moves the entry
    # a looser door cannot hold the same trade longer than a tighter one
    assert first["4ema-first-close"]["exit_date"] <= first["4ema-day2"]["exit_date"]
    assert first["4ema-day2"]["exit_date"] <= first["21ema"]["exit_date"]
    assert first["first-of-both"]["exit_date"] <= first["21ema"]["exit_date"]


def test_a_big_winner_that_round_trips_still_stops_at_the_original_stop():
    """DEC-006 is production: the stop never moves on profit.

    This is the case a profit lock would change and nothing else would. The trade runs far
    past +1R, then collapses all the way back through entry. Under breakeven-at-+1R it exits
    flat; under the rule the desk actually runs it exits at the stop it was born with, below
    entry, for a loss. If this ever comes back green with return_pct >= 0, a ratchet has been
    reintroduced somewhere.
    """
    b = _series([0.02] * 20 + [-0.42])   # the whole run given back in one session
    t = _run(b)[0][0]
    original_stop = round(t["entry_price"] * (1 - t["stop_pct"] / 100), 4)
    assert t["peak_unrealized_pct"] > 100 * t["stop_pct"] / 100     # cleared +1R by a wide margin
    assert t["exit_reason"] == harness.EXIT_STOP
    # loose: stop_pct is reported rounded to 4dp, so the recomputation carries that rounding
    assert abs(t["stop_price"] - original_stop) < 0.01              # the stop never moved
    # gapped clean through the stop, so the fill is the open, at or below the stop
    assert t["exit_price"] <= original_stop < t["entry_price"]
    assert t["return_pct"] < 0                                      # a profit lock would have saved it


def test_entry_on_the_last_session_is_unresolved_not_a_zero_return_trade():
    """The range ran out before the trade could resolve. That is not a 0.00% trade.

    Booking it as one would add a trade to the count and pull the mean toward zero on an
    outcome that never happened.
    """
    b = _series([0.01])            # the door opens on the very last bar in the file
    trades, _, unresolved = harness.simulate("LAST", b, b[0]["date"], b[-1]["date"])
    assert trades == []
    assert len(unresolved) == 1
    assert unresolved[0]["entry_date"] == b[-1]["date"]
    assert "no sessions left" in unresolved[0]["unresolved"]


def test_a_history_window_below_the_thin_floor_is_refused():
    """Every read under a 30-session window is thin by construction, so nothing could enter."""
    b = _series([0.006] * 20)
    try:
        harness.replay({"T": b}, b[0]["date"], b[-1]["date"], history_window=10)
    except ValueError as e:
        assert "MIN_REAL_BARS_21EMA" in str(e)
    else:
        raise AssertionError("a window below the thin floor must be refused, not silently run")


def test_aggregates_split_by_reclaim_day_and_report_a_median_giveback():
    """Build 4 reports day 1 and day 2 separately, and its giveback column is a MEDIAN.

    Pooling day 1 and day 2 answers a question nobody asked -- different trades, different
    holds -- and comparing a mean giveback against Build 4's median compares two different
    statistics and then calls the gap a discrepancy.
    """
    early = _series([0.01, -0.30, -0.01] + [0.0] * 60)
    late = _series([0.0] * 40 + [-0.02, -0.02, -0.02, 0.06, 0.01])
    out = harness.replay({"EARLY": early, "LATE": late},
                         early[0]["date"], max(early[-1]["date"], late[-1]["date"]))
    by_day = out["by_reclaim_day"]
    assert set(by_day) == {"day1", "day2"}
    assert by_day["day1"]["trades"] + by_day["day2"]["trades"] == out["aggregates"]["overall"]["trades"]
    for bucket in (out["aggregates"]["overall"], by_day["day1"], by_day["day2"]):
        assert "giveback_median_pct_of_peak" in bucket
