from ccsolver import doors
from synth import flat_then, bars_from_closes


def test_below_4ema_no_entry():
    b = flat_then([-0.02, -0.02, -0.02])
    s = doors.entry_state(b)
    assert s["reclaim_day"] == 0 and not s["door_open"]


def test_fresh_reclaim_day1_then_day2_then_stale():
    b = flat_then([-0.03, -0.03, -0.03])  # three down closes, price below 4 EMA
    # day 1: last price jumps above the 4 EMA
    s1 = doors.entry_state(b, last_price=b[-1]["close"] * 1.08)
    assert s1["reclaim_day"] == 1 and s1["door_open"] and "day 1" in s1["reason"]
    # settle day 1, then day 2 on live price
    b2 = b + [dict(b[-1], date="d1", close=b[-1]["close"] * 1.08, high=b[-1]["close"] * 1.09, low=b[-1]["close"] * 1.07)]
    s2 = doors.entry_state(b2, last_price=b2[-1]["close"] * 1.01)
    assert s2["reclaim_day"] == 2 and s2["door_open"]
    b3 = b2 + [dict(b2[-1], date="d2", close=b2[-1]["close"] * 1.01)]
    s3 = doors.entry_state(b3, last_price=b3[-1]["close"] * 1.01)
    assert s3["reclaim_day"] == 3 and not s3["door_open"] and "stale" in s3["reason"]


def test_slow_sto_20_low_trigger():
    # steady decline pushes slow %K under 20 while price stays under the 4 EMA, then first close back above
    b = flat_then([-0.02] * 8)
    s_armed = doors.entry_state(b)
    assert s_armed["sto_k"] is not None and s_armed["sto_k"] < 20 and s_armed["sto_20_low_armed"]
    s_trig = doors.entry_state(b, last_price=b[-1]["close"] * 1.06)
    assert s_trig["sto_20_low_trigger"] and s_trig["door_open"] and "slow sto" in s_trig["reason"]


def test_exit_doors_both_flagged():
    up = flat_then([0.01] * 25)  # long run above both EMAs
    assert doors.exit_state(up)["door_4ema"] == "none"
    d1 = up + [dict(up[-1], date="x1", close=up[-1]["close"] * 0.97, low=up[-1]["close"] * 0.96)]
    e1 = doors.exit_state(d1)
    assert e1["door_4ema"] == "day1_discretion" and not e1["mandatory_exit_under_4ema_door"]
    d2 = d1 + [dict(d1[-1], date="x2", close=d1[-1]["close"] * 0.97, low=d1[-1]["close"] * 0.96)]
    e2 = doors.exit_state(d2)
    assert e2["door_4ema"] == "day2_mandatory" and e2["mandatory_exit_under_4ema_door"]
    # 21 EMA door needs two closes below the 21 EMA; two 3% drops from a slow 1%/day climb are not enough
    assert e2["door_21ema"] in ("none", "warn")
    deep = d2 + [dict(d2[-1], date="x3", close=d2[-1]["close"] * 0.90, low=d2[-1]["close"] * 0.89)]
    e3 = doors.exit_state(deep)
    assert e3["deep_break_4ema"]


def test_stop_and_size():
    b = flat_then([0.0] * 5)
    s = doors.entry_state(b, last_price=100.0)
    assert s["stop_pct"] >= 0.08  # ATR on a flat tape is tiny, floor wins
    sz = doors.size(20_000, 100.0, s["stop_pct"], "floor")
    assert sz["shares"] == 30 and abs(sz["loss_at_stop"] - 30 * 8.0) < 1e-6


def test_breakeven_1r():
    assert doors.breakeven_1r(100, 92, 108)
    assert not doors.breakeven_1r(100, 92, 107)
