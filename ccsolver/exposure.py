"""Portfolio exposure vs the 150% gross / 130% net-long caps, ex-SPY, IBKR STK only.

Moved VERBATIM from the noon-scan / Last-Call / Desk Refresh trigger prompts
(Ray, Sep 7, 2026 calc spec). Do not change the math without a Desk Room ruling."""
import json
import sys

GROSS_CAP, NET_CAP = 150.0, 130.0


def exposure(positions, net_liq):
    """positions: IBKR get_account_positions JSON["positions"]. Returns dict + the exact banner line."""
    rows = [p for p in positions if p.get("asset_class") == "STK" and p["contract_description"] != "SPY"]
    gross = sum(abs(p["market_value"]) for p in rows)
    net = sum(p["market_value"] for p in rows)
    nl = float(net_liq)
    g, n = 100 * gross / nl, 100 * net / nl
    line = f"Exposure (ex-SPY): gross {g:.0f}% / net {n:.0f}% (caps {GROSS_CAP:.0f} / {NET_CAP:.0f})"
    flags = []
    if g > GROSS_CAP:
        flags.append(f"GROSS OVER by ${gross - GROSS_CAP / 100 * nl:,.0f} ({g - GROSS_CAP:.0f} pts)")
    if n > NET_CAP:
        flags.append(f"NET OVER by ${net - NET_CAP / 100 * nl:,.0f} ({n - NET_CAP:.0f} pts)")
    return {
        "gross_pct": round(g, 1),
        "net_pct": round(n, 1),
        "breach": bool(flags),
        "flags": flags,
        "line": line + (" -- BREACH: " + "; ".join(flags) if flags else ""),
    }


if __name__ == "__main__":  # usage: python -m ccsolver.exposure '<positions JSON>' <net_liq>
    print(exposure(json.loads(sys.argv[1])["positions"], sys.argv[2])["line"])
