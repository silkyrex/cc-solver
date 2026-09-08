from ccsolver import universe, grader
from synth import flat_then


def test_exclusion_patterns_pump_and_overrides():
    scans = {"CC Ripper": [
        {"ticker": "LABU", "name": "Direxion Daily S&P Biotech Bull 3X ETF", "last": 300, "rel_volume": 1.2},
        {"ticker": "BNC", "name": "CEA Industries", "last": 5.1, "rel_volume": 103},
        {"ticker": "BE", "name": "Bloom Energy", "last": 282, "rel_volume": 1.3},
        {"ticker": "SNDK", "name": "Sandisk", "last": 1794, "rel_volume": 0.5}]}
    rows = {r["ticker"]: r for r in universe.build(scans, {"Power": ["BE", "SMR", "EOSE"]}, ["SNDK"], [], {"names": ["SNDK"]})}
    assert rows["LABU"]["excluded"] and "pattern" in rows["LABU"]["exclusion_reason"]
    assert rows["BNC"]["excluded"] and "pump" in rows["BNC"]["exclusion_reason"]
    assert not rows["BE"]["excluded"] and rows["BE"]["theme"] == "Power"
    assert not rows["SNDK"]["excluded"] and "overrides" in rows["SNDK"]["exclusion_reason"]  # roster beats the named list


def test_forward_returns_and_miss_audit():
    b = flat_then([0.02] * 40)  # +2%/day → +20d well over 30%
    fr = grader.forward_returns(b, b[30]["date"])
    assert fr["Ret +5d"] and abs(fr["Ret +5d"] - (1.02 ** 5 - 1)) < 1e-6 and fr["Ret +30d"] is None or fr["Ret +30d"] is not None
    m = grader.miss_audit({"XYZ": b}, {})
    assert m and m[0]["ticker"] == "XYZ" and m[0]["bucket"] == "30%+"
    assert grader.miss_audit({"XYZ": b}, {"XYZ": b[0]["date"]}) == []  # flagged before the move = not a miss
