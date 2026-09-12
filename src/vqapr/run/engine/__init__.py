"""The loop: one walk over two clocks, and the stages the wiring table puts on them.

    loop.py       RunLoop, the one walk · MarketClock · strategy_loop / datamodel_loop
    events.py     what the walk sorts: a scheduled event, a market instant
    context.py    what a run's stages share (state, failure envelope, timing)
    run_state.py  the accepted state (account, memory, pending intent) until the Account publishes
    calls.py      the Call implementations a component is handed
    evidence.py   the immutable evidence a stage leaves
    failure.py    SimulationFailure and its kinds
    output.py     the warehouse door a DataModel run writes through
    stages/       one module per row of the wiring table

`events.py` is not folded into `loop.py`: the context carries a `MarketEvent` and the loop imports
the context, so one module would be a cycle. No re-export: import the module (record `192`).
"""
