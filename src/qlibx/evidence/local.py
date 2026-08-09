"""Atomic local artifact publication backed by DuckDB."""

import hashlib
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import duckdb

from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence.contracts import (
    ArtifactContract,
    ArtifactEnvelope,
    ArtifactStatus,
    CatalogRecoveryRecord,
    CatalogRecoveryResult,
    DependencyEdge,
    LoadedArtifact,
    PayloadFormat,
    PublicationEvent,
    PublicationPhase,
    RecoveryAction,
)
from qlibx.models import QlibxModel

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised on non-Windows CI
    import fcntl


PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)
CATALOG_SCHEMA_VERSION = 1
_ARTIFACT_COLUMNS = (
    "artifact_id",
    "logical_identity",
    "artifact_type",
    "artifact_schema_version",
    "producer_id",
    "content_hash",
    "payload_format",
    "payload_path",
    "status",
    "envelope_json",
)
_EDGE_COLUMNS = ("artifact_id", "dependency_id", "consumer_role", "edge_json")
_EVENT_COLUMNS = (
    "event_order",
    "event_id",
    "attempt_id",
    "artifact_id",
    "logical_identity",
    "phase",
    "event_json",
)
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class CatalogSchemaError(RuntimeError):
    """Raised when the durable catalog schema cannot be interpreted safely."""


class CatalogRecoveryError(RuntimeError):
    """Raised when abandoned publication state cannot be recovered safely."""


class CatalogCommitError(RuntimeError):
    """Raised after a catalog transaction has rolled back."""


class CatalogSessionConflictError(RuntimeError):
    """Raised when a bounded catalog session makes the database unavailable."""

    error_code = "CATALOG_SESSION_CONFLICT"
    retry_preconditions = ("retry after the active catalog session completes",)

    def __init__(self, catalog_path: Path, detail: str) -> None:
        self.catalog_path = catalog_path
        self.detail = detail
        super().__init__(f"catalog session conflict for {catalog_path}: {detail}")


@dataclass(frozen=True, slots=True)
class _PublicationAttempt:
    attempt_id: str
    envelope: ArtifactEnvelope
    staging_path: Path
    payload_path: Path


class LocalArtifactBackend:
    """Append-only artifact publisher and typed loader."""

    def __init__(
        self,
        catalog_path: Path,
        artifact_dir: Path,
        *,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self._catalog_path = catalog_path.resolve()
        self._artifact_dir = artifact_dir.resolve()
        self._lock_path = self._catalog_path.with_suffix(f"{self._catalog_path.suffix}.lock")
        self._lock_timeout_seconds = lock_timeout_seconds
        self._session_state_lock = threading.Lock()
        self._session_owner_thread_id: int | None = None
        self._session_depth = 0
        self._session_connection: duckdb.DuckDBPyConnection | None = None

    @contextmanager
    def session(self) -> Iterator[None]:
        """Reuse one catalog connection inside a single-threaded unit of work.

        The outer session holds the catalog writer lock and DuckDB file exclusively. Same-thread
        nested sessions share it by reference count. Other threads and processes must retry after
        the outer session exits. Outside a session, operations retain their per-call connections.
        """

        thread_id = threading.get_ident()
        with self._session_state_lock:
            if self._session_owner_thread_id == thread_id:
                if self._session_connection is None:
                    raise CatalogSessionConflictError(
                        self._catalog_path,
                        "the owning thread is still opening its outer session",
                    )
                self._session_depth += 1
                nested = True
            elif self._session_owner_thread_id is not None:
                raise CatalogSessionConflictError(
                    self._catalog_path,
                    "another thread owns the active session",
                )
            else:
                self._session_owner_thread_id = thread_id
                self._session_depth = 1
                nested = False

        if nested:
            try:
                yield
            finally:
                with self._session_state_lock:
                    self._session_depth -= 1
            return

        lock_context = self._exclusive_writer_lock()
        lock_acquired = False
        connection: duckdb.DuckDBPyConnection | None = None
        try:
            try:
                lock_context.__enter__()
                lock_acquired = True
            except TimeoutError as exc:
                raise CatalogSessionConflictError(
                    self._catalog_path,
                    "the catalog writer lock is held by another process",
                ) from exc
            try:
                connection = duckdb.connect(str(self._catalog_path))
                self._ensure_writer_schema(connection)
            except duckdb.Error as exc:
                self._raise_if_session_conflict(exc)
                raise
            with self._session_state_lock:
                self._session_connection = connection
            yield
        finally:
            if connection is not None:
                connection.close()
            if lock_acquired:
                lock_context.__exit__(None, None, None)
            with self._session_state_lock:
                self._session_connection = None
                self._session_owner_thread_id = None
                self._session_depth = 0

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
        envelope = ArtifactEnvelope(
            artifact_id=f"artifact-{digest(artifact_seed)[:32]}",
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
        try:
            with self._writer_lock():
                connection = self._connect_writer()
                try:
                    recovery = self._recover_locked(connection)
                    existing = self._existing(connection, logical_identity)
                    if existing:
                        if (
                            existing[1] == artifact_type
                            and existing[2] == artifact_schema_version
                            and existing[3] == content_hash
                        ):
                            current = ArtifactEnvelope.model_validate_json(existing[4])
                            return OperationOutcome(
                                status=OutcomeStatus.COMPLETE,
                                result=current,
                                diagnostics=(recovery,) if recovery.records else (),
                            )
                        return self._failure(
                            logical_identity,
                            "artifact.publish.identity_conflict",
                            "ARTIFACT_IDENTITY_CONFLICT",
                            context={
                                "logical_identity": logical_identity,
                                "existing_artifact_id": existing[0],
                            },
                            retry=(
                                "choose a new logical identity or retain the existing artifact",
                            ),
                        )

                    attempt = self._new_attempt(connection, envelope)
                    self._append_event(connection, attempt, PublicationPhase.STAGED)
                    self._write_staged_payload(attempt, payload_bytes)
                    self._append_event(connection, attempt, PublicationPhase.PAYLOAD_STAGED)
                    self._promote_staged_payload(attempt)
                    self._append_event(connection, attempt, PublicationPhase.PAYLOAD_PROMOTED)
                    self._commit_publication(connection, attempt, envelope, dependencies)
                    return OperationOutcome(
                        status=OutcomeStatus.COMPLETE,
                        result=envelope,
                        diagnostics=(recovery,) if recovery.records else (),
                    )
                finally:
                    connection.close()
        except CatalogSessionConflictError as exc:
            return self._failure(
                logical_identity,
                "artifact.publish.catalog_session",
                exc.error_code,
                context={"catalog_path": str(exc.catalog_path), "message": exc.detail},
                retry=exc.retry_preconditions,
            )
        except TimeoutError:
            return self._failure(
                logical_identity,
                "artifact.publish.lock",
                "CATALOG_WRITE_LOCK_TIMEOUT",
                context={
                    "lock_path": str(self._lock_path),
                    "timeout_seconds": self._lock_timeout_seconds,
                },
                retry=("retry after the current catalog writer completes",),
            )
        except CatalogSchemaError as exc:
            return self._failure(
                logical_identity,
                "artifact.publish.catalog_schema",
                "CATALOG_SCHEMA_UNSUPPORTED",
                context={"message": str(exc)[:500]},
                retry=("migrate the catalog with an explicitly supported schema",),
            )
        except CatalogRecoveryError as exc:
            return self._failure(
                logical_identity,
                "artifact.publish.recovery",
                "CATALOG_RECOVERY_FAILED",
                context={"message": str(exc)[:500]},
                retry=("inspect the publication audit before retrying",),
            )
        except CatalogCommitError as exc:
            return self._failure(
                logical_identity,
                "artifact.publish.catalog_commit",
                "CATALOG_COMMIT_FAILED",
                context={"message": str(exc)[:500]},
                retry=("retry publication with the same frozen candidate",),
            )
        except OSError as exc:
            return self._failure(
                logical_identity,
                "artifact.publish.payload_stage",
                "ARTIFACT_PAYLOAD_STAGE_FAILED",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                retry=("recover abandoned publication state, then retry",),
            )

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

    def load_envelope(
        self,
        artifact_id: str,
        *,
        include_failure: bool = False,
    ) -> OperationOutcome:
        """Load exact artifact metadata without selecting or decoding a payload model."""

        if not self._catalog_path.is_file():
            return self._not_found(artifact_id)
        try:
            connection = self._connect_reader()
            try:
                row = connection.execute(
                    "SELECT status, envelope_json FROM artifacts WHERE artifact_id = ?",
                    [artifact_id],
                ).fetchone()
            finally:
                connection.close()
        except CatalogSessionConflictError as exc:
            return self._failure(
                artifact_id,
                "artifact.load.catalog_session",
                exc.error_code,
                context={"catalog_path": str(exc.catalog_path), "message": exc.detail},
                retry=exc.retry_preconditions,
            )
        except CatalogSchemaError as exc:
            return self._failure(
                artifact_id,
                "artifact.load.catalog_schema",
                "CATALOG_SCHEMA_UNSUPPORTED",
                context={"message": str(exc)[:500]},
            )
        if not row or (row[0] == ArtifactStatus.FAILURE.value and not include_failure):
            return self._not_found(artifact_id)
        try:
            envelope = ArtifactEnvelope.model_validate_json(row[1])
        except Exception as exc:
            return self._failure(
                artifact_id,
                "artifact.load.envelope",
                "ARTIFACT_ENVELOPE_INVALID",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
            )
        return OperationOutcome(status=OutcomeStatus.COMPLETE, result=envelope)

    def load_model(
        self,
        artifact_id: str,
        contract: ArtifactContract[PayloadModel],
        *,
        include_failure: bool = False,
    ) -> OperationOutcome:
        if not self._catalog_path.is_file():
            return self._not_found(artifact_id)
        try:
            connection = self._connect_reader()
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
        except CatalogSessionConflictError as exc:
            return self._failure(
                artifact_id,
                "artifact.load.catalog_session",
                exc.error_code,
                context={"catalog_path": str(exc.catalog_path), "message": exc.detail},
                retry=exc.retry_preconditions,
            )
        except CatalogSchemaError as exc:
            return self._failure(
                artifact_id,
                "artifact.load.catalog_schema",
                "CATALOG_SCHEMA_UNSUPPORTED",
                context={"message": str(exc)[:500]},
            )
        if not row or (row[4] == ArtifactStatus.FAILURE.value and not include_failure):
            return self._not_found(artifact_id)
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
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=LoadedArtifact(envelope=envelope, payload=payload),
        )

    def list_envelopes(
        self,
        *,
        include_failure: bool = False,
        artifact_type: str | None = None,
    ) -> tuple[ArtifactEnvelope, ...]:
        if not self._catalog_path.is_file():
            return ()
        conditions: list[str] = []
        parameters: list[str] = []
        if not include_failure:
            conditions.append("status = ?")
            parameters.append(ArtifactStatus.COMPLETE.value)
        if artifact_type is not None:
            conditions.append("artifact_type = ?")
            parameters.append(artifact_type)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        connection = self._connect_reader()
        try:
            rows = connection.execute(
                f"SELECT envelope_json FROM artifacts{where_clause} ORDER BY artifact_id",
                parameters,
            ).fetchall()
        finally:
            connection.close()
        return tuple(ArtifactEnvelope.model_validate_json(row[0]) for row in rows)

    def latest_envelope(
        self,
        *,
        artifact_type: str,
        logical_identity_prefix: str,
        include_failure: bool = False,
    ) -> ArtifactEnvelope | None:
        """Return the lexicographically latest exact-prefix identity without LIKE wildcards."""

        if not self._catalog_path.is_file():
            return None
        conditions = ["artifact_type = ?", "starts_with(logical_identity, ?)"]
        parameters = [artifact_type, logical_identity_prefix]
        if not include_failure:
            conditions.append("status = ?")
            parameters.append(ArtifactStatus.COMPLETE.value)
        connection = self._connect_reader()
        try:
            row = connection.execute(
                "SELECT envelope_json FROM artifacts "
                f"WHERE {' AND '.join(conditions)} "
                "ORDER BY logical_identity DESC LIMIT 1",
                parameters,
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else ArtifactEnvelope.model_validate_json(row[0])

    def audit_publications(self) -> OperationOutcome:
        if not self._catalog_path.is_file():
            return OperationOutcome(status=OutcomeStatus.COMPLETE, result=())
        try:
            connection = self._connect_reader()
            try:
                if "publication_events" not in self._table_names(connection):
                    events: tuple[PublicationEvent, ...] = ()
                else:
                    events = self._read_events(connection)
            finally:
                connection.close()
        except CatalogSessionConflictError as exc:
            return self._failure(
                "catalog-audit",
                "artifact.audit.catalog_session",
                exc.error_code,
                context={"catalog_path": str(exc.catalog_path), "message": exc.detail},
                retry=exc.retry_preconditions,
            )
        except CatalogSchemaError as exc:
            return self._failure(
                "catalog-audit",
                "artifact.audit.catalog_schema",
                "CATALOG_SCHEMA_UNSUPPORTED",
                context={"message": str(exc)[:500]},
            )
        return OperationOutcome(status=OutcomeStatus.COMPLETE, result=events)

    def recover_publications(self) -> OperationOutcome:
        if not self._catalog_path.is_file():
            return OperationOutcome(
                status=OutcomeStatus.COMPLETE,
                result=CatalogRecoveryResult(),
            )
        try:
            with self._writer_lock():
                connection = self._connect_writer()
                try:
                    result = self._recover_locked(connection)
                finally:
                    connection.close()
        except CatalogSessionConflictError as exc:
            return self._failure(
                "catalog-recovery",
                "artifact.recover.catalog_session",
                exc.error_code,
                context={"catalog_path": str(exc.catalog_path), "message": exc.detail},
                retry=exc.retry_preconditions,
            )
        except TimeoutError:
            return self._failure(
                "catalog-recovery",
                "artifact.recover.lock",
                "CATALOG_WRITE_LOCK_TIMEOUT",
                context={"timeout_seconds": self._lock_timeout_seconds},
            )
        except CatalogSchemaError as exc:
            return self._failure(
                "catalog-recovery",
                "artifact.recover.catalog_schema",
                "CATALOG_SCHEMA_UNSUPPORTED",
                context={"message": str(exc)[:500]},
            )
        except CatalogRecoveryError as exc:
            return self._failure(
                "catalog-recovery",
                "artifact.recover.state",
                "CATALOG_RECOVERY_FAILED",
                context={"message": str(exc)[:500]},
            )
        return OperationOutcome(status=OutcomeStatus.COMPLETE, result=result)

    @contextmanager
    def _writer_lock(self) -> Iterator[None]:
        thread_id = threading.get_ident()
        with self._session_state_lock:
            owner = self._session_owner_thread_id
        if owner is not None:
            if owner != thread_id:
                raise CatalogSessionConflictError(
                    self._catalog_path,
                    "another thread owns the active session",
                )
            yield
            return
        with self._exclusive_writer_lock():
            yield

    @contextmanager
    def _exclusive_writer_lock(self) -> Iterator[None]:
        self._prepare_storage()
        deadline = time.monotonic() + self._lock_timeout_seconds
        lock_key = str(self._lock_path)
        with _THREAD_LOCKS_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(lock_key, threading.Lock())
        if not thread_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError("catalog thread lock timed out")
        handle = None
        locked = False
        try:
            handle = self._lock_path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            while not locked:
                try:
                    self._try_file_lock(handle)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("catalog process lock timed out") from None
                    time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
            yield
        finally:
            if locked and handle is not None:
                self._unlock_file(handle)
            if handle is not None:
                handle.close()
            thread_lock.release()

    @staticmethod
    def _try_file_lock(handle: object) -> None:
        handle.seek(0)  # type: ignore[attr-defined]
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        else:  # pragma: no cover - exercised on non-Windows CI
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]

    @staticmethod
    def _unlock_file(handle: object) -> None:
        try:
            handle.seek(0)  # type: ignore[attr-defined]
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:  # pragma: no cover - exercised on non-Windows CI
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        except OSError:
            pass

    def _new_attempt(
        self,
        connection: duckdb.DuckDBPyConnection,
        envelope: ArtifactEnvelope,
    ) -> _PublicationAttempt:
        attempt_number = (
            connection.execute(
                "SELECT count(DISTINCT attempt_id) FROM publication_events WHERE artifact_id = ?",
                [envelope.artifact_id],
            ).fetchone()[0]
            + 1
        )
        attempt_id = f"attempt-{digest(f'{envelope.artifact_id}:{attempt_number}'.encode())[:24]}"
        return _PublicationAttempt(
            attempt_id=attempt_id,
            envelope=envelope,
            staging_path=self._artifact_dir / ".staging" / f"{attempt_id}.json",
            payload_path=self._payload_path(envelope),
        )

    def _append_event(
        self,
        connection: duckdb.DuckDBPyConnection,
        attempt: _PublicationAttempt,
        phase: PublicationPhase,
    ) -> PublicationEvent:
        event_order = connection.execute(
            "SELECT coalesce(max(event_order), 0) + 1 FROM publication_events"
        ).fetchone()[0]
        event = PublicationEvent(
            event_order=event_order,
            event_id=f"event-{digest(f'{attempt.attempt_id}:{phase.value}'.encode())[:24]}",
            attempt_id=attempt.attempt_id,
            artifact_id=attempt.envelope.artifact_id,
            logical_identity=attempt.envelope.logical_identity,
            phase=phase,
            content_hash=attempt.envelope.content_hash,
            staging_path=str(attempt.staging_path),
            payload_path=str(attempt.payload_path),
        )
        connection.execute(
            "INSERT INTO publication_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                event.event_order,
                event.event_id,
                event.attempt_id,
                event.artifact_id,
                event.logical_identity,
                event.phase.value,
                event.model_dump_json(),
            ],
        )
        return event

    def _write_staged_payload(
        self,
        attempt: _PublicationAttempt,
        payload_bytes: bytes,
    ) -> None:
        attempt.staging_path.parent.mkdir(parents=True, exist_ok=True)
        with attempt.staging_path.open("xb") as handle:
            handle.write(payload_bytes)
            handle.flush()
            os.fsync(handle.fileno())

    def _promote_staged_payload(self, attempt: _PublicationAttempt) -> None:
        attempt.payload_path.parent.mkdir(parents=True, exist_ok=True)
        if attempt.payload_path.exists():
            if digest(attempt.payload_path.read_bytes()) != attempt.envelope.content_hash:
                raise CatalogRecoveryError(
                    f"content-addressed payload conflict: {attempt.payload_path}"
                )
            attempt.staging_path.unlink(missing_ok=True)
            return
        os.replace(attempt.staging_path, attempt.payload_path)

    def _commit_publication(
        self,
        connection: duckdb.DuckDBPyConnection,
        attempt: _PublicationAttempt,
        envelope: ArtifactEnvelope,
        dependencies: tuple[DependencyEdge, ...],
    ) -> None:
        try:
            connection.execute("BEGIN TRANSACTION")
            connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    envelope.artifact_id,
                    envelope.logical_identity,
                    envelope.artifact_type,
                    envelope.artifact_schema_version,
                    envelope.producer_id,
                    envelope.content_hash,
                    envelope.payload_format.value,
                    str(attempt.payload_path),
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
            self._append_event(connection, attempt, PublicationPhase.CATALOG_COMMITTED)
            connection.execute("COMMIT")
        except Exception as exc:
            with suppress(Exception):
                connection.execute("ROLLBACK")
            raise CatalogCommitError(f"{type(exc).__name__}: {exc}") from exc

    def _recover_locked(
        self,
        connection: duckdb.DuckDBPyConnection,
    ) -> CatalogRecoveryResult:
        latest: dict[str, PublicationEvent] = {}
        for event in self._read_unterminated_events(connection):
            latest[event.attempt_id] = event
        records: list[CatalogRecoveryRecord] = []
        terminal = {
            PublicationPhase.CATALOG_COMMITTED,
            PublicationPhase.RECOVERED_ABANDONED,
        }
        for event in sorted(latest.values(), key=lambda item: item.event_order):
            if event.phase in terminal:
                continue
            indexed = connection.execute(
                "SELECT count(*) FROM artifacts WHERE artifact_id = ?",
                [event.artifact_id],
            ).fetchone()[0]
            if indexed:
                raise CatalogRecoveryError(
                    f"artifact {event.artifact_id} is indexed without a committed event"
                )
            staging_path = self._validated_artifact_path(event.staging_path)
            payload_path = self._validated_artifact_path(event.payload_path)
            removed: list[str] = []
            if staging_path.exists():
                staging_path.unlink()
                removed.append(str(staging_path))
            if payload_path.exists():
                references = connection.execute(
                    "SELECT count(*) FROM artifacts WHERE payload_path = ?",
                    [str(payload_path)],
                ).fetchone()[0]
                if references:
                    raise CatalogRecoveryError(
                        f"uncommitted payload path is referenced: {payload_path}"
                    )
                if digest(payload_path.read_bytes()) != event.content_hash:
                    raise CatalogRecoveryError(f"uncommitted payload hash mismatch: {payload_path}")
                payload_path.unlink()
                removed.append(str(payload_path))
            attempt = _PublicationAttempt(
                attempt_id=event.attempt_id,
                envelope=ArtifactEnvelope(
                    artifact_id=event.artifact_id,
                    logical_identity=event.logical_identity,
                    artifact_type="recovery-placeholder",
                    artifact_schema_version=1,
                    producer_id="qlibx.catalog-recovery",
                    content_hash=event.content_hash,
                    payload_format=PayloadFormat.JSON,
                    status=ArtifactStatus.FAILURE,
                ),
                staging_path=staging_path,
                payload_path=payload_path,
            )
            self._append_event(connection, attempt, PublicationPhase.RECOVERED_ABANDONED)
            records.append(
                CatalogRecoveryRecord(
                    attempt_id=event.attempt_id,
                    artifact_id=event.artifact_id,
                    action=RecoveryAction.REMOVED_ABANDONED,
                    removed_paths=tuple(removed),
                )
            )
        return CatalogRecoveryResult(records=tuple(records))

    @classmethod
    def _read_unterminated_events(
        cls,
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[PublicationEvent, ...]:
        cls._validate_event_schema_versions(connection)
        rows = connection.execute(
            "SELECT event_json FROM publication_events "
            "WHERE attempt_id NOT IN ("
            "SELECT attempt_id FROM publication_events WHERE phase IN (?, ?)"
            ") ORDER BY event_order",
            [
                PublicationPhase.CATALOG_COMMITTED.value,
                PublicationPhase.RECOVERED_ABANDONED.value,
            ],
        ).fetchall()
        return cls._deserialize_events(rows)

    @staticmethod
    def _validate_event_schema_versions(
        connection: duckdb.DuckDBPyConnection,
    ) -> None:
        expected = str(PublicationEvent.model_fields["event_schema_version"].default)
        try:
            unsupported = connection.execute(
                "SELECT event_order FROM publication_events WHERE "
                "CAST(json_extract(event_json, '$.event_schema_version') AS VARCHAR) "
                "IS DISTINCT FROM ? LIMIT 1",
                [expected],
            ).fetchone()
        except Exception as exc:
            raise CatalogSchemaError(
                f"publication event schema is unsupported: {type(exc).__name__}: {exc}"
            ) from exc
        if unsupported is not None:
            raise CatalogSchemaError(
                "publication event schema is unsupported: "
                f"event_order={unsupported[0]} has an unknown event_schema_version"
            )

    @classmethod
    def _read_events(
        cls,
        connection: duckdb.DuckDBPyConnection,
    ) -> tuple[PublicationEvent, ...]:
        rows = connection.execute(
            "SELECT event_json FROM publication_events ORDER BY event_order"
        ).fetchall()
        return cls._deserialize_events(rows)

    @staticmethod
    def _deserialize_events(
        rows: list[tuple[object, ...]],
    ) -> tuple[PublicationEvent, ...]:
        try:
            return tuple(PublicationEvent.model_validate_json(row[0]) for row in rows)
        except Exception as exc:
            raise CatalogSchemaError(
                f"publication event schema is unsupported: {type(exc).__name__}: {exc}"
            ) from exc

    def _validated_artifact_path(self, value: str) -> Path:
        path = Path(value).resolve()
        if not path.is_relative_to(self._artifact_dir):
            raise CatalogRecoveryError(f"publication path escaped artifact root: {path}")
        return path

    def _prepare_storage(self) -> None:
        self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)

    def _connect_writer(self) -> duckdb.DuckDBPyConnection:
        session_cursor = self._session_cursor()
        if session_cursor is not None:
            return session_cursor
        try:
            connection = duckdb.connect(str(self._catalog_path))
        except duckdb.Error as exc:
            self._raise_if_session_conflict(exc)
            raise
        try:
            self._ensure_writer_schema(connection)
        except Exception:
            connection.close()
            raise
        return connection

    def _connect_reader(self) -> duckdb.DuckDBPyConnection:
        session_cursor = self._session_cursor()
        if session_cursor is not None:
            return session_cursor
        try:
            connection = duckdb.connect(str(self._catalog_path), read_only=True)
        except duckdb.Error as exc:
            self._raise_if_session_conflict(exc)
            raise
        try:
            self._validate_reader_schema(connection)
        except Exception:
            connection.close()
            raise
        return connection

    def _session_cursor(self) -> duckdb.DuckDBPyConnection | None:
        thread_id = threading.get_ident()
        with self._session_state_lock:
            owner = self._session_owner_thread_id
            connection = self._session_connection
            if owner is None:
                return None
            if owner != thread_id:
                raise CatalogSessionConflictError(
                    self._catalog_path,
                    "another thread owns the active session",
                )
            if connection is None:
                raise CatalogSessionConflictError(
                    self._catalog_path,
                    "the owning thread is still opening its outer session",
                )
            return connection.cursor()

    def _raise_if_session_conflict(self, exc: duckdb.Error) -> None:
        message = str(exc)
        lowered = message.lower()
        markers = (
            "different configuration than existing connections",
            "could not set lock on file",
            "conflicting lock",
            "another process",
            "database is locked",
        )
        if any(marker in lowered for marker in markers):
            raise CatalogSessionConflictError(self._catalog_path, message[:500]) from exc

    def _ensure_writer_schema(self, connection: duckdb.DuckDBPyConnection) -> None:
        tables = self._table_names(connection)
        if "catalog_metadata" in tables:
            self._require_schema_version(connection)
            self._validate_columns(connection, "artifacts", _ARTIFACT_COLUMNS)
            self._validate_columns(connection, "artifact_edges", _EDGE_COLUMNS)
            self._validate_columns(connection, "publication_events", _EVENT_COLUMNS)
            return
        legacy_tables = {"artifacts", "artifact_edges"}
        if tables.intersection(legacy_tables) and not legacy_tables.issubset(tables):
            raise CatalogSchemaError("partial legacy artifact schema")
        if legacy_tables.issubset(tables):
            self._validate_columns(connection, "artifacts", _ARTIFACT_COLUMNS)
            self._validate_columns(connection, "artifact_edges", _EDGE_COLUMNS)
        elif "publication_events" in tables:
            raise CatalogSchemaError("publication events exist without catalog metadata")
        try:
            connection.execute("BEGIN TRANSACTION")
            self._create_artifact_tables(connection)
            self._create_catalog_metadata(connection)
            self._create_publication_events(connection)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def _validate_reader_schema(self, connection: duckdb.DuckDBPyConnection) -> None:
        tables = self._table_names(connection)
        if "catalog_metadata" in tables:
            self._require_schema_version(connection)
            self._validate_columns(connection, "artifacts", _ARTIFACT_COLUMNS)
            self._validate_columns(connection, "artifact_edges", _EDGE_COLUMNS)
            self._validate_columns(connection, "publication_events", _EVENT_COLUMNS)
            return
        if {"artifacts", "artifact_edges"}.issubset(tables):
            self._validate_columns(connection, "artifacts", _ARTIFACT_COLUMNS)
            self._validate_columns(connection, "artifact_edges", _EDGE_COLUMNS)
            return
        raise CatalogSchemaError("catalog has no supported schema metadata")

    @staticmethod
    def _table_names(connection: duckdb.DuckDBPyConnection) -> set[str]:
        return {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }

    @staticmethod
    def _validate_columns(
        connection: duckdb.DuckDBPyConnection,
        table: str,
        expected: tuple[str, ...],
    ) -> None:
        actual = tuple(
            row[1] for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        )
        if actual != expected:
            raise CatalogSchemaError(
                f"unsupported {table} columns: expected={expected}, actual={actual}"
            )

    @staticmethod
    def _require_schema_version(connection: duckdb.DuckDBPyConnection) -> None:
        rows = connection.execute("SELECT schema_version FROM catalog_metadata").fetchall()
        if rows != [(CATALOG_SCHEMA_VERSION,)]:
            raise CatalogSchemaError(
                f"expected catalog schema {CATALOG_SCHEMA_VERSION}, found {rows}"
            )

    @staticmethod
    def _create_artifact_tables(connection: duckdb.DuckDBPyConnection) -> None:
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

    @staticmethod
    def _create_catalog_metadata(connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute("CREATE TABLE catalog_metadata (schema_version INTEGER NOT NULL)")
        connection.execute("INSERT INTO catalog_metadata VALUES (?)", [CATALOG_SCHEMA_VERSION])

    @staticmethod
    def _create_publication_events(connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(
            """
            CREATE TABLE publication_events (
                event_order BIGINT UNIQUE NOT NULL,
                event_id VARCHAR PRIMARY KEY,
                attempt_id VARCHAR NOT NULL,
                artifact_id VARCHAR NOT NULL,
                logical_identity VARCHAR NOT NULL,
                phase VARCHAR NOT NULL,
                event_json VARCHAR NOT NULL
            )
            """
        )

    @staticmethod
    def _existing(
        connection: duckdb.DuckDBPyConnection,
        logical_identity: str,
    ) -> tuple[object, ...] | None:
        return connection.execute(
            """
            SELECT artifact_id, artifact_type, artifact_schema_version, content_hash,
                   envelope_json
            FROM artifacts WHERE logical_identity = ?
            """,
            [logical_identity],
        ).fetchone()

    def _payload_path(self, envelope: ArtifactEnvelope) -> Path:
        return self._artifact_dir / envelope.artifact_id[9:11] / f"{envelope.artifact_id}.json"

    @classmethod
    def _not_found(cls, artifact_id: str) -> OperationOutcome:
        return cls._failure(
            artifact_id,
            "artifact.load.lookup",
            "ARTIFACT_NOT_FOUND",
            context={"artifact_id": artifact_id},
        )

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
        parts = stage_path.split(".")
        error = OperationError(
            operation=parts[0] + "." + parts[1],
            stage_path=stage_path,
            error_code=error_code,
            context=context or {},
            commit_status=CommitStatus.NONE,
            retry_preconditions=retry,
            idempotency_identity=identity,
            error_id=f"error-{seed}",
        )
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))
