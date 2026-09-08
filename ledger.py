"""Read Handoff + Run Log snapshots. Format Run Log / Discovery Board payloads. Never place orders."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

RUN_LOG_DS = "3f3a0dfe-6c6c-4b45-a71b-2766e2bdf547"
HANDOFF_DS = "4c7f51d9-b603-48b0-802d-caede5296732"
DISCOVERY_DS = "80054bcf-4866-44a6-ab57-8416317a6560"
ROSTER_DS = "85064c30-71d2-44e3-966f-667e2fab5533"


def fleet_paused(handoff: dict | None) -> bool:
    if not handoff:
        return False
    val = handoff.get("Fleet paused") or handoff.get("fleet_paused")
    return val in (True, "__YES__", "true", "True", 1)


def discovery_missing(run_log_rows: list[dict], task_names=("Slow discovery", "Fast discovery")) -> bool:
    have = {r.get("Task") or r.get("task") for r in run_log_rows}
    return not any(name in have for name in task_names)


def run_log_payload(
    *,
    task: str,
    started_iso: str,
    model: str,
    inputs_read: str,
    what_i_did: str,
    outcome: str,
    errors: str = "",
    duration_min: float | None = None,
    output_link: str = "",
    pushed: bool = False,
) -> dict:
    when = datetime.now(PT).strftime("%Y-%m-%d %H:%M PT")
    return {
        "data_source_id": RUN_LOG_DS,
        "properties": {
            "Run": f"{when} - {task}",
            "Task": task,
            "LLM": "Solver",
            "Model": model,
            "Outcome": outcome,
            "Inputs read": inputs_read,
            "What I did": what_i_did,
            "Errors": errors,
            "Output link": output_link,
            "Pushed": "__YES__" if pushed else "__NO__",
            "Trigger ID": "cli.py",
            "date:Started:start": started_iso,
            "date:Started:is_datetime": 1,
            **({"Duration min": duration_min} if duration_min is not None else {}),
        },
    }


def discovery_row_payload(
    *,
    ticker: str,
    layer: str,
    side: str,
    why: str,
    theme: str = "",
    excluded: bool = False,
    first_seen: str,
    last_seen: str,
    seen_count: int = 1,
    run_link: str = "",
    price: float | None = None,
) -> dict:
    props = {
        "Ticker": ticker,
        "Layer": layer,
        "Side": side,
        "Why": why,
        "Theme": theme,
        "Excluded": "__YES__" if excluded else "__NO__",
        "LLM": "Solver",
        "Seen count": seen_count,
        "Run link": run_link,
        "date:First seen:start": first_seen,
        "date:First seen:is_datetime": 0,
        "date:Last seen:start": last_seen,
        "date:Last seen:is_datetime": 0,
    }
    if price is not None:
        props["Price at first seen"] = price
    return {"data_source_id": DISCOVERY_DS, "properties": props}
