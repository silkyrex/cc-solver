"""Market calendar: closed days, early closes, and the chain shift.

Input JSON (exported by the harness from the Notion page "Market Calendar — NYSE
holidays and early closes (2026–2028)"):
    {"closed": ["2026-11-26", ...], "early": ["2026-11-27", ...]}
"""
from datetime import date, datetime

# Normal-day chain, minutes after midnight PT. Early close = 10:00 PT → shift -180 min.
CHAIN_PT = {
    "slow_discovery": "05:30",
    "macro": "06:00",
    "fast_discovery": "11:15",
    "take_action": "11:50",
    "confirm_pass": "12:35",
    "position_monitor": "13:10",
    "true_up": "13:15",
    "eod": "13:30",
}
MOC_DEADLINE_NORMAL = "12:45"
MOC_DEADLINE_EARLY = "09:45"
EARLY_SHIFT_MIN = -180


def _d(s):
    return s if isinstance(s, date) else datetime.strptime(s, "%Y-%m-%d").date()


def status(today, cal):
    """Return {status, moc_deadline_pt, chain_shift_min, chain}."""
    t = _d(today)
    closed = {_d(x) for x in cal.get("closed", [])}
    early = {_d(x) for x in cal.get("early", [])}
    if t.weekday() >= 5 or t in closed:
        return {"status": "closed", "moc_deadline_pt": None, "chain_shift_min": 0, "chain": {}}
    if t in early:
        return {
            "status": "early_close",
            "moc_deadline_pt": MOC_DEADLINE_EARLY,
            "chain_shift_min": EARLY_SHIFT_MIN,
            # premarket tasks keep their slots; only the intraday chain moves with the 10:00 PT close
            "chain": {k: (_shift(v, EARLY_SHIFT_MIN) if k not in ("slow_discovery", "macro") else v) for k, v in CHAIN_PT.items()},
        }
    return {"status": "normal", "moc_deadline_pt": MOC_DEADLINE_NORMAL, "chain_shift_min": 0, "chain": dict(CHAIN_PT)}


def _shift(hhmm, minutes):
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m + minutes
    return f"{total // 60:02d}:{total % 60:02d}"
