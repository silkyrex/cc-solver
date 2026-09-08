"""One entry point per scheduled task. Reads JSON from --inputs DIR, prints JSON.

Input files the harness writes (all optional unless noted):
  calendar.json   {"closed": [...], "early": [...]}                       (all tasks)
  bars.json       {"TICKER": [{date,open,high,low,close,volume}...]}     (take_action, confirm_pass, position_monitor, eow, miss_audit)
  quotes.json     {"TICKER": {"last": 12.3, "day_high": 12.6, "day_low": 11.9, "day_volume": 1e6, "avg_volume": 8e5}}  (take_action, confirm_pass, fast_discovery)
  scans.json      {"scan name": [rows]}                                   (fast_discovery, take_action)
  thematic.json   {"Theme": ["T1","T2"]}
  roster.json     ["SNDK", ...]
  positions.json  IBKR get_account_positions JSON (whole object)          (take_action, position_monitor, eod)
  account.json    {"net_liq": 18910.0, "pt_time": "11:50"}               (take_action, position_monitor)
  exclusion.json  {"names": [...], "patterns": [...]}
  run_log_today.json  [ {Task, Outcome} ... ]                            (take_action)
  board.json      [ {url, Ticker, Layer, first_seen, seen_count} ... ]   (take_action, eow, miss_audit)
  staged.json     [ {ticker, price, stop} ... ]                           (confirm_pass)
  held.json       [ {ticker, entry, initial_stop, side} ... ]            (position_monitor)
"""
import argparse
import json
import os
import sys

from . import calendar as cal
from . import doors, exposure, grader, ledger, rvol, universe


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
    held = [p["contract_description"] for p in positions if p.get("asset_class") == "STK"]
    quotes, bars = _load(d, "quotes.json", {}), _load(d, "bars.json", {})
    board = _load(d, "board.json", [])
    miss = ledger.discovery_missing(_load(d, "run_log_today.json", []))
    since = ledger.window_start(date)
    board_names = sorted({r["Ticker"] for r in board if r.get("first_seen", "") >= since})

    uni = universe.build(scans, thematic, roster, held, excl)
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
            v["callout"] = f"{t}: {es['reason']} — staged at 15% floor, say PASS to cancel"
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
        "board_payloads": ledger.board_rows([r for r in uni if any(s.startswith("scan:") for s in r["sources"])], "Momentum", "Bull", date, {(r["Ticker"], r["Layer"]): r for r in board}),
    }


def confirm_pass(d, date):
    staged, quotes, bars = _load(d, "staged.json", []), _load(d, "quotes.json", {}), _load(d, "bars.json", {})
    flips = []
    for s in staged:
        t = s["ticker"]
        q = quotes.get(t, {})
        es = doors.entry_state(bars.get(t, []), q.get("last"), q.get("day_high"), q.get("day_low"))
        if "price" in es and not es["above_4ema"]:
            flips.append({"ticker": t, "price": es["price"], "ema4": es["ema4"], "note": "flipped below 4 EMA since staging — cancel or size down, your call"})
    return {"task": "confirm_pass", "date": date, "checked": len(staged), "flips": flips, "push": bool(flips)}


def position_monitor(d, date):
    held, bars, acct = _load(d, "held.json", []), _load(d, "bars.json", {}), _load(d, "account.json", {})
    pos_json = _load(d, "positions.json", {"positions": []})
    out = []
    for h in held:
        t = h["ticker"]
        b = bars.get(t, [])
        if not b:
            out.append({"ticker": t, "verdict": "NO DATA"})
            continue
        ex = doors.exit_state(b, settled_only=True)
        cur = b[-1]["close"]
        out.append({"ticker": t, **ex, "breakeven_1r_reached": doors.breakeven_1r(h["entry"], h["initial_stop"], cur),
                    "stop_from_current": round(cur * (1 - max(doors.STOP_FLOOR_PCT, doors.ATR_MULT * (doors.atr(b, 14)[-1] or 0) / cur)), 4)})
    net_liq = float(acct.get("net_liq", 0) or 0)
    return {"task": "position_monitor", "date": date, "positions": out,
            "exposure": exposure.exposure(pos_json.get("positions", []), net_liq) if net_liq else None,
            "push": any(p.get("mandatory_exit_under_4ema_door") or p.get("mandatory_exit_under_21ema_door") for p in out)}


def fast_discovery(d, date):
    scans, thematic, quotes, acct = _load(d, "scans.json", {}), _load(d, "thematic.json", {}), _load(d, "quotes.json", {}), _load(d, "account.json", {})
    uni = universe.build(scans, thematic, _load(d, "roster.json", []), [], _load(d, "exclusion.json", {}))
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
    existing = {(r["Ticker"], r["Layer"]): r for r in board}
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
        first[r["Ticker"]] = min(first.get(r["Ticker"], "9999-99-99"), r["first_seen"])
    return {"task": "miss_audit", "date": date, "misses": grader.miss_audit(bars, first)}


def calendar_check(d, date):
    return _gate(d, date)


TASKS = {"take_action": take_action, "confirm_pass": confirm_pass, "position_monitor": position_monitor,
         "fast_discovery": fast_discovery, "eow": eow, "miss_audit": miss_audit, "calendar": calendar_check}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cc-solver")
    ap.add_argument("task", choices=sorted(TASKS))
    ap.add_argument("--inputs", required=True, help="directory of JSON inputs written by the harness")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD session date (PT)")
    a = ap.parse_args(argv)
    json.dump(TASKS[a.task](a.inputs, a.date), sys.stdout, indent=1, default=str)
    print()


if __name__ == "__main__":
    main()
