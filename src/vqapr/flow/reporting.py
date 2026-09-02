"""Read back what a finished run recorded, for the fields a surface renders.

**Moved out of `cli/run.py` by record `114`.** These take `SimulationResult` and `StoreSpec`, which
are `flow` types, so they live in `flow/` -- the lesson record `113` paid for when
`evidence/records.py` imported three `flow` modules and inverted the layers.
"""

from __future__ import annotations

from collections.abc import Mapping

from vqapr.flow.store_spec import StoreSpec

FRAMEWORK_TABLES = ("vqapr.account", "vqapr.fill", "vqapr.weight")
"""The three tables every run records, which nobody declares and which are not news.

Excluded from `tables_declared` so the field answers *what did THIS run declare* rather than
restating a constant. A reader comparing two runs learns nothing from three ids that are always
present.
"""


FILL_TABLE = "vqapr.fill"


def recorded(result: object) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    """Every row this run recorded, read from where a `SimulationResult` actually holds them.

    One reader for both envelope fields below, because they had drifted apart. `_tables_declared`
    read `result.tables`, and **`SimulationResult` has no such attribute** -- its two fields are
    `occurrences` and `final_state`. The unit test that verified it passed a stand-in carrying
    `.tables`, so the component-declared half of `docs/issues/024` reported nothing in production
    while its test stayed green. A test double that does not have the real object's shape proves
    the code works against the double.
    """
    return getattr(getattr(result, "final_state", None), "recorder_rows", None) or {}


def tables_declared(store: StoreSpec, result: object) -> list[str]:
    """Every table this run declared, from both surfaces that can declare one.

    `tables_declared` read `store.tables` alone and reported `[]` for a run that declared
    `ff3.formation` and wrote 42 rows to it (`docs/issues/024`). The empty list was not wrong about
    what it measured -- it was measuring one of two surfaces:

    * `store.tables`, declared in the run spec's `store:` section; and
    * `StrategyModel.tables()`, declared on the component itself.

    The journey declared through the second and read the first. So the field is kept and taught to
    report both, rather than removed: a reader asking what a run declared has nowhere else to look,
    and `show run`'s `tables` answers a different question -- what was RECORDED, which is empty for
    a table declared but never formed.

    This does not re-open what the comment at the call site closed. That refusal is about a
    `publishes`-shaped claim: asserting a DATASET exists when `list datasets` shows none. Naming a
    declared diagnostic table is not that claim, and nothing here says a dataset was registered.
    """
    declared = set(store.tables)
    # What the model declared and formed. A table declared on the component but never written is
    # invisible here, which is the honest limit of reading it back from the result: the run record
    # holds what was recorded, not the component's declaration list.
    declared.update(
        table_id for table_id in recorded(result) if table_id not in FRAMEWORK_TABLES
    )
    return sorted(declared)
