from datetime import UTC, datetime
from pathlib import Path

import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account
from qlibx.analysis import SessionPerformanceEvidence
from qlibx.context import StateAccessRecord
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.extensions import StrategyExtensionValidationRequest
from qlibx.extensions.local_modules import LocalModuleLoader
from qlibx.flow.analysis import SIMULATION_CHECKPOINT_CONTRACT
from qlibx.flow.daily import SimulationCheckpoint
from qlibx.flow.strategy_extensions import (
    SESSION_PERFORMANCE_CONTRACT,
    StrategyExtensionFlow,
)

EVALUATION_TIME = datetime(2025, 1, 3, 9, tzinfo=UTC)

VALID_MODULE = '''from qlibx.data import ComponentRequirement
from qlibx.extensions import StrategyExtensionSpec
from qlibx.operations import BudgetMode, StrategyDraft, WeightEntry

STRATEGY_SPEC = StrategyExtensionSpec(strategy_id="project.valid")

class Strategy:
    strategy_id = STRATEGY_SPEC.strategy_id

    def requirements(self):
        return (
            ComponentRequirement(
                requirement_id="project.valid.value",
                semantic_role="value",
                dataset_id="market",
            ),
        )

    def run(self, view):
        latest = view.latest("value")
        selected = str(latest.iloc[-1]["instrument"])
        return StrategyDraft(
            weights=(WeightEntry(instrument=selected, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        )

def create_strategy():
    return Strategy()
'''

CUSTOM_ARTIFACT_MODULE = '''from qlibx.extensions import (
    StrategyArtifactModelSpec,
    StrategyExtensionSpec,
)
from qlibx.models import QlibxModel
from qlibx.operations import (
    BudgetMode,
    StrategyArtifactRequirement,
    StrategyDraft,
    WeightEntry,
)

class CustomSignal(QlibxModel):
    semantics: str
    instrument: str
    score: float

STRATEGY_SPEC = StrategyExtensionSpec(
    strategy_id="project.custom-artifact",
    artifact_models=(
        StrategyArtifactModelSpec(
            artifact_type="project_custom_signal",
            artifact_schema_version=1,
            model_symbol="CustomSignal",
        ),
    ),
)

class Strategy:
    strategy_id = STRATEGY_SPEC.strategy_id

    def requirements(self):
        return ()

    def artifact_requirements(self):
        return (
            StrategyArtifactRequirement(
                requirement_id="project.custom.signal",
                consumer_role="custom_signal",
                artifact_type="project_custom_signal",
                artifact_schema_version=1,
            ),
        )

    def run(self, view):
        signal = view.artifact("custom_signal", CustomSignal)
        return StrategyDraft(
            weights=(WeightEntry(instrument=signal.instrument, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            diagnostics=(signal.semantics,),
        )

def create_strategy():
    return Strategy()
'''

STATEFUL_MODULE = '''from qlibx.extensions import StrategyExtensionSpec
from qlibx.operations import BudgetMode, StrategyDraft, WeightEntry

STRATEGY_SPEC = StrategyExtensionSpec(strategy_id="project.stateful")

class Strategy:
    strategy_id = STRATEGY_SPEC.strategy_id

    def requirements(self):
        return ()

    def run(self, view):
        account = view.account_snapshot()
        feedback = view.account_feedback()
        memory = view.memory_snapshot()
        performance = view.latest_session_performance()
        return StrategyDraft(
            weights=(WeightEntry(instrument="A", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            feedback_cursor=str(feedback.next_cursor),
            proposed_memory={"performance_event": performance.event_id},
            expected_memory_version=memory.version,
        )

def create_strategy():
    return Strategy()
'''

NONDETERMINISTIC_MODULE = '''from qlibx.extensions import StrategyExtensionSpec
from qlibx.operations import BudgetMode, StrategyDraft, WeightEntry

STRATEGY_SPEC = StrategyExtensionSpec(strategy_id="project.nondeterministic")
_counter = 0

class Strategy:
    strategy_id = STRATEGY_SPEC.strategy_id

    def requirements(self):
        return ()

    def run(self, view):
        global _counter
        _counter += 1
        sign = 1.0 if _counter % 2 else -1.0
        return StrategyDraft(
            weights=(WeightEntry(instrument="A", weight=sign),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        )

def create_strategy():
    return Strategy()
'''


def project_with_market(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    source = tmp_path / "market.csv"
    source.write_text(
        "AVAILABLE,CODE,VALUE\n2025-01-02T08:00:00Z,A,1.0\n",
        encoding="utf-8",
    )
    project = QlibxProject.open(tmp_path)
    outcome = project.register_dataset(
        DatasetRegistration(
            dataset_id="market",
            source="market.csv",
            source_format=SourceFormat.CSV,
            instrument_field="CODE",
            available_at=AvailableAtField(field="AVAILABLE"),
            logical_key=("AVAILABLE", "CODE"),
            semantic_bindings={"value": "VALUE"},
            source_provenance="Strategy extension fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return project


def write_module(project: QlibxProject, name: str, source: str) -> Path:
    path = project.root / project.config.extension_dir / name
    path.write_text(source, encoding="utf-8", newline="\n")
    return path


def flow(project: QlibxProject) -> StrategyExtensionFlow:
    return StrategyExtensionFlow(
        project_root=project.root,
        extension_root=project.root / project.config.extension_dir,
        registry=project.registry_snapshot(),
        artifacts=project.artifacts,
    )


def request(
    strategy_id: str,
    module_path: str,
    **updates: object,
) -> StrategyExtensionValidationRequest:
    payload: dict[str, object] = {
        "invocation_id": f"validate-{strategy_id}",
        "strategy_id": strategy_id,
        "module_path": module_path,
        "evaluation_time": EVALUATION_TIME,
        "config_fingerprint": "strategy-extension-validation-v1",
    }
    payload.update(updates)
    return StrategyExtensionValidationRequest.model_validate(payload)


def publish_state_fixture(project: QlibxProject) -> tuple[str, str]:
    account = Account(
        account_id="validation-account",
        base_currency="KRW",
        initial_cash=10_000,
        instrument_ids=frozenset({"A"}),
    )
    snapshot = account.snapshot(evaluation_time=EVALUATION_TIME)
    checkpoint = SimulationCheckpoint(
        run_id="validation-state",
        request_fingerprint="request-v1",
        config_fingerprint="config-v1",
        profile_fingerprint="profile-v1",
        registry_fingerprint="registry-v1",
        strategy_id="project.stateful",
        event_time=EVALUATION_TIME,
        account=StateAccessRecord(
            account_id=snapshot.account_id,
            version=snapshot.version,
            feedback_cursor=snapshot.feedback_cursor,
            cash=snapshot.cash,
            nav=snapshot.nav,
            valuation_status=snapshot.valuation_status.value,
            holdings=(),
            as_of=snapshot.as_of,
            realized_pnl=snapshot.realized_pnl,
        ),
        account_checkpoint=account.checkpoint(),
        memory_snapshots=(),
        event_trace=(),
        completed_decision_ids=(),
    )
    checkpoint_outcome = project.artifacts.publish_model(
        logical_identity="validation-checkpoint",
        artifact_type=SIMULATION_CHECKPOINT_CONTRACT.artifact_type,
        artifact_schema_version=SIMULATION_CHECKPOINT_CONTRACT.artifact_schema_version,
        producer_id="tests",
        payload=checkpoint,
    )
    assert checkpoint_outcome.status is OutcomeStatus.COMPLETE

    performance = SessionPerformanceEvidence(
        event_id="performance-1",
        event_time=EVALUATION_TIME,
        account_id="validation-account",
        source_mark_event_id="mark-1",
        source_execution_event_ids=(),
        opening_account_version=0,
        closing_account_version=0,
        feedback_cursor=0,
        opening_nav=10_000,
        closing_nav=10_000,
        closing_cash=10_000,
        trade_value=0,
        transaction_cost=0,
        turnover=0,
        transaction_cost_rate=0,
        gross_return=0,
        portfolio_return=0,
    )
    performance_outcome = project.artifacts.publish_model(
        logical_identity="validation-performance",
        artifact_type=SESSION_PERFORMANCE_CONTRACT.artifact_type,
        artifact_schema_version=SESSION_PERFORMANCE_CONTRACT.artifact_schema_version,
        producer_id="tests",
        payload=performance,
    )
    assert performance_outcome.status is OutcomeStatus.COMPLETE
    return (
        checkpoint_outcome.result.artifact_id,
        performance_outcome.result.artifact_id,
    )


def test_valid_local_strategy_registers_only_after_deterministic_fixture(
    tmp_path: Path,
) -> None:
    project = project_with_market(tmp_path)
    write_module(project, "valid.py", VALID_MODULE)

    outcome = flow(project).validate_local(request("project.valid", "valid.py"))

    assert outcome.status is OutcomeStatus.COMPLETE
    assert outcome.result.registration.strategy_id == "project.valid"
    assert len(outcome.result.registration.accesses) == 1
    assert outcome.result.registration.validation_output.weights[0].instrument == "A"
    registered = flow(project).registered()
    assert len(registered) == 1
    assert registered[0].registration_artifact_id == outcome.result.registration_artifact_id


@pytest.mark.parametrize(
    ("module_path", "error_code"),
    [
        ("../outside.py", "STRATEGY_EXTENSION_MODULE_INVALID"),
        ("missing.py", "STRATEGY_EXTENSION_MODULE_INVALID"),
    ],
)
def test_invalid_module_path_never_registers(
    tmp_path: Path,
    module_path: str,
    error_code: str,
) -> None:
    project = project_with_market(tmp_path)

    outcome = flow(project).validate_local(request("project.valid", module_path))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == error_code
    assert flow(project).registered() == ()


def test_singleton_factory_is_rejected_before_registration(tmp_path: Path) -> None:
    project = project_with_market(tmp_path)
    singleton = VALID_MODULE.replace(
        "def create_strategy():\n    return Strategy()",
        "_strategy = Strategy()\n\ndef create_strategy():\n    return _strategy",
    )
    write_module(project, "singleton.py", singleton)

    outcome = flow(project).validate_local(request("project.valid", "singleton.py"))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_EXTENSION_CONTRACT_INVALID"
    assert flow(project).registered() == ()


def test_nondeterministic_output_is_rejected_without_success_artifact(
    tmp_path: Path,
) -> None:
    project = project_with_market(tmp_path)
    write_module(project, "nondeterministic.py", NONDETERMINISTIC_MODULE)

    outcome = flow(project).validate_local(
        request("project.nondeterministic", "nondeterministic.py")
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_EXTENSION_NONDETERMINISTIC"
    assert flow(project).registered() == ()
    assert not any(
        envelope.artifact_type == "strategy_result"
        for envelope in project.artifacts.list_envelopes()
    )


def test_registration_scoped_local_payload_model_is_validated_and_accessed(
    tmp_path: Path,
) -> None:
    project = project_with_market(tmp_path)
    write_module(project, "custom.py", CUSTOM_ARTIFACT_MODULE)
    loaded = LocalModuleLoader(
        project_root=project.root,
        extension_root=project.root / project.config.extension_dir,
    ).load("custom.py", module_prefix="_qlibx_local_strategy")
    model = loaded.module.CustomSignal
    publication = project.artifacts.publish_model(
        logical_identity="custom-signal",
        artifact_type="project_custom_signal",
        artifact_schema_version=1,
        producer_id="tests",
        payload=model(semantics="alpha", instrument="A", score=1.0),
    )
    assert publication.status is OutcomeStatus.COMPLETE

    outcome = flow(project).validate_local(
        request(
            "project.custom-artifact",
            "custom.py",
            artifact_bindings=(
                {
                    "consumer_role": "custom_signal",
                    "artifact_id": publication.result.artifact_id,
                },
            ),
        )
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    registration = outcome.result.registration
    assert registration.artifact_models[0].model_symbol == "CustomSignal"
    assert registration.artifact_accesses[0].artifact_id == publication.result.artifact_id
    registration_envelope = outcome.diagnostics[0]
    assert any(
        edge.dependency_id == publication.result.artifact_id
        for edge in registration_envelope.dependencies
    )


def test_local_payload_model_cannot_collide_with_builtin_contract(tmp_path: Path) -> None:
    project = project_with_market(tmp_path)
    collision = CUSTOM_ARTIFACT_MODULE.replace(
        'artifact_type="project_custom_signal"',
        'artifact_type="stored_signal_result"',
    )
    write_module(project, "collision.py", collision)

    outcome = flow(project).validate_local(
        request("project.custom-artifact", "collision.py")
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID"
    assert flow(project).registered() == ()


def test_stateful_validation_requires_and_uses_exact_frozen_state(
    tmp_path: Path,
) -> None:
    project = project_with_market(tmp_path)
    write_module(project, "stateful.py", STATEFUL_MODULE)
    missing = flow(project).validate_local(
        request("project.stateful", "stateful.py", invocation_id="missing-state")
    )
    assert missing.status is OutcomeStatus.FAILED
    assert missing.errors[0].error_code == "STRATEGY_EXTENSION_VALIDATION_FAILED"
    assert flow(project).registered() == ()

    checkpoint_id, performance_id = publish_state_fixture(project)
    validated = flow(project).validate_local(
        request(
            "project.stateful",
            "stateful.py",
            invocation_id="with-state",
            account_checkpoint_artifact_id=checkpoint_id,
            session_performance_artifact_id=performance_id,
        )
    )

    assert validated.status is OutcomeStatus.COMPLETE
    registration = validated.result.registration
    assert len(registration.state_accesses) == 1
    assert len(registration.feedback_accesses) == 1
    assert len(registration.memory_accesses) == 1
    assert len(registration.performance_accesses) == 1
    dependencies = validated.diagnostics[0].dependencies
    assert {checkpoint_id, performance_id}.issubset(
        {edge.dependency_id for edge in dependencies}
    )