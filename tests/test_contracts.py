from typing import Any

import pytest
from pydantic import ValidationError

from qlibx import OperationError, OperationOutcome, OutcomeStatus, QlibxModel


class ExampleBoundary(QlibxModel):
    count: int


def make_error(**overrides: Any) -> OperationError:
    values: dict[str, Any] = {
        "operation": "dataset.register",
        "stage_path": "dataset.register.schema",
        "error_code": "SCHEMA_VALIDATION_FAILED",
        "idempotency_identity": "invocation-1",
        "error_id": "error-1",
    }
    values.update(overrides)
    return OperationError.model_validate(values)


def test_boundary_models_are_strict_and_frozen() -> None:
    with pytest.raises(ValidationError):
        ExampleBoundary.model_validate({"count": "1"})

    model = ExampleBoundary(count=1)
    with pytest.raises(ValidationError):
        model.count = 2


def test_complete_outcome_cannot_hide_error_evidence() -> None:
    with pytest.raises(ValueError, match="complete outcome"):
        OperationOutcome(status=OutcomeStatus.COMPLETE, errors=(make_error(),))


@pytest.mark.parametrize("status", [OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED])
def test_failure_outcome_requires_error_evidence(status: OutcomeStatus) -> None:
    with pytest.raises(ValueError, match="requires error evidence"):
        OperationOutcome(status=status)


def test_operation_error_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_error(guessed_resolution="use DATE as available_at")
