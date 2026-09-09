"""In-the-moment grader (forward returns) and the recursive Miss Audit.

bars_by_ticker: {"TICKER": [bars...]} settled daily bars, chronological.
"""
from . import bars as barlib

HORIZONS = (5, 10, 20, 30)
MISS_THRESHOLDS = (0.10, 0.15, 0.20, 0.30)
MISS_WINDOW = 20


def _idx_on_or_after(bars, date_str):
    for i, b in enumerate(bars):
        if b["date"] >= date_str:
            return i
    return None


def forward_returns(bars, from_date, horizons=HORIZONS):
    i = _idx_on_or_after(bars, from_date)
    if i is None:
        return {f"Ret +{h}d": None for h in horizons}
    base = bars[i]["close"]
    out = {}
    for h in horizons:
        j = i + h
        out[f"Ret +{h}d"] = round(bars[j]["close"] / base - 1, 4) if j < len(bars) else None
    return out


def grade_board(board_rows, bars_by_ticker):
    """board_rows: [{url, Ticker, Layer, first_seen}] → per-row return fills + hit rate by layer (+20d > 0)."""
    fills, by_layer, skipped = [], {}, []
    for r in board_rows:
        if not r.get("Ticker") or not r.get("first_seen"):
            skipped.append(r.get("url") or r.get("Ticker") or "<unidentifiable row>")
            continue
        bars = barlib.clean(bars_by_ticker.get(r["Ticker"]) or [])
        if not bars:
            continue
        # first_seen can predate the listing; forward_returns then based off a padded close.
        rets = forward_returns(bars, r["first_seen"])
        fills.append({"url": r.get("url"), **rets})
        if rets["Ret +20d"] is not None:
            s = by_layer.setdefault(r.get("Layer") or "Unlabelled", {"n": 0, "hits": 0, "sum": 0.0})
            s["n"] += 1
            s["hits"] += rets["Ret +20d"] > 0
            s["sum"] += rets["Ret +20d"]
    summary = {k: {"n": v["n"], "hit_rate": round(v["hits"] / v["n"], 2), "avg_20d": round(v["sum"] / v["n"], 4)} for k, v in by_layer.items() if v["n"]}
    return {"fills": fills, "by_layer": summary, "skipped_malformed_rows": skipped}


MISS_LOOKBACK = 25  # sessions: every 20-session window whose END falls in the last 25 sessions is tested


def miss_audit(bars_by_ticker, board_first_seen, as_of_idx=None, window=MISS_WINDOW, lookback=MISS_LOOKBACK):
    """Names that moved >= thresholds over ANY `window`-session window ending in the last `lookback` sessions,
    with NO board row before that window started. One row per ticker: the window with the largest |move|.
    as_of_idx pins a single window end (legacy behaviour); otherwise all window ends in the lookback are scanned.
    board_first_seen: {"TICKER": "YYYY-MM-DD"} earliest first_seen on the board."""
    misses = []
    for t, bars in bars_by_ticker.items():
        # A padded bar carries the listing-day open, so a window starting on one reports the
        # gap between a price that never traded and a real one as a move the desk "missed".
        bars = barlib.clean(bars)
        if len(bars) <= window:
            continue
        last = len(bars) - 1
        ends = [as_of_idx] if as_of_idx is not None else range(max(window, last - lookback), last + 1)
        best = None
        for end in ends:
            start = end - window
            move = bars[end]["close"] / bars[start]["close"] - 1
            if best is None or abs(move) > abs(best[0]):
                best = (move, start, end)
        move, start, end = best
        bucket = max((th for th in MISS_THRESHOLDS if abs(move) >= th), default=None)
        if bucket is None:
            continue
        seen = board_first_seen.get(t)
        flagged_before = seen is not None and seen <= bars[start]["date"]
        if not flagged_before:
            misses.append({"ticker": t, "move": round(move, 4), "bucket": f"{int(bucket*100)}%+", "direction": "up" if move > 0 else "down",
                           "window_start": bars[start]["date"], "window_end": bars[end]["date"], "first_seen_on_board": seen,
                           "classification": "TODO: universe gap / filter too tight / timing / exclusion false positive / unforeseeable"})
    return sorted(misses, key=lambda m: -abs(m["move"]))
