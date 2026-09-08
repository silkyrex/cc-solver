"""cc-solver: deterministic rules-as-code for Ray's Consistency Capital desk.

Written by: Claude (Fable 5.1), 2026-09-08. Spec: Notion Desk Post
"2026-09-08 Claude Open Build 2 handoff — solver repo spec for Grok".

Contract: the agent harness makes every MCP call (Robinhood, IBKR, Notion) and
dumps the results as JSON into an inputs directory. This package is pure
functions over that JSON and prints JSON verdicts. It never calls a broker.
"""
__version__ = "0.1.0"
