# cc-solver

Deterministic rules-as-code for the Scan Fleet Restructure v2 take-action chain.

LLMs format, rank, and stage. This repo returns verdicts with exact reasons. Same inputs, same verdict.

Written by: Grok · 2026-09-08

## What it is

Python package fetched by scheduled tasks at run time. Do not paste these modules into prompts.

| Module | Job |
|---|---|
| `calendar.py` | NYSE closed / early-close / normal. Early close: MOC 09:45 PT, chain shifts 3h. |
| `universe.py` | Roster ∪ Discovery Board ∪ positions. Robinhood scans are a 399-row sample, never a universe. Massive adapter is a stub until Ray rules. |
| `rvol.py` | Pace-adjusted RVOL with a U-shaped RTH profile. |
| `doors.py` | Fresh 4 EMA reclaim, slow-sto 20 low, new-high tag, both exit doors, stop from current price. |
| `exposure.py` | Verbatim noon-scan / Last-Call / Desk Refresh script. 150/130 ex-SPY. |
| `ledger.py` | Handoff + Run Log payloads. Take-action appends Run Log only. |
| `grader.py` | Forward returns and miss-audit proposals. Never edits a rule. |
| `cli.py` | One entry point per task. |

## Hard constraints

- Robinhood `get_scans` and `run_scan` only. Never create or modify a scan.
- Never place, modify, or cancel any broker order. Never touch Robinhood Agentic account 608898375.
- Longs only in this design. Shorts are alert-only.
- Exit door is unresolved: both 4 EMA and 21 EMA flags are reported.
- Persistence: Git for code, Notion for decisions, Drive folder "Consistency Capital — Data Pulls" for bytes with SHA-256 manifests.

## Run

```bash
make test
python3 cli.py take_action --date 2026-09-08
python3 cli.py take_action --date 2026-09-08 --data-dir data/live/2026-09-08
python3 backtest/harness.py --tickers SNDK,BE --start 2026-01-02 --end 2026-09-04 --bars-dir data/live/2026-09-08/bars
```

`take_action` reads a snapshot directory (quotes, daily bars, roster, Discovery Board, positions). The scheduled task fetches live MCP, writes the snapshot, then runs this CLI. The solver never calls a broker.

## Take-action set

`roster ∪ Discovery Board names last 63 sessions ∪ open positions`

Robinhood scans stay viewing-only per the plan page (wins over the Desk Post contract that still listed them as universe input).

## Size

15% floor / 20% default / 25% best. The decision is which size, never whether. Stop = max(8%, 2×ATR14) from current price. Exposure breach is a banner; still stage at 15% with "say PASS to cancel".

## Tests

`make test` runs synthetic-bar door states (reclaim 0/1/2/3, slow-sto 20 low, both exit doors, deep break) and an early-close calendar test (2026-11-27).
