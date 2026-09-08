#!/usr/bin/env python3
"""Deterministic solver entry point. One command per scheduled task. Prints JSON. Never places orders."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import calendar as calmod
import doors
import grader
import ledger
import rvol
import universe

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
STOCKCHARTS = "https://stockcharts.com/h-sc/ui?s={ticker}"
TASKS = (
    "slow_discovery",
    "fast_discovery",
    "take_action",
    "confirm_pass",
    "position_monitor",
    "true_up",
    "eod",
    "eow",
    "eom",
    "miss_audit",
)


def now_pt() -> datetime:
    return datetime.now(PT)


def stamp() -> str:
    return now_pt().strftime("%Y-%m-%d %H:%M %Z")


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def load_themes() -> dict[str, str]:
    raw = load_json(ROOT / "config" / "themes.json", {})
    inv = {}
    for theme, tickers in raw.items():
        for t in tickers:
            inv.setdefault(t.upper(), theme)
    return inv


def load_bars(bars_dir: Path, ticker: str) -> list[dict]:
    path = bars_dir / f"{ticker}.json"
    if not path.exists():
        return []
    return load_json(path)["bars"]


def append_today(bars: list[dict], day: str, last: float) -> list[dict]:
    if not bars:
        return bars
    if bars[-1]["date"] == day:
        b = dict(bars[-1])
        b["close"] = last
        b["high"] = max(b["high"], last)
        b["low"] = min(b["low"], last)
        return bars[:-1] + [b]
    prev = bars[-1]
    return bars + [{
        "date": day,
        "open": prev["close"],
        "high": max(prev["close"], last),
        "low": min(prev["close"], last),
        "close": last,
        "volume": 0,
        "provisional": True,
    }]


def series(bars: list[dict]):
    return (
        [b["date"] for b in bars],
        [b["open"] for b in bars],
        [b["high"] for b in bars],
        [b["low"] for b in bars],
        [b["close"] for b in bars],
    )


def exposure_line(positions: dict, net_liq: float | None) -> dict:
    if net_liq is None or not positions.get("positions"):
        return {
            "banner": None,
            "breach": False,
            "reason": "IBKR positions/net_liq missing; exposure not computed",
        }
    proc = subprocess.run(
        [sys.executable, str(ROOT / "exposure.py"), json.dumps(positions), str(net_liq)],
        capture_output=True,
        text=True,
        check=False,
    )
    line = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return {"banner": None, "breach": False, "reason": proc.stderr.strip() or "exposure.py failed"}
    return {"banner": line, "breach": "BREACH" in line, "reason": "exposure.py verbatim"}


def avg_volume(bars: list[dict], n: int = 30) -> float | None:
    vols = [b["volume"] for b in bars if b.get("volume") and not b.get("provisional")]
    if not vols:
        return None
    window = vols[-n:]
    if not window:
        return None
    return sum(window) / len(window)


def todays_intraday_volume(data_dir: Path, ticker: str) -> float | None:
    path = data_dir / "intraday" / f"{ticker}.json"
    if not path.exists():
        return None
    bars = load_json(path).get("bars") or []
    return float(sum(b.get("volume") or 0 for b in bars))


def index_bias(bars_dir: Path, quotes: dict, day: str) -> dict:
    states = {}
    for t in ("SPY", "QQQ", "IWM", "DIA"):
        bars = append_today(load_bars(bars_dir, t), day, float(quotes[t]["last"])) if t in quotes else load_bars(bars_dir, t)
        if len(bars) < 4 or t not in quotes:
            states[t] = "unknown"
            continue
        v = doors.evaluate(t, *series(bars), last=float(quotes[t]["last"]))
        states[t] = "above" if v.ema4 is not None and v.last >= v.ema4 else "below"
    above = sum(1 for s in states.values() if s == "above")
    below = sum(1 for s in states.values() if s == "below")
    if above >= 3:
        bias = "LONG BIAS"
    elif below >= 3:
        bias = "SHORT BIAS"
    else:
        bias = "MIXED"
    return {"states": states, "bias": bias, "note": "preference not gate"}


def short_break(v: doors.DoorVerdict, closes, ema4) -> bool:
    if v.ema4 is None or len(closes) < 2:
        return False
    e_prev = ema4[-2] if len(ema4) >= 2 else None
    if e_prev is None:
        return False
    return closes[-2] >= e_prev and v.last < v.ema4 and v.reclaim_day == 0


def size_for(grade: str, tags: list[str]) -> int:
    if grade == "A" and ("cluster" in tags or "new_high" in tags):
        return 25
    if grade == "A":
        return 20
    return 15


def grade_of(v: doors.DoorVerdict, rs: float | None, rs_rank: float | None) -> tuple[str, list[str]]:
    legs = []
    miss = []
    fresh = v.reclaim_day in (1, 2)
    above200 = v.sma200 is not None and v.last >= v.sma200
    top_rs = rs_rank is not None and rs_rank <= 0.20
    if fresh:
        legs.append("fresh reclaim")
    else:
        miss.append("no fresh reclaim")
    if above200:
        legs.append("above 200 SMA")
    else:
        miss.append("not above 200 SMA")
    if top_rs:
        legs.append("top-20% 20d RS vs SPY (set-relative)")
    else:
        miss.append("RS not top-20% of this set")
    if len(legs) == 3:
        return "A", legs
    if len(legs) == 2:
        return "B", legs + miss
    return "B", legs + miss


def take_action(data_dir: Path, day: str) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    session = calmod.session_status(day)
    quotes = load_json(data_dir / "quotes.json", {})
    uni_snap = load_json(data_dir / "universe.json", {})
    positions_raw = load_json(data_dir / "positions.json", {"positions": [], "net_liq": None})
    discovery = load_json(data_dir / "discovery_board.json", [])
    run_log = load_json(data_dir / "run_log.json", [])
    handoff = load_json(data_dir / "handoff.json", {})
    bars_dir = data_dir / "bars"
    themes = load_themes()
    banners = []
    if session["status"] == "closed":
        return {
            "written_by": "Grok",
            "timestamp": stamp(),
            "task": "take_action",
            "date": day,
            "calendar": session,
            "banners": ["session closed; skip"],
            "tickers": [],
            "orders": "none",
        }
    if ledger.fleet_paused(handoff if isinstance(handoff, dict) else {}):
        banners.append("fleet_paused=true on Trader Handoff; skip acting")
    if ledger.discovery_missing(run_log if isinstance(run_log, list) else []):
        banners.append("discovery missing: no Slow discovery / Fast discovery row in today's Run Log")
    if positions_raw.get("net_liq") is None:
        banners.append("IBKR unavailable this run; positions empty; exposure not computed")

    pos_tickers = []
    for p in positions_raw.get("positions") or []:
        desc = p.get("contract_description") or p.get("symbol") or ""
        if desc:
            pos_tickers.append(desc.split()[0])

    rows = universe.build_universe(
        roster=uni_snap.get("roster") or [],
        discovery=discovery if isinstance(discovery, list) else [],
        positions=pos_tickers,
        rh_scan_rows=load_json(data_dir / "scans.json", {}).get("runs") or [],
    )
    action_rows = universe.take_action_set(rows)
    exp = exposure_line(positions_raw, positions_raw.get("net_liq"))
    if exp.get("banner"):
        banners.append(exp["banner"])
    if exp.get("breach"):
        banners.append("breach is a banner, not a staging change; still stage at 15% floor with say PASS to cancel")

    hour = datetime.now(ET).hour
    minute = datetime.now(ET).minute
    mins = rvol.minutes_elapsed_rth(hour, minute)
    spy_bars = append_today(load_bars(bars_dir, "SPY"), day, float(quotes["SPY"]["last"])) if "SPY" in quotes else []
    spy_closes = [b["close"] for b in spy_bars]

    evaluated = []
    for row in action_rows:
        t = row["ticker"]
        if t not in quotes:
            evaluated.append({
                "ticker": t,
                "chart": STOCKCHARTS.format(ticker=t),
                "decision": "WATCH",
                "reasons": ["no last price"],
                "excluded": row["excluded"],
            })
            continue
        last = float(quotes[t]["last"])
        bars = append_today(load_bars(bars_dir, t), day, last)
        if len(bars) < 5:
            evaluated.append({
                "ticker": t,
                "chart": STOCKCHARTS.format(ticker=t),
                "decision": "WATCH",
                "reasons": ["not enough daily bars"],
                "excluded": row["excluded"],
            })
            continue
        v = doors.evaluate(t, *series(bars), last=last)
        rs = doors.rs_20d([b["close"] for b in bars], spy_closes) if spy_closes else None
        avg_vol = avg_volume(bars)
        today_vol = todays_intraday_volume(data_dir, t)
        rv = None
        if today_vol is not None and avg_vol:
            rv = rvol.pace_adjusted_rvol(today_vol, avg_vol, mins)
        e4s = doors.ema([b["close"] for b in bars], 4)
        is_short = short_break(v, [b["close"] for b in bars], e4s)
        evaluated.append({
            "row": row,
            "v": v,
            "rs": rs,
            "rvol": rv,
            "theme": themes.get(t),
            "is_short": is_short,
        })

    rs_vals = sorted(
        [(e["v"].ticker, e["rs"]) for e in evaluated if isinstance(e.get("v"), doors.DoorVerdict) and e["rs"] is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    n_rs = len(rs_vals)
    rank = {t: i / n_rs for i, (t, _) in enumerate(rs_vals)} if n_rs else {}

    theme_hits: dict[str, list[str]] = {}
    for e in evaluated:
        v = e.get("v")
        if not isinstance(v, doors.DoorVerdict):
            continue
        if v.reclaim_day in (1, 2) and e.get("theme"):
            theme_hits.setdefault(e["theme"], []).append(v.ticker)
    clusters = {th: ts for th, ts in theme_hits.items() if len(ts) >= 3}

    tickers_out = []
    staged = 0
    for e in evaluated:
        if "decision" in e and "v" not in e:
            tickers_out.append(e)
            continue
        v: doors.DoorVerdict = e["v"]
        row = e["row"]
        tags = []
        if v.new_high:
            tags.append("new_high")
        if e.get("theme") and e["theme"] in clusters:
            tags.append("cluster")
        grade, grade_legs = grade_of(v, e.get("rs"), rank.get(v.ticker))
        reasons = list(v.reasons) + grade_legs
        if e.get("theme"):
            reasons.append(f"theme={e['theme']}")
        if tags:
            reasons.append("tags: " + ",".join(tags))
        if row["excluded"]:
            decision = "EXCLUDED"
            size = None
            reasons.append(row.get("exclude_reason") or "excluded")
        elif e.get("is_short"):
            decision = "ALERT_SHORT"
            size = None
            reasons.append("short taxonomy: alert-only, no staging")
        elif v.reclaim_day in (1, 2):
            decision = "STAGE_LONG"
            size = 15 if exp.get("breach") else size_for(grade, tags)
            reasons.append(f"size {size}% (which size, never whether)")
            if exp.get("breach"):
                reasons.append("say PASS to cancel")
            staged += 1
        elif any(s == "position" for s in row["sources"]):
            decision = "HOLD"
            size = None
        else:
            decision = "WATCH"
            size = None
        tickers_out.append({
            "decision": decision,
            "ticker": v.ticker,
            "chart": STOCKCHARTS.format(ticker=v.ticker),
            "last": v.last,
            "size_pct": size,
            "grade": grade,
            "reclaim_day": v.reclaim_day,
            "slow_sto_20_low": v.slow_sto_20_low,
            "new_high": v.new_high,
            "exit_4ema": v.exit_4ema,
            "exit_21ema": v.exit_21ema,
            "deep_break": v.deep_break,
            "atr14": v.atr14,
            "ema4": v.ema4,
            "ema21": v.ema21,
            "sma200": v.sma200,
            "stop_price": v.stop_price,
            "stop_binds": v.stop_binds,
            "breakeven_at_1R": v.breakeven_at_1R,
            "rs_20d_vs_spy": e.get("rs"),
            "rvol": e.get("rvol"),
            "theme": e.get("theme"),
            "sources": row["sources"],
            "excluded": row["excluded"],
            "reasons": reasons,
        })

    tickers_out.sort(key=lambda r: (
        0 if r.get("decision") == "STAGE_LONG" else 1 if r.get("decision") == "ALERT_SHORT" else 2,
        r.get("grade") or "Z",
        -(r.get("rs_20d_vs_spy") or -999),
    ))

    payload = ledger.run_log_payload(
        task="Take-action",
        started_iso=started,
        model="solver",
        inputs_read=(
            f"calendar={session['status']}; roster={len(uni_snap.get('roster') or [])}; "
            f"discovery={len(discovery) if isinstance(discovery, list) else 0}; "
            f"positions={len(pos_tickers)}; bars={bars_dir}"
        ),
        what_i_did=f"{len(tickers_out)} names scored, {staged} STAGE_LONG",
        outcome="Partial" if banners else "OK",
    )
    return {
        "written_by": "Grok",
        "timestamp": stamp(),
        "task": "take_action",
        "date": day,
        "calendar": session,
        "banners": banners,
        "exposure": exp,
        "index_bias": index_bias(bars_dir, quotes, day) if quotes else None,
        "clusters": clusters,
        "universe_note": "take_action set = roster union Discovery Board (63d) union positions; RH scans are samples",
        "tickers": tickers_out,
        "run_log": payload,
        "orders": "none",
        "binding": [
            "never create or modify a Robinhood scan",
            "never place, modify, or cancel any broker order",
            "never touch Robinhood Agentic account 608898375",
        ],
    }


def confirm_pass(data_dir: Path, day: str, staged: list[str] | None = None) -> dict:
    quotes = load_json(data_dir / "quotes.json", {})
    bars_dir = data_dir / "bars"
    names = staged or load_json(data_dir / "staged.json", [])
    flips = []
    rows = []
    for t in names:
        if t not in quotes:
            continue
        last = float(quotes[t]["last"])
        bars = append_today(load_bars(bars_dir, t), day, last)
        v = doors.evaluate(t, *series(bars), last=last)
        still = v.ema4 is not None and v.last >= v.ema4
        rows.append({"ticker": t, "still_above_4ema": still, "last": v.last, "ema4": v.ema4})
        if not still:
            flips.append(t)
    return {
        "written_by": "Grok",
        "timestamp": stamp(),
        "task": "confirm_pass",
        "date": day,
        "calendar": calmod.session_status(day),
        "flips": flips,
        "rows": rows,
        "push": bool(flips),
        "orders": "none",
    }


def position_monitor(data_dir: Path, day: str) -> dict:
    quotes = load_json(data_dir / "quotes.json", {})
    positions_raw = load_json(data_dir / "positions.json", {"positions": [], "net_liq": None})
    bars_dir = data_dir / "bars"
    out = []
    for p in positions_raw.get("positions") or []:
        t = (p.get("contract_description") or p.get("symbol") or "").split()[0]
        if not t or t not in quotes:
            continue
        last = float(quotes[t]["last"])
        bars = append_today(load_bars(bars_dir, t), day, last)
        entry = p.get("avg_cost") or p.get("average_cost")
        v = doors.evaluate(t, *series(bars), last=last, entry_price=entry)
        out.append(v.to_dict())
    return {
        "written_by": "Grok",
        "timestamp": stamp(),
        "task": "position_monitor",
        "date": day,
        "calendar": calmod.session_status(day),
        "exposure": exposure_line(positions_raw, positions_raw.get("net_liq")),
        "positions": out,
        "orders": "none",
    }


def stub(task: str, day: str, extra=None) -> dict:
    body = {
        "written_by": "Grok",
        "timestamp": stamp(),
        "task": task,
        "date": day,
        "calendar": calmod.session_status(day),
        "status": "stub",
        "note": "CLI surface exists; full LLM+solver body lands in later fleet builds",
        "orders": "none",
    }
    if extra:
        body.update(extra)
    return body


def miss_audit_cmd(data_dir: Path, day: str) -> dict:
    discovery = load_json(data_dir / "discovery_board.json", [])
    moves = load_json(data_dir / "miss_moves.json", [])
    seen = {(d.get("ticker") or d.get("Ticker") or "").upper() for d in discovery}
    proposals = grader.miss_audit(moves, seen)
    return {
        "written_by": "Grok",
        "timestamp": stamp(),
        "task": "miss_audit",
        "date": day,
        "calendar": calmod.session_status(day),
        "proposals": proposals,
        "note": "Never edits a rule. Proposals only.",
        "orders": "none",
    }


def default_data_dir(day: str) -> Path:
    return ROOT / "data" / "live" / day


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Consistency Capital deterministic solver")
    p.add_argument("task", choices=TASKS)
    p.add_argument("--date", required=True, help="YYYY-MM-DD (PT session date)")
    p.add_argument("--data-dir", default=None)
    args = p.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir(args.date)
    if args.task == "take_action":
        out = take_action(data_dir, args.date)
    elif args.task == "confirm_pass":
        out = confirm_pass(data_dir, args.date)
    elif args.task == "position_monitor":
        out = position_monitor(data_dir, args.date)
    elif args.task == "miss_audit":
        out = miss_audit_cmd(data_dir, args.date)
    elif args.task == "eow":
        rows = load_json(data_dir / "discovery_board.json", [])
        bars_by = {}
        bars_dir = data_dir / "bars"
        for tkr in {r.get("ticker") or r.get("Ticker") for r in rows}:
            if tkr:
                bars_by[tkr] = load_bars(bars_dir, tkr)
        graded = grader.grade_rows(rows, bars_by)
        out = stub("eow", args.date, {"graded": graded, "hit_rate_20d": grader.hit_rate(graded)})
    else:
        out = stub(args.task, args.date)
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
