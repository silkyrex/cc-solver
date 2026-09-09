"""Entry doors, exit doors, stops, sizing. All verdicts carry the exact reason.

bars: chronological list of SETTLED daily bars {date, open, high, low, close, volume}.
last_price: the live price at run time. Ray decides before the close (MOC), so the
provisional "today" close is last_price and every indicator is computed with it appended.
"""
import math

from .indicators import atr, ema, slow_stoch_k

SIZE_TIERS = {"floor": 0.15, "default": 0.20, "best": 0.25}
STOP_FLOOR_PCT = 0.08
ATR_MULT = 2.0
DEEP_BREAK_PCT = 0.04
STO_LOW = 20.0
STO_LOOKBACK = 10  # sessions in which the sub-20 dip must have happened


def _with_live(bars, last_price, day_high=None, day_low=None):
    """Provisional bar for today. Ray ruled Sep 8 2026: the harness passes intraday high/low in quotes.json."""
    if last_price is None:
        return bars
    lp = float(last_price)
    hi = max(float(day_high), lp) if day_high is not None else lp
    lo = min(float(day_low), lp) if day_low is not None else lp
    return bars + [{"date": "live", "open": lp, "high": hi, "low": lo, "close": lp, "volume": 0}]


def _streak(closes, ref, above=True):
    """Consecutive sessions (from the end) with close above (or below) ref series."""
    n = 0
    for c, r in zip(reversed(closes), reversed(ref)):
        if r is None:
            break
        if (c > r) if above else (c < r):
            n += 1
        else:
            break
    return n


def entry_state(bars, last_price=None, day_high=None, day_low=None):
    b = _with_live(bars, last_price, day_high, day_low)
    closes = [x["close"] for x in b]
    e4 = ema(closes, 4)
    e21 = ema(closes, 21)
    s200 = None
    if len(closes) >= 200:
        s200 = sum(closes[-200:]) / 200
    price = closes[-1]
    if e4[-1] is None:
        return {"reason": "insufficient bars (<4)"}

    above = price > e4[-1]
    streak_above = _streak(closes, e4, above=True)
    # reclaim_day: 1 = fresh (yesterday below, today above), 2 = valid day 2, 3+ = stale
    reclaim_day = 0 if not above else min(streak_above, 3)

    # slow sto 20 low: dipped <20 within lookback and today is the FIRST close above 4 EMA since the dip
    sk = slow_stoch_k(b, 14, 3)
    dipped_idx = None
    for i in range(len(b) - 1, max(-1, len(b) - 1 - STO_LOOKBACK), -1):
        if sk[i] is not None and sk[i] < STO_LOW:
            dipped_idx = i
            break
    sto_armed = dipped_idx is not None and not above
    sto_trigger = False
    if dipped_idx is not None and above:
        # every close between the dip and yesterday was at or below the 4 EMA
        between = [closes[i] <= e4[i] for i in range(dipped_idx, len(b) - 1) if e4[i] is not None]
        sto_trigger = all(between) and streak_above == 1

    hi52 = max(x["high"] for x in bars[-252:]) if bars else None
    new_high = hi52 is not None and price >= hi52

    a = atr(b, 14)[-1]
    stop_pct = max(STOP_FLOOR_PCT, ATR_MULT * a / price) if a else STOP_FLOOR_PCT
    return {
        "price": round(price, 4),
        "ema4": round(e4[-1], 4),
        "ema21": round(e21[-1], 4) if e21[-1] else None,
        "above_200sma": (price > s200) if s200 else None,
        "above_4ema": above,
        "streak_above_4ema": streak_above,
        "reclaim_day": reclaim_day,
        "reclaim_label": {0: "below 4 EMA", 1: "DAY 1 fresh reclaim", 2: "DAY 2 valid", 3: "stale (day 3+), chasing"}[reclaim_day],
        "sto_k": round(sk[-1], 1) if sk[-1] is not None else None,
        "sto_20_low_armed": sto_armed,
        "sto_20_low_trigger": sto_trigger,
        "new_52w_high": new_high,
        "atr14": round(a, 4) if a else None,
        "stop_pct": round(stop_pct, 4),
        "stop_price": round(price * (1 - stop_pct), 4),
        "door_open": reclaim_day in (1, 2) or sto_trigger,
        "reason": _entry_reason(reclaim_day, sto_trigger, new_high),
    }


def _entry_reason(reclaim_day, sto_trigger, new_high):
    if reclaim_day == 0:
        return "below 4 EMA; no entry"
    if reclaim_day >= 3:
        return "above 4 EMA but stale (day 3+); no entry"
    parts = ["fresh 4 EMA reclaim (day 1)" if reclaim_day == 1 else "4 EMA reclaim day 2 (valid)"]
    if sto_trigger:
        parts.append("slow sto 20 low (dipped <20, first close back above)")
    if new_high:
        parts.append("NEW 52W HIGH")
    return " + ".join(parts)


def exit_state(bars, last_price=None, settled_only=True, side="long"):
    """Exit doors for a LONG or a SHORT. Position monitor runs on SETTLED closes (settled_only=True).

    Ray ruled 2026-09-08 (direct ruling, not a backtest result): the 21 EMA second consecutive close
    is the MANDATORY exit; the 4 EMA door is a WARNING only. A deep break (>4% through the 4 EMA) is
    also mandatory. Both doors stay in the payload so the harness can colour them.

    side="short" mirrors every test: a short is in trouble when price closes ABOVE the EMAs.
    """
    short = str(side).lower().startswith("s")
    b = bars if settled_only else _with_live(bars, last_price)
    closes = [x["close"] for x in b]
    e4, e21 = ema(closes, 4), ema(closes, 21)
    # "against" = the adverse side for this position: below the EMA for a long, above it for a short
    against4 = _streak(closes, e4, above=short)
    against21 = _streak(closes, e21, above=short) if e21[-1] is not None else 0
    price = closes[-1]
    if e4[-1] is None:
        deep = False
    elif short:
        deep = price > e4[-1] * (1 + DEEP_BREAK_PCT)
    else:
        deep = price < e4[-1] * (1 - DEEP_BREAK_PCT)
    # 4 EMA door names say "warn" because that is now what they are. A field called
    # mandatory_exit_under_4ema_door sitting next to mandatory_exit=false is a payload that
    # contradicts itself, and something downstream eventually believes the wrong half.
    door4 = {0: "none", 1: "day1_warn"}.get(against4, "day2_warn")
    door21 = {0: "none", 1: "warn"}.get(against21, "mandatory_2nd_close")
    mandatory = door21 == "mandatory_2nd_close" or deep
    return {
        "side": "short" if short else "long",
        "close": round(price, 4),
        # named "against", never "below": for a short these count closes ABOVE the EMA
        "closes_against_4ema": against4,
        "closes_against_21ema": against21,
        "door_4ema": door4,
        "door_21ema": door21,
        "deep_break_4ema": deep,
        "warning_4ema": against4 >= 1,
        "mandatory_exit": mandatory,
        "mandatory_reason": (
            "21 EMA 2nd consecutive close against the position" if door21 == "mandatory_2nd_close"
            else f"deep break: close more than {DEEP_BREAK_PCT:.0%} through the 4 EMA" if deep
            else None
        ),
        "note": "ruled 2026-09-08 (Ray, direct): 21 EMA 2nd consecutive close = MANDATORY exit; 4 EMA = warning only"
                + (" (short: mirrored, closes ABOVE the EMAs count against)" if short else ""),
    }


def size(net_liq, price, stop_pct, tier="floor"):
    frac = SIZE_TIERS[tier]
    dollars = net_liq * frac
    shares = math.floor(dollars / price)
    stop = price * (1 - stop_pct)
    return {
        "tier": tier,
        "pct_equity": frac,
        "shares": shares,
        "dollars": round(shares * price, 2),
        "stop_price": round(stop, 4),
        "loss_at_stop": round(shares * (price - stop), 2),
    }


def breakeven_1r(entry, initial_stop, current, side="long"):
    """True once the position is +1R. Long: current >= entry + (entry - initial_stop).
    Short: current <= entry - (initial_stop - entry). Stop then moves to entry."""
    if str(side).lower().startswith("s"):
        r = initial_stop - entry
        return r > 0 and current <= entry - r
    r = entry - initial_stop
    return r > 0 and current >= entry + r


def stop_from_current(bars, side="long"):
    """max(8%, 2*ATR14) away from the last close, on the adverse side for this position."""
    cur = bars[-1]["close"]
    a = atr(bars, 14)[-1] or 0
    pct = max(STOP_FLOOR_PCT, ATR_MULT * a / cur)
    return round(cur * (1 + pct), 4) if str(side).lower().startswith("s") else round(cur * (1 - pct), 4)
