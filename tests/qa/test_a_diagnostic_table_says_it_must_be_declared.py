"""Emitting an undeclared diagnostic table says how to declare it.

`docs/issues/019`. The refusal named the breach -- *"decide() emitted undeclared diagnostic tables:
['ff3.formation']"* -- and not the repair. Two sentences had led the author to expect none was
needed: the skill's *"Every run records three tables, plus any the model formed"*, which reads as
*form one and it is recorded*, and `StrategyResult`'s own docstring, which introduces `diagnostics`
as a convenience that saves typing rather than as a declaration you must override.

It cost a whole run to learn, because the refusal arrives mid-simulation.
"""

from __future__ import annotations

import pytest

from vqapr._internal.models.agent_first import _validated_diagnostics
from vqapr.authoring import DiagnosticTable


def test_the_refusal_names_the_method_that_declares_the_table() -> None:
    """The `fix` half: an author must be told where to declare it, not just that they did not."""
    with pytest.raises(ValueError) as raised:
        _validated_diagnostics({"ff3.formation": ()}, {})

    message = str(raised.value)

    assert "ff3.formation" in message, "the refusal no longer names what was emitted"
    assert "StrategyModel.diagnostics()" in message, (
        "the refusal still states the breach without naming the method that repairs it"
    )


def test_the_refusal_says_what_is_currently_declared() -> None:
    """Naming the declared set turns a guess into a comparison.

    An author who declared `ff3.formations` and emitted `ff3.formation` sees both spellings side by
    side; without it they are left checking their own file for a typo the refusal already knows.
    """
    declared = DiagnosticTable(table_id="ff3.formations", semantic_fields=("bucket",))

    with pytest.raises(ValueError) as raised:
        _validated_diagnostics(
            {"ff3.formation": ()}, {"ff3.formations": declared}
        )

    message = str(raised.value)
    assert "ff3.formation" in message
    assert "ff3.formations" in message, "the refusal does not say what IS declared"


def test_declaring_nothing_reads_as_nothing_rather_than_an_empty_bracket() -> None:
    """The common case is having declared none at all, and it should read that way."""
    with pytest.raises(ValueError) as raised:
        _validated_diagnostics({"anything": ()}, {})

    assert "nothing" in str(raised.value)


def test_a_declared_table_is_accepted() -> None:
    """The other half: declaring it must actually work, or this is a wall rather than a gate."""
    declared = DiagnosticTable(table_id="ff3.formation", semantic_fields=("bucket",))

    validated = _validated_diagnostics(
        {"ff3.formation": ({"bucket": "SH"},)},
        {"ff3.formation": declared},
    )

    assert set(validated) == {"ff3.formation"}
