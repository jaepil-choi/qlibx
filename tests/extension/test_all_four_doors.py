"""Every extension point enters through a door that proves the component loads.

Canon 10.2: the four extension points are named the same way, checked the same way, and
registered the same way. Before this, only StrategyModel and DataModel had that door. Exchange and
Constraint were assembled by hand from `ComponentRef.of` + `fingerprint_component` +
`register_component`, which records a reference without ever constructing the object.

That difference is not ergonomic. A hand-assembled reference to a broken Exchange registers
cleanly and fails in the middle of a run, where the reported stage names the run rather than the
registration that caused it. These tests pin that all four doors refuse before writing anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import render
from vqapr.public import (
    Workspace,
    register_constraint,
    register_data_model,
    register_exchange,
    register_strategy_model,
)


def _is_absent(project: Path, component_id: str) -> bool:
    """Nothing was persisted: either no workspace at all, or no such component in it.

    A refused registration writes nothing, so the workspace may legitimately not exist yet.
    """
    try:
        workspace = Workspace.open(project)
    except VqaprError:
        return True
    try:
        workspace.component(component_id)
    except (KeyError, VqaprError):
        return True
    return False


GOOD_CONSTRAINT = """
from vqapr.public import Constraint, ConstraintBounds, ConstraintFinding

class Limit(Constraint):
    @property
    def constraint_id(self):
        return "limit"

    def requirements(self):
        return ()

    def project(self, window, instruments):
        return ConstraintBounds({}, {})

    def validate_intended(self, intent, bounds):
        return None

    def evaluate(self, window, account, marks, bounds):
        return None
"""

GOOD_EXCHANGE = """
from decimal import Decimal
from vqapr.public import AcademicExchange, ListingRule, Side

class MyVenue(AcademicExchange):
    def __init__(self):
        super().__init__(
            {"A": ListingRule("A", Decimal("1"), Decimal("1"), False,
                              frozenset({Side.BUY, Side.SELL}))}
        )
"""

NOT_A_CONSTRAINT = '''
class Limit:
    """Looks plausible, implements nothing."""
'''

EXCHANGE_THAT_REPLACES_EXECUTE = """
from decimal import Decimal
from vqapr.public import AcademicExchange, ListingRule, Side

class MyVenue(AcademicExchange):
    def __init__(self):
        super().__init__(
            {"A": ListingRule("A", Decimal("1"), Decimal("1"), False,
                              frozenset({Side.BUY, Side.SELL}))}
        )

    def execute(self, orders, account, snapshot):
        # Replacing matching semantics makes the realism claim unverifiable.
        return None
"""

BROKEN_SYNTAX = "class Limit(:\n"


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_constraint_registers_through_its_own_door(tmp_path: Path) -> None:
    path = _write(tmp_path, "limit.py", GOOD_CONSTRAINT)

    ref = register_constraint(tmp_path, "limit", path, "Limit")

    assert ref.component_id == "limit"
    assert ref.fingerprint
    assert Workspace.open(tmp_path).component("limit") == ref


def test_an_exchange_registers_through_its_own_door(tmp_path: Path) -> None:
    path = _write(tmp_path, "venue.py", GOOD_EXCHANGE)

    ref = register_exchange(tmp_path, "venue", path, "MyVenue")

    assert ref.component_id == "venue"
    assert Workspace.open(tmp_path).component("venue") == ref


def test_a_constraint_that_implements_nothing_is_refused_before_it_is_stored(
    tmp_path: Path,
) -> None:
    """The whole point: refusal happens at registration, and nothing is written."""
    path = _write(tmp_path, "fake.py", NOT_A_CONSTRAINT)

    with pytest.raises(VqaprError):
        register_constraint(tmp_path, "fake", path, "Limit")

    assert _is_absent(tmp_path, "fake")


def test_an_exchange_that_replaces_execute_is_refused(tmp_path: Path) -> None:
    """A subclass may add listings and costs. It may not silently become a different venue."""
    path = _write(tmp_path, "rogue.py", EXCHANGE_THAT_REPLACES_EXECUTE)

    with pytest.raises(VqaprError):
        register_exchange(tmp_path, "rogue", path, "MyVenue")

    assert _is_absent(tmp_path, "rogue")


@pytest.mark.parametrize(
    "register,object_name",
    [
        (register_constraint, "Limit"),
        (register_exchange, "MyVenue"),
        (register_strategy_model, "Alpha"),
        (register_data_model, "Feature"),
    ],
)
def test_every_door_refuses_a_source_that_cannot_be_imported(
    tmp_path: Path, register, object_name: str
) -> None:
    """All four behave the same way, which is the property canon 10.2 asks for."""
    path = _write(tmp_path, f"broken_{object_name}.py", BROKEN_SYNTAX)

    with pytest.raises(VqaprError):
        register(tmp_path, "broken", path, object_name)

    assert _is_absent(tmp_path, "broken")


@pytest.mark.parametrize(
    "kind,register,object_name",
    [
        (ComponentKind.STRATEGY_MODEL, register_strategy_model, "MyAlpha"),
        (ComponentKind.DATA_MODEL, register_data_model, "MyAlpha"),
    ],
)
def test_the_scaffold_registers_as_written(tmp_path: Path, kind, register, object_name) -> None:
    """What `vqapr new` emits must pass the door it is emitted for.

    Canon 16 once asked for the opposite -- that a fresh template *fail* conformance so the user
    knew they were not done. That was withdrawn (`docs/issues/004`): conformance answers whether
    Flow can call a component, and a template that cannot be called teaches nothing on the first
    command a user types. The "not done yet" signal is the marked line in the source, not a
    manufactured failure. This test is what keeps the two from drifting apart again.
    """
    source = render(kind, "my-alpha", dataset_id="prices")
    path = _write(tmp_path, "my_alpha.py", source.replace("class MyAlpha", f"class {object_name}"))

    register(tmp_path, "my-alpha", path, object_name)

    assert not _is_absent(tmp_path, "my-alpha")
