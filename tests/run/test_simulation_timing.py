from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.data.lookback import RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.account import AccountSnapshot
from vqapr.domain.intent import PortfolioTarget
from vqapr.public import (
    Compliance,
    ComplianceCall,
    ComplianceFinding,
)
from vqapr.run.engine.stages.observe import evaluate_compliance


class _Rule(Compliance):
    def __init__(self, compliance_id: str, passed: bool) -> None:
        self._compliance_id = compliance_id
        self.passed = passed

    @property
    def compliance_id(self) -> str:
        return self._compliance_id

    def requirements(self) -> tuple[DataRequirement, ...]:
        return ()

    def observe(self, call: ComplianceCall) -> ComplianceFinding:
        # No call.account version and no read provenance in the evidence: both are framework facts,
        # and `ComplianceReport` carries the version for the whole report rather than per finding.
        return ComplianceFinding(
            passed=self.passed,
            measured=Decimal("2"),
            bound=Decimal("1"),
            excess=Decimal("0") if self.passed else Decimal("1"),
            details={"marked_names": len(call.account.values or ())},
        )


class _Catalog:
    def dataset(self, _dataset_id: str) -> object:
        raise AssertionError("rule fixture must not query data")

    def source(self, _source_id: str) -> object:
        raise AssertionError("rule fixture must not query data")


def test_portfolio_target_is_a_weight_and_never_a_quantity() -> None:
    """A callback cannot see the execution price, so it may not name a share count."""
    with pytest.raises(TypeError):
        PortfolioTarget("ABC")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        PortfolioTarget("ABC", quantity=Decimal("1"))  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="weight must be a finite Decimal"):
        PortfolioTarget("ABC", weight=Decimal("NaN"))
    assert PortfolioTarget("ABC", weight=Decimal("0")).weight == Decimal("0")


def test_closed_compliance_evaluation_preserves_pass_and_violation_without_mutation() -> None:
    account = AccountSnapshot(4, Decimal("10"), {"ABC": Decimal("2")})
    marks = account.value({"ABC": Decimal("3")})
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(1))
    window = ModelWindow(
        evaluation_time=datetime(2024, 1, 1, tzinfo=UTC),
        instruments=("ABC",),
        store=DuckDbObservationStore(_Catalog()),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )
    rules = (_Rule("pass", True), _Rule("violation", False))

    report = evaluate_compliance(rules, window, account, marks)

    assert report.account_version == 4
    assert [finding.passed for finding in report.findings] == [True, False]
    assert report.passed is False
    assert account == AccountSnapshot(4, Decimal("10"), {"ABC": Decimal("2")})
