"""Entry and exit door flags. Trading System v1.0 entry; both exit doors reported."""

from __future__ import annotations

from dataclasses import dataclass, asdict


def ema(values: list[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("period")
    k = 2.0 / (period + 1.0)
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = k * values[i] + (1.0 - k) * prev
        out[i] = prev
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def true_range(highs, lows, closes) -> list[float]:
    out = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return out


def atr_wilder(highs, lows, closes, period: int = 14) -> list[float | None]:
    tr = true_range(highs, lows, closes)
    out: list[float | None] = [None] * len(closes)
    if len(tr) < period:
        return out
    val = sum(tr[:period]) / period
    out[period - 1] = val
    for i in range(period, len(tr)):
        val = (val * (period - 1) + tr[i]) / period
        out[i] = val
    return out


def stoch_k(highs, lows, closes, n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        hh = max(highs[i - n + 1 : i + 1])
        ll = min(lows[i - n + 1 : i + 1])
        if hh == ll:
            out[i] = 50.0
        else:
            out[i] = 100.0 * (closes[i] - ll) / (hh - ll)
    return out


def reclaim_day_at(closes: list[float], ema4: list[float | None], idx: int) -> int:
    if ema4[idx] is None or closes[idx] < ema4[idx]:
        return 0
    days = 0
    j = idx
    while j >= 0 and ema4[j] is not None and closes[j] >= ema4[j]:
        days += 1
        if j == 0:
            return days
        prev_e = ema4[j - 1]
        if prev_e is None:
            return days
        if closes[j - 1] < prev_e:
            return days
        j -= 1
    return days


def exit_4ema_state(closes: list[float], ema4: list[float | None], idx: int) -> dict:
    e = ema4[idx]
    if e is None:
        return {"flag": "none", "deep_break": False, "reason": "ema4 not ready"}
    below = closes[idx] < e
    if not below:
        return {"flag": "none", "deep_break": False, "reason": "close >= 4 EMA"}
    deep = closes[idx] < e * 0.96
    prev_below = idx >= 1 and ema4[idx - 1] is not None and closes[idx - 1] < ema4[idx - 1]
    if deep and not prev_below:
        return {
            "flag": "day1_discretion",
            "deep_break": True,
            "reason": "first close >4% below 4 EMA (deep-break override)",
        }
    if prev_below:
        return {
            "flag": "day2_mandatory",
            "deep_break": deep,
            "reason": "second consecutive close below 4 EMA",
        }
    return {
        "flag": "day1_discretion",
        "deep_break": False,
        "reason": "first close below 4 EMA",
    }


def exit_21ema_state(closes: list[float], ema21: list[float | None], idx: int) -> dict:
    e = ema21[idx]
    if e is None:
        return {"flag": "none", "reason": "ema21 not ready"}
    if closes[idx] >= e:
        return {"flag": "none", "reason": "close >= 21 EMA"}
    prev_below = idx >= 1 and ema21[idx - 1] is not None and closes[idx - 1] < ema21[idx - 1]
    if prev_below:
        return {"flag": "mandatory_2nd_close", "reason": "second consecutive close below 21 EMA"}
    return {"flag": "warn", "reason": "first close below 21 EMA"}


def slow_sto_armed(k: list[float | None], closes, ema4, idx: int) -> bool:
    """First fresh 4 EMA reclaim after a %K dip under 20. One reclaim consumes."""
    rec = reclaim_day_at(closes, ema4, idx)
    if rec not in (1, 2):
        return False
    cross = idx
    while cross > 0 and ema4[cross - 1] is not None and closes[cross - 1] >= ema4[cross - 1]:
        cross -= 1
    prev_cross_end = 0
    j = cross - 1
    while j > 0:
        if ema4[j] is not None and closes[j] >= ema4[j] and ema4[j - 1] is not None and closes[j - 1] < ema4[j - 1]:
            prev_cross_end = j
            break
        j -= 1
    start = prev_cross_end
    for t in range(start, cross):
        if k[t] is not None and k[t] < 20:
            return True
    return False


def new_high_flags(highs: list[float]) -> dict:
    if not highs:
        return {"new_52w_high": False, "ath": False}
    today = highs[-1]
    ath = max(highs)
    window = highs[-252:] if len(highs) >= 252 else highs
    hi_52 = max(window)
    return {
        "new_52w_high": today >= hi_52,
        "ath": today >= ath,
        "high_52w": hi_52,
        "ath_price": ath,
    }


@dataclass
class DoorVerdict:
    ticker: str
    last: float
    ema4: float | None
    ema21: float | None
    sma200: float | None
    atr14: float | None
    reclaim_day: int
    slow_sto_20_low: bool
    new_high: bool
    exit_4ema: str
    exit_21ema: str
    deep_break: bool
    stop_price: float | None
    stop_pct: float | None
    stop_binds: str | None
    breakeven_at_1R: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(
    ticker: str,
    dates: list[str],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    last: float | None = None,
    entry_price: float | None = None,
) -> DoorVerdict:
    n = len(closes)
    if n == 0:
        raise ValueError(f"{ticker}: no bars")
    use_last = float(last if last is not None else closes[-1])
    c = list(closes)
    h = list(highs)
    l = list(lows)
    o = list(opens)
    c[-1] = use_last
    h[-1] = max(h[-1], use_last)
    l[-1] = min(l[-1], use_last)
    idx = n - 1
    e4 = ema(c, 4)
    e21 = ema(c, 21)
    s200 = sma(c, 200)
    atrs = atr_wilder(h, l, c, 14)
    k = stoch_k(h, l, c, 14)
    rec = reclaim_day_at(c, e4, idx)
    sto = slow_sto_armed(k, c, e4, idx)
    nh = new_high_flags(h)
    x4 = exit_4ema_state(c, e4, idx)
    x21 = exit_21ema_state(c, e21, idx)
    atr = atrs[idx]
    stop_pct = None
    stop_price = None
    binds = None
    if atr is not None and use_last > 0:
        atr_leg = 2.0 * atr / use_last
        pct_leg = 0.08
        stop_pct = max(pct_leg, atr_leg)
        binds = "2xATR14" if atr_leg > pct_leg else "8%"
        stop_price = round(use_last * (1.0 - stop_pct), 4)
    r_hit = False
    if entry_price is not None and stop_price is not None:
        r = entry_price - (entry_price * (1.0 - (stop_pct or 0.08)))
        if r > 0 and use_last >= entry_price + r:
            r_hit = True
    reasons = []
    if rec == 1:
        reasons.append("fresh 4 EMA reclaim day 1")
    elif rec == 2:
        reasons.append("valid 4 EMA reclaim day 2")
    elif rec >= 3:
        reasons.append(f"stale reclaim day {rec}")
    else:
        reasons.append("no 4 EMA reclaim")
    if sto:
        reasons.append("slow sto 20 low armed on this reclaim")
    if nh["new_52w_high"] or nh["ath"]:
        reasons.append("new-high tag (priority, not a door)")
    reasons.append(f"exit_4ema={x4['flag']}: {x4['reason']}")
    reasons.append(f"exit_21ema={x21['flag']}: {x21['reason']}")
    if stop_price is not None:
        reasons.append(f"stop {binds} at {stop_price} from current {use_last}")
    return DoorVerdict(
        ticker=ticker,
        last=use_last,
        ema4=e4[idx],
        ema21=e21[idx],
        sma200=s200[idx],
        atr14=atr,
        reclaim_day=rec if rec < 3 else rec,
        slow_sto_20_low=sto,
        new_high=bool(nh["new_52w_high"] or nh["ath"]),
        exit_4ema=x4["flag"],
        exit_21ema=x21["flag"],
        deep_break=bool(x4.get("deep_break")),
        stop_price=stop_price,
        stop_pct=stop_pct,
        stop_binds=binds,
        breakeven_at_1R=r_hit,
        reasons=reasons,
    )


def rs_20d(closes: list[float], bench: list[float]) -> float | None:
    if len(closes) < 21 or len(bench) < 21:
        return None
    if bench[-21] == 0 or closes[-21] == 0:
        return None
    a = closes[-1] / closes[-21] - 1.0
    b = bench[-1] / bench[-21] - 1.0
    return a - b
