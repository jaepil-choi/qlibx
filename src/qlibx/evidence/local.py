"""Atomic local artifact publication backed by DuckDB."""

import hashlib
import os
from pathlib import Path
from typing import TypeVar

import duckdb

from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence.contracts import (
    ArtifactContract,
    ArtifactEnvelope,
    ArtifactStatus,
    DependencyEdge,
    LoadedArtifact,
    PayloadFormat,
)
from qlibx.models import QlibxModel

PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class LocalArtifactBackend:
    """Append-only artifact publisher and typed loader."""

    def __init__(self, catalog_path: Path, artifact_dir: Path) -> None:
        self._catalog_path = catalog_path.resolve()
        self._artifact_dir = artifact_dir.resolve()

    def publish_model(
        self,
        *,
        logical_identity: str,
        artifact_type: str,
        artifact_schema_version: int,
        producer_id: str,
        payload: QlibxModel,
        status: ArtifactStatus = ArtifactStatus.COMPLETE,
        dependencies: tuple[DependencyEdge, ...] = (),
    ) -> OperationOutcome:
        payload_bytes = payload.model_dump_json().encode("utf-8")
        content_hash = digest(payload_bytes)
        artifact_seed = (
            f"{logical_identity}:{artifact_type}:{artifact_schema_version}:{content_hash}"
        ).encode()
        artifact_id = f"artifact-{digest(artifact_seed)[:32]}"
        envelope = ArtifactEnvelope(
            artifact_id=artifact_id,
            logical_identity=logical_identity,
            artifact_type=artifact_type,
            artifact_schema_version=artifact_schema_version,
            producer_id=producer_id,
            content_hash=content_hash,
            payload_format=PayloadFormat.JSON,
            status=status,
            dependencies=dependencies,
        )
        self._prepare_storage()
        connection = self._connect()
        try:
            existing = connection.execute(
                """
                SELECT artifact_id, artifact_type, artifact_schema_version, content_hash,
                       envelope_json
                FROM artifacts WHERE logical_identity = ?
                """,
                [logical_identity],
            ).fetchone()
            if existing:
                if (
                    existing[1] == artifact_type
                    and existing[2] == artifact_schema_version
                    and existing[3] == content_hash
                ):
                    current = ArtifactEnvelope.model_validate_json(existing[4])
                    return OperationOutcome(status=OutcomeStatus.COMPLETE, result=current)
                return self._failure(
                    logical_identity,
                    "artifact.publish.identity_conflict",
                    "ARTIFACT_IDENTITY_CONFLICT",
                    context={
                        "logical_identity": logical_identity,
                        "existing_artifact_id": existing[0],
                    },
                    retry=("choose a new logical identity or retain the existing artifact",),
                )

            payload_path = self._payload_path(envelope)
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = payload_path.with_name(f".{payload_path.name}.{os.getpid()}.tmp")
            temporary.write_bytes(payload_bytes)
            try:
                os.rename(temporary, payload_path)
            except FileExistsError:
                temporary.unlink(missing_ok=True)

            try:
                connection.execute("BEGIN TRANSACTION")
                connection.execute(
                    """
                    INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        envelope.artifact_id,
                        envelope.logical_identity,
                        envelope.artifact_type,
                        envelope.artifact_schema_version,
                        envelope.producer_id,
                        envelope.content_hash,
                        envelope.payload_format.value,
                        str(payload_path),
                        envelope.status.value,
                        envelope.model_dump_json(),
                    ],
                )
                for edge in dependencies:
                    connection.execute(
                        "INSERT INTO artifact_edges VALUES (?, ?, ?, ?)",
                        [
                            envelope.artifact_id,
                            edge.dependency_id,
                            edge.consumer_role,
                            edge.model_dump_json(),
                        ],
                    )
                connection.execute("COMMIT")
            except Exception as exc:
                connection.execute("ROLLBACK")
                return self._failure(
                    logical_identity,
                    "artifact.publish.catalog_commit",
                    "CATALOG_COMMIT_FAILED",
                    context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                    retry=("retry publication with the same frozen candidate",),
                )
            return OperationOutcome(status=OutcomeStatus.COMPLETE, result=envelope)
        finally:
            connection.close()

    def import_model_bytes(
        self,
        *,
        logical_identity: str,
        contract: ArtifactContract[PayloadModel],
        producer_id: str,
        payload_bytes: bytes,
        dependencies: tuple[DependencyEdge, ...] = (),
    ) -> OperationOutcome:
        """Validate an external payload before it can become catalog-visible."""
        try:
            payload = contract.payload_model.model_validate_json(payload_bytes)
        except Exception as exc:
            return self._failure(
                logical_identity,
                "artifact.import.validation",
                "ARTIFACT_PAYLOAD_INVALID",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                retry=("provide a payload valid for the documented artifact contract",),
            )
        return self.publish_model(
            logical_identity=logical_identity,
            artifact_type=contract.artifact_type,
            artifact_schema_version=contract.artifact_schema_version,
            producer_id=producer_id,
            payload=payload,
            dependencies=dependencies,
        )

    def publish_failure(self, failure: OperationError) -> OperationOutcome:
        return self.publish_model(
            logical_identity=f"failure:{failure.error_id}",
            artifact_type="operation_error",
            artifact_schema_version=1,
            producer_id="qlibx",
            payload=failure,
            status=ArtifactStatus.FAILURE,
        )

    def load_model(
        self,
        artifact_id: str,
        contract: ArtifactContract[PayloadModel],
        *,
        include_failure: bool = False,
    ) -> OperationOutcome:
        if not self._catalog_path.is_file():
            return self._failure(
                artifact_id,
                "artifact.load.lookup",
                "ARTIFACT_NOT_FOUND",
                context={"artifact_id": artifact_id},
            )
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT artifact_type, artifact_schema_version, content_hash, payload_path,
                       status, envelope_json
                FROM artifacts WHERE artifact_id = ?
                """,
                [artifact_id],
            ).fetchone()
        finally:
            connection.close()
        if not row or (row[4] == ArtifactStatus.FAILURE.value and not include_failure):
            return self._failure(
                artifact_id,
                "artifact.load.lookup",
                "ARTIFACT_NOT_FOUND",
                context={"artifact_id": artifact_id},
            )
        if row[0] != contract.artifact_type or row[1] != contract.artifact_schema_version:
            return self._failure(
                artifact_id,
                "artifact.load.contract",
                "ARTIFACT_CONTRACT_UNSUPPORTED",
                context={
                    "actual_type": row[0],
                    "actual_version": row[1],
                    "expected_type": contract.artifact_type,
                    "expected_version": contract.artifact_schema_version,
                },
                retry=("supply an explicit compatible migration or contract",),
            )
        try:
            payload_bytes = Path(row[3]).read_bytes()
            if digest(payload_bytes) != row[2]:
                raise ValueError("payload content hash does not match catalog")
            payload = contract.payload_model.model_validate_json(payload_bytes)
            envelope = ArtifactEnvelope.model_validate_json(row[5])
        except Exception as exc:
            return self._failure(
                artifact_id,
                "artifact.load.validation",
                "ARTIFACT_PAYLOAD_INVALID",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
            )
        loaded = LoadedArtifact(envelope=envelope, payload=payload)
        return OperationOutcome(status=OutcomeStatus.COMPLETE, result=loaded)

    def list_envelopes(self, *, include_failure: bool = False) -> tuple[ArtifactEnvelope, ...]:
        if not self._catalog_path.is_file():
            return ()
        connection = self._connect()
        try:
            if include_failure:
                rows = connection.execute(
                    "SELECT envelope_json FROM artifacts ORDER BY artifact_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT envelope_json FROM artifacts WHERE status = ? ORDER BY artifact_id",
                    [ArtifactStatus.COMPLETE.value],
                ).fetchall()
        finally:
            connection.close()
        return tuple(ArtifactEnvelope.model_validate_json(row[0]) for row in rows)

    def _prepare_storage(self) -> None:
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(str(self._catalog_path))
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
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
            CREATE TABLE IF NOT EXISTS artifact_edges (
                artifact_id VARCHAR NOT NULL,
                dependency_id VARCHAR NOT NULL,
                consumer_role VARCHAR NOT NULL,
                edge_json VARCHAR NOT NULL,
                PRIMARY KEY (artifact_id, dependency_id, consumer_role)
            )
            """
        )
        return connection

    def _payload_path(self, envelope: ArtifactEnvelope) -> Path:
        return self._artifact_dir / envelope.artifact_id[9:11] / f"{envelope.artifact_id}.json"

    @staticmethod
    def _failure(
        identity: str,
        stage_path: str,
        error_code: str,
        *,
        context: dict[str, object] | None = None,
        retry: tuple[str, ...] = (),
    ) -> OperationOutcome:
        seed = digest(f"{identity}:{stage_path}:{error_code}".encode())[:24]
        error = OperationError(
            operation=stage_path.split(".", maxsplit=2)[0] + "." + stage_path.split(".")[1],
            stage_path=stage_path,
            error_code=error_code,
            context=context or {},
            commit_status=CommitStatus.NONE,
            retry_preconditions=retry,
            idempotency_identity=identity,
            error_id=f"error-{seed}",
        )
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))
