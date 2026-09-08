"""Pace-adjusted intraday relative volume.

Raw dayVolume / avgVolume reads 0.5-0.7 at 11:15 PT on a normal day (Sep 8 pull showed it).
Buzz must divide by the volume EXPECTED by this minute of the session, which is U-shaped.
"""
SESSION_MIN = 390  # 06:30-13:00 PT
# cumulative fraction of a normal day's volume by minute since open (U-shaped, piecewise linear)
_CURVE = [(0, 0.0), (15, 0.09), (30, 0.15), (60, 0.24), (90, 0.31), (150, 0.42), (210, 0.52), (270, 0.63), (330, 0.77), (360, 0.86), (390, 1.0)]


def expected_fraction(minutes_since_open):
    m = max(0, min(SESSION_MIN, minutes_since_open))
    for (m0, f0), (m1, f1) in zip(_CURVE, _CURVE[1:]):
        if m0 <= m <= m1:
            return f0 + (f1 - f0) * (m - m0) / (m1 - m0)
    return 1.0


def pace_rvol(day_volume, avg_volume, minutes_since_open):
    """day_volume / (avg_volume * expected_fraction). 1.0 = on pace for a normal day."""
    f = expected_fraction(minutes_since_open)
    if not avg_volume or f <= 0:
        return None
    return round(day_volume / (avg_volume * f), 2)


def minutes_since_open(hhmm_pt, open_hhmm="06:30"):
    h, m = map(int, hhmm_pt.split(":"))
    oh, om = map(int, open_hhmm.split(":"))
    return (h * 60 + m) - (oh * 60 + om)
