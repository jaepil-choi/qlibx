"""The suite that judges components is itself judged here.

Canon §10.3: *"우리 테스트가 같은 빌더를 쓰므로 픽스처가 dogfooding된다. `tests/testing/`이 suite
자체를 검증한다."* — the shipped suite is the thing users depend on, so it needs the same proof it
demands of them.

The load door already refuses a component that cannot be constructed. What is pinned here is the
part loading cannot see: a component that constructs perfectly and still cannot be called, because
the methods Flow will invoke are not the methods it defined.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.exchange.venue import AcademicExchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.public import register_constraint
from vqapr.testing.conformance import STAGE, conformance

GOOD_CONSTRAINT = """
from vqapr.public import Constraint, ConstraintBounds

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

STALE_EVALUATE = GOOD_CONSTRAINT.replace(
    "def evaluate(self, window, account, marks, bounds):",
    "def evaluate(self, account, marks):",
)
"""A constraint written against an older `evaluate` contract.

This is not hypothetical: three fixtures in this repository were written this way and registered
without complaint, because loading only constructs the object. They would have failed at the first
monitoring occurrence.
"""


def _ref(root: Path, source: str, *, name: str = "limit") -> ComponentRef:
    path = root / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return ComponentRef.of(
        name,
        ComponentKind.CONSTRAINT,
        path,
        "Limit",
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.CONSTRAINT, object_name="Limit"
        ),
    )


def test_a_conforming_component_passes(tmp_path: Path) -> None:
    assert conformance(_ref(tmp_path, GOOD_CONSTRAINT)).ok


def test_a_stale_callback_signature_is_caught_though_it_constructs(tmp_path: Path) -> None:
    """The gap between "loads" and "conforms", in one component.

    The object builds and implements `Constraint`, so every load-time check passes. Flow calls
    `evaluate(window, account, marks, bounds)` positionally, and this class cannot receive it.
    """
    diagnosis = conformance(_ref(tmp_path, STALE_EVALUATE))

    assert not diagnosis.ok
    failure = diagnosis.failures[0]
    assert failure.code == f"{STAGE}.signature_invalid"
    assert "evaluate() must declare parameters" in failure.requirement
    assert "'window'" in failure.requirement and "'bounds'" in failure.requirement


def test_a_missing_contract_method_is_named(tmp_path: Path) -> None:
    source = GOOD_CONSTRAINT.replace("def project(self, window, instruments):", "def unused(self):")

    diagnosis = conformance(_ref(tmp_path, source))

    assert not diagnosis.ok
    # Abstract enforcement refuses instantiation first; either way it is refused before a run,
    # which is the contract. What must never happen is registering and failing mid-run.
    assert diagnosis.failures


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    """An agent fixes its component once, not once per run."""
    source = GOOD_CONSTRAINT.replace(
        "def validate_intended(self, intent, bounds):", "def validate_intended(self, intent):"
    ).replace("def evaluate(self, window, account, marks, bounds):", "def evaluate(self, account):")

    diagnosis = conformance(_ref(tmp_path, source))

    codes = [failure.code for failure in diagnosis.failures]
    assert len(codes) == 2, codes
    assert set(codes) == {f"{STAGE}.signature_invalid"}


def test_a_load_failure_rides_through_with_its_own_verdict(tmp_path: Path) -> None:
    """Conformance is a superset of the load, so it does not restate the load's findings."""
    diagnosis = conformance(_ref(tmp_path, "class Limit:\n    pass\n"))

    assert not diagnosis.ok
    # The typed load verdict is preserved verbatim rather than flattened into a generic message.
    assert diagnosis.failures[0].code.startswith("component.load.")


def test_the_shipped_profiles_are_the_first_two_implementations_to_pass(tmp_path: Path) -> None:
    """Canon §10.3: *"`academic`과 `krx`가 이 suite를 통과하는 첫 두 구현이다."*

    They enter as a `ComponentRef` like any user component, and there is no branch that can tell
    them apart from one.
    """
    for name, base in (("academic", "AcademicExchange"), ("krx", "KrxExchange")):
        path = tmp_path / f"{name}_venue.py"
        path.write_text(
            "from decimal import Decimal\n"
            f"from vqapr.public import {base}, ListingRule, Side\n"
            f"class Venue({base}):\n"
            "    def __init__(self):\n"
            "        super().__init__({'A': ListingRule('A', Decimal('1'), Decimal('1'), False,\n"
            "            frozenset((Side.BUY, Side.SELL)))})\n",
            encoding="utf-8",
        )
        ref = ComponentRef.of(
            name,
            ComponentKind.EXCHANGE,
            path,
            "Venue",
            fingerprint=fingerprint_component(
                path, kind=ComponentKind.EXCHANGE, object_name="Venue"
            ),
        )

        assert conformance(ref).ok, f"{name} must pass its own suite"


def test_registration_calls_this_suite_rather_than_its_own_checks(tmp_path: Path) -> None:
    """Canon §10.2: `pytest`, `vqapr check` and `vqapr register` call the same conformance code.

    One implementation with three entrances means a component cannot pass one and fail another.
    """
    path = tmp_path / "stale.py"
    path.write_text(STALE_EVALUATE, encoding="utf-8")

    with pytest.raises(Exception) as failure:
        register_constraint(tmp_path, "stale", path, "Limit")

    error = failure.value
    assert getattr(error, "stage", None) == STAGE, "registration must report the conformance stage"
    assert error.failures[0].code == f"{STAGE}.signature_invalid"


def test_the_suite_takes_a_component_ref_and_nothing_else() -> None:
    """Canon §10.3: the suite's input is a `ComponentRef`, for shipped and user components alike."""
    with pytest.raises(TypeError, match="must be a ComponentRef"):
        conformance(AcademicExchange({}))  # type: ignore[arg-type]
