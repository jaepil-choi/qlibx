from __future__ import annotations

import pandas as pd
import pytest

from qlibx.alpha import (
    BUDGET_POLICIES,
    OPERATIONS,
    BudgetPolicySpec,
    OperationSpec,
    analyze_exposure,
    apply_budget,
    apply_pipeline,
    apply_transform,
    hump,
    list_operations,
    plan_exposure,
    plan_operation,
    register_budget_policy,
    register_operation,
    top_bottom,
)
from qlibx.errors import QlibxError
from qlibx.requirements import CapabilityRequirement, DerivationAlternative


def test_builtin_operation_has_versioned_deterministic_lineage() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    values = pd.DataFrame(
        [[1.0, 3.0], [2.0, 6.0], [4.0, 8.0]],
        index=dates,
        columns=["A", "B"],
    )
    first = apply_transform("linear_decay", values, window=2)
    second = apply_transform("linear_decay", values, window=2)
    pd.testing.assert_frame_equal(first.values, second.values)
    assert first.lineage == second.lineage
    assert first.lineage[0].operation_id == "qlibx.alpha.linear_decay"
    assert first.lineage[0].version == "1"
    assert first.lineage[0].minimum_observations == 2
    assert first.lineage[0].nan_behavior == "full_window_required"


def test_group_demean_records_missing_group_and_neutrality_warning() -> None:
    date = pd.Timestamp("2025-01-01")
    values = pd.DataFrame([[1.0, 3.0, 9.0]], index=[date], columns=["A", "B", "C"])
    groups = pd.DataFrame([["x", "x", pd.NA]], index=[date], columns=values.columns)
    result = apply_transform("group_demean", values, groups=groups)
    assert result.values.loc[date, "A"] == pytest.approx(-1.0)
    assert pd.isna(result.values.loc[date, "C"])
    assert result.lineage[0].group_missing_behavior == "missing_group_produces_missing_output"
    assert "not proof" in result.neutrality_warning


def test_group_demean_plan_and_runtime_error_share_one_requirement_resolution() -> None:
    values = pd.DataFrame([[1.0, 3.0]], columns=["A", "B"])
    plan = plan_operation("group_demean")
    assert plan.ready is False
    assert plan.resolution.missing_requirements == ("group_label",)
    with pytest.raises(QlibxError) as failure:
        apply_transform("group_demean", values)
    assert failure.value.stage == "ALPHA"
    assert failure.value.context == plan.resolution.to_dict()


def test_exposure_artifact_records_method_data_window_coverage_and_missingness() -> None:
    dates = pd.date_range("2025-01-01", periods=2)
    weights = pd.DataFrame(
        [[0.4, -0.2, pd.NA], [0.3, -0.1, 0.2]],
        index=dates,
        columns=["A", "B", "C"],
        dtype="Float64",
    )
    beta = pd.DataFrame(1.0, index=dates, columns=weights.columns)
    groups = pd.DataFrame(
        [["tech", "finance", "tech"], ["tech", "finance", "tech"]],
        index=dates,
        columns=weights.columns,
    )
    realized = weights.fillna(0.0) * 0.5
    artifact = analyze_exposure(
        weights,
        input_id="alpha-run-1",
        dataset_ids={"market_beta": "beta-v2", "sector": "sector-pit-v1"},
        method="weighted_sum",
        requested_metrics=(
            "summary",
            "market_exposure",
            "benchmark_exposure",
            "group_exposure",
            "factor_exposure",
            "intended_realized_gap",
        ),
        market_beta=beta,
        benchmark_beta=beta * 0.8,
        groups=groups,
        factors={"value": beta * 0.5},
        realized_holdings=realized,
    )
    assert artifact.analyzer_id == "qlibx.alpha.exposure"
    assert artifact.analyzer_version == "2"
    assert artifact.method == "weighted_sum"
    assert artifact.dataset_ids["sector"] == "sector-pit-v1"
    assert artifact.estimation_window == (str(dates[0]), str(dates[-1]))
    assert artifact.coverage.iloc[0] == 2
    assert artifact.missingness.iloc[0] == pytest.approx(1 / 3)
    assert artifact.market_exposure.iloc[0] == pytest.approx(0.2)
    assert artifact.group_exposure.loc[dates[0], "finance"] == pytest.approx(-0.2)
    assert artifact.factor_exposure.loc[dates[1], "value"] == pytest.approx(0.2)
    assert artifact.intended_realized_gap is not None
    assert artifact.status == "complete"
    assert artifact.unavailable_outputs == ()
    assert "not proof" in artifact.neutrality_warning


def test_exposure_distinguishes_unrequested_from_requested_but_unavailable() -> None:
    weights = pd.DataFrame([[0.4, -0.2]], columns=["A", "B"])
    summary_only = analyze_exposure(
        weights,
        input_id="alpha-run-1",
        dataset_ids={},
        method="weighted_sum",
        requested_metrics=("summary",),
    )
    assert summary_only.status == "complete"
    assert summary_only.market_exposure is None
    assert summary_only.unavailable_outputs == ()

    plan = plan_exposure(
        requested_metrics=("summary", "market_exposure"),
        available_inputs=("weights",),
    )
    assert plan.ready is False
    with pytest.raises(QlibxError) as failure:
        analyze_exposure(
            weights,
            input_id="alpha-run-1",
            dataset_ids={},
            method="weighted_sum",
            requested_metrics=("summary", "market_exposure"),
        )
    assert failure.value.stage == "ALPHA"
    assert failure.value.context == plan.resolution.to_dict()


def test_hump_restarts_after_a_gap_instead_of_poisoning_the_series() -> None:
    dates = pd.date_range("2025-01-01", periods=4)
    values = pd.DataFrame(
        {"A": [1.0, float("nan"), 3.0, 9.0], "B": [1.0, 2.0, 3.0, 4.0]},
        index=dates,
    )
    result = hump(values, maximum_change=1.0)
    assert pd.isna(result.loc[dates[1], "A"])
    # The observation after the gap has no previous value to limit against.
    assert result.loc[dates[2], "A"] == pytest.approx(3.0)
    # Limiting resumes once a previous value exists again.
    assert result.loc[dates[3], "A"] == pytest.approx(4.0)


def test_top_bottom_fails_instead_of_selecting_one_name_on_both_sides() -> None:
    values = pd.DataFrame([[1.0, 2.0, 3.0]], columns=list("abc"))
    with pytest.raises(QlibxError, match="at least 4 valid observations") as thin:
        top_bottom(values, count=2)
    assert thin.value.stage == "ALPHA"
    assert thin.value.context["insufficient_dates"] == 1
    assert top_bottom(values, count=1).iloc[0].tolist() == [-1.0, 0.0, 1.0]


def test_registered_operations_compose_into_one_lineage_chain() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    values = pd.DataFrame([[1.0, 3.0], [2.0, 6.0], [4.0, 8.0]], index=dates, columns=["A", "B"])
    result = apply_pipeline(
        values,
        [("rolling_mean", {"window": 2}), "cross_sectional_demean"],
    )
    assert [item.operation_id for item in result.lineage] == [
        "qlibx.alpha.rolling_mean",
        "qlibx.alpha.cross_sectional_demean",
    ]
    assert result.lineage[0].parameters == {"window": 2}
    assert result.lineage[0].minimum_observations == 2
    assert "not proof" in result.neutrality_warning


def test_unknown_operation_and_parameter_fail_explicitly() -> None:
    values = pd.DataFrame([[1.0, 2.0]], columns=["A", "B"])
    with pytest.raises(QlibxError) as unknown:
        apply_transform("not_an_operation", values)
    assert unknown.value.stage == "ALPHA"
    assert "cross_sectional_rank" in unknown.value.context["available"]
    with pytest.raises(QlibxError, match="does not accept parameters") as misspelled:
        apply_transform("linear_decay", values, windwo=2)
    assert misspelled.value.stage == "ALPHA"
    assert misspelled.value.context["declared"] == ["window"]
    with pytest.raises(QlibxError, match="requires parameters") as absent:
        apply_transform("linear_decay", values)
    assert absent.value.context["missing"] == ["window"]


def test_project_local_operation_registers_and_carries_its_own_lineage() -> None:
    values = pd.DataFrame([[1.0, 3.0]], columns=["A", "B"])

    def double(frame, *, factor=2.0):
        return frame.mul(factor)

    spec = OperationSpec(
        name="test_double",
        operation_id="project.test_double",
        version="7",
        axis="date_by_ticker",
        tie_behavior="not_applicable",
        nan_behavior="preserve",
        minimum_observations=1,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary="Scale every observation by a constant factor.",
        apply=double,
        parameters={"factor": "multiplicative constant"},
    )
    register_operation(spec)
    try:
        result = apply_transform("test_double", values, factor=3.0)
        assert result.values.iloc[0].tolist() == [3.0, 9.0]
        assert result.lineage[0].operation_id == "project.test_double"
        assert result.lineage[0].version == "7"
        assert "test_double" in {item["name"] for item in list_operations()}
    finally:
        OPERATIONS.unregister("test_double")


def test_project_local_operation_uses_the_common_requirement_contract() -> None:
    values = pd.DataFrame([[1.0, 3.0]], columns=["A", "B"])
    auxiliary = pd.DataFrame([[2.0, 4.0]], columns=values.columns)

    def add_auxiliary(frame, *, auxiliary):
        return frame.add(auxiliary)

    requirement = CapabilityRequirement(
        requirement_id="auxiliary_signal",
        role="auxiliary",
        meaning="Explicit auxiliary signal matrix.",
        axis="date_by_ticker",
        unit="signal",
        currency="not_applicable",
        purpose="Add an explicitly supplied project-local signal.",
        satisfaction_rule="The auxiliary parameter is supplied.",
        availability="Bounded by the caller's decision context.",
        mandatory=True,
        unavailable_effect="The project-local transform cannot run.",
        alternatives=(
            DerivationAlternative(
                alternative_id="explicit_auxiliary",
                description="Use an explicitly supplied auxiliary matrix.",
                required_inputs=("auxiliary",),
                derivation="direct",
            ),
        ),
        next_commands=("qlibx data catalog --root <project>",),
    )
    register_operation(
        OperationSpec(
            name="test_auxiliary",
            operation_id="project.test_auxiliary",
            version="1",
            axis="date_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="preserve",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Use one explicitly required auxiliary signal.",
            apply=add_auxiliary,
            parameters={"auxiliary": "date-by-ticker auxiliary matrix"},
            requirements=(requirement,),
        )
    )
    try:
        with pytest.raises(QlibxError) as failure:
            apply_transform("test_auxiliary", values)
        assert failure.value.stage == "ALPHA"
        result = apply_transform("test_auxiliary", values, auxiliary=auxiliary)
        assert result.values.iloc[0].tolist() == [3.0, 7.0]
    finally:
        OPERATIONS.unregister("test_auxiliary")


def test_budget_policies_are_registered_and_report_leftover() -> None:
    weights = pd.DataFrame([[0.2, -0.1, 0.0]], columns=list("abc"))
    fixed = apply_budget(weights, policy="fixed")
    assert fixed.long_used.iloc[0] == pytest.approx(1.0)
    assert fixed.long_leftover.iloc[0] == pytest.approx(0.0)

    flexible = apply_budget(weights, policy="flexible")
    assert flexible.weights.equals(weights)
    assert flexible.long_leftover.iloc[0] == pytest.approx(0.8)
    assert flexible.short_leftover.iloc[0] == pytest.approx(0.9)

    def half(long_sum, short_sum, long_budget, short_budget):
        scale = pd.Series(0.5, index=long_sum.index)
        return scale, scale

    register_budget_policy(
        BudgetPolicySpec(
            name="test_half",
            policy_id="project.test_half",
            version="1",
            summary="Halve both sides.",
            unused_budget_behavior="half of each side is always left unused",
            resolve=half,
        )
    )
    try:
        halved = apply_budget(weights, policy="test_half")
        assert halved.weights.iloc[0].tolist() == pytest.approx([0.1, -0.05, 0.0])
    finally:
        BUDGET_POLICIES.unregister("test_half")

    with pytest.raises(QlibxError) as unknown:
        apply_budget(weights, policy="not_a_policy")
    assert unknown.value.stage == "ALPHA"
    assert unknown.value.context["available"] == ["fixed", "flexible"]
