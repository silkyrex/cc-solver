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
| `bars.py` | strip the leading/trailing runs of synthesized (padded) bars; count the sessions that actually traded | remove an interior gap (a halt is history); strip the provisional live bar |
| `doors.py` | entry state (4 EMA reclaim day 1/2/3+, slow sto 20 low, new 52w high), both exit doors (21 EMA 2nd close = mandatory, 4 EMA = warning), deep break, stop = max(8%, 2×ATR14) from current price on the adverse side, size tiers 15/20/25%, `breakeven_1r_reached` as context only (DEC-006 retired the profit-lock) — all side-aware (long or short) | authorize an entry; the LLM stages, Ray decides; guess a side |
| `exposure.py` | gross/net ex-SPY vs 150/130, verbatim math from the trigger prompts | change the caps |
| `ledger.py` | Run Log / Trader Handoff / Discovery Board payload dicts; `discovery_missing` failure banner; 63-session window | write to Notion |
| `grader.py` | forward returns at +5/10/20/30d, hit rate by layer, Miss Audit at 10/15/20/30%+ over 20 sessions | edit a rule |
| `cli.py` | `take_action`, `confirm_pass` (staged flips), `position_monitor`, `fast_discovery`, `eow`, `miss_audit`, `calendar` | anything not in `--inputs` |

## Run

```
make test                                                   # tests on synthetic bars
python -m ccsolver.cli take_action --inputs examples/inputs --date 2026-09-08 --allow-clock-drift
python -m ccsolver.cli calendar    --inputs examples/inputs --date 2026-11-27   # early close: chain shifts, MOC 9:45 AM
```

Every task runs a **PT clock check before any time-dependent work** and returns it as `time_check`.
A live task (`take_action`, `confirm_pass`, `position_monitor`, `fast_discovery`) **refuses** with exit
code 2 when the check errors: a session date in the future, an unparseable time, or a `pt_time` more
than two hours from the real Pacific clock. That last one is the real target — 11:50 AM PT is 18:50
UTC, so a UTC time landing in `pt_time` is 420 minutes off and would otherwise silently poison pace
RVOL and every provisional exit read. `--allow-clock-drift` is for deliberate replays and for the
shipped example, whose `pt_time` is pinned to 11:50 AM.

`examples/inputs/` shows every input file with its shape. `examples/take_action.out.json` is a full verdict.

## Input contract (what the harness writes)

See the docstring at the top of `ccsolver/cli.py`. Bars are settled daily bars; quotes are live; `pt_time` is the run time so pace RVOL and the provisional "today" close are honest about being intraday.

**Where the live fleet actually gets bars.** Every Fleet v2 task pulls them from Robinhood `get_equity_historicals` (interval `day`, bounds `regular`, `adjustment_type` `split`, `start_time` 130 calendar days ago), not IBKR `get_price_history`.

That feed returns one bar per session across the **whole** requested range, traded or not. Sessions before the listing come back synthesized: OHLC all equal, volume 0, `interpolated: true`, priced at the first real bar's open. The prompts map bars to `{date, open, high, low, close, volume}`, which drops the flag, so `bars.py` identifies them by shape as well and **no prompt edit is needed**. Pass `interpolated` through if you like; it is honoured when present.

## Rules encoded (source: Trading System v1.0 + Sep 8 rulings)

- Long entry: fresh 4 EMA reclaim day 1 or valid day 2 only; day 3+ = stale. Slow sto k(14) d(1) dip <20 then first close back above the 4 EMA = second door. New 52w high = priority tag, not a door.
- Price basis = last price at run time (MOC decision happens before the close). MOC deadline 12:45 PT, 09:45 on early-close days.
- Exit door RULED (Ray, 2026-09-08, direct ruling and not a backtest result): the **21 EMA second consecutive close is the mandatory exit**; the 4 EMA door is a **warning**. A deep break (>4% through the 4 EMA) is also mandatory. Both doors stay in the payload; only `mandatory_exit` drives the push budget.
- **The staged verdict carries its own record.** Every STAGE emits a `held_row` block for the harness to write onto `held.json`. The rule for what belongs in it: **store the decision, not the data.** Bars can always be re-pulled, so anything an indicator recomputes stays out. What dies if unwritten is why the trade was taken and on what terms — `reclaim_day_at_entry` (the bucketing key for the day-1-to-5 question), `entry_trigger`, `entry_door`, `entry_datetime`, the EMAs and ATR at entry, and `sizes_recommended_at_entry` alongside empty `size_tier_taken` / `shares_taken` slots the harness fills once Ray picks. Regime is deliberately absent: no task prompt supplies it, and inventing a source for a sizing input is a guess that goes unnoticed.
- **12:25 PM is the actionable slot, and two tasks share it.** `confirm_pass` re-checks the 11:50 AM staged names against the 4 EMA on the live price and pushes only on a flip. `position_monitor` runs the same slot against the Positions DB and owns the held-name provisional exit read (`provisional_mandatory`). The split is deliberate (Ray, 2026-09-08): held names were briefly checked in both, which would push the same name twice in the 20 minutes before the 12:45 PM MOC deadline. The 1:30 PM EOD run confirms on settled closes.
- **Provisional exits.** The MOC deadline is 12:45 PM PT and the close is 1:00 PM, so a mandatory exit computed on settled closes is only knowable *after* Ray can act on it. Pass `quotes.json` to `position_monitor` and every row also carries `provisional_mandatory` / `provisional_reason` / `provisional_note` — the same door tests run against the live price. Confirmed and provisional never share a field: `mandatory_exit` is settled closes only. A provisional bar can never **graduate** a position; graduation is one-way, so only a settled close may drive it.
- **The door binds at entry** (Ray, 2026-09-08, second ruling). The 21 EMA rule is incoherent for a position opened on the wrong side of the 21 EMA: a relaunch entry (>30% off the high, fresh 4 EMA reclaim) is under the 21 EMA by construction, so it would be born dozens of closes deep into its own mandatory exit. Verified: such an entry reported `closes_against_21ema=27` and `mandatory_exit=true` on the staging bar. So `entry_state` emits `entry_door` — `21ema` when price is on the favourable side of the 21 EMA at entry, `4ema` otherwise — and the position runs on that door. A `4ema` position **graduates** to the 21 EMA door on its first close on the favourable side of the 21 EMA since `entry_date`. The leash only loosens; a graduated position is never demoted. No `entry_date` means graduation cannot be established and the tight door stands. A held row with **no `entry_door` at all** also gets the tight `4ema` door: it cannot prove it ever cleared the 21 EMA, and the Positions DB backfills the field empty, so a loose default there would silently unleash every open position. `doors.exit_state` therefore takes `entry_door_` as a required keyword argument — there is no default to fall into.
- Every exit test is side-aware. A short is in trouble when price closes **above** the EMAs, its stop sits **above** the current price, and +1R is a move **down**. Side comes from `held.json`, else the sign of the IBKR position; if neither resolves, the row returns `SIDE UNKNOWN` and pushes rather than defaulting to long — a guessed side puts the stop on the profitable side of price and leaves the real risk unprotected.
- Sizing 15% floor / 20% / 25%; the decision is which size, never whether. Stop max(8%, 2×ATR14) from CURRENT price.
- **A stop never moves on profit** (DEC-006, Ray 2026-09-08, PRODUCTION). This supersedes DEC-005 (breakeven-at-+1R) and the 2026-08-26 stop ratchet ladder. `breakeven_1r_reached` is still emitted and is **context only** — no rule reads it. A 2026-09-08 replication put breakeven-at-+1R at 3.762% vs a 3.990% baseline over 2,231 trades, 95% CI −0.650 to +0.061, so the rule was never distinguishable from doing nothing; everything that harvests open profit earlier tested worse. The emotional-exit protocol (stop to just beyond the day's extreme) is unchanged and still authorized.
- Exposure 150/130 ex-SPY; breach = banner, still stage at the floor with "say PASS to cancel".
- Take-action inputs = roster ∪ Discovery Board (63 sessions) ∪ open positions ∪ today's non-excluded scan hits (Ray ruled Sep 8: same-day hits may stage). Shorts alert-only.
- Roster and held names are never excluded from monitoring, only from staging.

## Known gaps (honest list)

0. Fund-name exclusion needs a leverage word (`Bull`, `3X`, `UltraShort`, ...) on a word boundary AND an issuer token (`ETF`, `Shares`, `Direxion`, ...). Bare substrings used to eat RARE (Ultragenyx), ROLL (RBC Bearings) and DJCO (Daily Journal). Compound leverage forms are enumerated explicitly, so a new one (`UltraProShort2X`) needs adding to `DEFAULT_PATTERNS`.
1. Provisional bar takes `day_high`/`day_low` from quotes.json (Ray, Sep 8). If the harness omits them, high = low = last price and slow sto reads slightly low on strong up days.
2. `window_start` approximates 63 sessions as 91 calendar days.
3. `grader.miss_audit` classifies nothing; it lists. The LLM classifies, Ray rules.
4. No backtest harness **in this repo**, and no committed bar corpus. Backtests do get run outside it: DEC-006 rests on two, the second over 2,231 trades with a paired bootstrap. Read that as "the repo cannot reproduce a desk backtest", not "no backtest exists". The exit door no longer waits on one (ruled 2026-09-08); what is still gated is stop 5 vs 8, the day-3 staleness cutoff, and insurance thresholds.
5. Structure layer (HH/HL pivots) not implemented; the spec deferred it to the slow-discovery LLM task.
6. ~~Nothing filters interpolated bars.~~ **Handled 2026-09-09** (`bars.py`, Ray approved). Padded bars are stripped from both edges before any door is read, and every verdict now carries `real_bars`. Below **30 real sessions** the 21 EMA read is withheld rather than guessed: `entry_state` returns `ema21: null` and binds the tight `4ema` door, `exit_state` returns `closes_against_21ema: null` and `door_21ema: "unknown"`, and `position_monitor` pushes the row. A deep break still fires, because that is a 4 EMA test. **Residuals:** interior padded bars (a halt) are deliberately kept and counted as not-history, so a name with many interior gaps can read thin while holding a long date range; and 30 is a judgment call, not a derived number — 21 is the bare minimum for any 21 EMA value, and 60 (what the prompts ask for in raw bars) would have refused SKHY at 41 real sessions and SPCX at 59 on the day this shipped.
7. **`graduated_date` is written and never read.** `held_row` emits it, the Positions DB stores it as "Graduated on", and the position-monitor prompt maps it into `held.json`. `cli.position_monitor` does not pass it to `doors.exit_state`, which recomputes graduation from the bars it was given. A position held longer than the harness's 130-calendar-day bar window therefore loses its graduation and drops back to the tight `4ema` door, against the stated "never demoted" rule. Error direction is an early exit, not a late one.
