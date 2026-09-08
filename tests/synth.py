"""Synthetic bar builders for door-state tests."""


def bars_from_closes(closes, start="2026-01-02"):
    from datetime import datetime, timedelta
    d0 = datetime.strptime(start, "%Y-%m-%d")
    out, i = [], 0
    d = d0
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.strftime("%Y-%m-%d"), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1_000_000})
        d += timedelta(days=1)
    return out


def flat_then(pattern, base=100.0, n_flat=30):
    """n_flat flat bars then a list of multiplicative steps applied day by day."""
    closes = [base] * n_flat
    c = base
    for step in pattern:
        c = c * (1 + step)
        closes.append(c)
    return bars_from_closes(closes)
