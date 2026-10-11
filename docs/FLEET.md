# The fleet, from the solver's side

Twelve scheduled tasks call this repo. This file is for the agent inside one of them, and for
whoever edits the solver next. It answers one question: **what does the fleet assume about this
code, and what breaks upstream if I change it.**

It is deliberately not an orientation doc. Every task prompt already opens with
`Read project doc claude/START-HERE.md before anything else` — that doc owns the operational
picture. This file owns the contract, and nothing else.

**Scope rule, so this file does not rot like the pages did:**

| Belongs here | Belongs in Notion |
|---|---|
| Rules that change when the code changes | State that changes when the day changes |
| Ray's rulings, as they are encoded | Open items, statuses, run history |
| Input/output shapes | Which tickers, which positions, which day |
| Traps that outlive any single run | Anything with a date or a count in it |

If you are about to write a status, a count, or a date into this file, it belongs in Notion instead.

---

## The rule that costs the most when forgotten

**A Notion task page is a mirror. The scheduled trigger holds its own copy of its prompt.**

Editing the page changes nothing about what runs. The two have drifted more than once — on
2026-09-08 the confirm-pass page carried a rewrite its live trigger did not have, and a separate
page claimed a DST fix that had never been applied.

When the question is *what will actually run*, read the trigger:

```
RemoteTrigger action:get trigger_id:trig_...     # live text at derived_state.prompt
```

Corollary, learned the same day: **read the live prompt before calling anything a bug.** Several
prompts explain their own apparent anomalies in their first two paragraphs.

---

## Who calls what

Seven of the twelve invoke the CLI. Slots are PT. Taken from the live prompts, not the pages.

| Task | Slot | Invokes | Notes |
|---|---|---|---|
| Slow discovery | 5:30 AM | — | LLM only, no push |
| Macro context | 6:00 AM | — | LLM only, no push |
| Fast discovery | 11:15 AM | `fast_discovery` | |
| Take-action | 11:50 AM | `take_action` | pushes; emits `STAGED_JSON` |
| **Confirm pass** | **12:25 PM** | `confirm_pass` | **STAGED names only** |
| **Position monitor** | **12:25 PM** | `position_monitor` | **HELD names only**, provisional |
| True-up | 1:15 PM | `fast_discovery` | same command, full-day data |
| EOD | 1:30 PM | `position_monitor` | settled re-run; also calls `exposure.exposure` and `ledger.handoff_row` directly |
| EOW | Fri 2:00 PM | `eow` | |
| EOM | last trading day | — | LLM only |
| Miss Audit | Sat 8:00 AM | `miss_audit` | |
| Fleet health monitor | 2:30 PM weekdays | — | watchdog; pushes only on a gap |

`TASKS` in `cli.py` registers seven commands: `take_action`, `confirm_pass`, `position_monitor`,
`fast_discovery`, `eow`, `miss_audit`, `calendar`. There is **no** `slow_discovery`, `true_up`,
`eod` or `eom` command — those tasks are prompt-only, and True-up reuses `fast_discovery`. Adding
a command here does not make a task call it; that needs a trigger edit.

`LIVE_TASKS` (`take_action`, `confirm_pass`, `position_monitor`, `fast_discovery`) refuse to run on
a clock more than a few minutes off, because a bad clock on those reaches a real decision.

### The shared 12:25 PM slot is deliberate

Two tasks fire that minute. This is correct and has been mistakenly "fixed" before.

They split by **subject**, not by clock:

- `confirm_pass` — staged names. Did an 11:50 AM stage flip below the 4 EMA?
- `position_monitor` — held names. Positions DB → provisional exit doors.

Neither reads the other's. Both were briefly checking held names, which double-pushed the same exit
in the 20 minutes before the 12:45 PM MOC deadline; `pending_exits` was removed from `confirm_pass`
to end it (Ray, 2026-09-08). 12:25 PM also buys a 20-minute window before the MOC deadline — 12:35
would halve it.

**Do not move either task to un-collide them.** If you think you have found a collision here, you
have found this paragraph instead.

---

## Rulings encoded in the code

Ray's direct calls. None of these came from a backtest, and **no backtest exists in this repo** —
never cite one. `docs/reviews/` records where each was made.

1. **21 EMA second consecutive close against the position = mandatory exit.** The 4 EMA is a
   warning only. A deep break (>4% through the 4 EMA) is mandatory under either door.
2. **The exit door binds at entry and graduates one way.** A position opened on the wrong side of
   the 21 EMA runs the tight 4 EMA door until its first favourable settled close beyond the 21 EMA;
   then it graduates and is never demoted. Without this, a relaunch entry is born dozens of closes
   into its own mandatory exit.
3. **A provisional bar may never graduate a position.** Graduation is one-way, so an intraday pop
   that fades by the close would loosen the leash permanently.
4. **No profit-lock (DEC-006).** A stop does not move on profit. `breakeven_1r_reached` is reported
   as context, never as an instruction.
5. **Never guess a side.** A wrong side inverts the stop onto the profitable side of price. Side
   comes from `held.json`, else the sign of the IBKR position; if neither resolves, return
   `SIDE UNKNOWN` and push.
6. **A missing `entry_door` takes the tight door.** `doors.exit_state` requires `entry_door_` as a
   keyword argument and has no default — whichever default it picked would be silently wrong for
   half the book, and a loose leash on an unproven position looks exactly like a correct one until
   it costs money.
7. **Empty state is not consent.** A missing or stale Trader Handoff row means the fleet's shared
   state is gone, not clean. Every task treats it as PAUSED and stops; only EOD proceeds, because
   it writes the row that fixes it. Never report a value read from an empty table as a fact —
   report it as UNKNOWN, never as zero.
8. **The solver emits all three size tiers; Ray picks.** The decision is which size, never whether.
   No task places, modifies, or cancels a broker order.

---

## The input contract

The docstring at the top of `ccsolver/cli.py` is the contract, and `examples/inputs/*.json` are the
shapes. The prompts say so: *where this prompt and the repo differ, the repo wins.*

That split is easy to get backwards, and getting it backwards has caused a live crash:

- **What the solver OUTPUTS** — this repo controls it. Adding a field needs no Notion edit.
- **What a task writes IN** — the task prompt alone controls it. Requiring a new input field
  **always** needs a prompt edit, on the trigger, not the page.

On 2026-09-08 the task prompts moved to a 12-hour clock while `minutes_since_open` still parsed
only 24-hour; `take_action` would have died at its 11:50 AM slot. Adding an input is an upstream
change. Treat it like one.

---

## Traps

**Bars can be padded.** A thin real history can arrive front-filled with synthetic bars. `bars.py`
strips them and refuses a 21 EMA it cannot honestly compute. A padded bar that reaches an indicator
produces a confident number from nothing.

**A test can pass for the wrong reason.** Two attempts at the confirm-pass pending-exit test were
green while testing nothing: an uptrend entry binds to the 21 EMA door, and any close far enough
below the 4 EMA to matter is already a deep break — confirmed, not pending. Use a relaunch-shaped
fixture.

**The exclusion matcher needs both halves.** A leverage word on a word boundary AND an issuer
token. Compound forms (`UltraShort`, `UltraProShort`) are enumerated explicitly, because boundary
matching means `Ultra` no longer matches inside `UltraPro`. The Notion Exclusion List page is
**unioned** with the built-ins, never a replacement — on the page's patterns alone, TQQQ and SDS
leak through. Verified 2026-09-08: 13 wrapper funds excluded, 9 real companies survived.

**`make example` is not reproducible.** Since the clock guard shipped, it embeds a wall-clock
`time_check` block. `examples/take_action.out.json` is maintained by hand.

---

## Where the live state lives

Nothing below is mirrored into this repo on purpose. It changes daily; this file does not.

- **Open items** — Notion `Fleet Open Items` DB, `collection://9575363f-0978-4ad5-b7a1-674e7e491f88`,
  IDs `FOI-n`. File new findings there, not here and not in a page's inline table.
- **Positions** — Notion Positions DB, `collection://10461ddd-3dcc-42c9-9dbe-16b2e21600b5`.
  EOD owns it: opens, closes and graduates rows. Position monitor reads it and may backfill a
  missing Open row. Take-action never writes it. The Handoff's "Open positions" text is a
  human-readable mirror; nothing reads it back as data.
- **Run history** — Notion Run Log DB. Each run embeds its raw pulls and verdict JSON in the row's
  page body, not in Google Drive (the connector caps inline content ~20 KB and `bars.json` never fit).
- **Rulings and incidents** — Notion Message Board Posts, `PST-n`.
- **Prompts** — the triggers. Not the pages. See the top of this file.
