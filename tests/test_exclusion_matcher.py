"""The exclusion matcher must not eat real momentum names.

Before the word-boundary fix these three were excluded on `main` by a bare substring test,
which deletes a candidate before it ever reaches a door check. The Miss Audit's own
classification string lists "exclusion false positive" as a bucket; this was that bucket, live.
"""
from ccsolver import universe, ledger, grader

# (ticker, company name) that MUST survive
SURVIVORS = [
    ("RARE", "Ultragenyx Pharmaceutical Inc"),      # "Ultra" inside a word
    ("ROLL", "RBC Bearings Incorporated"),          # "Bear" inside "Bearings"
    ("DJCO", "Daily Journal Corp"),                 # "Daily" with no issuer token
    ("BULL", "Webull Corporation"),                 # "Bull" inside a word
    ("NVDA", "NVIDIA Corp"),
    ("BE", "Bloom Energy"),
]

# (ticker, company name) that MUST still be excluded
WRAPPERS = [
    ("SOXL", "Direxion Daily Semiconductor Bull 3X Shares"),
    ("TQQQ", "ProShares UltraPro QQQ"),
    ("LABU", "Direxion Daily S&P Biotech Bull 3X ETF"),
    ("SQQQ", "ProShares UltraShort QQQ ETF"),
    ("NVDY", "YieldMax NVDA Option Income Strategy ETF"),
    ("SPXU", "ProShares UltraPro Short S&P500 ETF"),
]


def _row(ticker, name, **kw):
    scans = {"CC Ripper": [{"ticker": ticker, "name": name, "last": 50.0, "rel_volume": 1.1}]}
    return {r["ticker"]: r for r in universe.build(scans, {}, kw.get("roster", []), kw.get("positions", []), {})}[ticker]


def test_real_names_survive_the_matcher():
    for ticker, name in SURVIVORS:
        r = _row(ticker, name)
        assert not r["excluded"], f"{ticker} ({name}) wrongly excluded: {r['exclusion_reason']}"


def test_wrappers_still_excluded():
    for ticker, name in WRAPPERS:
        r = _row(ticker, name)
        assert r["excluded"] and "pattern" in r["exclusion_reason"], f"{ticker} ({name}) should be excluded"


def test_leverage_word_alone_is_not_enough():
    # issuer token present, no leverage word -> survives
    assert not _row("BX", "Blackstone Trust")["excluded"]
    # leverage word present, no issuer token -> survives
    assert not _row("DJCO", "Daily Journal Corp")["excluded"]
    # both -> excluded
    assert _row("XYZ", "Acme Daily Bull 2X Shares")["excluded"]


def test_held_and_roster_override_still_fires():
    """The escape hatch that makes this bug survivable: never drop monitoring on a live name."""
    held = _row("SOXL", "Direxion Daily Semiconductor Bull 3X Shares", positions=["SOXL"])
    assert not held["excluded"] and "overrides" in held["exclusion_reason"]
    rostered = _row("TQQQ", "ProShares UltraPro QQQ", roster=["TQQQ"])
    assert not rostered["excluded"] and "overrides" in rostered["exclusion_reason"]


def test_custom_patterns_from_exclusion_json_still_honoured():
    scans = {"s": [{"ticker": "ZZZ", "name": "Zeta Widget Fund", "last": 50.0, "rel_volume": 1.0}]}
    rows = {r["ticker"]: r for r in universe.build(scans, {}, [], [], {"patterns": ["Widget"]})}
    assert rows["ZZZ"]["excluded"]  # "Widget" + issuer token "Fund"


def test_malformed_board_rows_do_not_raise():
    board = [
        {"url": "u1", "Ticker": "AAA", "Layer": "Momentum", "first_seen": "2026-01-02", "seen_count": 1},
        {"url": "u2", "Layer": "Momentum", "first_seen": "2026-01-02"},   # no Ticker
        {"url": "u3", "Ticker": "BBB", "Layer": "Momentum"},              # no first_seen
    ]
    bars = {"AAA": [{"date": f"2026-01-{d:02d}", "open": 10, "high": 11, "low": 9, "close": 10 + d, "volume": 1} for d in range(1, 29)]}
    out = grader.grade_board(board, bars)
    assert len(out["skipped_malformed_rows"]) == 2

    first = {}
    for r in board:
        t, fs = r.get("Ticker"), r.get("first_seen")
        if t and fs:
            first[t] = fs
    assert grader.miss_audit(bars, first) is not None

    uni = [{"ticker": "AAA", "sources": ["scan:x"], "theme": None, "excluded": False, "last": 10.0},
           {"ticker": None, "sources": ["scan:x"], "theme": None, "excluded": False, "last": None}]
    rows = ledger.board_rows(uni, "Momentum", "Bull", "2026-01-05", {("AAA", "Momentum"): {"url": "u1"}})
    assert len(rows) == 1 and rows[0]["Ticker"] == "AAA" and rows[0]["Seen count"] == 1
