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
from vqapr.public import register_compliance
from vqapr.extension.conformance import STAGE, conformance

GOOD_RULE = """
from vqapr.public import Compliance

class Limit(Compliance):
    @property
    def compliance_id(self):
        return "limit"

    def inputs(self):
        return {}

    def observe(self, call, account):
        return None
"""

STALE_OBSERVE = GOOD_RULE.replace(
    "def observe(self, call, account):",
    "def observe(self, account):",
)
"""A rule written against an older observing contract.

This is not hypothetical: three fixtures in this repository were written this way and registered
without complaint, because loading only constructs the object. They would have failed at the first
monitoring occurrence.
"""


def _ref(root: Path, source: str, *, name: str = "limit") -> ComponentRef:
    path = root / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return ComponentRef.of(
        name,
        ComponentKind.COMPLIANCE,
        path,
        "Limit",
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.COMPLIANCE, object_name="Limit"
        ),
    )


def test_a_conforming_component_passes(tmp_path: Path) -> None:
    assert conformance(_ref(tmp_path, GOOD_RULE)).ok


def test_a_stale_callback_signature_is_caught_though_it_constructs(tmp_path: Path) -> None:
    """The gap between "loads" and "conforms", in one component.

    The object builds and implements `Compliance`, so every load-time check passes. Flow calls
    `evaluate(window, account, marks, bounds)` positionally, and this class cannot receive it.
    """
    diagnosis = conformance(_ref(tmp_path, STALE_OBSERVE))

    assert not diagnosis.ok
    failure = diagnosis.failures[0]
    assert failure.code == "component.signature_invalid"
    assert "observe() must accept 3 positional arguments" in failure.requirement


def test_a_renamed_parameter_passes_because_flow_calls_positionally(tmp_path: Path) -> None:
    """Spelling is not a contract. Arity is.

    Flow calls `observe(call, account)` positionally, so a component that names them
    `c` and `book` receives exactly the same call. Failing it would punish a legal rename and
    teach that the contract is about words rather than the shape of the call.
    """
    source = GOOD_RULE.replace(
        "def observe(self, call, account):", "def observe(self, c, book):"
    )

    assert conformance(_ref(tmp_path, source)).ok


def test_a_star_args_component_passes_and_a_short_one_does_not(tmp_path: Path) -> None:
    """`*args` can absorb the call; a method one parameter short cannot."""
    absorbing = GOOD_RULE.replace(
        "def observe(self, call, account):", "def observe(self, *args):"
    )
    assert conformance(_ref(tmp_path, absorbing)).ok

    short = GOOD_RULE.replace(
        "def observe(self, call, account):",
        "def observe(self, call):",
    )
    assert not conformance(_ref(tmp_path, short)).ok


def test_an_optional_extra_parameter_passes(tmp_path: Path) -> None:
    """A default-valued extra is not a break: Flow's call still lands."""
    source = GOOD_RULE.replace(
        "def observe(self, call, account):",
        "def observe(self, call, account, scale=1):",
    )

    assert conformance(_ref(tmp_path, source)).ok


def test_a_missing_contract_method_is_named(tmp_path: Path) -> None:
    source = GOOD_RULE.replace("def observe(self, call, account):", "def unused(self):")

    diagnosis = conformance(_ref(tmp_path, source))

    assert not diagnosis.ok
    # Abstract enforcement refuses instantiation first; either way it is refused before a run,
    # which is the contract. What must never happen is registering and failing mid-run.
    assert diagnosis.failures


def test_a_load_failure_rides_through_with_its_own_verdict(tmp_path: Path) -> None:
    """Conformance is a superset of the load, so it does not restate the load's findings."""
    diagnosis = conformance(_ref(tmp_path, "class Limit:\n    pass\n"))

    assert not diagnosis.ok
    # The typed load verdict is preserved verbatim rather than flattened into a generic message.
    assert diagnosis.failures[0].code == "component.wrong_type"


def test_the_shipped_profiles_are_the_first_two_implementations_to_pass(tmp_path: Path) -> None:
    """Canon §10.3: *"`academic`과 `krx`가 이 suite를 통과하는 첫 두 구현이다."*

    They enter as a `ComponentRef` like any user component, and there is no branch that can tell
    them apart from one.
    """
    for name, base in (("academic", "AcademicExchange"), ("krx", "KrxExchange")):
        path = tmp_path / f"{name}_venue.py"
        path.write_text(
            "from decimal import Decimal\n"
            f"from vqapr.public import {base}, ListingAccess, TradeRule\n"
            f"class Venue({base}):\n"
            "    def __init__(self):\n"
            "        super().__init__({'A': TradeRule('A', Decimal('1'), Decimal('1'), False,\n"
            "            ListingAccess.SIGNED)})\n",
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
    """Canon §10.2: `pytest` and `vqapr register` call the same conformance code.

    One implementation with two entrances means a component cannot pass one and fail another.
    """
    path = tmp_path / "stale.py"
    path.write_text(STALE_OBSERVE, encoding="utf-8")

    # Registered as `limit`, which is what this `Limit` answers to. The stale `evaluate` signature
    # is the one defect under test; registering it under `stale` would add an id mismatch that
    # `load_compliance` refuses first, and this test is about which suite runs, not about ids.
    with pytest.raises(Exception) as failure:
        register_compliance(tmp_path, "limit", path, "Limit")

    error = failure.value
    assert getattr(error, "stage", None) == STAGE, "registration must report the conformance stage"
    assert error.failures[0].code == "component.signature_invalid"


def test_the_suite_takes_a_component_ref_and_nothing_else() -> None:
    """Canon §10.3: the suite's input is a `ComponentRef`, for shipped and user components alike."""
    with pytest.raises(TypeError, match="must be a ComponentRef"):
        conformance(AcademicExchange({}))  # type: ignore[arg-type]
