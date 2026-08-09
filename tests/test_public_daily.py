import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    OperationOutcome,
    OutcomeStatus,
    QlibxProject,
    StrategyExtensionValidationRequest,
)
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.errors import CommitStatus
from qlibx.evidence import ArtifactEnvelope, LocalArtifactBackend
from qlibx.execution import CostRule, KrxExchangeConfig, Side, StockInstrument
from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StoredSignalEntry,
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyDraft,
    WeightEntry,
)

KST = ZoneInfo("Asia/Seoul")


class RebalanceThenFailStrategy:
    strategy_id = "test.public-daily-rebalance"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        selected = "A000002" if account.positions else "A000001"
        return StrategyDraft(
            weights=(WeightEntry(instrument=selected, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            feedback_cursor=str(feedback.next_cursor),
        )


class PublicDailyStrategy:
    strategy_id = "test.public-daily"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        if account.positions:
            assert feedback.next_cursor == feedback.after_cursor
            return StrategyDraft(
                weights=(),
                budget_mode=BudgetMode.FLEXIBLE,
                target_gross=1.0,
                decision_action=DecisionAction.HOLD,
                path_dependent=True,
                state_identity=f"{account.account_id}:v{account.version}",
                feedback_cursor=str(feedback.next_cursor),
            )
        return StrategyDraft(
            weights=(WeightEntry(instrument="A000001", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            feedback_cursor=str(feedback.next_cursor),
        )


class ArtifactDailyStrategy(PublicDailyStrategy):
    strategy_id = "test.public-daily-artifact"

    def __init__(self) -> None:
        self.artifact_access_count = 0

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return (
            StrategyArtifactRequirement(
                requirement_id="daily.alpha_signal",
                consumer_role="alpha_signal",
                artifact_type="stored_signal_result",
                artifact_schema_version=1,
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        view.artifact("alpha_signal", StoredSignalResult)  # type: ignore[attr-defined]
        self.artifact_access_count += 1
        return super().run(view)


def at(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


def spec(**updates: object) -> DailySimulationSpec:
    payload: dict[str, object] = {
        "run_id": "public-daily-run",
        "strategy_fingerprint": "test-public-daily-v1",
        "account": DailyAccountSeed(
            account_id="public-account",
            base_currency="KRW",
            initial_cash=10_000,
        ),
        "instruments": tuple(
            StockInstrument(
                instrument_id=instrument,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
            for instrument in ("A000001", "A000002")
        ),
        "exchange": KrxExchangeConfig(
            schedule_version="test-cost-v1",
            cost_rules=tuple(
                CostRule(
                    rule_id=f"stock-{side.value.lower()}",
                    product_type="stock",
                    side=side,
                    effective_from=datetime(2020, 1, 1, tzinfo=KST),
                    rate=0,
                    minimum_cost=0,
                )
                for side in Side
            ),
        ),
        "market": DailyMarketBinding(market_dataset_id="public-market"),
        "decision_times": (at(2), at(4)),
        "session_closes": (at(2), at(3), at(4), at(5)),
    }
    payload.update(updates)
    return DailySimulationSpec.model_validate(payload)


def project(tmp_path: Path) -> QlibxProject:
    root = tmp_path / "public-project"
    QlibxProject.init(root, apply=True)
    market = root / "market.csv"
    market.write_text(
        "date,available_at,ticker,close\n"
        "2024-01-02T09:00:00+09:00,2024-01-02T15:30:00+09:00,A000001,100\n"
        "2024-01-02T09:00:00+09:00,2024-01-02T15:30:00+09:00,A000002,100\n"
        "2024-01-03T09:00:00+09:00,2024-01-03T15:30:00+09:00,A000001,100\n"
        "2024-01-03T09:00:00+09:00,2024-01-03T15:30:00+09:00,A000002,100\n"
        "2024-01-04T09:00:00+09:00,2024-01-04T15:30:00+09:00,A000001,101\n"
        "2024-01-04T09:00:00+09:00,2024-01-04T15:30:00+09:00,A000002,99\n"
        "2024-01-05T09:00:00+09:00,2024-01-05T15:30:00+09:00,A000001,102\n"
        "2024-01-05T09:00:00+09:00,2024-01-05T15:30:00+09:00,A000002,100\n",
        encoding="utf-8",
    )
    selected = QlibxProject.open(root)
    outcome = selected.register_dataset(
        DatasetRegistration(
            dataset_id="public-market",
            source="market.csv",
            source_format=SourceFormat.CSV,
            instrument_field="ticker",
            observation_time_field="date",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("date", "available_at", "ticker"),
            semantic_bindings={
                "execution_price": "close",
                "valuation_price": "close",
            },
            source_provenance="bounded public daily facade fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return selected


def publish_daily_signal(selected: QlibxProject, identity: str) -> ArtifactEnvelope:
    outcome = selected.artifacts.publish_model(
        logical_identity=identity,
        artifact_type="stored_signal_result",
        artifact_schema_version=1,
        producer_id="tests.daily-signal",
        payload=StoredSignalResult(
            signal_semantics="alpha",
            observation_time=at(1),
            entries=(StoredSignalEntry(instrument="A000001", value=1.0),),
        ),
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return outcome.result


def test_public_daily_facade_runs_closed_loop(tmp_path: Path) -> None:
    outcome = project(tmp_path).run_daily(PublicDailyStrategy(), spec())

    assert outcome.status is OutcomeStatus.COMPLETE
    assert len(outcome.result.strategy_results) == 2
    assert len(outcome.result.executions) == 1
    assert outcome.result.final_account.positions[0].quantity == 100
    assert outcome.result.strategy_results[1].feedback_accesses[0].next_cursor == 2
    assert outcome.result.checkpoint.config_fingerprint == spec().frozen_config_fingerprint()


def test_public_daily_spec_rejects_runtime_capability_overclaims() -> None:
    base = spec().model_dump(mode="python")
    base["exchange"]["participation_rate"] = 0.1
    with pytest.raises(ValidationError, match="does not support volume participation"):
        DailySimulationSpec.model_validate(base)

    base = spec().model_dump(mode="python")
    base["exchange"]["impact_rate"] = 0.001
    with pytest.raises(ValidationError, match="does not support market impact"):
        DailySimulationSpec.model_validate(base)


def test_public_daily_spec_rejects_inconsistent_instrument_authority() -> None:
    duplicate = spec().model_dump(mode="python")
    duplicate["instruments"] = (
        duplicate["instruments"][0],
        duplicate["instruments"][0],
    )
    with pytest.raises(ValidationError, match="instruments must be unique"):
        DailySimulationSpec.model_validate(duplicate)

    wrong_currency = spec().model_dump(mode="python")
    wrong_currency["account"]["base_currency"] = "USD"
    with pytest.raises(ValidationError, match="currency must match"):
        DailySimulationSpec.model_validate(wrong_currency)

    wrong_exchange = spec().model_dump(mode="python")
    wrong_exchange["instruments"][0]["exchange_id"] = "OTHER"
    with pytest.raises(ValidationError, match="exchange_id must match"):
        DailySimulationSpec.model_validate(wrong_exchange)

    unsupported = spec().model_dump(mode="python")
    unsupported["instruments"] = (
        {
            "kind": "index",
            "instrument_id": "K200",
            "exchange_id": "XKRX",
            "currency": "KRW",
            "tracking_only": True,
        },
    )
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        DailySimulationSpec.model_validate(unsupported)


def test_public_daily_is_deterministic_and_resumable(tmp_path: Path) -> None:
    selected = project(tmp_path)
    selected_spec = spec()

    first = selected.run_daily(PublicDailyStrategy(), selected_spec)
    repeated = selected.run_daily(PublicDailyStrategy(), selected_spec)
    resumed = selected.run_daily(PublicDailyStrategy(), selected_spec, resume=True)

    assert first.status is repeated.status is resumed.status is OutcomeStatus.COMPLETE
    assert (
        first.result.final_account
        == repeated.result.final_account
        == resumed.result.final_account
    )
    assert tuple(item.artifact_id for item in first.result.artifacts) == tuple(
        item.artifact_id for item in repeated.result.artifacts
    )
    assert {item.artifact_id for item in first.result.artifacts} == {
        item.artifact_id for item in resumed.result.artifacts
    }

    changed = spec(strategy_fingerprint="test-public-daily-v2")
    rejected = selected.run_daily(PublicDailyStrategy(), changed, resume=True)
    assert rejected.status is OutcomeStatus.FAILED
    assert rejected.errors[0].error_code == "RESUME_BRANCH_REQUIRED"
    assert rejected.errors[0].commit_status is CommitStatus.NONE


def test_empty_daily_bindings_preserve_pre_m2_fingerprints() -> None:
    selected = spec()
    assert (
        selected.frozen_config_fingerprint()
        == "0e602a61282040af577e7187e92b3c20f4851247672fa3ec803e94cf86ea4628"
    )
    request = DailyRunRequest(
        run_id=selected.run_id,
        config_fingerprint=selected.frozen_config_fingerprint(),
        decision_times=selected.decision_times,
        session_closes=selected.session_closes,
    )
    assert hashlib.sha256(request.compatibility_json().encode()).hexdigest() == (
        "6120f8fc7dfe1e4526bbd054ce0ed61f40ffa528ca0d714c44cdc6b0bb6eb643"
    )
    assert "artifact_bindings" not in request.compatibility_json()
    assert "session_opens" not in request.compatibility_json()
    profile = DailyExecutionProfile(market_dataset_id="dw-real-market")
    assert hashlib.sha256(profile.compatibility_json().encode()).hexdigest() == (
        "71ad9830c5a66478a449e724b7e96369a43ad4c99a487f50671d37331619588d"
    )
    assert "execution_timing" not in profile.compatibility_json()


def test_next_open_requires_an_explicit_open_schedule() -> None:
    with pytest.raises(ValidationError, match="requires session_opens"):
        spec(execution_timing="next_session_open")

    with pytest.raises(ValidationError, match="session_opens require"):
        spec(session_opens=(datetime(2024, 1, 3, 9, 0, tzinfo=KST),))

    with pytest.raises(ValidationError, match="session_opens must be unique and sorted"):
        spec(
            execution_timing="next_session_open",
            session_opens=(
                datetime(2024, 1, 4, 9, 0, tzinfo=KST),
                datetime(2024, 1, 3, 9, 0, tzinfo=KST),
            ),
        )

    selected = spec(
        execution_timing="next_session_open",
        session_opens=(datetime(2024, 1, 3, 9, 0, tzinfo=KST),),
    )
    assert selected.frozen_config_fingerprint() != spec().frozen_config_fingerprint()


def test_non_empty_daily_bindings_change_frozen_and_recovery_identity() -> None:
    binding = StrategyArtifactBinding(
        consumer_role="alpha_signal",
        artifact_id="artifact-alpha-1",
    )
    empty = spec()
    bound = spec(artifact_bindings=(binding,))
    assert bound.frozen_config_fingerprint() != empty.frozen_config_fingerprint()

    empty_request = DailyRunRequest(
        run_id=empty.run_id,
        config_fingerprint=empty.frozen_config_fingerprint(),
        decision_times=empty.decision_times,
        session_closes=empty.session_closes,
    )
    bound_request = DailyRunRequest(
        run_id=bound.run_id,
        config_fingerprint=bound.frozen_config_fingerprint(),
        decision_times=bound.decision_times,
        session_closes=bound.session_closes,
        artifact_bindings=bound.artifact_bindings,
    )
    assert bound_request.compatibility_json() != empty_request.compatibility_json()
    assert "artifact-alpha-1" in bound_request.compatibility_json()


def test_daily_propagates_the_same_frozen_binding_to_every_decision(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    signal = publish_daily_signal(selected, "daily-signal:alpha")
    strategy = ArtifactDailyStrategy()
    selected_spec = spec(
        artifact_bindings=(
            StrategyArtifactBinding(
                consumer_role="alpha_signal",
                artifact_id=signal.artifact_id,
            ),
        )
    )

    outcome = selected.run_daily(strategy, selected_spec)

    assert outcome.status is OutcomeStatus.COMPLETE
    assert strategy.artifact_access_count == len(selected_spec.decision_times)
    strategy_artifacts = tuple(
        envelope
        for envelope in outcome.result.artifacts
        if envelope.artifact_type == "strategy_result"
    )
    assert len(strategy_artifacts) == len(selected_spec.decision_times)
    for envelope in strategy_artifacts:
        artifact_edges = tuple(
            edge for edge in envelope.dependencies if edge.consumer_role == "alpha_signal"
        )
        assert len(artifact_edges) == 1
        assert artifact_edges[0].dependency_id == signal.artifact_id


def test_changed_daily_artifact_selection_requires_a_new_recovery_branch(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    first_signal = publish_daily_signal(selected, "daily-signal:first")
    second_signal = publish_daily_signal(selected, "daily-signal:second")
    first_spec = spec(
        artifact_bindings=(
            StrategyArtifactBinding(
                consumer_role="alpha_signal",
                artifact_id=first_signal.artifact_id,
            ),
        )
    )
    first = selected.run_daily(ArtifactDailyStrategy(), first_spec)
    assert first.status is OutcomeStatus.COMPLETE

    changed = spec(
        artifact_bindings=(
            StrategyArtifactBinding(
                consumer_role="alpha_signal",
                artifact_id=second_signal.artifact_id,
            ),
        )
    )
    resumed = selected.run_daily(ArtifactDailyStrategy(), changed, resume=True)

    assert resumed.status is OutcomeStatus.FAILED
    assert resumed.errors[0].error_code == "RESUME_BRANCH_REQUIRED"
    assert resumed.errors[0].commit_status is CommitStatus.NONE


def test_daily_binding_roles_must_be_unique() -> None:
    duplicate = StrategyArtifactBinding(
        consumer_role="alpha_signal",
        artifact_id="artifact-alpha-1",
    )
    second = StrategyArtifactBinding(
        consumer_role="alpha_signal",
        artifact_id="artifact-alpha-2",
    )
    with pytest.raises(ValidationError, match="binding roles must be unique"):
        spec(artifact_bindings=(duplicate, second))
    selected = spec()
    with pytest.raises(ValidationError, match="binding roles must be unique"):
        DailyRunRequest(
            run_id=selected.run_id,
            config_fingerprint=selected.frozen_config_fingerprint(),
            decision_times=selected.decision_times,
            session_closes=selected.session_closes,
            artifact_bindings=(duplicate, second),
        )


def test_public_daily_missing_market_role_fails_before_account_commit(tmp_path: Path) -> None:
    selected = project(tmp_path)
    missing = spec(
        market=DailyMarketBinding(
            market_dataset_id="public-market",
            execution_price_role="missing_execution_price",
        )
    )

    outcome = selected.run_daily(PublicDailyStrategy(), missing)

    assert outcome.status is OutcomeStatus.FAILED
    assert any(error.error_code == "REQUIREMENT_NOT_RESOLVED" for error in outcome.errors)
    assert all(error.commit_status is CommitStatus.NONE for error in outcome.errors)
    assert not any(
        artifact.artifact_type == "execution_result" for artifact in outcome.diagnostics
    )


def test_public_daily_missing_initial_buy_cost_fails_before_account_commit(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    sell_only = KrxExchangeConfig(
        schedule_version="sell-only-cost-v1",
        cost_rules=(
            CostRule(
                rule_id="stock-sell-only",
                product_type="stock",
                side=Side.SELL,
                effective_from=datetime(2020, 1, 1, tzinfo=KST),
                rate=0,
                minimum_cost=0,
            ),
        ),
    )

    outcome = selected.run_daily(PublicDailyStrategy(), spec(exchange=sell_only))

    assert outcome.status is OutcomeStatus.FAILED
    missing = next(
        error for error in outcome.errors if error.error_code == "EXACT_COST_RULE_MISSING"
    )
    assert missing.commit_status is CommitStatus.NONE
    assert not any(
        artifact.artifact_type == "execution_result" for artifact in outcome.diagnostics
    )


def test_public_daily_missing_later_sell_cost_preserves_prior_evidence(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    buy_only = KrxExchangeConfig(
        schedule_version="buy-only-cost-v1",
        cost_rules=(
            CostRule(
                rule_id="stock-buy-only",
                product_type="stock",
                side=Side.BUY,
                effective_from=datetime(2020, 1, 1, tzinfo=KST),
                rate=0,
                minimum_cost=0,
            ),
        ),
    )

    outcome = selected.run_daily(
        RebalanceThenFailStrategy(),
        spec(exchange=buy_only, strategy_fingerprint="rebalance-missing-sell-v1"),
    )

    assert outcome.status is OutcomeStatus.FAILED
    missing = next(
        error for error in outcome.errors if error.error_code == "EXACT_COST_RULE_MISSING"
    )
    assert missing.commit_status is CommitStatus.NONE
    assert any(
        artifact.artifact_type == "execution_result" for artifact in outcome.diagnostics
    )
    assert any(
        artifact.artifact_type == "simulation_recovery_point"
        for artifact in selected.artifacts.list_envelopes()
    )


def test_empty_mark_is_recorded_only_after_publication_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = project(tmp_path)
    original_backend_publish = LocalArtifactBackend.publish_model
    original_flow_publish = DailyExecutionFlow._publish_model
    marks_seen_at_publication: list[tuple[object, ...]] = []

    def fail_mark_publication(
        backend: LocalArtifactBackend,
        **kwargs: Any,
    ) -> OperationOutcome:
        if kwargs["artifact_type"] == "mark_result":
            return backend._failure(
                str(kwargs["logical_identity"]),
                "artifact.publish.test",
                "SYNTHETIC_MARK_PUBLICATION_FAILURE",
            )
        return original_backend_publish(backend, **kwargs)

    def observe_mark_publication(
        flow: DailyExecutionFlow,
        **kwargs: Any,
    ) -> ArtifactEnvelope | None:
        if kwargs["artifact_type"] == "mark_result":
            marks_seen_at_publication.append(tuple(flow._marks))
        return original_flow_publish(flow, **kwargs)

    monkeypatch.setattr(LocalArtifactBackend, "publish_model", fail_mark_publication)
    monkeypatch.setattr(DailyExecutionFlow, "_publish_model", observe_mark_publication)

    outcome = selected.run_daily(
        PublicDailyStrategy(),
        spec(
            run_id="empty-mark-publication-failure",
            strategy_fingerprint="empty-mark-publication-failure-v1",
            decision_times=(),
            session_closes=(at(2),),
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "ARTIFACT_PUBLICATION_FAILED"
    assert outcome.errors[0].stage_path == "daily_flow.mark.artifact"
    assert marks_seen_at_publication == [()]


def test_exact_registered_strategy_runs_through_daily_facade(tmp_path: Path) -> None:
    selected = project(tmp_path)
    module = selected.root / selected.config.extension_dir / "daily_strategy.py"
    module.write_text(
        "from qlibx import (\n"
        "    BudgetMode, StrategyDraft, StrategyExtensionSpec, WeightEntry,\n"
        ")\n\n"
        "STRATEGY_SPEC = StrategyExtensionSpec(strategy_id='project.daily')\n\n"
        "class Strategy:\n"
        "    strategy_id = STRATEGY_SPEC.strategy_id\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def run(self, view):\n"
        "        return StrategyDraft(\n"
        "            weights=(WeightEntry(instrument='A000001', weight=1.0),),\n"
        "            budget_mode=BudgetMode.FIXED,\n"
        "            target_gross=1.0,\n"
        "        )\n\n"
        "def create_strategy():\n"
        "    return Strategy()\n",
        encoding="utf-8",
    )
    validated = selected.validate_strategy_extension(
        StrategyExtensionValidationRequest(
            invocation_id="validate-project-daily",
            strategy_id="project.daily",
            module_path="daily_strategy.py",
            evaluation_time=at(2),
            config_fingerprint="project-daily-validation-v1",
        )
    )
    assert validated.status is OutcomeStatus.COMPLETE
    selected_spec = spec(
        run_id="registered-daily-run",
        strategy_fingerprint="registered-daily-v1",
    )

    outcome = selected.run_daily_registered_strategy(
        validated.result.registration_artifact_id,
        selected_spec,
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert len(outcome.result.strategy_results) == 2
    assert (
        outcome.result.checkpoint.config_fingerprint
        != selected_spec.frozen_config_fingerprint()
    )
    strategy_artifacts = tuple(
        artifact
        for artifact in outcome.result.artifacts
        if artifact.artifact_type == "strategy_result"
    )
    assert len(strategy_artifacts) == 2
    assert all(
        any(
            edge.consumer_role == "strategy_extension_registration"
            and edge.dependency_id == validated.result.registration_artifact_id
            for edge in artifact.dependencies
        )
        for artifact in strategy_artifacts
    )
