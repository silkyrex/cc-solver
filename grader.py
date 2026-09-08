"""Fill forward returns and classify misses. Never edits a rule; writes proposals."""

from __future__ import annotations

HORIZONS = (5, 10, 20, 30)
MISS_THRESHOLDS = (0.10, 0.15, 0.20, 0.30)


def forward_return(closes: list[float], start_idx: int, n: int) -> float | None:
    end = start_idx + n
    if start_idx < 0 or end >= len(closes) or closes[start_idx] == 0:
        return None
    return closes[end] / closes[start_idx] - 1.0


def grade_rows(rows: list[dict], bars_by_ticker: dict[str, list[dict]]) -> list[dict]:
    out = []
    for row in rows:
        ticker = row.get("ticker") or row.get("Ticker")
        first = row.get("first_seen") or row.get("First seen")
        bars = bars_by_ticker.get(ticker) or []
        dates = [b["date"] for b in bars]
        closes = [b["close"] for b in bars]
        filled = dict(row)
        if first in dates:
            i = dates.index(first)
            for n in HORIZONS:
                filled[f"ret_{n}d"] = forward_return(closes, i, n)
        else:
            for n in HORIZONS:
                filled[f"ret_{n}d"] = None
        out.append(filled)
    return out


def hit_rate(rows: list[dict], key: str = "ret_20d", win: float = 0.0) -> dict:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return {"n": 0, "hit_rate": None, "avg": None}
    hits = sum(1 for v in vals if v > win)
    return {"n": len(vals), "hit_rate": hits / len(vals), "avg": sum(vals) / len(vals)}


def miss_audit(
    universe_moves: list[dict],
    discovery_tickers: set[str],
) -> list[dict]:
    """universe_moves: {ticker, move_20d, direction}. Classify names with no Discovery Board row."""
    proposals = []
    for rec in universe_moves:
        t = rec["ticker"]
        move = rec["move_20d"]
        abs_move = abs(move)
        buckets = [th for th in MISS_THRESHOLDS if abs_move >= th]
        if not buckets:
            continue
        flagged = t in discovery_tickers
        if flagged:
            continue
        klass = rec.get("class") or "unforeseeable"
        proposals.append({
            "ticker": t,
            "move_20d": move,
            "thresholds": buckets,
            "class": klass,
            "proposal": rec.get("proposal") or "Do not edit a rule. Desk Post for Ray.",
        })
    return proposals
