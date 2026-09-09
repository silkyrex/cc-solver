"""confirm_pass at 12:35 PM is the last slot where an exit is still actionable.

MOC deadline 12:45 PM, close 1:00 PM, position_monitor 1:10 PM. A mandatory exit computed on
settled closes is only knowable AFTER Ray can act on it, so the provisional read lives here.
"""
import json
from datetime import date, timedelta

from ccsolver import cli


def _weekdays(n, start="2025-10-01"):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _relaunch_then_one_close_against():
    """A relaunch entry (below the 21 EMA, so the tight 4 EMA door) with one close against it.

    Deliberately NOT an uptrend: an uptrend entry sits above the 21 EMA, binds to the 21 EMA door,
    and any close far enough below the 4 EMA to matter is already a deep break, i.e. confirmed
    rather than pending. This shape is the one that actually produces a pending state.
    """
    closes = [100 * (0.985 ** i) for i in range(45)]
    closes += [closes[-1] * 1.05, closes[-1] * 1.05 * 1.03]   # reclaims the 4 EMA, still under the 21
    closes += [closes[-1] * 0.96]                             # one close back below the 4 EMA
    ds = _weekdays(len(closes))
    bars = [{"date": ds[i], "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1}
            for i, c in enumerate(closes)]
    return bars, ds[46], ds[-1]                               # bars, entry date, last settled date


def _inputs(tmp_path, last_price=None, side="long", positions=None, quotes=None, held=None):
    bars, entry, last_day = _relaunch_then_one_close_against()
    files = {
        "staged": [],
        "bars": {"AAA": bars},
        "quotes": quotes if quotes is not None else (
            {"AAA": {"last": bars[-1]["close"] * last_price}} if last_price else {}),
        "held": held if held is not None else [
            {"ticker": "AAA", "entry": 60.0, "initial_stop": 55.0, "side": side,
             "entry_door": "4ema", "entry_datetime": f"{entry}T11:50:00-07:00"}],
        "positions": {"positions": positions if positions is not None else []},
        "calendar": {"closed": [], "early": []},
    }
    for name, obj in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(obj))
    return str(tmp_path), last_day


def test_pending_exit_is_flagged_before_the_moc_deadline(tmp_path):
    d, day = _inputs(tmp_path, last_price=0.995)          # still below the 4 EMA at 12:35 PM
    out = cli.confirm_pass(d, day)
    assert out["moc_deadline_pt"] == "12:45"
    assert len(out["pending_exits"]) == 1
    row = out["pending_exits"][0]
    assert row["ticker"] == "AAA"
    assert row["already_confirmed"] is False               # settled closes have NOT said it yet
    assert "if it closes here" in row["note"]
    assert out["push"] is True                            # this has to reach Ray before 12:45


def test_recovered_price_clears_the_pending_flag(tmp_path):
    d, day = _inputs(tmp_path, last_price=1.08)           # bounced back over the 4 EMA
    out = cli.confirm_pass(d, day)
    assert out["pending_exits"] == [] and out["push"] is False


def test_side_falls_back_to_the_broker_then_refuses(tmp_path):
    bars, entry, day = _relaunch_then_one_close_against()
    # no side on the row, but IBKR has a signed line -> resolved from the broker
    d, _ = _inputs(tmp_path, last_price=0.995,
                   held=[{"ticker": "AAA", "entry": 60.0, "initial_stop": 55.0,
                          "entry_door": "4ema", "entry_datetime": f"{entry}T11:50:00-07:00"}],
                   positions=[{"asset_class": "STK", "contract_description": "AAA  US",
                               "market_value": 5000}])
    assert cli.confirm_pass(d, day)["pending_exits"][0]["side"] == "long"

    # no side anywhere -> refuse and push, never guess
    d2, _ = _inputs(tmp_path, last_price=0.995,
                    held=[{"ticker": "AAA", "entry": 60.0, "initial_stop": 55.0}],
                    positions=[])
    out = cli.confirm_pass(d2, day)
    assert out["pending_exits"][0]["verdict"] == "SIDE UNKNOWN" and out["push"] is True


def test_missing_quote_is_reported_not_silently_dropped(tmp_path):
    d, day = _inputs(tmp_path, quotes={})
    out = cli.confirm_pass(d, day)
    assert out["skipped"] == [{"ticker": "AAA", "reason": "no live quote"}]
    assert out["pending_exits"] == []
