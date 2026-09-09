# Build 4 replication — `backtest/harness.py` against the 2026-09-08 exit-door backtest

**Run 2026-09-09.** Corpus rebuilt from Robinhood in-session; Build 4's own summary and
universe read from Drive ("Consistency Capital — Data Pulls").

## Build 4 exists

`docs/HANDOFF-2026-09-08.md` and `docs/reviews/2026-09-08-build-2-review.md` both say the
Build 4 backtest "does not exist in any branch". That is true of this repo and false as a
statement about the run. It is in Drive:

- `build4_exit-door_2026-09-08_summary.json`
- `build4_exit-door_2026-09-08_universe.json`

with bars, per-trade CSVs and summary on Ray's Mac at `~/Downloads/cc-solver 2/build4/`.
Those two files are the source for every Build 4 figure quoted below. The "never cite one"
instruction should be read as "never cite it from this repo", not "it did not happen".

## The corpus is bit-identical

Rebuilt with `get_equity_historicals`, `day` / `regular` / `split`, 2024-08-01 → 2026-09-04,
the exact pull Build 4's universe file describes.

| | Build 4 | rebuilt |
|---|---|---|
| symbols | 114 | 114 |
| interpolated bars | 3040 | **3040** |
| short histories | IOND 29, SKHY 41, SPCX 59, FRVO 80, DRAM 108, LIFE 152 | **all six match** |

Same input, not an approximation.

## Results, reclaim day 1

Build 4 door names: A = 4 EMA 2nd close, B = 21 EMA 2nd close, C = first of A/B,
A1 = 4 EMA 1st close.

| door | metric | Build 4 | harness | ratio |
|---|---|---|---|---|
| **A1** `4ema-first-close` | n | 7889 | 7763 | 0.984 |
| | win rate | 33.5 | 33.6 | 1.002 |
| | profit factor | 1.517 | 1.486 | 0.980 |
| | mean return | 1.340 | 1.278 | 0.954 |
| | avg hold | 3.62 | 3.60 | 0.994 |
| **A** `4ema-day2` | n | 5104 | **5109** | 1.001 |
| | win rate | 35.7 | 36.2 | 1.015 |
| | profit factor | 1.694 | 1.625 | 0.959 |
| | mean return | 2.564 | 2.301 | 0.898 |
| | avg hold | 7.09 | 6.79 | 0.958 |
| **B** `21ema` | n | 4125 | 3957 | 0.959 |
| | profit factor | 2.343 | 1.925 | 0.822 |
| | mean return | 4.409 | 3.675 | 0.833 |
| **C** `first-of-both` | n | 5566 | 5927 | 1.065 |
| | mean return | 2.212 | 1.654 | 0.748 |
| | avg hold | 5.70 | 4.69 | 0.823 |

Door ranking is preserved: B > A > C > A1 in both.

**The two pure 4 EMA doors reproduce.** A's trade count lands within 5 of 5104 and A1's
average hold within 0.02 sessions of 3.62. Counts that structural do not match by accident
across 5,000–8,000 trades: the entry rule, the stop and the 4 EMA door are right.

## Build 4's two conventions, recovered from the numbers

The residual return gap on those two doors is **not** noise and it is not the door. Two
convention differences account for it, isolated in a 2×2 over both 4 EMA doors. Ratios are
harness/Build 4; 1.000 is an exact reproduction.

| door A — Build 4 n=5104, mean 2.564, PF 1.694, hold 7.09 | n | mean | PF | hold |
|---|---|---|---|---|
| deep break + close fill — *what the harness does* | 0.989 | 0.843 | 0.933 | 0.965 |
| no deep break + close fill | 0.971 | 0.897 | 0.944 | **1.002** |
| deep break + next-open fill | 0.989 | 0.947 | 0.977 | 0.965 |
| **no deep break + next-open fill** | 0.971 | **0.980** | 0.975 | **1.002** |

| door A1 — Build 4 n=7889, mean 1.340, PF 1.517, hold 3.62 | n | mean | PF | hold |
|---|---|---|---|---|
| deep break + close fill — *what the harness does* | 0.975 | 0.885 | 0.954 | 0.997 |
| no deep break + close fill | 0.975 | 0.885 | 0.954 | 0.997 |
| **next-open fill** (the deep break is a no-op here) | 0.975 | **1.010** | 0.986 | 0.997 |

1. **Build 4's doors do not apply the >4% deep break.** Its door names are plain close tests
   and they behave like them. Removing the deep break moves door A's average hold from 6.84
   to 7.10 against Build 4's 7.09 — 0.965 to **1.002**. `doors.py` makes the deep break
   mandatory under either door (Ray, 2026-09-08), so the harness is right for the live rule
   and Build 4 measured the door in isolation.
2. **Build 4 fills an exit at the next session's open.** The harness fills at the signal
   day's close. Next-open is the more conservative reading of a settled-close signal — you
   cannot sell into a close you have only just observed. The harness's choice is defensible
   for *this* desk, which reads provisional exits at 12:25 PT and can act before the 12:45
   MOC deadline, so a same-day close fill is genuinely reachable live. Both are legitimate;
   they are not the same experiment.

The two are additive, not double-counted: door A walks 0.843 → 0.897 → 0.980. **Under both
conventions the harness reproduces Build 4 to within 3% on every metric of both 4 EMA doors.**

The control that makes this trustworthy: door A1 is **bit-identical** with and without the
deep break — n, mean, PF and hold unchanged to three decimals — because for "first close
below the 4 EMA" a deep break already *is* a first close below: same bar, same price, only
the label differs. That was predicted before the run.

Residual `n` of 0.971–0.975 is accounted for by documented, deliberate differences: IOND is
refused outright (29 real sessions, permanently under `MIN_REAL_BARS_21EMA`; it is the only
name in the universe with zero trades here, and Build 4 kept it), 32 unresolved end-of-range
entries are dropped rather than booked at 0.00%, and 22 day-2 trades sit outside the day-1
bucket.

**Neither convention is adopted into the harness.** Both would change what it measures away
from the live rule: the deep break is production under Ray's 2026-09-08 ruling, and the close
fill matches how this desk actually exits. They are recorded here so a Build 4 figure and a
harness figure are never compared as though they were the same measurement.

**Both doors that involve the 21 EMA diverge**, and they diverge in opposite directions —
B holds longer and trades less, C holds shorter and trades more. Those are two different
causes, one per door, and both are identified below.

## Why B diverges: the door binds at entry now, and did not then

How production splits the day-1 trades, which is what makes the 21 EMA door a different
animal from the one Build 4 measured:

| day-1 trades, door B, as production runs it | n | share | mean | PF | hold |
|---|---|---|---|---|---|
| all | 3957 | 100% | 3.675 | 1.925 | 9.33 |
| bound `21ema` at entry | 1508 | 38% | 4.420 | 2.005 | 10.86 |
| bound `4ema` at entry | 2449 | 62% | 3.215 | 1.866 | 8.39 |
| …graduated | 1093 | 28% | 13.670 | 12.917 | 14.79 |
| …never graduated | 1356 | 34% | −5.212 | 0.098 | 3.22 |

62% of the trades never run on the 21 EMA door at all — they bind to the tight 4 EMA leash
at entry under the second 2026-09-08 ruling.

(The bound-`21ema` subgroup averaging 4.420 against Build 4's 4.409 is a **coincidence** of
subgroup composition, not evidence. It was briefly read as evidence and it is not: the
reproduction below comes from a full replay, not a subgroup.)

Build 4 ran on 2026-09-08, the same date as the bind-at-entry ruling, so the hypothesis was
that **it measured the 21 EMA door before binding existed.** That hypothesis was tested,
rejected, and then **re-confirmed** — the rejection was itself wrong, because the rejecting
run used the deep break and close fills, i.e. the two conventions this document later shows
Build 4 does not use. Under Build 4's own conventions:

| door B variant, day 1 | n | mean | PF | hold |
|---|---|---|---|---|
| Build 4 B (reference) | 4125 | 4.409 | 2.343 | 8.73 |
| bound at entry, deep break, close fill — **full production** | 3927 (0.952) | 3.521 (0.799) | 1.870 (0.798) | 9.47 (1.085) |
| bound at entry, no deep break, next-open fill | 3927 (0.952) | 3.832 (0.869) | 1.953 (0.833) | 9.47 (1.085) |
| unbound (streak since entry), deep break, close fill | 4323 (1.048) | 2.999 (0.680) | 1.863 (0.795) | 7.75 (0.888) |
| **unbound, no deep break, next-open fill** | **3988 (0.967)** | **4.640 (1.052)** | **2.333 (0.996)** | **8.81 (1.009)** |

The last row is a reproduction: profit factor within 0.4%, hold within 1%, trade count within
3.3%, mean within 5.2%. **Build 4's door B is the 21 EMA second consecutive close counted
since entry, with no bind-at-entry, no deep break, and a next-open fill.**

The methodological lesson is worth keeping: the first probe rejected the right hypothesis
because two unrelated conventions were wrong at the same time, and they happened to suppress
the unbound variant (2.999) below the bound one (3.521). One wrong control inverted the
conclusion. Nothing was concluded from a single probe after that.

### What this means for the desk

With both conventions matched, binding is the only remaining difference, so it can be priced
cleanly for the first time:

| 21 EMA door, like-for-like (no deep break, next-open fill) | mean/trade | PF |
|---|---|---|
| unbound — what Build 4 measured | 4.640 | 2.333 |
| bound at entry — the 2026-09-08 ruling | 3.832 | 1.953 |
| **cost of binding** | **−0.81%/trade** | −0.38 |

And the number that actually describes the live rule — bound, deep break, close fill — is
**3.521%/trade at PF 1.870**, against the 4.409% in the Build 4 summary.

> **Build 4's +4.41% does not describe the exit door the desk runs today**, and the gap is
> now fully accounted for rather than asserted: −0.81 from binding, and the remainder from
> the deep break and the fill convention.

That is not an argument to unbind. Binding exists because the unbound rule is incoherent for
a relaunch entry, which is born dozens of closes into its own mandatory exit — and the
unbound row above cannot express that cost, because a backtest never suffers the incoherence
a live position does. It is an argument that the Build 4 figure should not be quoted as the
current door's expectancy. **Ray's call, not the harness's.**

## Why C diverges: a real defect in this harness

`first-of-both` reads `closes_against_21ema`, which `doors.exit_state` counts over the whole
history rather than since entry. A position opened below the 21 EMA is therefore already
past the test on its first session:

| `first-of-both`, day 1 | value |
|---|---|
| trades entered below the 21 EMA | 2935 of 5927 (50%) |
| …of those, exiting within 1 session | **2380 (81%)** |
| avg hold, entered below | 2.4 |
| avg hold, entered above | 6.94 |

That door does not implement "first of both doors"; it implements "exit at once if you
entered below the 21 EMA". Its returns are unusable and its hold is a lower bound.

**Not fixed here, deliberately.** The fix needs a since-entry 21 EMA count, which
`exit_state` does not publish. Computing one in the harness would put a second copy of the
door logic outside `doors.py` — the thing the port was told not to do. Per the standing
rule, a harness that cannot express something without changing a rule reports it instead:
this needs a `ccsolver` change and therefore a Decision Log entry. Until then the door
carries the defect in its own output payload (`warnings`), so no number can be quoted
without the caveat travelling with it.

The production `21ema` door is **not** affected — only 6% of its below-21-EMA entries exit
within a session, against 81% here. Binding is exactly what handles this case.

## Two definitional differences, neither a defect

1. **Giveback.** Build 4's column is `giveback_median_pct`. On door A it reports 46.6; this
   harness reports 56.1 over winners and 125.7 over all trades. An all-trades median cannot
   be what Build 4 reports — at a 35% win rate the median trade is a loser, and a loser that
   peaks +1% and closes −5% gives back 600% of its peak. So their peak, or their population,
   is measured differently. Not reverse-engineered to match.
2. **"Day 2".** Build 4's day-2 n (2949) is comparable to its day-1 n (4125), so day 2 there
   is a separate *entry policy* run — take day 2 instead of day 1. This harness takes day 1
   whenever it is available, so day 2 only appears when day 1 was not (n=73). Same name,
   different quantity. Comparing them directly is a mistake.

## The profit lock

Build 4's `day1_exit_mix` carries a `breakeven` exit category (A 2.5%, B 4.4%, C 2.3%,
summing to 100% with door/stop/open) — the DEC-005 breakeven-at-+1R stop that **DEC-006
retired the same day**. This harness has no such exit and never will.

The exit mixes corroborate each other rather than conflict:

| door B, day 1 | Build 4 | harness |
|---|---|---|
| door (incl. deep break) | 88.1 | 55.7 + 37.2 deep = 92.9 |
| breakeven | 4.4 | — |
| stop | 5.9 | **5.3** |
| open / end of range | 1.6 | 1.8 |

Build 4's door + breakeven = 92.5 against this harness's door + deep break = 92.9: the
trades the profit lock took at breakeven are the ones that, without it, go on to exit at a
door. The stop rates agree to 0.6 points, which is independent confirmation that
`max(8%, 2×ATR14)` and the fill convention are right.

## What was not done

No harness number was tuned toward a Build 4 figure, and no rule was changed to close a gap.
Every difference above is reported as a difference.
