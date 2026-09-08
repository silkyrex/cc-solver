"""Pace-adjusted relative volume using a U-shaped RTH profile, not a linear clock."""

from __future__ import annotations

RTH_MINUTES = 390  # 09:30-16:00 ET


def _minute_weights(n: int = RTH_MINUTES) -> list[float]:
    raw = []
    for t in range(n):
        x = t / (n - 1)
        raw.append(0.28 + 2.6 * (x - 0.5) ** 2)
    total = sum(raw)
    return [w / total for w in raw]


WEIGHTS = _minute_weights()
CUMULATIVE = []
running = 0.0
for w in WEIGHTS:
    running += w
    CUMULATIVE.append(running)


def minutes_elapsed_rth(hour_et: int, minute_et: int) -> int:
    start = 9 * 60 + 30
    now = hour_et * 60 + minute_et
    elapsed = now - start
    if elapsed < 0:
        return 0
    if elapsed > RTH_MINUTES:
        return RTH_MINUTES
    return elapsed


def expected_fraction(minutes_elapsed: int) -> float:
    if minutes_elapsed <= 0:
        return 0.0
    if minutes_elapsed >= RTH_MINUTES:
        return 1.0
    return CUMULATIVE[minutes_elapsed - 1]


def pace_adjusted_rvol(
    todays_volume: float,
    avg_30d_volume: float,
    minutes_elapsed: int,
) -> dict:
    if avg_30d_volume <= 0:
        return {
            "rvol_pace": None,
            "rvol_raw": None,
            "expected_fraction": expected_fraction(minutes_elapsed),
            "reason": "avg_30d_volume missing",
        }
    frac = expected_fraction(minutes_elapsed)
    expected_now = avg_30d_volume * frac
    raw = todays_volume / avg_30d_volume
    pace = todays_volume / expected_now if expected_now > 0 else None
    return {
        "rvol_pace": round(pace, 4) if pace is not None else None,
        "rvol_raw": round(raw, 4),
        "expected_fraction": round(frac, 4),
        "expected_volume_by_now": round(expected_now, 2),
        "todays_volume": todays_volume,
        "avg_30d_volume": avg_30d_volume,
        "minutes_elapsed": minutes_elapsed,
        "reason": "pace = today_vol / (30d_avg * U_shape_fraction)",
    }
