"""Prove direct forward-label materialization and progressive PIT requirement closure."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from qlibx import (
    ForwardReturnLabelModel,
    MaterializationInvocation,
    OutcomeStatus,
    QlibxProject,
)
from qlibx.data import DatasetRegistration, RowsLookback


def at_close(day: int) -> datetime:
    return datetime(2024, 1, day, 6, 30, tzinfo=UTC)


def require_complete(outcome: object, label: str) -> object:
    if outcome.status is not OutcomeStatus.COMPLETE:  # type: ignore[attr-defined]
        raise RuntimeError(f"{label} failed: {outcome.errors}")  # type: ignore[attr-defined]
    return outcome


def load_registration(sample_dir: Path, name: str) -> DatasetRegistration:
    payload = yaml.safe_load((sample_dir / name).read_text(encoding="utf-8"))
    return DatasetRegistration.model_validate_json(json.dumps(payload, ensure_ascii=False))


def main(project_root: Path) -> dict[str, object]:
    sample_dir = Path(__file__).resolve().parent
    project = QlibxProject.open(project_root)
    if project.registry_snapshot().get("sample-forward-label-prices") is None:
        require_complete(
            project.register_dataset(load_registration(sample_dir, "price-registration.yaml")),
            "sample forward-label price registration",
        )

    missing_model = ForwardReturnLabelModel(
        "sample-forward-label-prices",
        "sample-forward-label-unregistered-horizon",
        RowsLookback(rows=100),
        producer_id="sample.forward-label.missing-horizon",
    )
    missing = project.materialize(
        missing_model,
        MaterializationInvocation(
            invocation_id="sample-forward-label-missing-horizon",
            evaluation_time=at_close(3),
            config_fingerprint="sample-forward-label-missing-v1",
        ),
    )
    if missing.status is not OutcomeStatus.FAILED:
        raise RuntimeError("missing horizon unexpectedly materialized a reusable result")
    failure = missing.diagnostics[0]

    if project.registry_snapshot().get("sample-forward-label-horizon") is None:
        require_complete(
            project.register_dataset(load_registration(sample_dir, "horizon-registration.yaml")),
            "sample forward-label horizon registration",
        )
    model = ForwardReturnLabelModel(
        "sample-forward-label-prices",
        "sample-forward-label-horizon",
        RowsLookback(rows=100),
        producer_id="sample.forward-label.v1",
    )
    retry = require_complete(
        project.materialize(
            model,
            MaterializationInvocation(
                invocation_id="sample-forward-label-valid-horizon",
                evaluation_time=at_close(3),
                config_fingerprint="sample-forward-label-valid-v1",
                resolves_error_artifact_id=failure.artifact_id,
            ),
        ),
        "sample forward-label linked retry",
    )
    later = require_complete(
        project.materialize(
            model,
            MaterializationInvocation(
                invocation_id="sample-forward-label-later-horizon",
                evaluation_time=at_close(4),
                config_fingerprint="sample-forward-label-valid-v1",
            ),
        ),
        "sample forward-label later horizon",
    )

    retry_result = retry.result
    later_result = later.result
    registrations = project.registry_snapshot()
    return {
        "failure_artifact_id": failure.artifact_id,
        "failure_code": missing.errors[0].error_code,
        "failure_stage": missing.errors[0].stage_path,
        "failure_requirement_id": missing.errors[0].requirement_id,
        "retry_artifact_id": retry_result.artifact.artifact_id,
        "retry_entries": [entry.model_dump(mode="json") for entry in retry_result.result.entries],
        "later_entry_count": len(later_result.result.entries),
        "future_hidden_entry_count": (
            len(later_result.result.entries) - len(retry_result.result.entries)
        ),
        "registration_identities": {
            dataset_id: registrations.get(dataset_id).registration_identity
            for dataset_id in (
                "sample-forward-label-prices",
                "sample-forward-label-horizon",
            )
        },
        "retry_dependency_roles": [
            edge.consumer_role for edge in retry_result.artifact.dependencies
        ],
        "retry_resolves_error": any(
            edge.dependency_kind == "error" and edge.dependency_id == failure.artifact_id
            for edge in retry_result.artifact.dependencies
        ),
        "artifact_types": sorted(
            {item.artifact_type for item in project.artifacts.list_envelopes()}
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))
