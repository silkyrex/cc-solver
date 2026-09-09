"""Bar hygiene. The feed pads a requested range with bars that never traded.

Robinhood `get_equity_historicals` returns one bar per session across the WHOLE requested
range, whether or not the instrument traded. Sessions before the listing (and any no-trade
session) come back synthesized: OHLC all equal, volume 0, and `interpolated: true`. The pad
price is the first real bar's OPEN, carried backward. Verified live 2026-09-09 on a 130-day
pull: SKHY is flat 149.00 with volume 0 every session before 2026-07-10, SPCX flat 150.00
before 2026-06-12, and the tool's own guide says to ignore these bars for analytics.

The harness maps each bar to {date, open, high, low, close, volume}, which DROPS the
`interpolated` flag, so downstream a fabricated bar is indistinguishable from a real quiet
session. That is why this module identifies them by SHAPE as well as by flag: no prompt edit
is needed for the strip to work, and the flag is still honoured when a caller passes it.

What the padding does if left in (DEC-006 data note, Ray 2026-09-08):
  - the 21 EMA is seeded on prices that never traded, biased toward the listing-day open;
  - a new listing looks like it sat flat for months and then exploded, so a 4 EMA reclaim,
    a 52-week high and a slow sto dip are all measured against a shelf that is not real;
  - the pad also keeps the bar COUNT above the 21 needed to compute a 21 EMA at all, which
    is what hides a too-short history today.

Strip the LEADING run and the TRAILING run separately, never "everything up to the last
flagged bar" -- today's forming bar can also arrive flagged, and that rule would delete a
whole history.
"""

# Real sessions required before a 21 EMA read is trusted. 21 is the bare minimum to produce
# any value (it is seeded with the 21-bar average), but at exactly 21 the line is that average
# and has not yet reacted to anything. 30 leaves nine sessions of real trading past the seed.
# Not 60 (what the task prompts ask for in raw bars): counting REAL bars only, 60 would refuse
# to read roster names on 2026-09-09 -- SKHY had 41 real sessions and SPCX 59.
MIN_REAL_BARS_21EMA = 30


def is_synthetic(bar):
    """True for a padded bar: no volume AND no range, or the feed's own flag.

    The provisional live bar built from quotes.json is never synthetic. It also carries
    volume 0, and with no day_high/day_low in quotes its OHLC collapse to the last price,
    so without this guard the trailing trim would eat the very bar the MOC read depends on.
    """
    if bar.get("provisional"):
        return False
    try:
        if float(bar.get("volume") or 0) > 0:
            return False
    except (TypeError, ValueError):
        return False
    if bar.get("interpolated") is True:
        return True
    try:
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    except (KeyError, TypeError, ValueError):
        return False
    return o == h == l == c


def clean(bars):
    """Drop the leading and trailing runs of synthesized bars. Idempotent.

    Interior padded bars are LEFT IN and counted by `real_count`. A gap in the middle of a
    real history is a halt or a no-trade session, and removing it would silently close the
    gap and shift every streak count by a session it did not live through. Only the runs at
    the edges -- history the instrument did not have -- are removed.
    """
    if not bars:
        return []
    i, j = 0, len(bars)
    while i < j and is_synthetic(bars[i]):
        i += 1
    while j > i and is_synthetic(bars[j - 1]):
        j -= 1
    return bars[i:j]


def real_count(bars):
    """Sessions in `bars` that actually traded. Interior padding does not count as history."""
    return sum(1 for b in bars if not is_synthetic(b))


def thin(bars, minimum=MIN_REAL_BARS_21EMA):
    """Too little real history to trust a 21 EMA read."""
    return real_count(bars) < minimum
