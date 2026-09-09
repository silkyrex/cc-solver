"""One place that knows what time it is, and one guard that checks it before anything trades.

Ray's standing rules (2026-09-08/09):
  - Every timestamp is Pacific. Not UTC, not naive, not "whatever the container is set to".
  - Every date carries a time.
  - Anything a human reads is a 12-hour clock: "1:10 PM", never "13:10".
  - Nothing that depends on the time runs before the time is checked.

The failure this exists to stop: a scheduled task hands the solver a pt_time that is actually UTC,
or a stale one from a retry, and the solver computes pace RVOL and a provisional exit against it
without complaint. Both are silently wrong, and both feed a real order.
"""
from datetime import date as _date, datetime, time as _time
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

# Beyond this the supplied clock is untrustworthy but plausible: a slow container, a retry.
DRIFT_WARN_MIN = 15
# Beyond this it is not drift, it is the wrong clock. 7h is exactly PT read as UTC.
DRIFT_FAIL_MIN = 120


def now_pt():
    return datetime.now(PT)


def today_pt():
    return now_pt().date()


def parse_clock(t):
    """Minutes past midnight from "6:30", "06:30", "11:50 AM", "1:10 PM", "1:10pm".

    Accepts both clocks because machines write 24-hour and Ray's task prompts write 12-hour.
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


def render(minutes_or_dt):
    """12-hour string for anything a human reads. 790 -> "1:10 PM"."""
    if isinstance(minutes_or_dt, datetime):
        minutes_or_dt = minutes_or_dt.astimezone(PT).hour * 60 + minutes_or_dt.astimezone(PT).minute
    m = int(minutes_or_dt) % (24 * 60)
    h24, mm = divmod(m, 60)
    ampm = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return f"{h12}:{mm:02d} {ampm}"


def iso(session_date, clock_time):
    """ISO 8601 with the REAL PT offset for that date. December gets -08:00, not a hardcoded -07:00."""
    mins = max(0, min(24 * 60 - 1, parse_clock(clock_time)))
    d0 = _date.fromisoformat(str(session_date)[:10])
    return datetime.combine(d0, _time(mins // 60, mins % 60), tzinfo=PT).isoformat()


def check(session_date, pt_time=None, now=None, task=None):
    """Run BEFORE anything that depends on the time. Returns a report; never raises.

    errors mean do not trade on this. warnings mean say it out loud and continue.
    """
    now = (now or now_pt()).astimezone(PT)
    warnings, errors = [], []
    try:
        d0 = _date.fromisoformat(str(session_date)[:10])
    except (TypeError, ValueError):
        return {"ok": False, "now_pt": render(now), "now_pt_iso": now.isoformat(),
                "session_date": str(session_date), "errors": [f"unparseable session date {session_date!r}"],
                "warnings": [], "task": task}

    day_delta = (d0 - now.date()).days
    if day_delta > 0:
        errors.append(f"session date {d0} is {day_delta} day(s) in the FUTURE; PT today is {now.date()}")
    elif day_delta < 0:
        warnings.append(f"replay: session date {d0} is {-day_delta} day(s) before PT today ({now.date()}); "
                        "live-price and pace-RVOL reads are meaningless on a past date")

    drift = None
    if pt_time is not None:
        try:
            supplied = parse_clock(pt_time)
        except (TypeError, ValueError):
            errors.append(f"unparseable pt_time {pt_time!r}; expected \"11:50 AM\" or \"13:10\"")
        else:
            if day_delta == 0:
                drift = supplied - (now.hour * 60 + now.minute)
                if abs(drift) > DRIFT_FAIL_MIN:
                    msg = (f"pt_time {render(supplied)} is {abs(drift)} min from the real PT clock "
                           f"({render(now)}). That is not drift, that is the wrong clock.")
                    if 360 <= abs(drift) <= 480:
                        msg += " A gap this close to 420 means a UTC time was sent as if it were PT."
                    msg += (" Pass --allow-clock-drift only if you meant to run against a stale time.")
                    errors.append(msg)
                elif abs(drift) > DRIFT_WARN_MIN:
                    warnings.append(f"pt_time {render(supplied)} is {abs(drift)} min from the real PT "
                                    f"clock ({render(now)}); stale retry?")
    return {
        "ok": not errors,
        "task": task,
        "now_pt": render(now),
        "now_pt_iso": now.isoformat(),
        "session_date": str(d0),
        "supplied_pt_time": render(parse_clock(pt_time)) if pt_time is not None and not errors else pt_time,
        "drift_minutes": drift,
        "warnings": warnings,
        "errors": errors,
        "note": "checked against the real America/Los_Angeles clock before any time-dependent work",
    }
