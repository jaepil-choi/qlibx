"""Writing to an undeclared table says how to declare it.

`docs/issues/archive/019`. The refusal named the breach -- *"decide() emitted undeclared diagnostic tables:
['ff3.formation']"* -- and not the repair. The skill's *"Every run records three tables, plus any
the model formed"* reads as *form one and it is recorded*, so an author who had not declared one
learned the gate existed only when it fired, and it fires mid-simulation.

The gate is the recorder's now (record `132`): a Strategy writes rows through `self.recorder`
into the tables `tables()` declared, and the adapter that once checked a returned `diagnostics`
mapping is gone. The property is unchanged -- the refusal names what was written, the method that
declares it, and what is currently declared.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vqapr.component.strategy.recorder import InvocationRecorder, TableSpec

_NOW = datetime(2026, 1, 5, tzinfo=UTC)


def _recorder(*tables: TableSpec) -> InvocationRecorder:
    return InvocationRecorder(
        tables, run_id="run", producer_id="alpha", stage="strategy_callback", event_time=_NOW
    )


def test_the_refusal_names_the_method_that_declares_the_table() -> None:
    """The `fix` half: an author must be told where to declare it, not just that they did not."""
    with pytest.raises(KeyError) as raised:
        _recorder().append("ff3.formation", {"bucket": 1})

    message = str(raised.value)

    assert "ff3.formation" in message, "the refusal no longer names what was written"
    assert "StrategyModel.tables()" in message, (
        "the refusal still states the breach without naming the method that repairs it"
    )


def test_the_refusal_says_what_is_currently_declared() -> None:
    """Naming the declared set turns a guess into a comparison.

    An author who declared `ff3.formations` and wrote `ff3.formation` sees both spellings side by
    side; without it they are left checking their own file for a typo the refusal already knows.
    """
    declared = TableSpec("ff3.formations", ("bucket",))

    with pytest.raises(KeyError) as raised:
        _recorder(declared).append("ff3.formation", {"bucket": 1})

    message = str(raised.value)
    assert "ff3.formation" in message
    assert "ff3.formations" in message, "the refusal does not say what IS declared"


def test_declaring_nothing_reads_as_nothing_rather_than_an_empty_bracket() -> None:
    """The common case is having declared none at all, and it should read that way."""
    with pytest.raises(KeyError) as raised:
        _recorder().append("anything", {"bucket": 1})

    assert "nothing" in str(raised.value)


def test_a_declared_table_is_accepted() -> None:
    """The other half: declaring it must actually work, or this is a wall rather than a gate."""
    recorder = _recorder(TableSpec("ff3.formation", ("bucket",)))

    recorder.append("ff3.formation", {"bucket": 1})

    assert len(recorder.staged_rows()["ff3.formation"]) == 1
