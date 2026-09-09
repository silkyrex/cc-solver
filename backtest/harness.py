"""Replay the production doors forward over a ticker list and a date range.

Same inputs, same trades. Bars come from a directory of JSON files, one per ticker
(`--bars-dir`); there is no broker call and no Notion call anywhere in this module.

WHAT IS AND IS NOT DECIDED HERE
  Entry is `doors.entry_state(hist)["door_open"]` on SETTLED closes. The 4 EMA reclaim
  day-1/day-2 window and the slow-sto-20-low door are not re-derived here.
  Exit is `doors.exit_state(hist, entry_door_=..., entry_date=..., side=...)`, with the
  door BOUND AT ENTRY from `entry_state`'s `entry_door`. Graduation from the 4 EMA door
  to the 21 EMA door is one-way and settled-closes-only; that is `exit_state`'s logic and
  it is read, never rewritten. The alternative doors behind `--door` are expressed as
  tests over the neutral counts `exit_state` already publishes (`closes_against_4ema`,
  `closes_against_21ema`, `deep_break_4ema`) for exactly that reason.
  Stop is max(8%, 2xATR14) at the entry bar, straight off `entry_state["stop_pct"]`.

NO PROFIT LOCK. DEC-006 (Ray 2026-09-08, PRODUCTION) is that the stop never moves on
profit. There is no breakeven-at-+1R here and no trailing ratchet, not even behind a
flag: an option flag for a retired rule is how a retired rule comes back.

Stdlib only, matching `ccsolver/indicators.py`. The container is ephemeral and every
dependency is a failure mode.

FILL CONVENTIONS (daily bars cannot resolve intraday order; these are the choices made)
  - Entry fills at the CLOSE of the session whose settled read opened the door. That is
    the desk's basis: the decision is made at MOC against the day's price.
  - A door exit fills at the CLOSE of the session that produced the signal, same reason.
  - A stop fills at the stop price, or at the OPEN when the session gapped through it.
  - Within a session the stop is tested before the door: the stop is an intraday order
    and the door is a settled close.
  - Peak unrealized runs over the highs from the session after entry through the exit
    session inclusive. Daily bars cannot say whether a stop-out session's high came
    before or after the stop was touched, so it is counted; on a stop-out session the
    high is almost never the trade's peak, so the effect is small and it errs toward
    reporting MORE giveback, never less.

BAR HYGIENE (non-negotiable, constraint of the port)
  - Every series is `bars.clean()`ed once at load, before any indexing or arithmetic.
    Robinhood back-fills a requested range with synthetic bars; dropping that flag
    silently fabricates history.
  - No entry is taken while the real history is thin (`bars.thin()`,
    MIN_REAL_BARS_21EMA = 30). Below that the 21 EMA is withheld rather than guessed,
    so an exit-door comparison run there would be comparing one real door against a
    door that never ran. Refusals are reported, not skipped in silence.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean, median

if __package__ in (None, ""):  # allows `python backtest/harness.py` as well as `-m`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccsolver import bars as barlib  # noqa: E402
from ccsolver import doors  # noqa: E402

DOOR_21EMA = "21ema"
DOOR_4EMA_DAY2 = "4ema-day2"
DOOR_FIRST_OF_BOTH = "first-of-both"
DOOR_4EMA_FIRST = "4ema-first-close"
DOORS = (DOOR_21EMA, DOOR_4EMA_DAY2, DOOR_FIRST_OF_BOTH, DOOR_4EMA_FIRST)

EXIT_STOP = "stop"
EXIT_DOOR = "door"
EXIT_DEEP = "deep break"
EXIT_END = "end of range"

SIDE = "long"  # entry_state has no short door; shorts are alert-only on this desk


# --------------------------------------------------------------------------- bars


def normalise(payload, ticker):
    """Accept the shapes a bars file actually arrives in, then clean it once.

    {"bars": [...]}  (what the build-2 harness wrote) | a bare list | the cli.py
    bars.json shape {"TICKER": [...]}. Anything else is an error, not a guess.
    """
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("bars"), list):
            raw = payload["bars"]
        elif isinstance(payload.get(ticker), list):
            raw = payload[ticker]
        elif len(payload) == 1 and isinstance(next(iter(payload.values())), list):
            raw = next(iter(payload.values()))
        else:
            raise ValueError("unrecognised bars file shape")
    else:
        raise ValueError("unrecognised bars file shape")
    # One clean at the door. Every index, price and date below is a real session.
    return barlib.clean(sorted(raw, key=lambda b: b["date"]))


def load_bars_dir(bars_dir, tickers):
    """Read one JSON file per ticker. Missing and unreadable files are reported, not raised."""
    out, problems = {}, []
    for t in tickers:
        path = os.path.join(bars_dir, f"{t}.json")
        if not os.path.exists(path):
            problems.append({"ticker": t, "skipped": "no bars file", "path": path})
            continue
        try:
            with open(path) as f:
                series = normalise(json.load(f), t)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            problems.append({"ticker": t, "skipped": f"unreadable bars file: {e}", "path": path})
            continue
        if not series:
            problems.append({"ticker": t, "skipped": "no real bars after bars.clean()"})
            continue
        out[t] = series
    return out, problems


# --------------------------------------------------------------------- exit doors


def door_fires(es, door):
    """Does `door` fire on this settled close? Returns (reason, detail) or None.

    Reads what `doors.exit_state` published. The streak counts, the entry binding and the
    one-way graduation are its logic; re-deriving any of them here is how a backtest ends
    up measuring a rule the desk does not run.
    """
    deep = es["deep_break_4ema"]
    a4 = es["closes_against_4ema"]
    a21 = es["closes_against_21ema"]  # None on a thin history: that test did not run

    if door == DOOR_21EMA:
        # Production: the door bound at entry, graduation included, deep break under either.
        if not es["mandatory_exit"]:
            return None
        return (EXIT_DEEP if deep else EXIT_DOOR), es["mandatory_reason"]

    # A deep break is mandatory under every door in doors.py; the alternatives keep that.
    if deep:
        return EXIT_DEEP, "deep break: close more than 4% through the 4 EMA"
    if door == DOOR_4EMA_FIRST and a4 >= 1:
        return EXIT_DOOR, "4 EMA first close against the position"
    if door == DOOR_4EMA_DAY2 and a4 >= 2:
        return EXIT_DOOR, "4 EMA 2nd consecutive close against the position"
    if door == DOOR_FIRST_OF_BOTH:
        if a4 >= 2:
            return EXIT_DOOR, "4 EMA 2nd consecutive close against the position"
        if a21 is not None and a21 >= 2:
            return EXIT_DOOR, "21 EMA 2nd consecutive close against the position"
    return None


# ----------------------------------------------------------------------- replay


def _hist(series, i, window, floor_i=0):
    """History through bar i. `window` trims the left edge; `floor_i` protects graduation.

    An EMA is seeded with the SMA of its first n bars, so where a series STARTS moves every
    line on it. --history-window exists because the live desk pulls ~130 calendar days and a
    full-file replay does not; it is a reproducibility knob, and it changes the numbers.
    While a position is open the window never trims past its entry bar: exit_state recomputes
    graduation from the bars it is handed, and a window that cut the entry away would silently
    demote a graduated position to the tight door.
    """
    lo = 0 if not window else max(0, i + 1 - window)
    return series[min(lo, floor_i):i + 1]


def _peak_pct(series, entry_i, exit_i, entry_price):
    """Highest unrealized gain shown, entry+1 through the exit session. Never negative."""
    if exit_i <= entry_i:
        return 0.0
    hi = max(b["high"] for b in series[entry_i + 1:exit_i + 1])
    return max(0.0, 100.0 * (hi - entry_price) / entry_price)


def simulate(ticker, series, start, end, door=DOOR_21EMA, history_window=0, side=SIDE):
    """Walk one ticker forward. Flat -> look for an entry; long -> look for an exit.

    Returns (trades, refusals, unresolved). `unresolved` is an entry the range had no room
    to resolve -- the door opened on the last in-range session. Booking it as a 0.00% trade
    would be inventing an outcome and would drag the mean toward zero by trade count.
    """
    trades, refusals, unresolved = [], [], []
    in_range = [i for i, b in enumerate(series) if start <= b["date"] <= end]
    if not in_range:
        return trades, [{"ticker": ticker, "refused": "no sessions in range"}], unresolved

    last_i = in_range[-1]
    thin_refused = 0
    open_trade = None
    i = in_range[0]
    while i <= last_i:
        bar = series[i]
        if open_trade is None:
            hist = _hist(series, i, history_window)
            # No entry on a fabricated session, and none on a history too thin to carry a
            # 21 EMA: the exit-door comparison would be against a door that never ran.
            is_thin = barlib.thin(hist)
            if is_thin:
                thin_refused += 1
            if is_thin or barlib.is_synthetic(bar):
                i += 1
                continue
            es = doors.entry_state(hist)
            if es.get("door_open"):
                open_trade = {
                    "ticker": ticker,
                    "side": side,
                    "entry_date": bar["date"],
                    # the price the door itself read, so entry can never drift from the signal
                    "entry_price": es["price"],
                    "entry_door": es["entry_door"],
                    "entry_trigger": es["entry_trigger"],
                    "reclaim_day_at_entry": es["reclaim_day"],
                    "stop_pct": es["stop_pct"],
                    "stop_price": es["stop_price"],
                    "_i": i,
                }
            i += 1
            continue

        # ---- holding. Stop is an intraday order, so it is tested before the settled close.
        entry_i = open_trade["_i"]
        stop = open_trade["stop_price"]
        if bar["low"] <= stop:
            fill = min(bar["open"], stop)  # gapped through -> filled at the open
            trades.append(_close_trade(open_trade, series, i, fill, EXIT_STOP,
                                       f"stop hit: max(8%, 2xATR14) = {open_trade['stop_pct']:.2%} from entry"))
            open_trade = None
            i += 1
            continue

        hist = _hist(series, i, history_window, floor_i=entry_i)
        es = doors.exit_state(hist, entry_door_=open_trade["entry_door"], side=side,
                              entry_date=open_trade["entry_date"], settled_only=True)
        fired = door_fires(es, door)
        if fired:
            reason, detail = fired
            trades.append(_close_trade(open_trade, series, i, bar["close"], reason, detail,
                                       graduated=es["graduated"], active_door=es["active_door"]))
            open_trade = None
        i += 1

    if open_trade is not None:
        if open_trade["_i"] == last_i:
            unresolved.append({"ticker": ticker, "entry_date": open_trade["entry_date"],
                               "entry_price": open_trade["entry_price"],
                               "entry_door": open_trade["entry_door"],
                               "reclaim_day_at_entry": open_trade["reclaim_day_at_entry"],
                               "unresolved": "door opened on the last session in range; "
                                             "no sessions left to resolve it"})
        else:
            trades.append(_close_trade(open_trade, series, last_i, series[last_i]["close"], EXIT_END,
                                       "still open at the end of the range; marked out at the last close"))
    if thin_refused:
        refusals.append({"ticker": ticker, "refused": "thin real history",
                         "sessions_refused": thin_refused,
                         "detail": f"fewer than {barlib.MIN_REAL_BARS_21EMA} real sessions "
                                   "(bars.MIN_REAL_BARS_21EMA); no 21 EMA, so no entry"})
    return trades, refusals, unresolved


def _close_trade(t, series, exit_i, exit_price, reason, detail, graduated=False, active_door=None):
    entry_i, entry = t["_i"], t["entry_price"]
    exit_price = round(float(exit_price), 4)
    ret = 100.0 * (exit_price - entry) / entry
    peak = _peak_pct(series, entry_i, exit_i, entry)
    stop_pct_pts = t["stop_pct"] * 100.0
    return {
        "ticker": t["ticker"],
        "side": t["side"],
        "entry_date": t["entry_date"],
        "entry_price": entry,
        "entry_door": t["entry_door"],
        "entry_trigger": t["entry_trigger"],
        "reclaim_day_at_entry": t["reclaim_day_at_entry"],
        "stop_pct": round(stop_pct_pts, 4),
        "stop_price": t["stop_price"],
        "exit_date": series[exit_i]["date"],
        "exit_price": exit_price,
        "exit_reason": reason,
        "exit_detail": detail,
        "active_door_at_exit": active_door,
        "graduated": graduated,
        "sessions_held": exit_i - entry_i,
        "return_pct": round(ret, 4),
        "r_multiple": round(ret / stop_pct_pts, 4) if stop_pct_pts else None,
        "peak_unrealized_pct": round(peak, 4),
        # giveback is undefined when the trade never showed an open profit; None, not 0.
        "giveback_pct_of_peak": round(100.0 * (peak - ret) / peak, 4) if peak > 0 else None,
    }


# ------------------------------------------------------------------- aggregates


def aggregate(trades, label):
    """Headline figures for one bucket of trades.

    Three givebacks are reported because a bare "giveback 36.8%" does not say which. `median`
    is the middle per-trade ratio, and it is the one the 2026-09-08 Build 4 summary reports --
    its column is literally `giveback_median_pct` -- so it is the one to compare against.
    `mean` averages the per-trade ratios; `pooled` is 1 - (total realized / total peak), which
    weights by trade size.
    """
    n = len(trades)
    if n == 0:
        # same keys as a populated bucket: a consumer should never have to branch on shape
        return {"bucket": label, "trades": 0, "mean_return_pct": None, "profit_factor": None,
                "win_rate_pct": None, "giveback_median_pct_of_peak": None,
                "giveback_mean_pct_of_peak": None,
                "giveback_pooled_pct_of_peak": None, "mean_r_multiple": None,
                "gross_win_pct": 0.0, "gross_loss_pct": 0.0,
                "exit_reasons": {r: 0 for r in (EXIT_DOOR, EXIT_STOP, EXIT_DEEP, EXIT_END)}}
    rets = [t["return_pct"] for t in trades]
    gross_win = sum(r for r in rets if r > 0)
    gross_loss = -sum(r for r in rets if r < 0)
    rs = [t["r_multiple"] for t in trades if t["r_multiple"] is not None]
    gb = [t for t in trades if t["giveback_pct_of_peak"] is not None]
    peaks = sum(t["peak_unrealized_pct"] for t in gb)
    return {
        "bucket": label,
        "trades": n,
        "mean_return_pct": round(mean(rets), 4),
        # None, not inf: "no losing trade" is not a profit factor, and inf is not JSON.
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "win_rate_pct": round(100.0 * sum(1 for r in rets if r > 0) / n, 4),
        # the statistic Build 4 reports as "giveback"; compare against this one, not the mean
        "giveback_median_pct_of_peak": round(median(t["giveback_pct_of_peak"] for t in gb), 4) if gb else None,
        "giveback_mean_pct_of_peak": round(mean(t["giveback_pct_of_peak"] for t in gb), 4) if gb else None,
        "giveback_pooled_pct_of_peak": (round(100.0 * (peaks - sum(t["return_pct"] for t in gb)) / peaks, 4)
                                        if peaks > 0 else None),
        "mean_r_multiple": round(mean(rs), 4) if rs else None,
        "gross_win_pct": round(gross_win, 4),
        "gross_loss_pct": round(gross_loss, 4),
        "exit_reasons": {r: sum(1 for t in trades if t["exit_reason"] == r)
                         for r in (EXIT_DOOR, EXIT_STOP, EXIT_DEEP, EXIT_END)},
    }


def split_date(bars_by_ticker, start, end):
    """The session that halves the period, by SESSIONS traded rather than by calendar days.

    A calendar midpoint splits a holiday-heavy half against a busy one. The union of every
    in-range session date across the universe is the closest thing to the desk's own clock.
    """
    sessions = sorted({b["date"] for series in bars_by_ticker.values()
                       for b in series if start <= b["date"] <= end})
    return sessions[len(sessions) // 2] if sessions else end


def replay(bars_by_ticker, start, end, door=DOOR_21EMA, history_window=0, side=SIDE):
    """Run every ticker and assemble the report. Pure: no I/O, no clock, no network."""
    if door not in DOORS:
        raise ValueError(f"unknown door {door!r}; expected one of {', '.join(DOORS)}")
    if history_window and history_window < barlib.MIN_REAL_BARS_21EMA:
        raise ValueError(f"history_window {history_window} is below MIN_REAL_BARS_21EMA "
                         f"({barlib.MIN_REAL_BARS_21EMA}); every read would be thin by construction")
    trades, refusals, unresolved = [], [], []
    for ticker in sorted(bars_by_ticker):
        t, r, u = simulate(ticker, bars_by_ticker[ticker], start, end, door=door,
                           history_window=history_window, side=side)
        trades.extend(t)
        refusals.extend(r)
        unresolved.extend(u)
    trades.sort(key=lambda t: (t["entry_date"], t["ticker"]))
    mid = split_date(bars_by_ticker, start, end)
    first = [t for t in trades if t["entry_date"] <= mid]
    second = [t for t in trades if t["entry_date"] > mid]
    return {
        "task": "backtest",
        "door": door,
        "start": start,
        "end": end,
        "side": side,
        "history_window": history_window or "full file",
        "universe": len(bars_by_ticker),
        "stop_rule": "max(8%, 2xATR14) at the entry bar; DEC-006: never moves on profit",
        "half_split_session": mid,
        "aggregates": {
            "overall": aggregate(trades, "overall"),
            "first_half": aggregate(first, f"first half ({start}..{mid})"),
            "second_half": aggregate(second, f"second half (after {mid}..{end})"),
        },
        # Build 4 (2026-09-08) reports reclaim day 1 and day 2 as SEPARATE populations and never
        # pools them: they are different trades with different holds, so a pooled mean answers a
        # question nobody asked. Reported alongside the pooled figure, not instead of it.
        "by_reclaim_day": {
            "day1": aggregate([t for t in trades if t["reclaim_day_at_entry"] == 1], "reclaim day 1"),
            "day2": aggregate([t for t in trades if t["reclaim_day_at_entry"] == 2], "reclaim day 2"),
        },
        "refusals": refusals,
        # entries the range had no room to resolve. Counted here, never in `trades`.
        "unresolved_entries": unresolved,
        "trades": trades,
    }


# --------------------------------------------------------------------------- cli


def _tickers(args):
    names = []
    if args.tickers_file:
        with open(args.tickers_file) as f:
            body = f.read()
        payload = None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            pass
        names += payload if isinstance(payload, list) else body.replace(",", "\n").split()
    if args.tickers:
        names += args.tickers.split(",")
    seen, out = set(), []
    for n in names:
        n = n.strip().upper()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="backtest",
        description="Replay the ccsolver doors over daily bars. JSON to stdout.")
    ap.add_argument("--bars-dir", required=True, help="directory of one JSON file per ticker, TICKER.json")
    ap.add_argument("--tickers", help="comma-separated")
    ap.add_argument("--tickers-file", help="JSON list, or one ticker per line")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD, first session an entry may be taken")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD, last session; open trades mark out at its close")
    ap.add_argument("--door", default=DOOR_21EMA, choices=list(DOORS),
                    help="exit door under test. 21ema is production (bound at entry, graduates); "
                         "the others are alternatives compared on the SAME entry set")
    ap.add_argument("--history-window", type=int, default=0, metavar="N",
                    help="sessions of history fed to each read; 0 = the whole file, and anything below "
                         f"{barlib.MIN_REAL_BARS_21EMA} is refused. An EMA is seeded with the SMA of "
                         "its first n bars, so this moves every number. The live desk pulls ~130 "
                         "calendar days; a full-file replay does not")
    ap.add_argument("--no-trades", action="store_true", help="aggregates and refusals only")
    a = ap.parse_args(argv)

    tickers = _tickers(a)
    if not tickers:
        json.dump({"task": "backtest", "status": "refused",
                   "reason": "no tickers; pass --tickers or --tickers-file"},
                  sys.stdout, indent=1, default=str)
        print()
        return 2

    bars_by_ticker, problems = load_bars_dir(a.bars_dir, tickers)
    if not bars_by_ticker:
        json.dump({"task": "backtest", "status": "refused",
                   "reason": "no readable bars for any ticker", "skipped": problems},
                  sys.stdout, indent=1, default=str)
        print()
        return 2

    try:
        out = replay(bars_by_ticker, a.start, a.end, door=a.door,
                     history_window=a.history_window)
    except ValueError as e:
        json.dump({"task": "backtest", "status": "refused", "reason": str(e)},
                  sys.stdout, indent=1, default=str)
        print()
        return 2
    out["requested"] = len(tickers)
    out["skipped"] = problems
    if a.no_trades:
        out["trades"] = f"{len(out['trades'])} trades suppressed by --no-trades"
    json.dump(out, sys.stdout, indent=1, default=str)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
