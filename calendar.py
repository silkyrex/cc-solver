"""NYSE session calendar. Source: Notion Market Calendar page plus 2026 holidays already passed."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
ROOT = Path(__file__).resolve().parent
CAL_PATH = ROOT / "config" / "holidays.json"


def load_calendar(path: Path | None = None) -> dict:
    return json.loads((path or CAL_PATH).read_text())


def parse_day(today) -> date:
    if today is None:
        return datetime.now(PT).date()
    if isinstance(today, datetime):
        return today.astimezone(PT).date()
    if isinstance(today, date):
        return today
    return date.fromisoformat(str(today)[:10])


def session_status(today=None, calendar: dict | None = None) -> dict:
    day = parse_day(today)
    cal = calendar or load_calendar()
    key = day.isoformat()
    if day.weekday() >= 5:
        return {
            "status": "closed",
            "moc_deadline_pt": None,
            "chain_shift_hours": 0,
            "reason": "weekend",
            "date": key,
        }
    if key in cal["closed"]:
        return {
            "status": "closed",
            "moc_deadline_pt": None,
            "chain_shift_hours": 0,
            "reason": "holiday",
            "date": key,
        }
    if key in cal["early_close"]:
        return {
            "status": "early_close",
            "moc_deadline_pt": cal["early_moc_deadline_pt"],
            "chain_shift_hours": int(cal["chain_shift_hours_early"]),
            "reason": "nyse_early_close",
            "date": key,
        }
    return {
        "status": "normal",
        "moc_deadline_pt": cal["regular_moc_deadline_pt"],
        "chain_shift_hours": 0,
        "reason": "regular_session",
        "date": key,
    }
