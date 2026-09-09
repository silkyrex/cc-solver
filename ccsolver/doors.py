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
    # provisional=True is load-bearing: this bar may drive a provisional exit flag, but it must never
    # graduate a position. An intraday pop over the 21 EMA that fades by the close would otherwise
    # loosen the leash permanently, and graduation is deliberately one-way.
    return bars + [{"date": "live", "open": lp, "high": hi, "low": lo, "close": lp, "volume": 0,
                    "provisional": True}]


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
        "entry_door": entry_door(price, e21[-1], side="long"),
        "entry_trigger": ("both" if reclaim_day in (1, 2) and sto_trigger
                          else "slow_sto" if sto_trigger
                          else "reclaim" if reclaim_day in (1, 2) else None),
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


def _favourable(price, ema_val, short):
    """Is price on the side of this EMA that a position of this side WANTS to be on?"""
    if ema_val is None:
        return None
    return price < ema_val if short else price > ema_val


def entry_door(price, ema21_val, side="long"):
    """Which EMA is this position's mandatory exit, decided at ENTRY.

    Ray ruled 2026-09-08 that the 21 EMA second consecutive close is the mandatory exit. That rule
    is incoherent for a position opened on the WRONG side of the 21 EMA: a relaunch entry (>30% off
    the high, fresh 4 EMA reclaim) is under the 21 EMA by construction, so it would be born dozens
    of closes deep into its own mandatory exit. Verified 2026-09-08: such an entry reported
    closes_against_21ema=27 and mandatory_exit=True on the staging bar itself.

    So the door binds at entry. Above the 21 EMA (below it, for a short) the 21 EMA is the exit.
    Otherwise the position is unproven and runs on the tighter 4 EMA door until it GRADUATES.
    """
    short = str(side).lower().startswith("s")
    fav = _favourable(price, ema21_val, short)
    return "21ema" if fav else "4ema"


def exit_state(bars, *, entry_door_, last_price=None, settled_only=True, side="long", entry_date=None):
    """Exit doors for a LONG or a SHORT, against the door this position bound to at entry.

    Ray ruled 2026-09-08 (direct ruling, not a backtest result): the 21 EMA second consecutive close
    is the MANDATORY exit and the 4 EMA door is a warning. Ray ruled 2026-09-08 (second ruling) that
    a position opened on the wrong side of the 21 EMA runs on the 4 EMA door instead, and GRADUATES
    to the 21 EMA door on its first close on the favourable side of the 21 EMA since entry. The leash
    only ever loosens; a graduated position is never demoted back to the tight door.

    A deep break (>4% through the 4 EMA, adverse direction) is mandatory under either door.

    entry_door_ is REQUIRED and keyword-only. There is deliberately no default: whichever door a
    default picked would be silently wrong for half the positions, and the wrong one is unnoticeable
    from the outside. A caller that does not know the door must decide, in the open, what a missing
    door means -- position_monitor treats it as the tight 4 EMA door, because a position that cannot
    prove it cleared the 21 EMA has not earned the loose leash.

    entry_date is what makes graduation checkable. Without it graduation cannot be established, and
    the position stays on the TIGHT door -- erring toward the earlier exit, never the later one.
    It accepts a full timestamp ("2026-09-08T11:52:00-07:00") or a bare date; bars are daily, so only
    the date part is compared.

    settled_only=False appends today's live bar from last_price and reports the SAME tests against it
    as provisional_*. That exists because the MOC deadline is 12:45 PM PT and the close is 1:00 PM:
    a mandatory exit computed on settled closes is only knowable after Ray can act on it.

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

    bound = "4ema" if str(entry_door_) == "4ema" else "21ema"
    graduated = False
    if bound == "4ema" and entry_date is not None:
        for i, bar in enumerate(b):
            if bar.get("provisional"):
                continue  # only a SETTLED close can graduate a position
            if bar.get("date") is not None and str(bar["date"])[:10] >= str(entry_date)[:10]:
                if _favourable(closes[i], e21[i], short):
                    graduated = True
                    break
    active = "21ema" if (bound == "21ema" or graduated) else "4ema"

    against_active = against21 if active == "21ema" else against4
    mandatory = deep or against_active >= 2
    if deep:
        reason = f"deep break: close more than {DEEP_BREAK_PCT:.0%} through the 4 EMA"
    elif mandatory:
        reason = f"{'21' if active == '21ema' else '4'} EMA 2nd consecutive close against the position"
    else:
        reason = None
    # door strings are neutral counts on purpose. Whether "day2" means exit depends on active_door,
    # so a name like day2_mandatory or day2_warn would be wrong half the time.
    door4 = {0: "none", 1: "day1"}.get(against4, "day2")
    door21 = {0: "none", 1: "day1"}.get(against21, "day2")
    prov = {}
    if settled_only and last_price is not None:
        # Same tests, with today's last price standing in for today's close. Kept in its OWN keys:
        # a provisional flag is a warning to act before 12:45 PM, never a confirmed exit.
        p2 = exit_state(bars, last_price=last_price, settled_only=False, side=side,
                        entry_door_=entry_door_, entry_date=entry_date)
        pending = p2["mandatory_exit"] and not mandatory
        prov = {
            "provisional_close": p2["close"],
            "provisional_mandatory": p2["mandatory_exit"],
            "provisional_reason": p2["mandatory_reason"],
            "provisional_note": (
                f"not an exit yet. {p2['mandatory_reason']} if it closes here."
                if pending else
                "already a confirmed exit on settled closes" if mandatory else
                "nothing pending against the active door at this price"
            ),
        }

    return {
        "side": "short" if short else "long",
        "close": round(price, 4),
        # named "against", never "below": for a short these count closes ABOVE the EMA
        "closes_against_4ema": against4,
        "closes_against_21ema": against21,
        "door_4ema": door4,
        "door_21ema": door21,
        "entry_door": bound,
        "graduated": graduated,
        "active_door": active,
        "deep_break_4ema": deep,
        "warning_4ema": against4 >= 1,
        "mandatory_exit": mandatory,
        "mandatory_reason": reason,
        "note": f"active door = {active} (bound at entry: {bound}"
                + (", graduated" if graduated else "")
                + "); deep break is mandatory under either"
                + (" (short: mirrored, closes ABOVE the EMAs count against)" if short else ""),
        **prov,
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
