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
    held = _held(d)
    quotes, bars = _load(d, "quotes.json", {}), _load(d, "bars.json", {})
    board = _load(d, "board.json", [])
    miss = ledger.discovery_missing(_load(d, "run_log_today.json", []))
    since = ledger.window_start(date)
    board_names = sorted({r["Ticker"] for r in board if r.get("Ticker") and r.get("first_seen", "") >= since})

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
        "board_payloads": ledger.board_rows([r for r in uni if any(s.startswith("scan:") for s in r["sources"])], "Momentum", "Bull", date, {(r["Ticker"], r["Layer"]): r for r in board if r.get("Ticker") and r.get("Layer")}),
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
        ex = doors.exit_state(b, settled_only=True, side=side)
        cur = b[-1]["close"]
        out.append({"ticker": t, **ex,
                    "breakeven_1r_reached": doors.breakeven_1r(h["entry"], h["initial_stop"], cur, side=side),
                    "stop_from_current": doors.stop_from_current(b, side=side)})
    net_liq = float(acct.get("net_liq", 0) or 0)
    return {"task": "position_monitor", "date": date, "positions": out,
            "exposure": exposure.exposure(pos_json.get("positions", []), net_liq) if net_liq else None,
            # push budget: the 21 EMA door (or a deep break) is the mandatory exit; the 4 EMA door is a
            # warning. An unresolvable side is also worth a push -- it means a position is unmonitored.
            "push": any(p.get("mandatory_exit") or p.get("verdict") == "SIDE UNKNOWN" for p in out)}


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
