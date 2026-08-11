"""Prove installed path-dependent composition and downstream Account authority."""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from producer import CountingPathProducer

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    EnsembleDefinition,
    EnsembleMemberSpec,
    OutcomeStatus,
    QlibxProject,
    StrategyArtifactBinding,
    StrategyExtensionValidationRequest,
    StrategyInvocation,
    StrategyResult,
)
from qlibx.contracts import BudgetMode
from qlibx.data import DatasetRegistration
from qlibx.evidence import ArtifactEnvelope
from qlibx.execution import CostRule, KrxExchangeConfig, Side, StockInstrument

KST = ZoneInfo("Asia/Seoul")


def at(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


def require_complete(outcome: object, label: str) -> object:
    if outcome.status is not OutcomeStatus.COMPLETE:  # type: ignore[attr-defined]
        raise RuntimeError(f"{label} failed: {outcome.errors}")  # type: ignore[attr-defined]
    return outcome


def install_consumer_source(sample_dir: Path, project: QlibxProject) -> str:
    source = sample_dir / "consumer_strategy.py"
    extension_root = project.root / project.config.extension_dir
    extension_root.mkdir(parents=True, exist_ok=True)
    target = extension_root / "sample_frozen_ensemble_consumer.py"
    payload = source.read_bytes()
    if target.exists():
        if target.read_bytes() != payload:
            raise RuntimeError(
                "refusing to overwrite modified qlibx_extensions/sample_frozen_ensemble_consumer.py"
            )
    else:
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return target.relative_to(extension_root).as_posix()


def daily_spec(
    run_id: str,
    account_id: str,
    strategy_fingerprint: str,
    *,
    session_closes: tuple[datetime, ...],
    artifact_bindings: tuple[StrategyArtifactBinding, ...] = (),
) -> DailySimulationSpec:
    return DailySimulationSpec(
        run_id=run_id,
        strategy_fingerprint=strategy_fingerprint,
        account=DailyAccountSeed(
            account_id=account_id,
            base_currency="KRW",
            initial_cash=10_000,
        ),
        instruments=tuple(
            StockInstrument(
                instrument_id=instrument,
                exchange_id="XKRX",
                currency="KRW",
                lot_size=1,
            )
            for instrument in ("A000001", "A000002")
        ),
        exchange=KrxExchangeConfig(
            schedule_version="sample-composition-cost-v1",
            cost_rules=tuple(
                CostRule(
                    rule_id=f"sample-stock-{side.value.lower()}",
                    product_type="stock",
                    side=side,
                    effective_from=datetime(2020, 1, 1, tzinfo=KST),
                    rate=0,
                    minimum_cost=0,
                )
                for side in Side
            ),
        ),
        market=DailyMarketBinding(market_dataset_id="sample-composition-market"),
        session_closes=session_closes,
        artifact_bindings=artifact_bindings,
    )


def final_strategy_artifact(outcome: object) -> tuple[StrategyResult, ArtifactEnvelope]:
    result = outcome.result  # type: ignore[attr-defined]
    strategy_result = result.strategy_results[-1]
    if not isinstance(strategy_result, StrategyResult):
        raise RuntimeError("daily source did not publish strategy_result:v3")
    envelope = next(
        item
        for item in result.artifacts
        if item.artifact_type == "strategy_result"
        and item.logical_identity == f"strategy:{strategy_result.invocation_id}"
    )
    return strategy_result, envelope


def source_fingerprints(
    project: QlibxProject,
    source_ids: tuple[str, ...],
) -> dict[str, str]:
    loaded = tuple(project.artifacts.load_envelope(artifact_id) for artifact_id in source_ids)
    if any(item.status is not OutcomeStatus.COMPLETE for item in loaded):
        raise RuntimeError("failed to reload exact source envelopes")
    return {item.result.artifact_id: item.result.content_hash for item in loaded}


def main(project_root: Path) -> dict[str, object]:
    sample_dir = Path(__file__).resolve().parent
    project = QlibxProject.open(project_root)
    registration_payload = yaml.safe_load(
        (sample_dir / "registration.yaml").read_text(encoding="utf-8")
    )
    if project.registry_snapshot().get("sample-composition-market") is None:
        require_complete(
            project.register_dataset(
                DatasetRegistration.model_validate_json(
                    json.dumps(registration_payload, ensure_ascii=False)
                )
            ),
            "sample composition registration",
        )

    producer_source_hash = hashlib.sha256((sample_dir / "producer.py").read_bytes()).hexdigest()
    producer_a = CountingPathProducer("a", "A000001")
    producer_b = CountingPathProducer("b", "A000002")
    source_sessions = (at(2), at(3), at(4), at(5))
    source_a = require_complete(
        project.run_daily(
            producer_a,
            daily_spec(
                "sample-composition-source-a",
                "sample-source-account-a",
                f"{producer_source_hash}:a",
                session_closes=source_sessions,
            ),
        ),
        "source A daily run",
    )
    source_b = require_complete(
        project.run_daily(
            producer_b,
            daily_spec(
                "sample-composition-source-b",
                "sample-source-account-b",
                f"{producer_source_hash}:b",
                session_closes=source_sessions,
            ),
        ),
        "source B daily run",
    )
    source_result_a, source_envelope_a = final_strategy_artifact(source_a)
    source_result_b, source_envelope_b = final_strategy_artifact(source_b)
    source_ids = tuple(sorted((source_envelope_a.artifact_id, source_envelope_b.artifact_id)))
    fingerprints_before = source_fingerprints(project, source_ids)
    producer_calls_before = {
        producer_a.strategy_id: producer_a.call_count,
        producer_b.strategy_id: producer_b.call_count,
    }

    composed = require_complete(
        project.run_ensemble(
            EnsembleDefinition(
                strategy_id="sample.path-dependent-ensemble",
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
                invocation_id="sample-path-dependent-ensemble",
                evaluation_time=at(5),
                config_fingerprint="sample-path-dependent-ensemble-v1",
            ),
        ),
        "frozen Ensemble composition",
    )
    ensemble_result = composed.result.strategy.result
    ensemble_artifact = composed.result.strategy.artifact

    module_path = install_consumer_source(sample_dir, project)
    binding = StrategyArtifactBinding(
        consumer_role="frozen_ensemble",
        artifact_id=ensemble_artifact.artifact_id,
    )
    validated = require_complete(
        project.validate_strategy_extension(
            StrategyExtensionValidationRequest(
                invocation_id="sample-validate-frozen-ensemble",
                strategy_id="sample.frozen-ensemble-consumer",
                module_path=module_path,
                evaluation_time=at(5),
                config_fingerprint="sample-validate-frozen-ensemble-v1",
                artifact_bindings=(binding,),
            )
        ),
        "frozen Ensemble consumer validation",
    )
    downstream = require_complete(
        project.run_daily_registered_strategy(
            validated.result.registration_artifact_id,
            daily_spec(
                "sample-composition-downstream-b",
                "sample-downstream-account-b",
                "sample-frozen-ensemble-consumer-v1",
                session_closes=(at(8), at(9), at(10), at(11)),
                artifact_bindings=(binding,),
            ),
        ),
        "Account B registered daily run",
    )

    producer_calls_after = {
        producer_a.strategy_id: producer_a.call_count,
        producer_b.strategy_id: producer_b.call_count,
    }
    fingerprints_after = source_fingerprints(project, source_ids)
    lineage = tuple(
        {
            "source_artifact_id": item.source_artifact_id,
            "source_strategy_id": item.source_strategy_id,
            "declared_state_identity": item.declared_state_identity,
            "declared_feedback_cursor": item.declared_feedback_cursor,
            "account_ids": sorted(access.account_id for access in item.state_accesses),
            "memory": [
                {
                    "strategy_id": access.strategy_id,
                    "version": access.version,
                    "feedback_cursor": access.feedback_cursor,
                }
                for access in item.memory_accesses
            ],
        }
        for item in ensemble_result.source_state_lineage
    )
    downstream_result = downstream.result
    downstream_lineage_ids = [
        [item.source_artifact_id for item in result.source_state_lineage]
        for result in downstream_result.strategy_results
    ]
    return {
        "module_path": module_path,
        "source_artifact_ids": list(source_ids),
        "source_content_hashes_before": fingerprints_before,
        "source_content_hashes_after": fingerprints_after,
        "source_state_identities": [
            source_result_a.state_identity,
            source_result_b.state_identity,
        ],
        "producer_calls_before_composition": producer_calls_before,
        "producer_calls_after_downstream": producer_calls_after,
        "ensemble_artifact_id": ensemble_artifact.artifact_id,
        "ensemble_state_identity": ensemble_result.state_identity,
        "ensemble_source_state_lineage": lineage,
        "registration_artifact_id": validated.result.registration_artifact_id,
        "downstream_account_id": downstream_result.final_account.account_id,
        "downstream_decision_account_ids": [
            item.account_id for item in downstream_result.decision_intents
        ],
        "downstream_decision_account_versions": [
            item.account_version for item in downstream_result.decision_intents
        ],
        "downstream_execution_account_ids": [
            [item.account_before.account_id, item.account_after.account_id]
            for item in downstream_result.executions
        ],
        "downstream_direct_state_access_counts": [
            len(item.state_accesses) for item in downstream_result.strategy_results
        ],
        "downstream_direct_memory_access_counts": [
            len(item.memory_accesses) for item in downstream_result.strategy_results
        ],
        "downstream_source_lineage_ids": downstream_lineage_ids,
        "final_positions": {
            item.instrument_id: item.quantity for item in downstream_result.final_account.positions
        },
        "artifact_types": sorted(
            {item.artifact_type for item in project.artifacts.list_envelopes()}
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))
