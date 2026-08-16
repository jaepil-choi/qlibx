from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.evaluation import evaluate_constraints
from vqapr.constraints.findings import ConstraintFinding
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.portfolio.intents import EconomicPortfolioIntent, PortfolioTarget
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

    def project(self, window: ModelWindow, instruments: tuple[str, ...]) -> ConstraintBounds:
        return ConstraintBounds(
            {instrument: Decimal("0") for instrument in instruments},
            {instrument: Decimal("1") for instrument in instruments},
        )

    def validate_intended(
        self, intent: EconomicPortfolioIntent, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        return ConstraintFinding(
            constraint_id=self.constraint_id,
            passed=self.passed,
            measured=Decimal("2"),
            bound=Decimal("1"),
            excess=Decimal("0") if self.passed else Decimal("1"),
            input_lineage={},
        )

    def evaluate(self, account: AccountSnapshot, marks: object) -> ConstraintFinding:
        return ConstraintFinding(
            constraint_id=self.constraint_id,
            passed=self.passed,
            measured=Decimal("2"),
            bound=Decimal("1"),
            excess=Decimal("0") if self.passed else Decimal("1"),
            input_lineage={"account_version": account.version, "mark_count": len(marks.marks)},
        )


def test_portfolio_target_requires_one_complete_economic_target() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        PortfolioTarget("ABC")
    with pytest.raises(ValueError, match="exactly one"):
        PortfolioTarget("ABC", weight=Decimal("1"), quantity=Decimal("1"))
    assert PortfolioTarget("ABC", quantity=Decimal("0")).quantity == Decimal("0")


def test_closed_constraint_evaluation_preserves_pass_and_violation_without_mutation() -> None:
    account = AccountSnapshot(4, Decimal("10"), {"ABC": Decimal("2")})
    marks = ValuationService().mark(account, {"ABC": Decimal("3")})

    report = evaluate_constraints(
        (_Constraint("pass", True), _Constraint("violation", False)), account, marks
    )

    assert report.account_version == 4
    assert [finding.passed for finding in report.findings] == [True, False]
    assert report.passed is False
    assert account == AccountSnapshot(4, Decimal("10"), {"ABC": Decimal("2")})
