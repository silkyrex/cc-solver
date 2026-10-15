"""One entry point per scheduled task. Reads JSON from --inputs DIR, prints JSON.

Input files the harness writes (all optional unless noted):
  calendar.json   {"closed": [...], "early": [...]}                       (all tasks)
  bars.json       {"TICKER": [{date,open,high,low,close,volume}...]}     (take_action, confirm_pass, position_monitor, eow, miss_audit)
  quotes.json     {"TICKER": {"last": 12.3, "day_high": 12.6, "day_low": 11.9, "day_volume": 1e6, "avg_volume": 8e5}}  (take_action, confirm_pass, fast_discovery)
  scans.json      {"scan name": [rows]}                                   (fast_discovery, take_action)
  thematic.json   {"Theme": ["T1","T2"]}
  roster.json     ["SNDK", ...]
  positions.json  IBKR get_account_positions JSON (whole object)          (take_action, position_monitor, eod)
  account.json    {"net_liq": 18910.0, "pt_time": "11:50 AM"}            (take_action, position_monitor)
                  pt_time takes a 12-hour ("11:50 AM", "1:10 PM") or 24-hour ("13:10") clock
  exclusion.json  {"names": [...], "patterns": [...]}
  run_log_today.json  [ {Task, Outcome} ... ]                            (take_action)
  board.json      [ {url, Ticker, Layer, first_seen, seen_count} ... ]   (take_action, eow, miss_audit)
  staged.json     [ <held_row block, verbatim from a take_action STAGE verdict> ... ] (confirm_pass)
  held.json       [ {ticker, entry, initial_stop, side, entry_door, entry_datetime, graduated_date} ... ]
                  (position_monitor) copy the staged verdict's held_row block verbatim; entry_date
                  (bare date) still accepted. quotes.json is OPTIONAL here: supply it and every row
                  also carries a provisional_* read against the live price, usable before the
                  12:45 PM MOC deadline
"""
import argparse
import json
import os
import sys

from . import calendar as cal
from . import clock, doors, exposure, grader, ledger, rvol, universe


def _load(d, name, default=None):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def _gate(d, date):
    c = _load(d, "calendar.json", {"closed": [], "early": []})
    return cal.status(date, c)


def take_action(d, date):
    st = _gate(d, date)
    if st["status"] == "closed":
        return {"status": "skipped", "reason": "market closed", "calendar": st}
    acct = _load(d, "account.json", {})
    scans, thematic = _load(d, "scans.json", {}), _load(d, "thematic.json", {})
    roster, excl = _load(d, "roster.json", []), _load(d, "exclusion.json", {})
    pos_json = _load(d, "positions.json", {"positions": []})
    positions = pos_json.get("positions", [])
    held = _held(d)
    quotes, bars = _load(d, "quotes.json", {}), _load(d, "bars.json", {})
    board = _load(d, "board.json", [])
    miss = ledger.discovery_missing(_load(d, "run_log_today.json", []))
    since = ledger.window_start(date)
    board_names = sorted({r["Ticker"] for r in board if r.get("Ticker") and r.get("first_seen", "") >= since})

    uni = universe.build(scans, thematic, roster, held, excl)
    uni_by_ticker = {r["ticker"]: r for r in uni}
    # take-action inputs = roster ∪ board (63 sessions) ∪ positions; scans/thematic feed the board, not the door check
    candidates = set(roster) | set(board_names) | set(held)
    for r in uni:
        if any(s.startswith("scan:") for s in r["sources"]) and not r["excluded"]:
            candidates.add(r["ticker"])  # same-day scan hits are eligible too (the board row lands this run)
    mins = rvol.minutes_since_open(acct.get("pt_time", "11:50"))
    net_liq = float(acct.get("net_liq", 0) or 0)
    verdicts = []
    for t in sorted(candidates):
        b = bars.get(t)
        q = quotes.get(t, {})
        if not b:
            verdicts.append({"ticker": t, "verdict": "NO DATA", "reason": "no bars in bars.json"})
            continue
        es = doors.entry_state(b, q.get("last"), q.get("day_high"), q.get("day_low"))
        if "price" not in es:
            verdicts.append({"ticker": t, "verdict": "NO DATA", "reason": es["reason"]})
            continue
        pr = rvol.pace_rvol(q.get("day_volume", 0), q.get("avg_volume", 0), mins) if q else None
        v = {"ticker": t, "held": t in held, "roster": t in roster, **es, "pace_rvol": pr}
        if es["door_open"] and t not in held:
            v["verdict"] = "STAGE"
            v["sizes"] = {k: doors.size(net_liq, es["price"], es["stop_pct"], k) for k in doors.SIZE_TIERS} if net_liq else None
            v["callout"] = (f"{t}: {es['reason']} — staged at 15% floor, say PASS to cancel"
                            + (" [exit door: 4 EMA until it clears the 21]" if es.get("entry_door") == "4ema" else ""))
            # held_row is what the harness writes onto held.json. The rule for what belongs here:
            # store the DECISION, not the DATA. Bars can always be re-pulled, so anything an
            # indicator recomputes is free later and stays out. What dies if unwritten is why this
            # trade was taken and on what terms.
            v["held_row"] = {
                "ticker": t,
                "entry": es["price"],
                "initial_stop": es["stop_price"],
                "side": "long",
                "entry_door": es.get("entry_door"),
                "entry_datetime": clock.iso(date, acct.get("pt_time") or "11:50 AM"),
                "graduated_date": None,            # harness fills this the day it graduates
                "reclaim_day_at_entry": es.get("reclaim_day"),
                "entry_trigger": es.get("entry_trigger"),
                "new_52w_high_at_entry": es.get("new_52w_high"),
                "above_200sma_at_entry": es.get("above_200sma"),
                "ema4_at_entry": es.get("ema4"),
                "ema21_at_entry": es.get("ema21"),
                "atr14_at_entry": es.get("atr14"),
                "theme_at_entry": (uni_by_ticker.get(t) or {}).get("theme"),
                # What the solver RECOMMENDED at entry, and a slot for what Ray actually took.
                # Ray picks the tier, so the solver can never know it at stage time -- but the
                # recommendation is a decision the solver made, and it dies if unwritten. Keeping
                # both is what later answers "did taking the floor instead of best cost me anything".
                "sizes_recommended_at_entry": v.get("sizes"),
                "size_tier_taken": None,   # harness fills after Ray picks
                "shares_taken": None,      # harness fills from the fill
            }
        elif t in held:
            v["verdict"] = "HELD"
        else:
            v["verdict"] = "WATCH" if es["above_4ema"] else "PASS"
        verdicts.append(v)
    verdicts.sort(key=lambda v: ({"STAGE": 0, "HELD": 1, "WATCH": 2, "PASS": 3, "NO DATA": 4}[v["verdict"]], -(v.get("new_52w_high") or 0), v["ticker"]))
    exp = exposure.exposure(positions, net_liq) if net_liq else None
    return {
        "task": "take_action", "date": date, "calendar": st, "moc_deadline_pt": st["moc_deadline_pt"],
        "discovery": miss, "exposure": exp, "clusters": universe.clusters(uni),
        "counts": {"candidates": len(candidates), "staged": sum(v["verdict"] == "STAGE" for v in verdicts)},
        "verdicts": verdicts,
        "board_payloads": ledger.board_rows([r for r in uni if any(s.startswith("scan:") for s in r["sources"])], "Momentum", "Bull", date, {(r["Ticker"], r["Layer"]): r for r in board if r.get("Ticker") and r.get("Layer")}),
    }


def confirm_pass(d, date):
    """12:25 PM slot: staged names that flipped below the 4 EMA since they were staged.

    Held names are deliberately NOT read here. position_monitor runs the same 12:25 PM slot and
    owns the provisional exit read off the Positions DB (Ray, 2026-09-08). Checking held names in
    both would push the same name twice in the 20 minutes before the 12:45 PM MOC deadline.

    A staged name whose quote or bars are missing is reported in `skipped`, never dropped: an
    unchecked staged name looks exactly like a clean one in the output otherwise.
    """
    staged, quotes, bars = _load(d, "staged.json", []), _load(d, "quotes.json", {}), _load(d, "bars.json", {})
    flips, skipped = [], []
    for s_row in staged:
        t = s_row["ticker"]
        b, q = bars.get(t, []), quotes.get(t) or {}
        # entry_state raises on an empty bar list, and a name checked without a live quote is
        # checked against yesterday's close -- neither can be allowed to look like a clean pass.
        if not b or q.get("last") is None:
            skipped.append({"ticker": t, "reason": "no bars" if not b else "no live quote"})
            continue
        es = doors.entry_state(b, q["last"], q.get("day_high"), q.get("day_low"))
        if "price" not in es:
            skipped.append({"ticker": t, "reason": es.get("reason", "no entry state")})
            continue
        if not es["above_4ema"]:
            flips.append({"ticker": t, "price": es["price"], "ema4": es["ema4"],
                          "note": "flipped below 4 EMA since staging — cancel or size down, your call"})
    return {"task": "confirm_pass", "date": date, "checked": len(staged), "flips": flips,
            "skipped": skipped,
            "moc_deadline_pt": _gate(d, date).get("moc_deadline_pt"),
            "push": bool(flips)}


def _position_sides(pos_json):
    """{ticker: "long"|"short"} from the signed IBKR STK line.

    Keyed on the symbol, not the whole contract_description, so a description that carries more than
    a bare ticker still resolves. Zero-quantity lines are skipped: an unsigned number is not a side.
    """
    out = {}
    for p in pos_json.get("positions", []) or []:
        if p.get("asset_class") != "STK":
            continue
        desc = (p.get("contract_description") or p.get("symbol") or "").split()
        if not desc:
            continue
        for key in ("position", "quantity", "market_value"):
            v = p.get(key)
            if v is None:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f != 0:
                out[desc[0]] = "short" if f < 0 else "long"
                break
    return out


def position_monitor(d, date):
    held, bars, acct = _load(d, "held.json", []), _load(d, "bars.json", {}), _load(d, "account.json", {})
    pos_json = _load(d, "positions.json", {"positions": []})
    # quotes are optional here. When present, every row also carries a provisional_* read against the
    # live price, so this task is usable BEFORE the 12:45 PM MOC deadline and not only at 1:10 PM.
    quotes = _load(d, "quotes.json", {})
    sides = _position_sides(pos_json)
    out = []
    for h in held:
        t = h["ticker"]
        b = bars.get(t, [])
        if not b:
            out.append({"ticker": t, "verdict": "NO DATA"})
            continue
        # side: held.json wins, then the sign of the IBKR position. Never a default.
        # Guessing long on a short inverts the stop to the profitable side and leaves the
        # direction that actually hurts completely unprotected.
        side = h.get("side") or sides.get(t)
        if side is None:
            out.append({"ticker": t, "verdict": "SIDE UNKNOWN",
                        "reason": "no side on the held.json row and no signed STK position for this ticker; "
                                  "refusing to guess, because the wrong side puts the stop on the wrong side of price"})
            continue
        # entry_door / entry_date come off the held.json row, written when the name was staged.
        # Missing entry_door defaults to the tight 4 EMA door for a position that cannot prove it
        # was ever above the 21 EMA; missing entry_date simply blocks graduation. Both err early.
        # entry_datetime is the field going forward (Ray, 2026-09-08: every date carries a time);
        # entry_date still accepted so existing held.json rows keep working.
        # graduated_date is the Positions DB "Graduated on" column, which the prompt already maps
        # into held.json. Read, a graduation stops depending on the graduating close still being
        # inside the harness's 130-calendar-day bar window; unread, a position held past that window
        # is demoted to the tight door on a scan that finds nothing, which the rule forbids.
        ex = doors.exit_state(b, settled_only=True, side=side,
                              last_price=(quotes.get(t) or {}).get("last"),
                              entry_door_=h.get("entry_door", "4ema"),
                              entry_date=h.get("entry_datetime") or h.get("entry_date"),
                              graduated_date=h.get("graduated_date"))
        cur = b[-1]["close"]
        out.append({"ticker": t, **ex,
                    "breakeven_1r_reached": doors.breakeven_1r(h["entry"], h["initial_stop"], cur, side=side),
                    "stop_from_current": doors.stop_from_current(b, side=side)})
    net_liq = float(acct.get("net_liq", 0) or 0)
    return {"task": "position_monitor", "date": date, "positions": out,
            "exposure": exposure.exposure(pos_json.get("positions", []), net_liq) if net_liq else None,
            # Graduations the solver DERIVED this run, for EOD to write into the Positions DB
            # "Graduated on" column. Deriving one is free only while the graduating close is still
            # in the bar window; writing it down is what makes the position survive leaving it.
            # This is an OUTPUT field, so it needs no prompt edit to appear -- but the EOD prompt
            # has to map it before the write actually happens.
            "graduated_payloads": [{"ticker": p["ticker"], "Graduated on": p["graduated_date"]}
                                   for p in out if p.get("graduated_source") == "derived"],
            # push budget: the 21 EMA door (or a deep break) is the mandatory exit; the 4 EMA door is a
            # warning. An unresolvable side is also worth a push -- it means a position is unmonitored.
            # thin_history pushes for the same reason SIDE UNKNOWN does: the read did not run.
            # A held name whose 21 EMA test could not be computed is unmonitored, not fine.
            # graduated_date_error pushes for the same reason: a refused "Graduated on" value means
            # the Positions DB row contradicts itself and only Ray can say which half is right.
            "push": any(p.get("mandatory_exit") or p.get("provisional_mandatory")
                        or p.get("thin_history") or p.get("graduated_date_error")
                        or p.get("verdict") == "SIDE UNKNOWN" for p in out)}


def _held(d):
    """IBKR open STK tickers. Held names are never excluded from monitoring, only from staging."""
    pos = _load(d, "positions.json", {"positions": []}).get("positions", [])
    return [p["contract_description"] for p in pos if p.get("asset_class") == "STK"]


def fast_discovery(d, date):
    scans, thematic, quotes, acct = _load(d, "scans.json", {}), _load(d, "thematic.json", {}), _load(d, "quotes.json", {}), _load(d, "account.json", {})
    uni = universe.build(scans, thematic, _load(d, "roster.json", []), _held(d), _load(d, "exclusion.json", {}))
    mins = rvol.minutes_since_open(acct.get("pt_time", "11:15"))
    buzz = []
    for r in uni:
        q = quotes.get(r["ticker"])
        if q and not r["excluded"]:
            pr = rvol.pace_rvol(q.get("day_volume", 0), q.get("avg_volume", 0), mins)
            if pr and pr >= 1.5:
                buzz.append({"ticker": r["ticker"], "pace_rvol": pr, "theme": r["theme"]})
    buzz.sort(key=lambda x: -x["pace_rvol"])
    board = _load(d, "board.json", [])
    existing = {(r["Ticker"], r["Layer"]): r for r in board if r.get("Ticker") and r.get("Layer")}
    return {"task": "fast_discovery", "date": date, "minutes_since_open": mins, "universe": len(uni), "excluded": sum(r["excluded"] for r in uni),
            "volume_buzz": buzz, "clusters": universe.clusters(uni),
            "board_payloads": ledger.board_rows([r for r in uni if r["ticker"] in {b["ticker"] for b in buzz}], "Volume buzz", "Bull", date, existing, why_fn=lambda r: f"pace RVOL at {acct.get('pt_time','11:15')} PT")}


def eow(d, date):
    board, bars = _load(d, "board.json", []), _load(d, "bars.json", {})
    return {"task": "eow", "date": date, **grader.grade_board(board, bars)}


def miss_audit(d, date):
    board, bars = _load(d, "board.json", []), _load(d, "bars.json", {})
    first = {}
    for r in board:
        t, fs = r.get("Ticker"), r.get("first_seen")
        if not t or not fs:
            continue
        first[t] = min(first.get(t, "9999-99-99"), fs)
    return {"task": "miss_audit", "date": date, "misses": grader.miss_audit(bars, first)}


def calendar_check(d, date):
    return _gate(d, date)


TASKS = {"take_action": take_action, "confirm_pass": confirm_pass, "position_monitor": position_monitor,
         "fast_discovery": fast_discovery, "eow": eow, "miss_audit": miss_audit, "calendar": calendar_check}


# Tasks that act on live prices. A bad clock here reaches a real order, so these refuse.
LIVE_TASKS = {"take_action", "confirm_pass", "position_monitor", "fast_discovery"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cc-solver")
    ap.add_argument("task", choices=sorted(TASKS))
    ap.add_argument("--inputs", required=True, help="directory of JSON inputs written by the harness")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD session date (PT)")
    ap.add_argument("--allow-clock-drift", action="store_true",
                    help="proceed even when the clock check errors. For deliberate replays only; "
                         "the refusal exists because a wrong clock silently poisons pace RVOL and "
                         "every provisional exit read")
    a = ap.parse_args(argv)

    # THE TIME CHECK. Nothing time-dependent runs above this line.
    acct = _load(a.inputs, "account.json", {})
    tc = clock.check(a.date, acct.get("pt_time"), task=a.task)
    if tc["errors"] and a.task in LIVE_TASKS and not a.allow_clock_drift:
        json.dump({"task": a.task, "date": a.date, "status": "refused",
                   "reason": "clock check failed; refusing to compute live-price verdicts on a "
                             "clock this far off. Fix the input, or pass --allow-clock-drift if "
                             "this is a deliberate replay.",
                   "time_check": tc}, sys.stdout, indent=1, default=str)
        print()
        return 2

    out = TASKS[a.task](a.inputs, a.date)
    if isinstance(out, dict):
        out = {"time_check": tc, **out}
    json.dump(out, sys.stdout, indent=1, default=str)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
