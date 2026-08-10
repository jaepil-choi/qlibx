from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    OutcomeStatus,
    QlibxProject,
    StrategyArtifactBinding,
    StrategyExtensionValidationRequest,
    StrategyInvocation,
)
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.execution import CostRule, KrxExchangeConfig, Side, StockInstrument
from qlibx.flow import CompositionFlow, EnsembleDefinition, EnsembleMemberSpec
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StrategyDraft,
    StrategyResult,
    WeightEntry,
)

KST = ZoneInfo("Asia/Seoul")


def at(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


class CountingPathProducer:
    def __init__(self, identity: str, instrument: str) -> None:
        self.strategy_id = f"tests.path-producer-{identity}"
        self.instrument = instrument
        self.call_count = 0

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        account = view.account_snapshot()  # type: ignore[attr-defined]
        feedback = view.account_feedback()  # type: ignore[attr-defined]
        memory = view.memory_snapshot()  # type: ignore[attr-defined]
        self.call_count += 1
        return StrategyDraft(
            weights=(WeightEntry(instrument=self.instrument, weight=0.5),),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            path_dependent=True,
            state_identity=(
                f"{account.account_id}:v{account.version}:cursor{feedback.next_cursor}"
            ),
            feedback_cursor=str(feedback.next_cursor),
            proposed_memory={
                "call_count": self.call_count,
                "feedback_cursor": feedback.next_cursor,
            },
            expected_memory_version=memory.version,
        )


def project(tmp_path: Path) -> QlibxProject:
    root = tmp_path / "strategy-composition-project"
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
        "2024-01-05T09:00:00+09:00,2024-01-05T15:30:00+09:00,A000002,100\n"
        "2024-01-08T09:00:00+09:00,2024-01-08T15:30:00+09:00,A000001,103\n"
        "2024-01-08T09:00:00+09:00,2024-01-08T15:30:00+09:00,A000002,101\n"
        "2024-01-09T09:00:00+09:00,2024-01-09T15:30:00+09:00,A000001,104\n"
        "2024-01-09T09:00:00+09:00,2024-01-09T15:30:00+09:00,A000002,102\n"
        "2024-01-10T09:00:00+09:00,2024-01-10T15:30:00+09:00,A000001,105\n"
        "2024-01-10T09:00:00+09:00,2024-01-10T15:30:00+09:00,A000002,103\n"
        "2024-01-11T09:00:00+09:00,2024-01-11T15:30:00+09:00,A000001,106\n"
        "2024-01-11T09:00:00+09:00,2024-01-11T15:30:00+09:00,A000002,104\n",
        encoding="utf-8",
    )
    selected = QlibxProject.open(root)
    registered = selected.register_dataset(
        DatasetRegistration(
            dataset_id="composition-market",
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
            source_provenance="installed Strategy composition acceptance fixture",
        )
    )
    assert registered.status is OutcomeStatus.COMPLETE
    return selected


def daily_spec(run_id: str, account_id: str, **updates: object) -> DailySimulationSpec:
    payload: dict[str, object] = {
        "run_id": run_id,
        "strategy_fingerprint": f"{run_id}-strategy-v1",
        "account": DailyAccountSeed(
            account_id=account_id,
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
            schedule_version="composition-cost-v1",
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
        "market": DailyMarketBinding(market_dataset_id="composition-market"),
        "decision_times": (at(2), at(4)),
        "session_closes": (at(2), at(3), at(4), at(5)),
    }
    payload.update(updates)
    return DailySimulationSpec.model_validate(payload)


def final_strategy_artifact(outcome: object) -> tuple[StrategyResult, object]:
    result = outcome.result  # type: ignore[attr-defined]
    strategy_result = result.strategy_results[-1]
    assert isinstance(strategy_result, StrategyResult)
    envelope = next(
        item
        for item in result.artifacts
        if item.artifact_type == "strategy_result"
        and item.logical_identity == f"strategy:{strategy_result.invocation_id}"
    )
    return strategy_result, envelope


def test_installed_path_dependent_composition_uses_current_account_only_downstream(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    producer_a = CountingPathProducer("a", "A000001")
    producer_b = CountingPathProducer("b", "A000002")

    source_a = selected.run_daily(
        producer_a,
        daily_spec("source-run-a", "source-account-a"),
    )
    source_b = selected.run_daily(
        producer_b,
        daily_spec("source-run-b", "source-account-b"),
    )
    assert source_a.status is source_b.status is OutcomeStatus.COMPLETE
    source_result_a, source_envelope_a = final_strategy_artifact(source_a)
    source_result_b, source_envelope_b = final_strategy_artifact(source_b)
    source_envelopes_before = tuple(
        selected.artifacts.load_envelope(item.artifact_id).result
        for item in (source_envelope_a, source_envelope_b)
    )
    producer_counts_before = (producer_a.call_count, producer_b.call_count)
    assert producer_counts_before == (2, 2)
    assert source_result_a.state_accesses[-1].account_id == "source-account-a"
    assert source_result_b.state_accesses[-1].account_id == "source-account-b"
    assert source_result_a.memory_accesses[-1].strategy_id == producer_a.strategy_id
    assert source_result_b.memory_accesses[-1].strategy_id == producer_b.strategy_id
    assert source_result_a.memory_accesses[-1].version == 1
    assert source_result_b.memory_accesses[-1].version == 1

    composed = CompositionFlow(
        registry=selected.registry_snapshot(),
        artifacts=selected.artifacts,
    ).invoke_ensemble(
        EnsembleDefinition(
            strategy_id="tests.installed-path-ensemble",
            members=(
                EnsembleMemberSpec(
                    artifact_id=source_envelope_a.artifact_id,
                    allocation=1.0,
                ),
                EnsembleMemberSpec(
                    artifact_id=source_envelope_b.artifact_id,
                    allocation=1.0,
                ),
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        ),
        StrategyInvocation(
            invocation_id="installed-path-ensemble",
            evaluation_time=at(5),
            config_fingerprint="installed-path-ensemble-v1",
        ),
    )
    assert composed.status is OutcomeStatus.COMPLETE
    ensemble_result = composed.result.strategy.result
    ensemble_artifact = composed.result.strategy.artifact
    assert ensemble_result.state_identity is None
    assert ensemble_result.feedback_cursor is None
    assert tuple(item.source_artifact_id for item in ensemble_result.source_state_lineage) == tuple(
        sorted((source_envelope_a.artifact_id, source_envelope_b.artifact_id))
    )
    assert {
        access.account_id
        for lineage in ensemble_result.source_state_lineage
        for access in lineage.state_accesses
    } == {"source-account-a", "source-account-b"}
    assert {
        access.strategy_id
        for lineage in ensemble_result.source_state_lineage
        for access in lineage.memory_accesses
    } == {producer_a.strategy_id, producer_b.strategy_id}

    extension_root = selected.root / selected.config.extension_dir
    extension_root.mkdir(parents=True, exist_ok=True)
    consumer = extension_root / "frozen_ensemble_consumer.py"
    consumer.write_text(
        "from qlibx import (\n"
        "    DecisionAction, StrategyArtifactRequirement, StrategyDraft,\n"
        "    StrategyExtensionSpec, StrategyResult,\n"
        ")\n\n"
        "STRATEGY_SPEC = StrategyExtensionSpec(strategy_id='project.frozen-ensemble')\n\n"
        "class Strategy:\n"
        "    strategy_id = STRATEGY_SPEC.strategy_id\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def artifact_requirements(self):\n"
        "        return (StrategyArtifactRequirement(\n"
        "            requirement_id='frozen.ensemble',\n"
        "            consumer_role='frozen_ensemble',\n"
        "            artifact_type='strategy_result',\n"
        "            artifact_schema_version=3,\n"
        "        ),)\n"
        "    def run(self, view):\n"
        "        source = view.artifact('frozen_ensemble', StrategyResult)\n"
        "        return StrategyDraft(\n"
        "            weights=source.weights,\n"
        "            budget_mode=source.budget_mode,\n"
        "            target_gross=source.target_gross,\n"
        "            decision_action=DecisionAction.TARGET,\n"
        "        )\n\n"
        "def create_strategy():\n"
        "    return Strategy()\n",
        encoding="utf-8",
    )
    binding = StrategyArtifactBinding(
        consumer_role="frozen_ensemble",
        artifact_id=ensemble_artifact.artifact_id,
    )
    validated = selected.validate_strategy_extension(
        StrategyExtensionValidationRequest(
            invocation_id="validate-frozen-ensemble",
            strategy_id="project.frozen-ensemble",
            module_path="frozen_ensemble_consumer.py",
            evaluation_time=at(5),
            config_fingerprint="validate-frozen-ensemble-v1",
            artifact_bindings=(binding,),
        )
    )
    assert validated.status is OutcomeStatus.COMPLETE

    downstream = selected.run_daily_registered_strategy(
        validated.result.registration_artifact_id,
        daily_spec(
            "downstream-run-b",
            "downstream-account-b",
            artifact_bindings=(binding,),
            decision_times=(at(8), at(10)),
            session_closes=(at(8), at(9), at(10), at(11)),
        ),
    )
    assert downstream.status is OutcomeStatus.COMPLETE
    assert (producer_a.call_count, producer_b.call_count) == producer_counts_before
    assert (
        tuple(
            selected.artifacts.load_envelope(item.artifact_id).result
            for item in (source_envelope_a, source_envelope_b)
        )
        == source_envelopes_before
    )

    downstream_result = downstream.result
    assert all(
        item.account_id == "downstream-account-b" for item in downstream_result.decision_intents
    )
    assert downstream_result.decision_intents[-1].account_version > 0
    assert all(
        execution.account_before.account_id == "downstream-account-b"
        and execution.account_after.account_id == "downstream-account-b"
        for execution in downstream_result.executions
    )
    assert downstream_result.final_account.account_id == "downstream-account-b"
    assert downstream_result.final_account.positions
    for result in downstream_result.strategy_results:
        assert isinstance(result, StrategyResult)
        assert result.state_identity is None
        assert result.feedback_cursor is None
        assert result.state_accesses == ()
        assert result.memory_accesses == ()
        assert tuple(item.source_artifact_id for item in result.source_state_lineage) == tuple(
            item.source_artifact_id for item in ensemble_result.source_state_lineage
        )
