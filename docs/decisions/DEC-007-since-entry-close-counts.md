# DEC-007 (PROPOSED) — publish a since-entry adverse-close count from `doors.exit_state`

**Status: PROPOSED, not ruled. Ray rules; this document only makes the case.**
Raised 2026-09-09 by the Build 4 replication (`docs/reviews/2026-09-09-build-4-replication.md`).
Nothing in `ccsolver/` has been changed. The defect below is live and flagged in the
harness's own output rather than worked around.

## The problem

`doors.exit_state` publishes `closes_against_4ema` and `closes_against_21ema`. Both are
streaks measured **from the end of the bar history**, with no reference to when the position
was opened. `_streak` walks backwards from the last bar until the run breaks; it never sees
`entry_date`.

For the live path that is correct and deliberate. A position opened on the wrong side of the
21 EMA binds to the tight 4 EMA door and graduates one-way, so the whole-history 21 EMA count
is never the active test for it. `entry_date` exists in the signature precisely to drive
graduation, and it does.

The gap is that **no caller can ask "how many consecutive closes has this position taken
against its door since it was opened?"** That question has no answer in the payload, and it
is a different question from the one `mandatory_exit` answers.

## What it breaks today

`backtest/harness.py`, `--door first-of-both`. The door is defined as "whichever of the 4 EMA
and 21 EMA doors fires first". Its 21 EMA leg reads `closes_against_21ema`, so a position
opened below the 21 EMA is already several closes into that test on its first session.
Measured on the Build 4 corpus (114 names, 2024-08-01 → 2026-09-04):

| `first-of-both`, reclaim day 1 | value |
|---|---|
| trades entered below the 21 EMA | 2935 of 5927 (50%) |
| …of those, exiting within one session | **2380 (81%)** |
| average hold, entered below | 2.4 |
| average hold, entered above | 6.94 |

The door does not implement "first of both doors". It implements "exit at once if you entered
below the 21 EMA". Its returns are unusable and its hold is a lower bound. The production
`21ema` door is **not** affected — 6% of its below-21-EMA entries exit within a session, not
81% — because binding is exactly what handles this case.

The harness carries this in its `warnings` payload so no figure escapes without the caveat.
That is containment, not a fix.

## Why it could not be fixed in the harness

Computing a since-entry streak inside `backtest/` means writing a second copy of the door
logic outside `doors.py`. The standing constraint on the harness is that it replays the real
doors and never re-derives them — a backtest carrying its own copy of a rule stops measuring
the rule the desk runs the moment the two drift. The harness therefore reports the defect
instead of working around it, which is what the rule asks for.

## Second reason this matters

The same missing quantity is what made the Build 4 replication awkward. Build 4's door B is
a **since-entry** 21 EMA count, and reproducing it (PF within 0.4%, hold within 1%) required
computing that count in a scratchpad probe outside the package. Any future validation against
an external backtest will hit the same wall.

Note the shape this explains: Build 4 reports door B (4.409) *and* a separate
`literal_21ema_streak` control (3.696). Those look like the since-entry count and the
whole-history count of the same door. The distinction is real and was worth measuring to
whoever ran Build 4.

## Proposal

Add two **purely additive** fields to the `exit_state` return value:

```
closes_against_4ema_since_entry   int | None
closes_against_21ema_since_entry  int | None
```

- Counted from the first settled bar whose date is `>= entry_date`, using the same
  `_streak` comparison and the same side-awareness as the existing counts.
- `None` when `entry_date` is not supplied, when the history is thin (matching how
  `closes_against_21ema` already withholds rather than reporting a misleading zero), or when
  the relevant EMA has no value.
- The provisional live bar is included or excluded exactly as it is for the existing counts.

### What does NOT change

- `mandatory_exit`, `mandatory_reason`, `active_door`, `graduated`, `entry_door`, the deep
  break, binding, and one-way graduation: **all unchanged**.
- No live task reads the new fields. `cli.position_monitor` and `confirm_pass` are untouched.
- The existing whole-history counts keep their names, meanings and values. Nothing that
  reads `closes_against_21ema` today sees a different number tomorrow.

## Why this needs a ruling rather than a patch

The change is additive and cannot alter a verdict, so the mechanical risk is near zero. It
still needs a ruling for one reason: **it publishes a new door-relevant quantity, and a new
count invites a new rule.** Once `closes_against_21ema_since_entry` exists in the payload,
someone — an LLM formatting a verdict, a future task prompt, a future me — will be one step
from treating it as a door. The Decision Log is where that gets bounded in advance.

The bound this proposal asks for: **these fields are context only, for backtests and audits.
No live rule reads them.** That is the same fence DEC-006 put around `breakeven_1r_reached`,
and it held.

## If Ray approves

1. Add the two fields to `doors.exit_state`, computed with the existing `_streak` helper.
2. Add a `doors` test: a relaunch-shaped position entered below the 21 EMA reports
   `closes_against_21ema` large and `closes_against_21ema_since_entry` small on its first
   session, and both agree once the position has been open longer than the streak.
3. Repoint `harness.door_fires` for `first-of-both` at the since-entry count, delete
   `WARN_FIRST_OF_BOTH` and its test, and re-run the Build 4 comparison for door C.
4. Record the fence in the README rules list next to DEC-006.

## If Ray declines

The harness keeps the warning and `--door first-of-both` stays unusable for returns. Doors
`21ema`, `4ema-day2` and `4ema-first-close` are unaffected and all three are validated against
Build 4. Nothing else in the repo depends on this.
