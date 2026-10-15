"""Backtest harness. Replays the production doors in `ccsolver` forward over real bars.

Deliberately separate from the `ccsolver` package: nothing in the live decision path may
import from here, and nothing here may change a rule. A backtest that can edit the rules
it is measuring measures itself.
"""
