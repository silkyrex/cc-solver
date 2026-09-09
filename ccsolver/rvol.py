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


def _minutes(t):
    """Minutes past midnight from "6:30", "06:30", "11:50 AM", "1:10 PM", "1:10pm".

    Ray's output rule is 12-hour clock everywhere, so the scheduled tasks write pt_time as
    "11:50 AM". This used to raise ValueError on the space, which killed take_action outright.
    24-hour input still works: a bare "13:10" is read as 13:10.
    """
    s = str(t).strip().upper().replace(".", "")
    meridiem = None
    for tag in ("AM", "PM"):
        if s.endswith(tag):
            meridiem, s = tag, s[: -len(tag)].strip()
            break
    parts = s.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    if meridiem == "AM" and h == 12:
        h = 0
    elif meridiem == "PM" and h != 12:
        h += 12
    return h * 60 + m


def minutes_since_open(hhmm_pt, open_hhmm="06:30"):
    return _minutes(hhmm_pt) - _minutes(open_hhmm)
