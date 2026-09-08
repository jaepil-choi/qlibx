"""The substrate a run's phases share: the event loop, the lineage, and the accepted state.

`flow/` held two altitudes in one directory until record `197`. Its root has the assembly --
`orchestration.py` builds a run and drives it, `freeze.py` turns what it produced into a record --
and its subpackages have the phases: `declaration/` for what preflight makes of a run,
`strategy/` and `datamodel/` for the two loops. But the three modules here sat in the root beside
the assembly while the phases imported them fifteen times, so the root was simultaneously above
its children and below them.

Nothing here knows what a strategy is. `loop.py` merges a static schedule with the due events a
callback mints, `artifacts.py` declares the immutable evidence a phase emits, and `run_state.py`
holds what a callback accepted until the Account publishes it. All three depend only on `domain/`,
`account/` and the authoring contract -- which is what makes them a floor rather than a peer.

No re-export: import the module. The convention is record `192`'s -- an `__init__` carries the
package's argument, and a door is for a published import path or for a package deliberately
hiding its layout, and this is neither.
"""
