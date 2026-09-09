"""Compliance: the observer on the market clock (design §7.2).

A `Compliance` rule subscribes, remembers, observes the committed and marked account right after
VALUATION at every market-clock instant, and leaves a finding on the notice board. It changes
nothing. `evaluation.py` runs a loaded rule set and stamps what each said; `builtin/` ships two.
"""
