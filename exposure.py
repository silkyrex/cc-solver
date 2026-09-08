import json, sys
pos = json.loads(sys.argv[1])["positions"]
nl = float(sys.argv[2])
rows = [p for p in pos if p.get("asset_class") == "STK" and p["contract_description"] != "SPY"]
gross = sum(abs(p["market_value"]) for p in rows)
net = sum(p["market_value"] for p in rows)
g, n = 100 * gross / nl, 100 * net / nl
G, N = 150.0, 130.0
line = f"Exposure (ex-SPY): gross {g:.0f}% / net {n:.0f}% (caps {G:.0f} / {N:.0f})"
flags = []
if g > G: flags.append(f"GROSS OVER by ${gross - G / 100 * nl:,.0f} ({g - G:.0f} pts)")
if n > N: flags.append(f"NET OVER by ${net - N / 100 * nl:,.0f} ({n - N:.0f} pts)")
print(line + (" -- BREACH: " + "; ".join(flags) if flags else ""))
