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
    assert e1["door_4ema"] == "day1_warn" and not e1["mandatory_exit"]
    d2 = d1 + [dict(d1[-1], date="x2", close=d1[-1]["close"] * 0.97, low=d1[-1]["close"] * 0.96)]
    e2 = doors.exit_state(d2)
    assert e2["door_4ema"] == "day2_warn" and not e2["mandatory_exit"]  # 4 EMA never mandates (Ray 2026-09-08)
    # 21 EMA door needs two closes below the 21 EMA; two 3% drops from a slow 1%/day climb are not enough
    assert e2["door_21ema"] in ("none", "warn")
    deep = d2 + [dict(d2[-1], date="x3", close=d2[-1]["close"] * 0.90, low=d2[-1]["close"] * 0.89)]
    e3 = doors.exit_state(deep)
    assert e3["deep_break_4ema"] and e3["mandatory_exit"]  # deep break IS mandatory
    assert "deep break" in e3["mandatory_reason"]


def test_stop_and_size():
    b = flat_then([0.0] * 5)
    s = doors.entry_state(b, last_price=100.0)
    assert s["stop_pct"] >= 0.08  # ATR on a flat tape is tiny, floor wins
    sz = doors.size(20_000, 100.0, s["stop_pct"], "floor")
    assert sz["shares"] == 30 and abs(sz["loss_at_stop"] - 30 * 8.0) < 1e-6


def test_breakeven_1r():
    assert doors.breakeven_1r(100, 92, 108)
    assert not doors.breakeven_1r(100, 92, 107)


def test_intraday_high_low_feeds_stoch():
    b = flat_then([-0.02] * 8)
    lp = b[-1]["close"] * 1.06
    no_hl = doors.entry_state(b, last_price=lp)
    with_hl = doors.entry_state(b, last_price=lp, day_high=105.0, day_low=lp * 0.95)  # day high above the 14-bar high moves the window
    assert with_hl["sto_k"] != no_hl["sto_k"]  # intraday range changes the stochastic window
    assert with_hl["door_open"] and with_hl["reclaim_day"] == 1


def test_exit_doors_short_mirrored():
    # a short in a steady decline is healthy: closes BELOW the EMAs are the good side
    down = flat_then([-0.01] * 25)
    s = doors.exit_state(down, side="short")
    assert s["side"] == "short" and s["door_4ema"] == "none" and s["door_21ema"] == "none" and not s["mandatory_exit"]
    # the same tape read as a LONG is deep in mandatory territory
    assert doors.exit_state(down, side="long")["mandatory_exit"]
    # two closes above the 4 EMA against a short = day2 on the 4 EMA door (warning), 21 EMA needs more
    u1 = down + [dict(down[-1], date="x1", close=down[-1]["close"] * 1.03, high=down[-1]["close"] * 1.04)]
    u2 = u1 + [dict(u1[-1], date="x2", close=u1[-1]["close"] * 1.03, high=u1[-1]["close"] * 1.04)]
    e2 = doors.exit_state(u2, side="short")
    assert e2["door_4ema"] == "day2_warn" and e2["warning_4ema"]
    assert e2["door_21ema"] in ("none", "warn") and not e2["mandatory_exit"]
    # a violent squeeze = deep break for the short
    sq = u2 + [dict(u2[-1], date="x3", close=u2[-1]["close"] * 1.10, high=u2[-1]["close"] * 1.11)]
    assert doors.exit_state(sq, side="short")["deep_break_4ema"]


def test_breakeven_and_stop_short():
    assert doors.breakeven_1r(100, 108, 92, side="short")
    assert not doors.breakeven_1r(100, 108, 93, side="short")
    b = flat_then([0.0] * 5)
    assert doors.stop_from_current(b, side="short") >= 108.0 - 1e-9
    assert doors.stop_from_current(b, side="long") <= 92.0 + 1e-9


def test_mandatory_is_21ema_not_4ema():
    up = flat_then([0.01] * 25)
    d1 = up + [dict(up[-1], date="x1", close=up[-1]["close"] * 0.97, low=up[-1]["close"] * 0.96)]
    d2 = d1 + [dict(d1[-1], date="x2", close=d1[-1]["close"] * 0.97, low=d1[-1]["close"] * 0.96)]
    e2 = doors.exit_state(d2)
    # 4 EMA day 2 is a warning, not the exit (Ray ruling 2026-09-08). No field in the payload
    # may claim otherwise -- a self-contradicting payload gets half-believed downstream.
    assert e2["door_4ema"] == "day2_warn" and e2["warning_4ema"]
    assert not e2["mandatory_exit"] and e2["mandatory_reason"] is None
    assert not any(k.startswith("mandatory_exit_under_") for k in e2)
    assert not any("below" in k for k in e2)  # "closes_below_*" lied for shorts; it is gone


def test_side_is_never_guessed(tmp_path):
    """A missing side must refuse, not default to long: the wrong side inverts the stop.

    Reproduces the shape that broke it -- held.json without a side, and an IBKR line whose
    contract_description carries more than the bare ticker.
    """
    import json
    from ccsolver import cli
    d = tmp_path
    (d / "held.json").write_text(json.dumps([
        {"ticker": "TJX", "entry": 100.0, "initial_stop": 108.0},   # no side
        {"ticker": "DNN", "entry": 100.0, "initial_stop": 92.0},    # no side
    ]))
    (d / "positions.json").write_text(json.dumps({"positions": [
        {"asset_class": "STK", "contract_description": "TJX  US", "market_value": -2100},
        {"asset_class": "STK", "contract_description": "ZZZZ", "market_value": 10},
    ]}))
    bars = [{"date": f"2026-01-{i:02d}", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
            for i in range(1, 29)]
    (d / "bars.json").write_text(json.dumps({"TJX": bars, "DNN": bars}))
    (d / "account.json").write_text(json.dumps({"net_liq": 100000.0, "pt_time": "13:10"}))
    (d / "calendar.json").write_text(json.dumps({"closed": [], "early": []}))

    out = {p["ticker"]: p for p in cli.position_monitor(str(d), "2026-09-08")["positions"]}
    # TJX resolves from the signed position even though the description is not a bare ticker
    assert out["TJX"]["side"] == "short"
    assert out["TJX"]["stop_from_current"] > 100      # a short stops ABOVE price
    # DNN has no side anywhere -- refuse, do not guess, and make it loud
    assert out["DNN"]["verdict"] == "SIDE UNKNOWN" and "stop_from_current" not in out["DNN"]
    assert cli.position_monitor(str(d), "2026-09-08")["push"] is True
