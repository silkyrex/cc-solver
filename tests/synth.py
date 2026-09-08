from __future__ import annotations

from datetime import date, timedelta


def weekday_dates(n: int, start: date = date(2025, 10, 1)) -> list[str]:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def ohlc_from_closes(closes: list[float], width: float = 1.0) -> dict:
    dates = weekday_dates(len(closes))
    opens, highs, lows = [], [], []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        opens.append(o)
        highs.append(max(o, c) + width)
        lows.append(min(o, c) - width)
    return {
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
    }
