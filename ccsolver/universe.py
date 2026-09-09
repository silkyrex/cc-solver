"""Union the sources, tag each name, apply the Exclusion List. Robinhood scans are samples (399 cap), never a universe.

inputs:
  scans:     {"CC Ripper — 5d +20%": [ {ticker, last, rel_volume, name, ...}, ...], ...}
  thematic:  {"Neoclouds": ["CRWV", ...], ...}          (Notion Thematic Watchlists page sections)
  roster:    ["SNDK", "BE", ...]                        (Robinhood roster, canonical)
  positions: ["XOM", ...]                               (IBKR open STK positions)
  exclusion: {"names": ["ABC"], "patterns": ["2X","3X","Ultra","Bull","Bear","Inverse","Daily","YieldMax","Acquisition Corp","SPAC"]}
"""
import re

# Leverage / wrapper vocabulary. Matched on WORD BOUNDARIES only. The old test was an
# unanchored substring search, which excluded real momentum names before they ever
# reached a door check: RARE (Ultragenyx -> "Ultra"), ROLL (RBC Bearings -> "Bear"),
# DJCO (Daily Journal -> "Daily").
# Compound forms are enumerated on purpose: boundary matching means "Ultra" no longer
# matches inside "UltraShort", so every leverage compound has to be listed explicitly.
DEFAULT_PATTERNS = ["2X", "3X", "1.5X", "Ultra", "UltraPro", "UltraShort", "UltraProShort", "Short", "Bull", "Bear", "Inverse", "Daily", "YieldMax", "Option Income", "Acquisition Corp", "SPAC", "Blank Check"]
# A leverage word alone is not enough. The name must ALSO look like a fund or wrapper.
# "Daily Journal Corp" has the leverage word and no issuer token, so it survives.
ISSUER_TOKENS = ["ETF", "ETN", "Shares", "Trust", "Fund", "Direxion", "ProShares", "UltraPro", "YieldMax", "Acquisition Corp", "SPAC", "Blank Check"]
PUMP_PRICE, PUMP_RVOL = 10.0, 20.0  # C3: sub-$10 name on >20x volume = pump, not a theme


def _boundary_hit(name, tokens):
    """True if any token appears in `name` on a word boundary. Case-insensitive.

    \\b will not do: half these tokens start or end with a digit or a dot ("3X", "1.5X"),
    where \\b sits in the wrong place. Explicit alnum lookaround instead.
    """
    for t in tokens:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", name, re.IGNORECASE):
            return True
    return False


def is_fund_wrapper(name, patterns=None):
    """C1/C2/C4: leveraged, inverse, or single-stock wrapper. Needs a leverage word AND an issuer token."""
    if not name:
        return False
    return _boundary_hit(name, patterns or DEFAULT_PATTERNS) and _boundary_hit(name, ISSUER_TOKENS)


def merge_patterns(custom):
    """Notion patterns are ADDED to the built-in list, never a replacement.

    The Exclusion List page is a human category description, not a regex spec. It says
    "Ultra" and means the whole Ultra family. Boundary matching does not, so if the page's
    list replaced the defaults, "ProShares UltraPro QQQ" (TQQQ) would survive -- the page
    has no "UltraPro" entry. Union keeps the page editable in plain English and keeps the
    compound forms covered. Removing a built-in pattern is a code change, by design.
    """
    out = list(DEFAULT_PATTERNS)
    seen = {p.lower() for p in out}
    for p in custom or []:
        if p.lower() not in seen:
            out.append(p)
            seen.add(p.lower())
    return out


def build(scans, thematic, roster, positions, exclusion=None):
    exclusion = exclusion or {}
    pats = merge_patterns(exclusion.get("patterns"))
    named = {t.upper() for t in exclusion.get("names", [])}
    rows = {}

    def add(t, source, name=None, last=None, rvol=None, theme=None):
        t = t.upper().strip()
        r = rows.setdefault(t, {"ticker": t, "sources": [], "name": name, "last": last, "rel_volume": rvol, "theme": theme, "excluded": False, "exclusion_reason": None})
        if source not in r["sources"]:
            r["sources"].append(source)
        r["name"] = r["name"] or name
        r["last"] = r["last"] if r["last"] is not None else last
        r["rel_volume"] = r["rel_volume"] if r["rel_volume"] is not None else rvol
        r["theme"] = r["theme"] or theme

    for scan_name, results in (scans or {}).items():
        for x in results:
            add(x["ticker"], f"scan:{scan_name}", x.get("name"), x.get("last"), x.get("rel_volume"))
    for theme, tickers in (thematic or {}).items():
        for t in tickers:
            add(t, "thematic", theme=theme)
    for t in roster or []:
        add(t, "roster")
    for t in positions or []:
        add(t, "position")

    for r in rows.values():
        if r["ticker"] in named:
            r["excluded"], r["exclusion_reason"] = True, "named exclusion"
        elif is_fund_wrapper(r["name"] or "", pats):
            r["excluded"], r["exclusion_reason"] = True, "C1/C2/C4 fund-name pattern"
        elif r["last"] is not None and r["rel_volume"] is not None and r["last"] < PUMP_PRICE and r["rel_volume"] > PUMP_RVOL:
            r["excluded"], r["exclusion_reason"] = True, f"C3 sub-${PUMP_PRICE:.0f} pump (rvol {r['rel_volume']:.0f}x)"
        # positions and roster are never excluded from monitoring, only from staging
        if r["excluded"] and ("position" in r["sources"] or "roster" in r["sources"]):
            r["excluded"], r["exclusion_reason"] = False, f"held/roster overrides: {r['exclusion_reason']}"
    return sorted(rows.values(), key=lambda r: r["ticker"])


def clusters(rows, min_names=3):
    """Theme clusters with 3+ names surfaced by a scan today = priority tag (tandem rule)."""
    by = {}
    for r in rows:
        if r["theme"] and any(s.startswith("scan:") for s in r["sources"]) and not r["excluded"]:
            by.setdefault(r["theme"], []).append(r["ticker"])
    return {k: v for k, v in by.items() if len(v) >= min_names}
