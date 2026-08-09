import hashlib
import multiprocessing
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.account import Account, FillBatch, MarkBatch, StrategyMemoryStore
from qlibx.errors import CommitStatus
from qlibx.flow import DailyExecutionFlow, DailyExecutionProfile, DailyRunRequest
from qlibx.flow.recovery import (
    SIMULATION_RECOVERY_POINT_CONTRACT,
    SimulationRecoveryPoint,
    SimulationRecoveryPointV1,
)
from qlibx.kernel import BacktestClock
from tests.acceptance.real_dw_support import (
    ActualStateMomentumStrategy,
    RealDwProject,
    close_at,
    configured_exchange,
    create_real_dw_project,
    initial_account,
    run_real_daily_flow,
)

RUN_ID = "gap-recovery-real-dw"
CRASH_EXIT_CODE = 97


def _terminate(marker: Path) -> None:
    marker.write_text("crashed", encoding="utf-8")
    os._exit(CRASH_EXIT_CODE)


@dataclass(frozen=True, slots=True)
class RecoveryBaseline:
    checkpoint: object
    final_account: object
    result_signature: tuple[tuple[str, ...], ...]
    domain_artifacts: tuple[tuple[str, str, str], ...]


class _CrashAfterArtifact:
    def __init__(
        self,
        delegate: object,
        artifact_type: str,
        marker: Path,
        occurrence: int = 1,
    ) -> None:
        self._delegate = delegate
        self._artifact_type = artifact_type
        self._marker = marker
        self._occurrence = occurrence
        self._seen = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    def publish_model(self, **kwargs: object) -> object:
        outcome = self._delegate.publish_model(**kwargs)  # type: ignore[attr-defined]
        if (
            kwargs["artifact_type"] == self._artifact_type
            and outcome.status is OutcomeStatus.COMPLETE
        ):
            self._seen += 1
            if self._seen == self._occurrence:
                _terminate(self._marker)
        return outcome


class _CrashAfterAccountCommit(Account):
    def __init__(
        self,
        crash_change: type[FillBatch] | type[MarkBatch],
        marker: Path,
    ) -> None:
        super().__init__(
            account_id="real-dw-account",
            base_currency="KRW",
            initial_cash=10_000_000,
            instrument_ids=frozenset({"A000660", "A005930"}),
        )
        self._crash_change = crash_change
        self._marker = marker
        self._crashed = False

    def commit(self, change: object, *, expected_version: int) -> object:
        committed = super().commit(change, expected_version=expected_version)  # type: ignore[arg-type]
        if isinstance(change, self._crash_change) and not self._crashed:
            self._crashed = True
            _terminate(self._marker)
        return committed


class _CrashAfterMemoryCommit(StrategyMemoryStore):
    def __init__(self, marker: Path) -> None:
        super().__init__()
        self._marker = marker

    def commit(self, **kwargs: object) -> object:
        committed = super().commit(**kwargs)  # type: ignore[arg-type]
        _terminate(self._marker)
        return committed


def _request(*, config_fingerprint: str = "real-dw-actual-state-momentum-v1") -> DailyRunRequest:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3, 4, 5))
    return DailyRunRequest(
        run_id=RUN_ID,
        config_fingerprint=config_fingerprint,
        decision_times=(sessions[0], sessions[2]),
        session_closes=sessions,
    )


def _profile() -> DailyExecutionProfile:
    return DailyExecutionProfile(
        market_dataset_id="dw-real-market",
        execution_price_role="execution_price",
        valuation_price_role="valuation_price",
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _publish_v1_anchor(case: RealDwProject, request: DailyRunRequest):
    registry = case.project.registry_snapshot()
    profile = _profile()
    point = SimulationRecoveryPointV1(
        run_id=request.run_id,
        request_fingerprint=_fingerprint(request.compatibility_json()),
        config_fingerprint=request.config_fingerprint,
        profile_fingerprint=_fingerprint(profile.model_dump_json()),
        registry_fingerprint=_fingerprint(
            "|".join(
                item.registration_identity
                for item in sorted(registry.datasets, key=lambda value: value.dataset_id)
            )
        ),
        strategy_id=ActualStateMomentumStrategy.strategy_id,
        sequence=0,
        account_checkpoint=initial_account().checkpoint(),
    )
    published = case.project.artifacts.publish_model(
        logical_identity=f"simulation-recovery:{request.run_id}:00000000:initial",
        artifact_type="simulation_recovery_point",
        artifact_schema_version=1,
        producer_id=profile.profile_id,
        payload=point,
    )
    assert published.status is OutcomeStatus.COMPLETE
    return published.result, point


def _result_signature(result: object) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(item.model_dump_json() for item in collection)
        for collection in (
            result.strategy_results,  # type: ignore[attr-defined]
            result.decision_intents,  # type: ignore[attr-defined]
            result.executions,  # type: ignore[attr-defined]
            result.marks,  # type: ignore[attr-defined]
            result.session_performance,  # type: ignore[attr-defined]
            result.monitors,  # type: ignore[attr-defined]
            result.memory_commits,  # type: ignore[attr-defined]
        )
    )


def _domain_artifacts(case: RealDwProject) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                envelope.logical_identity,
                envelope.artifact_type,
                envelope.artifact_id,
            )
            for envelope in case.project.artifacts.list_envelopes()
            if RUN_ID in envelope.logical_identity
            and envelope.artifact_type != "simulation_recovery_point"
        )
    )


def _crash_worker(project_root: str, crash_point: str) -> None:
    root = Path(project_root)
    marker = root / f".{crash_point}.crashed"
    project = QlibxProject.open(root)
    account: Account = initial_account()
    memory: StrategyMemoryStore = StrategyMemoryStore()
    artifacts: object = project.artifacts
    if crash_point == "decision_recovery_published":
        artifacts = _CrashAfterArtifact(
            artifacts,
            "simulation_recovery_point",
            marker,
            occurrence=2,
        )
    elif crash_point == "account_fill_committed":
        account = _CrashAfterAccountCommit(FillBatch, marker)
    elif crash_point == "execution_artifact_published":
        artifacts = _CrashAfterArtifact(artifacts, "execution_result", marker)
    elif crash_point == "account_mark_committed":
        account = _CrashAfterAccountCommit(MarkBatch, marker)
    elif crash_point == "strategy_memory_committed":
        memory = _CrashAfterMemoryCommit(marker)
    elif crash_point == "final_checkpoint_published":
        artifacts = _CrashAfterArtifact(artifacts, "simulation_checkpoint", marker)
    else:
        os._exit(98)

    sessions = _request().session_closes
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=project.registry_snapshot(),
        artifacts=artifacts,  # type: ignore[arg-type]
        exchange=configured_exchange(),
        account=account,
        memory=memory,
        profile=_profile(),
    )
    flow.run(ActualStateMomentumStrategy(), _request())
    os._exit(99)


@pytest.fixture(scope="session")
def recovery_baseline(
    tmp_path_factory: pytest.TempPathFactory,
    bounded_real_dw_source: Path,
) -> RecoveryBaseline:
    case = create_real_dw_project(
        tmp_path_factory.mktemp("recovery-baseline"),
        bounded_real_dw_source,
    )
    outcome = run_real_daily_flow(case, run_id=RUN_ID)
    assert outcome.status is OutcomeStatus.COMPLETE
    return RecoveryBaseline(
        checkpoint=outcome.result.checkpoint,
        final_account=outcome.result.final_account,
        result_signature=_result_signature(outcome.result),
        domain_artifacts=_domain_artifacts(case),
    )


@pytest.mark.parametrize(
    "crash_point",
    (
        "decision_recovery_published",
        "account_fill_committed",
        "execution_artifact_published",
        "account_mark_committed",
        "strategy_memory_committed",
        "final_checkpoint_published",
    ),
)
def test_gap_recovery_001_process_crash_matrix_real_dw(
    tmp_path: Path,
    bounded_real_dw_source: Path,
    recovery_baseline: RecoveryBaseline,
    crash_point: str,
) -> None:
    case = create_real_dw_project(tmp_path / crash_point, bounded_real_dw_source)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_worker,
        args=(str(case.root), crash_point),
    )
    process.start()
    process.join(timeout=90)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        pytest.fail(f"crash worker did not terminate: {crash_point}")
    marker = case.root / f".{crash_point}.crashed"
    assert process.exitcode not in (None, 0), crash_point
    assert marker.read_text(encoding="utf-8") == "crashed"

    request = _request()
    resumed = DailyExecutionFlow(
        clock=BacktestClock(request.session_closes[0]),
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
        exchange=configured_exchange(),
        account=initial_account(),
        memory=StrategyMemoryStore(),
        profile=_profile(),
    ).run(ActualStateMomentumStrategy(), request, resume=True)

    assert resumed.status is OutcomeStatus.COMPLETE
    assert resumed.result.final_account == recovery_baseline.final_account
    assert resumed.result.checkpoint == recovery_baseline.checkpoint
    assert _result_signature(resumed.result) == recovery_baseline.result_signature
    journal = resumed.result.checkpoint.account_checkpoint.journal
    assert len({entry.event_id for entry in journal}) == len(journal)
    memory = resumed.result.checkpoint.memory_snapshots
    assert len({item.commit_id for item in memory}) == len(memory)
    assert _domain_artifacts(case) == recovery_baseline.domain_artifacts


def test_gap_recovery_001_changed_identity_requires_explicit_branch(
    real_dw_case: RealDwProject,
) -> None:
    completed = run_real_daily_flow(real_dw_case, run_id=RUN_ID)
    assert completed.status is OutcomeStatus.COMPLETE

    account = initial_account("identity-guard-probe")
    memory = StrategyMemoryStore()
    account_before = account.checkpoint()
    memory_before = memory.checkpoint()
    changed = _request(config_fingerprint="changed-config-requires-new-run")
    outcome = DailyExecutionFlow(
        clock=BacktestClock(changed.session_closes[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(),
        account=account,
        memory=memory,
        profile=_profile(),
    ).run(ActualStateMomentumStrategy(), changed, resume=True)

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "RESUME_BRANCH_REQUIRED"
    assert outcome.errors[0].commit_status is CommitStatus.NONE
    assert account.checkpoint() == account_before
    assert memory.checkpoint() == memory_before


def test_v1_anchor_resumes_and_bridges_to_v2(
    tmp_path: Path,
    bounded_real_dw_source: Path,
) -> None:
    case = create_real_dw_project(tmp_path / "v1-bridge", bounded_real_dw_source)
    request = _request()
    anchor, _ = _publish_v1_anchor(case, request)

    resumed = DailyExecutionFlow(
        clock=BacktestClock(request.session_closes[0]),
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
        exchange=configured_exchange(),
        account=initial_account(),
        memory=StrategyMemoryStore(),
        profile=_profile(),
    ).run(ActualStateMomentumStrategy(), request, resume=True)

    assert resumed.status is OutcomeStatus.COMPLETE
    envelopes = tuple(
        sorted(
            (
                item
                for item in case.project.artifacts.list_envelopes()
                if item.artifact_type == "simulation_recovery_point"
                and item.logical_identity.startswith(
                    f"simulation-recovery:{request.run_id}:"
                )
            ),
            key=lambda item: item.logical_identity,
        )
    )
    assert envelopes[0].artifact_schema_version == 1
    first_v2 = next(item for item in envelopes if item.artifact_schema_version == 2)
    loaded = case.project.artifacts.load_model(
        first_v2.artifact_id,
        SIMULATION_RECOVERY_POINT_CONTRACT,
    )
    assert loaded.status is OutcomeStatus.COMPLETE
    assert loaded.result.payload.previous_recovery_artifact_id == anchor.artifact_id


def test_v2_chain_sequence_gap_is_rejected(
    tmp_path: Path,
    bounded_real_dw_source: Path,
) -> None:
    case = create_real_dw_project(tmp_path / "v2-gap", bounded_real_dw_source)
    request = _request()
    anchor, v1 = _publish_v1_anchor(case, request)
    checkpoint = v1.account_checkpoint
    gap = SimulationRecoveryPoint(
        run_id=v1.run_id,
        request_fingerprint=v1.request_fingerprint,
        config_fingerprint=v1.config_fingerprint,
        profile_fingerprint=v1.profile_fingerprint,
        registry_fingerprint=v1.registry_fingerprint,
        strategy_id=v1.strategy_id,
        sequence=2,
        previous_recovery_artifact_id=anchor.artifact_id,
        account_id=checkpoint.account_id,
        account_base_currency=checkpoint.base_currency,
        account_cash=checkpoint.cash,
        account_instrument_ids=checkpoint.instrument_ids,
        account_positions=checkpoint.positions,
        account_version=checkpoint.version,
    )
    published = case.project.artifacts.publish_model(
        logical_identity=f"simulation-recovery:{request.run_id}:00000002:gap",
        artifact_type="simulation_recovery_point",
        artifact_schema_version=2,
        producer_id=_profile().profile_id,
        payload=gap,
    )
    assert published.status is OutcomeStatus.COMPLETE

    outcome = DailyExecutionFlow(
        clock=BacktestClock(request.session_closes[0]),
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
        exchange=configured_exchange(),
        account=initial_account(),
        memory=StrategyMemoryStore(),
        profile=_profile(),
    ).run(ActualStateMomentumStrategy(), request, resume=True)

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "RECOVERY_CHAIN_SEQUENCE_GAP"
