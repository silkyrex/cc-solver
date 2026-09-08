# Build 2 review — `main` vs `grok/build-2`

Reviewed 2026-09-08 by Claude (Opus 5). Both trees read in full; both suites run.
`main` @ b926945 (13 pytest, pass) · `grok/build-2` @ e9320ee (26 unittest, pass).

## There is nothing to merge

`main` and `grok/build-2` share **no common ancestor** — GitHub's compare endpoint returns 404. These are two independent implementations of the same spec (Desk Post "2026-09-08 Claude Open Build 2 handoff", plan page "Scan Fleet Restructure v2"). This was a pick, not a diff.

## Verdict

**`main` stays canonical.** build-2 is competent code with one disqualifying design flaw: it collapses the harness/solver boundary the repo exists to enforce.

Passing tests were not the deciding evidence. Both suites are green; the defects below are all outside what either suite covers.

---

## build-2 defects (each reproduced by running the code)

| # | Defect | Evidence | Cost |
|---|---|---|---|
| 1 | **An open position returns `EXCLUDED`, not `HOLD`** | Ran `take_action` with TQQQ held: `EXCLUDED TQQQ … exit_4ema=day1_discretion` | Exit-door monitoring silently drops on live money. `main` has a `held/roster overrides` escape; build-2 has none. |
| 2 | **Non-deterministic** — `cli.py:248` reads `datetime.now(ET)` for the RVOL pace clock | Same snapshot, different run time → different verdict | Breaks "same inputs, same verdict", the one line both READMEs open with. Any replay or backtest through the CLI is wrong. `main` takes `pt_time` from `account.json`. |
| 3 | **Root `calendar.py` shadows the stdlib** | `import pandas` inside the repo → `AttributeError: module 'calendar' has no attribute 'day_abbr'` | Latent until someone adds a dependency; then anything touching stdlib `calendar` (pandas, requests, email.utils) dies. `main`'s `ccsolver/` package avoids it. |
| 4 | **Held names on a fresh reclaim hit `STAGE_LONG`** | The `reclaim_day in (1,2)` branch is evaluated before the position check | Silent pyramiding into an open position with no add rule. `main` gates on `and t not in held`. |
| 5 | **`slow_sto_20_low` computed, never read** | Appears in output; no branch consumes it | Entry door #2 is decorative. `main` folds it into `door_open`. |
| 6 | **Breakeven-at-+1R uses today's stop, not the entry-time stop** | `r = entry - entry*(1-stop_pct)` where `stop_pct` is recomputed from current ATR | R drifts with volatility; the BE trigger fires early or late. `main` passes `initial_stop` from `held.json`. |
| 7 | **63-session board window is in the README, not the code** | `take_action` loads `discovery_board.json` wholesale | Stale names re-enter the action set forever. `main` has `ledger.window_start`. |
| 8 | `reclaim_day` never clamped | Output showed `reclaim_day: 258`. The clamp is a no-op ternary: `rec if rec < 3 else rec` | Cosmetic, but it is dead code where a clamp was intended. |
| 9 | `exposure.py` is a bare argv script, not a module | `cli.py` shells out via `subprocess` with the positions blob as an argv string | Untestable as a function; degrades silently to `banner: None` on any `KeyError`. `main` keeps identical math in a function with a `__main__` shim. |
| 10 | No example inputs, no golden output | build-2 ships only a `data/README.md` describing a gitignored directory | The input contract is unverifiable. `main` ships `examples/inputs/*` + `examples/take_action.out.json`. |

## What build-2 does better

- **`backtest/harness.py`** — replays `doors.evaluate` over a ticker list and date range. `main`'s own README lists this as known gap #4, and the exit-door question is explicitly blocked on a backtest. Worth porting.
- **`persistence.py`** — SHA-256 manifests over a pull directory. Clean, dependency-free, no `main` equivalent.
- **`config/*.json`** — exclusions, holidays and scan IDs as committed data rather than module constants. Better shape.

---

## Shared flaw — fixed on `main` 2026-09-08

The exclusion matcher was an unanchored substring test on **both** trees. Confirmed false positives:

| Ticker | Name | Matched on |
|---|---|---|
| RARE | Ultragenyx Pharmaceutical | `Ultra` |
| ROLL | RBC Bearings Inc | `Bear` |
| DJCO | Daily Journal Corp | `Daily` |

For a momentum desk this deletes real candidates before they reach a door check. The Miss Audit's own `classification` string already lists "exclusion false positive" as a bucket — this was that bucket, live.

`main`'s `held/roster overrides` escape capped the blast radius. build-2's lack of one is exactly what turns this shared flaw into defect #1 above.

Fixed in `fix/exclusion-matcher`: a name is excluded only when a leverage word matches on a **word boundary** AND an issuer token (`ETF`, `Shares`, `Direxion`, `ProShares`, `YieldMax`, …) is present. Compound forms (`UltraShort`, `UltraProShort`) are enumerated explicitly, since boundary matching means `Ultra` no longer matches inside `UltraShort`.

**Open follow-up:** the two-token rule now also applies to custom patterns supplied via `exclusion.json`. A bare pattern from the Notion Exclusion List used to exclude on its own; it now needs an issuer token in the name. Verify the live list still fires as intended.

Also hardened in the same commit: `board_rows` / `grade_board` / `miss_audit` degrade on a malformed Notion row instead of raising, and `fast_discovery` no longer drops the held/roster override (it was calling `universe.build(..., positions=[], ...)`).

---

## Spec conflicts

The two builds read the same source documents and disagreed. These are desk rulings, not code defects.

All five were ruled by Ray on 2026-09-08. **Every ruling went to `main`, which already implements all of them — no code change followed from any of the five.**

| # | Question | Ruling | Why |
|---|---|---|---|
| 1 | Can a same-day scan hit be staged today? | **Yes** (`main`) | The entry door is reclaim day 1 / day 2 only. A one-session lag eats the window the edge lives in. |
| 2 | Pump exclusion threshold | **sub-$10 on >20x RVOL** (`main`) | The $3–$10 band is where most freak-volume pumps actually sit. The held/roster override protects anything already owned or rostered. |
| 3 | "Slow sto k(14) d(1)" | **SMA(3) of fast %K** (`main`) | The chart draws the smoothed line; `d(1)` means "no extra D line", not "no smoothing". Raw %K dips under 20 far more often, so build-2 would have armed the second entry door on setups Ray never sees. |
| 4 | Who picks the size? | **Solver emits all three tiers, Ray picks** (`main`) | "The decision is which size, never whether" means Ray choosing among tiers. Letting code pick converts a judgment call into an unruled rule. |
| 5 | Cluster source | **Notion Thematic Watchlists, fed in at run time** (`main`) | Themes are edited where every other desk artifact is edited, and are live on the next run. A committed `themes.json` goes stale exactly when a new theme is heating up. |

build-2 lost all five. Combined with the ten defects above, nothing in that branch survives except the two ports listed under "What build-2 does better".

## Recommended sequence

1. ~~Rule conflict #1~~ — done 2026-09-08.
2. ~~Fix the exclusion matcher on `main`~~ — done, commit 5856920.
3. ~~Rule conflicts #2–#5~~ — done 2026-09-08, all to `main`, no code change.
4. Verify the live Notion Exclusion List patterns still fire under the two-token rule.
5. Port `backtest/harness.py` and `persistence.py` into `ccsolver/`.
6. Retire `grok/build-2` once #5 lands.
