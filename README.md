# cc-solver

Deterministic rules-as-code for Ray's Consistency Capital desk. Repo: https://github.com/silkyrex/cc-solver Build 2 of the Scan Fleet Restructure v2 (Sep 2026).
Written by: Claude (Fable 5.1), 2026-09-08. Spec: Notion Desk Post "2026-09-08 Claude Open Build 2 handoff — solver repo spec for Grok". Rulings: Notion plan page "Scan Fleet Restructure v2 — plan (2026-09-08)".

## The one design decision

The solver never calls a broker or Notion. The scheduled-task harness (Cowork / Claude / Grok) makes every MCP call, writes the results as JSON into a directory, runs one CLI command, and formats the JSON verdict it gets back. Same inputs, same verdict, every time. This is what makes the code testable on synthetic bars and what keeps three LLMs from each re-implementing the rules in prose.

```
harness: MCP calls → inputs/*.json → python -m ccsolver.cli <task> --inputs inputs --date YYYY-MM-DD → JSON → LLM formats, stages, writes Notion rows
```

## Modules

| Module | Does | Never does |
|---|---|---|
| `calendar.py` | closed / early_close / normal; MOC deadline; chain times (intraday chain shifts −3h on early close, premarket slots stay) | fetch the calendar (harness exports the Notion page) |
| `universe.py` | union scans + thematic + roster + positions; tag sources and theme; apply the Exclusion List (fund-name patterns, sub-$10 pumps on >20x volume, named list); tandem clusters (3+ names) | treat a Robinhood scan as a universe (399-row cap); exclude a name on a leverage word alone, or exclude anything held or rostered |
| `rvol.py` | pace-adjusted relative volume against a U-shaped intraday curve | use raw dayVolume/avgVolume as buzz (reads 0.5–0.7 at 11:15) |
| `doors.py` | entry state (4 EMA reclaim day 1/2/3+, slow sto 20 low, new 52w high), both exit doors (21 EMA 2nd close = mandatory, 4 EMA = warning), deep break, stop = max(8%, 2×ATR14) from current price on the adverse side, size tiers 15/20/25%, breakeven at +1R — all side-aware (long or short) | authorize an entry; the LLM stages, Ray decides; guess a side |
| `exposure.py` | gross/net ex-SPY vs 150/130, verbatim math from the trigger prompts | change the caps |
| `ledger.py` | Run Log / Trader Handoff / Discovery Board payload dicts; `discovery_missing` failure banner; 63-session window | write to Notion |
| `grader.py` | forward returns at +5/10/20/30d, hit rate by layer, Miss Audit at 10/15/20/30%+ over 20 sessions | edit a rule |
| `cli.py` | `take_action`, `confirm_pass`, `position_monitor`, `fast_discovery`, `eow`, `miss_audit`, `calendar` | anything not in `--inputs` |

## Run

```
make test                                                   # 12 tests on synthetic bars
python -m ccsolver.cli take_action --inputs examples/inputs --date 2026-09-08
python -m ccsolver.cli calendar    --inputs examples/inputs --date 2026-11-27   # early close: chain shifts, MOC 09:45
```

`examples/inputs/` shows every input file with its shape. `examples/take_action.out.json` is a full verdict.

## Input contract (what the harness writes)

See the docstring at the top of `ccsolver/cli.py`. Bars are settled daily bars from IBKR `get_price_history`; quotes are live; `pt_time` is the run time so pace RVOL and the provisional "today" close are honest about being intraday.

## Rules encoded (source: Trading System v1.0 + Sep 8 rulings)

- Long entry: fresh 4 EMA reclaim day 1 or valid day 2 only; day 3+ = stale. Slow sto k(14) d(1) dip <20 then first close back above the 4 EMA = second door. New 52w high = priority tag, not a door.
- Price basis = last price at run time (MOC decision happens before the close). MOC deadline 12:45 PT, 09:45 on early-close days.
- Exit door RULED (Ray, 2026-09-08, direct ruling and not a backtest result): the **21 EMA second consecutive close is the mandatory exit**; the 4 EMA door is a **warning**. A deep break (>4% through the 4 EMA) is also mandatory. Both doors stay in the payload; only `mandatory_exit` drives the push budget.
- **The door binds at entry** (Ray, 2026-09-08, second ruling). The 21 EMA rule is incoherent for a position opened on the wrong side of the 21 EMA: a relaunch entry (>30% off the high, fresh 4 EMA reclaim) is under the 21 EMA by construction, so it would be born dozens of closes deep into its own mandatory exit. Verified: such an entry reported `closes_against_21ema=27` and `mandatory_exit=true` on the staging bar. So `entry_state` emits `entry_door` — `21ema` when price is on the favourable side of the 21 EMA at entry, `4ema` otherwise — and the position runs on that door. A `4ema` position **graduates** to the 21 EMA door on its first close on the favourable side of the 21 EMA since `entry_date`. The leash only loosens; a graduated position is never demoted. No `entry_date` means graduation cannot be established and the tight door stands.
- Every exit test is side-aware. A short is in trouble when price closes **above** the EMAs, its stop sits **above** the current price, and +1R is a move **down**. Side comes from `held.json`, else the sign of the IBKR position; if neither resolves, the row returns `SIDE UNKNOWN` and pushes rather than defaulting to long — a guessed side puts the stop on the profitable side of price and leaves the real risk unprotected.
- Sizing 15% floor / 20% / 25%; the decision is which size, never whether. Stop max(8%, 2×ATR14) from CURRENT price; breakeven at +1R.
- Exposure 150/130 ex-SPY; breach = banner, still stage at the floor with "say PASS to cancel".
- Take-action inputs = roster ∪ Discovery Board (63 sessions) ∪ open positions ∪ today's non-excluded scan hits (Ray ruled Sep 8: same-day hits may stage). Shorts alert-only.
- Roster and held names are never excluded from monitoring, only from staging.

## Known gaps (honest list)

0. Fund-name exclusion needs a leverage word (`Bull`, `3X`, `UltraShort`, ...) on a word boundary AND an issuer token (`ETF`, `Shares`, `Direxion`, ...). Bare substrings used to eat RARE (Ultragenyx), ROLL (RBC Bearings) and DJCO (Daily Journal). Compound leverage forms are enumerated explicitly, so a new one (`UltraProShort2X`) needs adding to `DEFAULT_PATTERNS`.
1. Provisional bar takes `day_high`/`day_low` from quotes.json (Ray, Sep 8). If the harness omits them, high = low = last price and slow sto reads slightly low on strong up days.
2. `window_start` approximates 63 sessions as 91 calendar days.
3. `grader.miss_audit` classifies nothing; it lists. The LLM classifies, Ray rules.
4. No backtest harness, and no bar corpus to run one on. The exit door no longer waits on it (ruled 2026-09-08), so this now only gates the *next* rule questions: stop 5 vs 8, the day-3 staleness cutoff, insurance thresholds.
5. Structure layer (HH/HL pivots) not implemented; the spec deferred it to the slow-discovery LLM task.
