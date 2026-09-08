"""Replay doors.py over a ticker list and date range. Build 4 will drive the exit-door backtest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import doors  # noqa: E402


def load_bars(path: Path) -> dict:
    return json.loads(path.read_text())


def slice_to(bars: list[dict], asof: str) -> list[dict]:
    return [b for b in bars if b["date"] <= asof]


def replay(tickers: list[str], start: str, end: str, bars_dir: Path) -> list[dict]:
    rows = []
    for ticker in tickers:
        path = bars_dir / f"{ticker}.json"
        if not path.exists():
            rows.append({"ticker": ticker, "error": "no bars file"})
            continue
        payload = load_bars(path)
        by_date = {b["date"]: b for b in payload["bars"]}
        ordered = sorted(by_date)
        dates = [d for d in ordered if start <= d <= end]
        if not dates:
            rows.append({"ticker": ticker, "error": "no dates in range"})
            continue
        n_before = len(rows)
        for d in dates:
            hist = [by_date[x] for x in ordered if x <= d]
            if len(hist) < 30:
                continue
            v = doors.evaluate(
                ticker,
                [b["date"] for b in hist],
                [b["open"] for b in hist],
                [b["high"] for b in hist],
                [b["low"] for b in hist],
                [b["close"] for b in hist],
                last=hist[-1]["close"],
            )
            rows.append({"date": d, **v.to_dict()})
        if len(rows) == n_before:
            rows.append({"ticker": ticker, "error": "not enough history before range"})
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Replay doors over IBKR/RH daily history files")
    p.add_argument("--tickers", required=True, help="comma-separated")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--bars-dir", default="data/live/2026-09-08/bars")
    args = p.parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    rows = replay(tickers, args.start, args.end, Path(args.bars_dir))
    json.dump({"n": len(rows), "rows": rows[:50], "truncated": len(rows) > 50}, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
