"""Run Log, Trader Handoff, Discovery Board payload builders + the failure detector.

The harness writes these dicts to Notion with notion-create-pages. Property names match the
databases created 2026-09-08:
  Run Log        ds collection://3f3a0dfe-6c6c-4b45-a71b-2766e2bdf547
  Trader Handoff ds collection://4c7f51d9-b603-48b0-802d-caede5296732
  Discovery Board ds collection://80054bcf-4866-44a6-ab57-8416317a6560
"""
from datetime import datetime, timedelta

RUN_LOG_DS = "collection://3f3a0dfe-6c6c-4b45-a71b-2766e2bdf547"
HANDOFF_DS = "collection://4c7f51d9-b603-48b0-802d-caede5296732"
BOARD_DS = "collection://80054bcf-4866-44a6-ab57-8416317a6560"
TASKS = ["Slow discovery", "Macro", "Fast discovery", "Take-action", "Confirm pass", "Position monitor", "True-up", "EOD", "EOW", "EOM", "Miss Audit", "Ad hoc"]
PUSH_TASKS = {"Take-action", "Confirm pass", "Position monitor", "EOD"}  # push budget ruling


def run_log_row(task, started_iso_pt, outcome, model, llm, inputs_read, what_i_did, output_link=None, errors="", duration_min=None, trigger_id=""):
    assert task in TASKS, task
    return {
        "Run": f"{started_iso_pt[:16].replace('T', ' ')} PT — {task}",
        "Task": task,
        "date:Started:start": started_iso_pt,
        "date:Started:is_datetime": 1,
        "Outcome": outcome,
        "Model": model,
        "LLM": llm,
        "Inputs read": inputs_read,
        "What I did": what_i_did,
        "Output link": output_link,
        "Pushed": "__YES__" if task in PUSH_TASKS and outcome == "OK" else "__NO__",
        "Duration min": duration_min,
        "Errors": errors,
        "Trigger ID": trigger_id,
    }


def handoff_row(session_date, fields, written_by="Claude", run_link=None, fleet_paused=False):
    d = datetime.strptime(session_date, "%Y-%m-%d")
    row = {
        "Session": f"{session_date} ({d.strftime('%a')})",
        "date:Date:start": session_date,
        "date:Date:is_datetime": 0,
        "Fleet paused": "__YES__" if fleet_paused else "__NO__",
        "Written by": written_by,
        "Run link": run_link,
    }
    for k in ["Open positions", "Staged today", "Doors near", "Exposure", "Open risk", "Discovery highlights", "Pending decisions", "Notes for tomorrow", "Day P&L", "Rule breaks"]:
        row[k] = fields.get(k, "")
    return row


def board_rows(universe_rows, layer, side, session_date, existing, llm="Solver", run_link=None, why_fn=None):
    """One Discovery Board payload per NEW (ticker, layer) or an update for an existing one.
    existing: {(ticker, layer): {"url", "first_seen", "seen_count"}} from today's query of the board (63-session window)."""
    out = []
    for r in universe_rows:
        if not r.get("ticker") or not any(s.startswith("scan:") or s == "thematic" for s in r["sources"]):
            continue
        key = (r["ticker"], layer)
        prev = existing.get(key)
        payload = {
            "Ticker": r["ticker"],
            "Layer": layer,
            "Side": side,
            "Theme": r.get("theme") or "",
            "Why": why_fn(r) if why_fn else ", ".join(r["sources"]),
            "date:Last seen:start": session_date,
            "date:Last seen:is_datetime": 0,
            "Excluded": "__YES__" if r["excluded"] else "__NO__",
            "Run link": run_link,
            "LLM": llm,
        }
        if prev:
            payload.update({"_update_url": prev.get("url"), "Seen count": (prev.get("seen_count") or 0) + 1})
        else:
            payload.update({"date:First seen:start": session_date, "date:First seen:is_datetime": 0, "Seen count": 1, "Price at first seen": r.get("last")})
        out.append(payload)
    return out


def discovery_missing(run_log_rows_today, required=("Slow discovery", "Fast discovery")):
    """Failure detector for the take-action run: which required discovery tasks have no OK/Partial row today."""
    done = {r.get("Task") for r in run_log_rows_today if r.get("Outcome") in ("OK", "Partial")}
    missing = [t for t in required if t not in done]
    return {"missing": missing, "banner": (f"DISCOVERY MISSING: {', '.join(missing)} — running on roster + 63-session board + positions only" if missing else None)}


def window_start(session_date, sessions=63):
    """Calendar-day approximation of 63 trading sessions (~91 days). Exact enough for a board filter."""
    return (datetime.strptime(session_date, "%Y-%m-%d") - timedelta(days=91)).strftime("%Y-%m-%d")
