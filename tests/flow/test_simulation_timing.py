from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.evaluation import evaluate_constraints
from vqapr.constraints.findings import ConstraintFinding
from vqapr.portfolio.intents import PortfolioTarget
from vqapr.valuation.marking import ValuationService


class _Constraint:
    def __init__(self, constraint_id: str, passed: bool) -> None:
        self.constraint_id = constraint_id
        self.passed = passed

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
