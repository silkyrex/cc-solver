"""Deduped ticker set. Robinhood scans are samples (cap 399), never a universe."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCL_PATH = ROOT / "config" / "exclusions.json"
SCAN_CAP = 399


def load_exclusions(path: Path | None = None) -> dict:
    return json.loads((path or EXCL_PATH).read_text())


def _norm(ticker: str) -> str:
    return str(ticker).strip().upper()


def category_hit(ticker: str, name: str | None, excl: dict) -> str | None:
    t = _norm(ticker)
    if t in {x.upper() for x in excl.get("known_levered_tickers", [])}:
        return "C1"
    blob = f"{t} {name or ''}"
    for cat in excl.get("categories", []):
        for needle in cat.get("name_contains", []):
            if needle.lower() in blob.lower():
                return cat["id"]
    return None


def pump_sub3(price: float | None, rvol: float | None) -> bool:
    return price is not None and rvol is not None and price < 3 and rvol > 20


def build_universe(
    roster: list[str],
    discovery: list[dict],
    positions: list[str],
    rh_scan_rows: list[dict] | None = None,
    named_exclusions: list[str] | None = None,
    exclusions: dict | None = None,
    names: dict | None = None,
    prices: dict | None = None,
    rvols: dict | None = None,
) -> list[dict]:
    """Return one row per ticker with source tags. Excluded names kept with excluded=true."""
    excl = exclusions or load_exclusions()
    named = {_norm(x) for x in (named_exclusions or excl.get("named") or [])}
    names = names or {}
    prices = prices or {}
    rvols = rvols or {}
    by: dict[str, dict] = {}

    def add(ticker: str, source: str):
        t = _norm(ticker)
        if not t:
            return
        row = by.get(t)
        if row is None:
            row = {
                "ticker": t,
                "sources": [],
                "excluded": False,
                "exclude_reason": None,
                "sample_only": False,
            }
            by[t] = row
        if source not in row["sources"]:
            row["sources"].append(source)

    for t in roster:
        add(t, "roster")
    for d in discovery:
        add(d.get("ticker") or d.get("Ticker") or "", "discovery_board")
    for t in positions:
        add(t, "position")

    scan_note = None
    if rh_scan_rows:
        if len(rh_scan_rows) >= SCAN_CAP:
            scan_note = f"Robinhood scan returned {len(rh_scan_rows)} rows (cap {SCAN_CAP}); sample, not a universe"
        for rec in rh_scan_rows:
            t = rec.get("ticker") or rec.get("symbol") or ""
            add(t, "rh_scan_sample")
            if t and _norm(t) in by:
                by[_norm(t)]["sample_only"] = True

    out = []
    for t, row in sorted(by.items()):
        reasons = []
        if t in named:
            row["excluded"] = True
            reasons.append("named exclusion")
        cat = category_hit(t, names.get(t), excl)
        if cat:
            row["excluded"] = True
            reasons.append(f"category {cat}")
        if pump_sub3(prices.get(t), rvols.get(t)):
            row["excluded"] = True
            reasons.append("C3 sub-$3 pump")
        row["exclude_reason"] = "; ".join(reasons) if reasons else None
        out.append(row)
    return out


def take_action_set(rows: list[dict]) -> list[dict]:
    """Roster ∪ Discovery Board ∪ open positions. Scan samples do not enter the set alone."""
    keep = []
    for row in rows:
        src = row["sources"]
        if any(s in src for s in ("roster", "discovery_board", "position")):
            keep.append(row)
    return keep


def massive_universe() -> list[dict]:
    raise NotImplementedError(
        "Massive adapter stub. Plan page §2b: Massive is primary universe once Ray rules. "
        "Build 2 take_action does not need a full-market universe."
    )
