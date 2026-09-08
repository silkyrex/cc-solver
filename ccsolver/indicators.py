"""Pure-Python indicators over lists of floats. No pandas on purpose: the
scheduled-task container is ephemeral and every dependency is a failure mode."""
from statistics import mean


def ema(values, n):
    """Exponential moving average, seeded with SMA(n). Returns list aligned to values (None until seed)."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    e = mean(values[:n])
    out[n - 1] = e
    for i in range(n, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def sma(values, n):
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = mean(values[i - n + 1 : i + 1])
    return out


def atr(bars, n=14):
    """Wilder ATR over bars [{high, low, close}]. Returns list aligned to bars."""
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["high"] - b["low"])
        else:
            pc = bars[i - 1]["close"]
            trs.append(max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc)))
    out = [None] * len(bars)
    if len(bars) < n:
        return out
    a = mean(trs[:n])
    out[n - 1] = a
    for i in range(n, len(bars)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def slow_stoch_k(bars, k_len=14, smooth=3):
    """Slow %K = SMA(smooth) of fast %K(k_len). Ray's 'slow sto k(14) d(1)' = this series, no %D smoothing."""
    fast = [None] * len(bars)
    for i in range(k_len - 1, len(bars)):
        win = bars[i - k_len + 1 : i + 1]
        hh = max(b["high"] for b in win)
        ll = min(b["low"] for b in win)
        fast[i] = 50.0 if hh == ll else 100.0 * (bars[i]["close"] - ll) / (hh - ll)
    out = [None] * len(bars)
    for i in range(len(bars)):
        win = [v for v in fast[max(0, i - smooth + 1) : i + 1] if v is not None]
        if len(win) == smooth:
            out[i] = mean(win)
    return out
