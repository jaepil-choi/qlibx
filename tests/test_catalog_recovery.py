import json
import os
from multiprocessing.context import BaseContext
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from qlibx import OutcomeStatus, QlibxModel, QlibxProject
from qlibx.evidence import (
    ArtifactContract,
    LocalArtifactBackend,
    PublicationPhase,
    RecoveryAction,
)


class WeightPayload(QlibxModel):
    weights: dict[str, float]


CONTRACT = ArtifactContract(
    artifact_type="catalog_test_weights",
    artifact_schema_version=1,
    payload_model=WeightPayload,
)
CRASH_EXIT = 73


def _backend(root: Path, *, lock_timeout_seconds: float = 5.0) -> LocalArtifactBackend:
    return LocalArtifactBackend(
        root / ".qlibx" / "catalog.duckdb",
        root / ".qlibx" / "artifacts",
        lock_timeout_seconds=lock_timeout_seconds,
    )


def _publish(backend: LocalArtifactBackend, value: float):
    return backend.publish_model(
        logical_identity="catalog:concurrent",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=CONTRACT.artifact_schema_version,
        producer_id="tests.catalog",
        payload=WeightPayload(weights={"A005930": value}),
    )


def _publish_worker(
    root: str,
    value: float,
    start: Any,
    results: Any,
) -> None:
    start.wait(10)
    outcome = _publish(_backend(Path(root)), value)
    results.put(
        {
            "status": outcome.status.value,
            "artifact_id": getattr(outcome.result, "artifact_id", None),
            "error_code": outcome.errors[0].error_code if outcome.errors else None,
        }
    )


def _run_concurrent(
    context: BaseContext,
    root: Path,
    values: tuple[float, float],
) -> tuple[dict[str, object], dict[str, object]]:
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_publish_worker,
            args=(str(root), value, start, results),
        )
        for value in values
    ]
    for process in processes:
        process.start()
    start.set()
    observed = tuple(results.get(timeout=20) for _ in processes)
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    return observed  # type: ignore[return-value]


class _CrashAfterStageBackend(LocalArtifactBackend):
    def _write_staged_payload(self, *args: object, **kwargs: object) -> None:
        super()._write_staged_payload(*args, **kwargs)
        os._exit(CRASH_EXIT)


class _CrashAfterPromoteBackend(LocalArtifactBackend):
    def _promote_staged_payload(self, *args: object, **kwargs: object) -> None:
        super()._promote_staged_payload(*args, **kwargs)
        os._exit(CRASH_EXIT)


class _CrashAfterCommitBackend(LocalArtifactBackend):
    def _commit_publication(self, *args: object, **kwargs: object) -> None:
        super()._commit_publication(*args, **kwargs)
        os._exit(CRASH_EXIT)


def _crash_worker(root: str, crash_point: str) -> None:
    backend_type = {
        "staged": _CrashAfterStageBackend,
        "promoted": _CrashAfterPromoteBackend,
        "committed": _CrashAfterCommitBackend,
    }[crash_point]
    backend = backend_type(
        Path(root) / ".qlibx" / "catalog.duckdb",
        Path(root) / ".qlibx" / "artifacts",
    )
    _publish(backend, 0.5)


def _hold_lock(root: str, ready: Any, release: Any) -> None:
    backend = _backend(Path(root))
    with backend._writer_lock():
        ready.set()
        release.wait(10)


def test_same_candidate_concurrent_writers_are_idempotent(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    context = pytest.importorskip("multiprocessing").get_context("spawn")

    observed = _run_concurrent(context, tmp_path, (0.5, 0.5))

    assert {item["status"] for item in observed} == {OutcomeStatus.COMPLETE.value}
    assert len({item["artifact_id"] for item in observed}) == 1
    assert len(_backend(tmp_path).list_envelopes()) == 1


def test_different_candidate_concurrent_writers_conflict(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    context = pytest.importorskip("multiprocessing").get_context("spawn")

    observed = _run_concurrent(context, tmp_path, (0.5, 0.6))

    assert sorted(item["status"] for item in observed) == ["complete", "failed"]
    assert {item["error_code"] for item in observed} == {
        None,
        "ARTIFACT_IDENTITY_CONFLICT",
    }
    assert len(_backend(tmp_path).list_envelopes()) == 1


@pytest.mark.parametrize("crash_point", ["staged", "promoted"])
def test_precommit_crash_is_hidden_and_recoverable(
    tmp_path: Path,
    crash_point: str,
) -> None:
    QlibxProject.init(tmp_path, apply=True)
    context = pytest.importorskip("multiprocessing").get_context("spawn")
    process = context.Process(target=_crash_worker, args=(str(tmp_path), crash_point))
    process.start()
    process.join(timeout=20)
    assert process.exitcode == CRASH_EXIT

    backend = _backend(tmp_path)
    assert backend.list_envelopes() == ()
    audit_before = backend.audit_publications()
    assert audit_before.status is OutcomeStatus.COMPLETE
    assert audit_before.result[-1].phase in {
        PublicationPhase.STAGED,
        PublicationPhase.PAYLOAD_STAGED,
    }

    recovered = backend.recover_publications()
    assert recovered.status is OutcomeStatus.COMPLETE
    assert recovered.result.records[0].action is RecoveryAction.REMOVED_ABANDONED
    assert backend.list_envelopes() == ()

    retry = _publish(backend, 0.5)
    assert retry.status is OutcomeStatus.COMPLETE
    assert backend.load_model(retry.result.artifact_id, CONTRACT).status is OutcomeStatus.COMPLETE
    phases = tuple(event.phase for event in backend.audit_publications().result)
    assert PublicationPhase.RECOVERED_ABANDONED in phases
    assert PublicationPhase.CATALOG_COMMITTED in phases


def test_postcommit_crash_replays_idempotently(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    context = pytest.importorskip("multiprocessing").get_context("spawn")
    process = context.Process(target=_crash_worker, args=(str(tmp_path), "committed"))
    process.start()
    process.join(timeout=20)
    assert process.exitcode == CRASH_EXIT

    backend = _backend(tmp_path)
    committed = backend.list_envelopes()
    assert len(committed) == 1
    replay = _publish(backend, 0.5)
    assert replay.status is OutcomeStatus.COMPLETE
    assert replay.result.artifact_id == committed[0].artifact_id
    assert backend.recover_publications().result.records == ()


def test_writer_lock_timeout_is_typed(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    context = pytest.importorskip("multiprocessing").get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_lock, args=(str(tmp_path), ready, release))
    holder.start()
    assert ready.wait(10)
    try:
        outcome = _publish(_backend(tmp_path, lock_timeout_seconds=0.05), 0.5)
    finally:
        release.set()
        holder.join(timeout=20)
    assert holder.exitcode == 0
    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "CATALOG_WRITE_LOCK_TIMEOUT"
    assert _backend(tmp_path).list_envelopes() == ()


def test_unknown_catalog_schema_fails_without_mutation(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    backend = _backend(tmp_path)
    first = _publish(backend, 0.5)
    assert first.status is OutcomeStatus.COMPLETE
    catalog_path = tmp_path / ".qlibx" / "catalog.duckdb"
    connection = duckdb.connect(str(catalog_path))
    try:
        connection.execute("UPDATE catalog_metadata SET schema_version = 99")
    finally:
        connection.close()

    rejected = backend.publish_model(
        logical_identity="catalog:unknown-schema",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=1,
        producer_id="tests.catalog",
        payload=WeightPayload(weights={"A000660": 0.5}),
    )

    assert rejected.status is OutcomeStatus.FAILED
    assert rejected.errors[0].error_code == "CATALOG_SCHEMA_UNSUPPORTED"
    connection = duckdb.connect(str(catalog_path), read_only=True)
    try:
        assert connection.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1
    finally:
        connection.close()


def test_legacy_catalog_schema_is_adopted_on_first_write(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    catalog_path = tmp_path / ".qlibx" / "catalog.duckdb"
    connection = duckdb.connect(str(catalog_path))
    try:
        connection.execute(
            """
            CREATE TABLE artifacts (
                artifact_id VARCHAR PRIMARY KEY,
                logical_identity VARCHAR UNIQUE NOT NULL,
                artifact_type VARCHAR NOT NULL,
                artifact_schema_version INTEGER NOT NULL,
                producer_id VARCHAR NOT NULL,
                content_hash VARCHAR NOT NULL,
                payload_format VARCHAR NOT NULL,
                payload_path VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                envelope_json VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE artifact_edges (
                artifact_id VARCHAR NOT NULL,
                dependency_id VARCHAR NOT NULL,
                consumer_role VARCHAR NOT NULL,
                edge_json VARCHAR NOT NULL,
                PRIMARY KEY (artifact_id, dependency_id, consumer_role)
            )
            """
        )
    finally:
        connection.close()

    outcome = _publish(_backend(tmp_path), 0.5)

    assert outcome.status is OutcomeStatus.COMPLETE
    connection = duckdb.connect(str(catalog_path), read_only=True)
    try:
        assert connection.execute("SELECT schema_version FROM catalog_metadata").fetchall() == [
            (1,)
        ]
        assert connection.execute("SELECT count(*) FROM publication_events").fetchone()[0] == 4
    finally:
        connection.close()


def test_unknown_publication_event_schema_fails_without_mutation(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    backend = _backend(tmp_path)
    assert _publish(backend, 0.5).status is OutcomeStatus.COMPLETE
    catalog_path = tmp_path / ".qlibx" / "catalog.duckdb"
    connection = duckdb.connect(str(catalog_path))
    try:
        event_json = json.loads(
            connection.execute(
                "SELECT event_json FROM publication_events WHERE event_order = 1"
            ).fetchone()[0]
        )
        event_json["event_schema_version"] = 99
        connection.execute(
            "UPDATE publication_events SET event_json = ? WHERE event_order = 1",
            [json.dumps(event_json)],
        )
    finally:
        connection.close()

    audit = backend.audit_publications()
    rejected = backend.publish_model(
        logical_identity="catalog:event-schema",
        artifact_type=CONTRACT.artifact_type,
        artifact_schema_version=1,
        producer_id="tests.catalog",
        payload=WeightPayload(weights={"A000660": 0.5}),
    )

    assert audit.status is OutcomeStatus.FAILED
    assert audit.errors[0].error_code == "CATALOG_SCHEMA_UNSUPPORTED"
    assert rejected.status is OutcomeStatus.FAILED
    assert rejected.errors[0].error_code == "CATALOG_SCHEMA_UNSUPPORTED"
    connection = duckdb.connect(str(catalog_path), read_only=True)
    try:
        assert connection.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1
    finally:
        connection.close()


def test_catalog_scenarios_are_owned_by_yaml() -> None:
    registry_path = Path(__file__).parent / "scenarios" / "catalog_recovery.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert registry["gap_id"] == "GAP-CATALOG-001"
    assert {scenario["id"] for scenario in registry["scenarios"]} == {
        "CATALOG-CONCURRENT-IDEMPOTENT-001",
        "CATALOG-CONCURRENT-CONFLICT-001",
        "CATALOG-CRASH-STAGED-001",
        "CATALOG-CRASH-PROMOTED-001",
        "CATALOG-CRASH-COMMITTED-001",
        "CATALOG-LOCK-TIMEOUT-001",
        "CATALOG-SCHEMA-001",
        "CATALOG-LEGACY-MIGRATION-001",
        "CATALOG-EVENT-SCHEMA-001",
    }
