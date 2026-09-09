"""Running a run: its clocks, and the handlers the wiring table puts on them.

Until record `214` this was two packages, `flow/strategy/` and `flow/datamodel/`, split by the
kind of run. The two-clocks campaign (design §3-4) made the kinds the same thing seen twice --
one part on its own clock, tools on the market clock -- so the split by kind became a split of
the same walk, and the modules here are arranged by clock instead:

    loop.py          StrategyEventLoop (two clocks) · DataModelEventLoop (one clock)
    callback.py      strategy clock: StrategyModel.decide
    compute.py       strategy clock: DataModel.compute
    accrual.py       market clock, 1st: a place (design §7.3)
    execution.py     market clock, 2nd: the pending intent fills, the account appends
    valuation.py     market clock, 3rd: the framework marks the committed book
    compliance.py    market clock, 4th: the declared rules observe it
    context.py       what a strategy run's handlers share (state, failure envelope, timing)
    output.py        the warehouse door a datamodel run writes through

No re-export: import the module (record `192`'s convention, as `flow/engine/`).
"""
