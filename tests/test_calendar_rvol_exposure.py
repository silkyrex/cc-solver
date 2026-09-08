from ccsolver import calendar as cal, exposure, rvol, ledger

CAL = {"closed": ["2026-11-26"], "early": ["2026-11-27"]}


def test_calendar_normal_early_closed_weekend():
    assert cal.status("2026-09-08", CAL)["status"] == "normal"
    e = cal.status("2026-11-27", CAL)
    assert e["status"] == "early_close" and e["moc_deadline_pt"] == "09:45" and e["chain"]["take_action"] == "08:50" and e["chain"]["slow_discovery"] == "05:30"
    assert cal.status("2026-11-26", CAL)["status"] == "closed"
    assert cal.status("2026-09-12", CAL)["status"] == "closed"  # Saturday


def test_pace_rvol_normal_day_reads_one():
    m = rvol.minutes_since_open("11:15")
    assert m == 285
    f = rvol.expected_fraction(m)
    assert 0.6 < f < 0.75
    assert rvol.pace_rvol(f * 1_000_000, 1_000_000, m) == 1.0
    assert rvol.pace_rvol(1_000_000, 1_000_000, 390) == 1.0


def test_exposure_verbatim_line_and_breach():
    pos = [{"asset_class": "STK", "contract_description": "SPY", "market_value": 5000},
           {"asset_class": "STK", "contract_description": "TJX", "market_value": -8000},
           {"asset_class": "STK", "contract_description": "DNN", "market_value": 22000}]
    r = exposure.exposure(pos, 18_910)
    assert r["gross_pct"] == 158.6 and r["net_pct"] == 74.0
    assert r["breach"] and "GROSS OVER" in r["line"] and "NET OVER" not in r["line"]
    assert r["line"].startswith("Exposure (ex-SPY): gross 159% / net 74% (caps 150 / 130)")


def test_discovery_missing_banner():
    rows = [{"Task": "Slow discovery", "Outcome": "OK"}]
    m = ledger.discovery_missing(rows)
    assert m["missing"] == ["Fast discovery"] and "DISCOVERY MISSING" in m["banner"]
    assert ledger.discovery_missing(rows + [{"Task": "Fast discovery", "Outcome": "Partial"}])["banner"] is None
