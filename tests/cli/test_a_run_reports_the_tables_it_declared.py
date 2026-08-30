"""`run.complete` names the tables the run declared, and the counter says what it counts.

`docs/issues/024`. Two halves.

**`tables_declared: []`** for a run that declared `ff3.formation` and wrote 42 rows to it. The empty
list was not wrong about what it measured -- it measured `store.tables`, the run spec's `store:`
section, while the journey declared through `StrategyModel.diagnostics()` on the component. Two
surfaces; the envelope read one.

**The counter nobody could interpret.** 7 for `ff3.formation` and `vqapr.weight`, 85 for
`vqapr.account`, and 1 for `vqapr.fill` -- *"which is the one that defeats any reading I could
construct, because 7 rebalances produced 13,012 fills across 7 distinct instants"*. It counted
distinct `event_time`, fills carried none (`docs/issues/022`), and it was called `formations`, which
is portfolio vocabulary for a counter applied to every table.
"""

from __future__ import annotations

from types import SimpleNamespace

from vqapr.cli.run import _FRAMEWORK_TABLES, _tables_declared
from vqapr.flow.store_spec import StoreSpec


def _result(*table_ids: str) -> SimpleNamespace:
    """A stand-in carrying only what `_tables_declared` reads: the recorded table ids."""
    return SimpleNamespace(tables={table_id: () for table_id in table_ids})


def test_a_table_declared_on_the_component_is_reported() -> None:
    """The journey's own case: declared via `diagnostics()`, written, and reported as nothing."""
    declared = _tables_declared(
        StoreSpec(root=None, tables=()),
        _result("vqapr.account", "vqapr.fill", "vqapr.weight", "ff3.formation"),
    )

    assert declared == ["ff3.formation"], (
        "a run that declared and wrote ff3.formation still reports nothing for it"
    )


def test_a_table_declared_in_the_spec_is_still_reported() -> None:
    """The surface that already worked must keep working."""
    declared = _tables_declared(
        StoreSpec(root=None, tables=("spec.declared",)),
        _result("vqapr.account"),
    )

    assert declared == ["spec.declared"]


def test_both_surfaces_are_merged_without_duplication() -> None:
    """A table declared in the spec AND formed by the model is one table, not two."""
    declared = _tables_declared(
        StoreSpec(root=None, tables=("shared", "spec.only")),
        _result("shared", "model.only", "vqapr.fill"),
    )

    assert declared == ["model.only", "shared", "spec.only"]


def test_the_three_framework_tables_are_not_reported_as_declared() -> None:
    """`tables_declared` answers what THIS run declared, not what every run records.

    `vqapr.account`, `vqapr.fill` and `vqapr.weight` are always present, so restating them would
    make the field useless for the comparison it exists to serve.
    """
    declared = _tables_declared(StoreSpec(root=None, tables=()), _result(*_FRAMEWORK_TABLES))

    assert declared == []


def test_the_counter_is_named_for_what_it_counts() -> None:
    """`formations` -> `instants`.

    The counter is applied to every table, including `vqapr.fill`, where a formation is not a
    thing that happens. Its expression counts distinct `event_time`, and the name now says so.
    """
    from vqapr import public

    source = public.__dict__["__file__"]
    text = open(source, encoding="utf-8").read()

    assert '"instants": len({str(row.get("event_time")) for row in rows})' in text
    assert '"formations":' not in text, "the old name is still emitted somewhere"
