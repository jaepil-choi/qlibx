from datetime import datetime, timezone

from qlibx.portfolio import (
    BenchmarkWeight,
    ConstraintAdjustmentRequest,
    ConstraintDeclaration,
    ConstraintValidationRequest,
    ConstructionProfile,
    ExecutionLotInput,
    PortfolioConstructionResult,
    PortfolioWeight,
    adjust_single_name_caps,
    validate_single_name_caps,
)


def test_no_short_adjustment_is_independently_validated() -> None:
    evaluation_time = datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc)
    source = PortfolioConstructionResult(
        invocation_id="signed-source",
        source_artifact_id="alpha-1",
        source_strategy_id="signed-alpha",
        evaluation_time=evaluation_time,
        profile=ConstructionProfile.HYPOTHETICAL_SIGNED,
        original_weights=(
            PortfolioWeight(instrument="A", weight=-0.02),
            PortfolioWeight(instrument="B", weight=0.08),
        ),
        target_weights=(
            PortfolioWeight(instrument="A", weight=-0.02),
            PortfolioWeight(instrument="B", weight=0.08),
        ),
        requested_budget=0.10,
        realized_gross=0.10,
        realized_net=0.06,
        cash_residual=0.0,
        diagnostics=(),
    )
    declaration = ConstraintDeclaration(
        declaration_id="mvp-v1",
        benchmark_weight_role="benchmark_weight",
        single_name_floor=0.10,
    )
    adjustment_request = ConstraintAdjustmentRequest(
        invocation_id="adjust-no-short",
        source_portfolio_artifact_id="portfolio-1",
        evaluation_time=evaluation_time,
        config_fingerprint="constraint-v1",
        account_state_identity="account:test:v0",
        capital=100.0,
        lots=(
            ExecutionLotInput(
                instrument="A", price=1.0, lot_size=1.0, current_quantity=0.0
            ),
            ExecutionLotInput(
                instrument="B", price=1.0, lot_size=1.0, current_quantity=0.0
            ),
        ),
    )
    benchmark = (
        BenchmarkWeight(instrument="A", weight=0.01),
        BenchmarkWeight(instrument="B", weight=0.08),
    )

    adjustment = adjust_single_name_caps(
        adjustment_request,
        declaration,
        source,
        benchmark,
        (),
    )
    validation = validate_single_name_caps(
        ConstraintValidationRequest(
            invocation_id="validate-no-short",
            adjustment_artifact_id="adjustment-1",
            evaluation_time=evaluation_time,
            config_fingerprint="constraint-v1",
        ),
        declaration,
        adjustment,
        benchmark,
        (),
    )

    adjusted = {item.instrument: item.weight for item in adjustment.adjusted_weights}
    assert adjusted == {"A": 0.0, "B": 0.08}
    assert adjustment.items[0].reasons == ("no_short",)
    assert validation.eligible is True
