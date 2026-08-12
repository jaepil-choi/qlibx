"""Shared construction and publication mechanics for flow failures."""

import hashlib

from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import LocalArtifactBackend


def build_operation_error(
    *,
    operation: str,
    stage_path: str,
    error_code: str,
    idempotency_identity: str,
    error_identity_seed: str,
    context: dict[str, object],
    retry_preconditions: tuple[str, ...],
    requirement_id: str | None = None,
    expected: dict[str, object] | None = None,
    commit_status: CommitStatus = CommitStatus.NONE,
) -> OperationError:
    """Build one error while leaving its identity seed under the caller's authority."""

    seed = hashlib.sha256(error_identity_seed.encode()).hexdigest()[:24]
    return OperationError(
        operation=operation,
        stage_path=stage_path,
        error_code=error_code,
        requirement_id=requirement_id,
        expected=expected,
        context=context,
        commit_status=commit_status,
        retry_preconditions=retry_preconditions,
        idempotency_identity=idempotency_identity,
        error_id=f"error-{seed}",
    )


def publish_failed_outcome(
    artifacts: LocalArtifactBackend,
    error: OperationError,
    *,
    include_publication_diagnostics: bool = True,
) -> OperationOutcome:
    """Publish one error and preserve the caller's prior diagnostic policy."""

    publication = artifacts.publish_failure(error)
    diagnostics: tuple[object, ...] = ()
    if include_publication_diagnostics:
        diagnostics = (
            (publication.result,)
            if publication.status is OutcomeStatus.COMPLETE
            else publication.errors
        )
    return OperationOutcome(
        status=OutcomeStatus.FAILED,
        diagnostics=diagnostics,
        errors=(error,),
    )


def publish_failed_errors(
    artifacts: LocalArtifactBackend,
    errors: tuple[OperationError, ...],
) -> OperationOutcome:
    """Publish resolver errors and retain only successful envelopes as diagnostics."""

    publications = tuple(artifacts.publish_failure(error) for error in errors)
    return OperationOutcome(
        status=OutcomeStatus.FAILED,
        diagnostics=tuple(
            publication.result
            for publication in publications
            if publication.status is OutcomeStatus.COMPLETE
        ),
        errors=errors,
    )