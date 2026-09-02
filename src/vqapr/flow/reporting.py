"""Read back what a finished run recorded, for the fields a surface renders.

**Moved out of `cli/run.py` by record `114`.** These take `SimulationResult`, a `flow` type, so
they live in `flow/` -- the lesson record `113` paid for when `evidence/records.py` imported three
`flow` modules and inverted the layers.

`tables_declared` and the `store:` spec block left with record `139`: the run spec file is gone,
and the half of that field that read `store.tables` described a publication nothing performed.
What a strategy recorded is in its `strategy.json` `tables` block.
"""

from __future__ import annotations

from collections.abc import Mapping

FRAMEWORK_TABLES = ("vqapr.account", "vqapr.fill", "vqapr.weight")
"""The three tables every strategy records, which nobody declares and which are not news."""


FILL_TABLE = "vqapr.fill"


def recorded(result: object) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    """Every row this run recorded, read from where a `SimulationResult` actually holds them.

    `SimulationResult` has two fields, `occurrences` and `final_state`; the rows are on the
    latter. A test double that does not have the real object's shape proves the code works
    against the double (`docs/issues/024`).
    """
    return getattr(getattr(result, "final_state", None), "recorder_rows", None) or {}
