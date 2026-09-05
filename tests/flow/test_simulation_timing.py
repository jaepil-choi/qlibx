from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.authoring import (
    ConstraintCall,
    EconomicAccountView,
)
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.evaluation import evaluate_constraints, project_constraints
from vqapr.constraints.findings import ConstraintFinding
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.portfolio.intents import PortfolioTarget
from vqapr.valuation.marking import ValuationService


class _Constraint(Constraint):
    def __init__(self, constraint_id: str, passed: bool) -> None:
        self._constraint_id = constraint_id
        self.passed = passed

    @property
    def constraint_id(self) -> str:
        return self._constraint_id

    def requirements(self) -> tuple[DataRequirement, ...]:
        return ()

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        return ConstraintBounds(
            lower_weights={instrument: Decimal("0") for instrument in call.instruments},
            upper_weights={instrument: Decimal("1") for instrument in call.instruments},
        )

    def monitor(
        self,
        call: ConstraintCall,
        account: EconomicAccountView,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        # No account version and no read provenance in the evidence: both are framework facts,
        # and `ConstraintReport` carries the version for the whole report rather than per finding.
        return ConstraintFinding(
            passed=self.passed,
            measured=Decimal("2"),
            bound=Decimal("1"),
            excess=Decimal("0") if self.passed else Decimal("1"),
            details={"marked_names": len(account.values or ())},
        )


class _Catalog:
    def dataset(self, _dataset_id: str) -> object:
        raise AssertionError("constraint fixture must not query data")

    def source(self, _source_id: str) -> object:
        raise AssertionError("constraint fixture must not query data")


def test_portfolio_target_is_a_weight_and_never_a_quantity() -> None:
    """A callback cannot see the execution price, so it may not name a share count."""
    with pytest.raises(TypeError):
        PortfolioTarget("ABC")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        PortfolioTarget("ABC", quantity=Decimal("1"))  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="weight must be a finite Decimal"):
        PortfolioTarget("ABC", weight=Decimal("NaN"))
    assert PortfolioTarget("ABC", weight=Decimal("0")).weight == Decimal("0")


def test_closed_constraint_evaluation_preserves_pass_and_violation_without_mutation() -> None:
    account = AccountSnapshot(4, Decimal("10"), {"ABC": Decimal("2")})
    marks = ValuationService().mark(account, {"ABC": Decimal("3")})
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(1))
    window = ModelWindow(
        evaluation_time=datetime(2024, 1, 1, tzinfo=UTC),
        instruments=("ABC",),
        store=DuckDbObservationStore(_Catalog()),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )
    constraints = (_Constraint("pass", True), _Constraint("violation", False))
    projected = project_constraints(constraints, window)

    report = evaluate_constraints(constraints, window, account, marks, projected)

    assert report.account_version == 4
    assert [finding.passed for finding in report.findings] == [True, False]
    assert report.passed is False
    assert account == AccountSnapshot(4, Decimal("10"), {"ABC": Decimal("2")})
