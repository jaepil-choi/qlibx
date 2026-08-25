"""An authoring-protocol Constraint, executed by the retained engine.

`vqapr.authoring.Constraint` and the engine's own `Constraint` are disjoint protocols.
These tests pin the translation between them: the adapter wears the engine's surface, the
authored class keeps deciding, and a constraint still reads only what it declared.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from vqapr._internal.constraint_bridge import legacy_constraint_class
from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintFinding,
    DatasetInput,
    RowsLookback,
)


def _finding(passed: bool = True) -> ConstraintFinding:
    return ConstraintFinding(
        passed=passed,
        measured=Decimal(0),
        bound=Decimal("0.5"),
        excess=Decimal(0),
        details={},
    )


class _CapWeights(Constraint):
    """Declares no reads: bounds come from the universe alone."""

    def inputs(self):
        return {}

    def project(self, call):
        return ConstraintBounds(
            lower_weights={i: Decimal(0) for i in call.instruments},
            upper_weights={i: Decimal("0.5") for i in call.instruments},
        )

    def validate(self, decision, bounds):
        return _finding()

    def monitor(self, call, bounds):
        return _finding()


class _Rejecting(_CapWeights):
    def validate(self, decision, bounds):
        return _finding(passed=False)


class _WindowStub:
    evaluation_time = None

    def __init__(self, rows=()):
        self._rows = rows
        self.observed = []

    def observations(self, requirement):
        self.observed.append(requirement)

        class _Batch:
            rows = self._rows

        return _Batch()


def test_the_adapter_wears_the_engine_protocol():
    from vqapr.constraints.constraint import Constraint as EngineConstraint

    adapted = legacy_constraint_class(_CapWeights, name="cap-weights")
    assert issubclass(adapted, EngineConstraint)
    instance = adapted()
    assert instance.constraint_id == "cap-weights"


def test_the_authored_class_still_decides_the_bounds():
    adapted = legacy_constraint_class(_CapWeights, name="cap-weights")()
    bounds = adapted.project(_WindowStub(), ("A005930", "A000660"))

    assert bounds.upper_weights["A005930"] == Decimal("0.5")
    assert bounds.lower_weights["A000660"] == Decimal(0)
    # Bounds cover exactly the universe handed to the callback.
    assert sorted(bounds.lower_weights) == ["A000660", "A005930"]


def test_a_rejection_is_carried_through_unchanged():
    """The adapter must not soften a constraint's refusal."""
    from vqapr.authoring import Rebalance
    from vqapr.portfolio.budgets import Budget, PortfolioDirection

    budget = Budget(
        direction=PortfolioDirection.LONG_ONLY,
        cash_lower=Decimal(0),
        cash_upper=Decimal(1),
        target_lower=Decimal(0),
        target_upper=Decimal(1),
    )
    decision = Rebalance(
        target_weights={"A005930": Decimal("0.5")},
        cash_weight=Decimal("0.5"),
        budget=budget,
    )
    adapted = legacy_constraint_class(_Rejecting, name="rejecting")()
    bounds = ConstraintBounds(lower_weights={}, upper_weights={})
    finding = adapted.validate_intended(decision, bounds)
    assert finding.passed is False


def test_a_constraint_that_declares_no_reads_never_touches_the_window():
    window = _WindowStub()
    adapted = legacy_constraint_class(_CapWeights, name="cap-weights")()
    adapted.project(window, ("A005930",))
    assert window.observed == [], "a constraint with no declared aliases must not read"
    assert adapted.requirements() == ()


def test_a_declared_alias_becomes_an_engine_requirement():
    class _Reading(_CapWeights):
        def inputs(self):
            return {
                "prices": DatasetInput(
                    dataset_id="stock_daily", fields=("ret",), lookback=RowsLookback(rows=1)
                )
            }

    adapted = legacy_constraint_class(_Reading, name="reading")()
    requirements = adapted.requirements()
    assert len(requirements) == 1
    assert str(requirements[0].dataset_id) == "stock_daily"
    assert requirements[0].fields == ("ret",)


def test_reading_an_undeclared_alias_raises():
    from vqapr._internal.constraint_bridge import _ProjectionCall

    call = _ProjectionCall(reads={"prices": ()}, instruments=("A",))
    assert call.read("prices") == ()
    with pytest.raises(KeyError, match="was not declared in inputs"):
        call.read("never_declared")


def test_each_construction_builds_a_fresh_authored_instance():
    """No state accumulates across the run through this adapter."""
    constructions = []

    class _Counting(_CapWeights):
        def __init__(self):
            constructions.append(1)

    adapted = legacy_constraint_class(_Counting, name="counting")
    adapted()
    adapted()
    assert len(constructions) == 2


def test_a_non_authoring_class_is_refused():
    class _NotAConstraint:
        pass

    with pytest.raises(TypeError, match=r"subclass of vqapr\.authoring\.Constraint"):
        legacy_constraint_class(_NotAConstraint, name="nope")


def test_a_malformed_name_is_refused():
    with pytest.raises(ValueError, match="without whitespace"):
        legacy_constraint_class(_CapWeights, name="has whitespace")


def test_a_monitoring_constraint_receives_the_committed_valuation():
    """`evaluate` was handed the marks and dropped them.

    An authored `monitor` saw cash and quantities with `nav=None`, so any weight-based
    rule - which is most real constraints - could only return an honest non-judgement.
    show_005 had to abandon its cap-drift claim over exactly this.
    """
    from vqapr._internal.constraint_bridge import _marked_account

    class _Snapshot:
        cash = Decimal(1000)
        positions: ClassVar[dict] = {"A005930": Decimal(6)}

    class _Marks:
        total_value = Decimal("432000.0")

    at = datetime(2024, 3, 4, 16, tzinfo=UTC)
    view = _marked_account(_Snapshot(), _Marks(), at)

    assert view.nav == Decimal("432000.0")
    assert view.nav_observed_at == at
    # The weight a real cap rule needs is now computable.
    assert view.quantity("A005930") / view.nav > 0


def test_nav_and_its_instant_stay_coupled_at_monitor_time():
    """Both present or both absent - never a NAV the author cannot place in time."""
    from vqapr._internal.constraint_bridge import _marked_account

    class _Snapshot:
        cash = Decimal(1000)
        positions: ClassVar[dict] = {}

    class _NoValuation:
        total_value = None

    class _Marks:
        total_value = Decimal("432000.0")

    # No committed valuation: both None.
    view = _marked_account(_Snapshot(), _NoValuation(), datetime(2024, 3, 4, tzinfo=UTC))
    assert view.nav is None and view.nav_observed_at is None

    # A valuation with no instant is refused rather than half-reported.
    view = _marked_account(_Snapshot(), _Marks(), None)
    assert view.nav is None and view.nav_observed_at is None
