"""Validate, register, and execute one exact project-local Strategy."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from qlibx import (
    OutcomeStatus,
    QlibxProject,
    StoredSignalEntry,
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyExtensionValidationRequest,
    StrategyInvocation,
)

EVALUATION_TIME = datetime(2025, 1, 3, 9, tzinfo=UTC)


def require_complete(outcome: object, label: str) -> object:
    if outcome.status is not OutcomeStatus.COMPLETE:  # type: ignore[attr-defined]
        raise RuntimeError(f"{label} failed: {outcome.errors}")  # type: ignore[attr-defined]
    return outcome


def install_example_source(sample_dir: Path, project: QlibxProject) -> str:
    source = sample_dir / "strategy.py"
    extension_root = project.root / project.config.extension_dir
    extension_root.mkdir(parents=True, exist_ok=True)
    target = extension_root / "sample_ranked_signal.py"
    payload = source.read_bytes()
    if target.exists():
        if target.read_bytes() != payload:
            raise RuntimeError(
                "refusing to overwrite modified qlibx_extensions/sample_ranked_signal.py"
            )
    else:
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return target.relative_to(extension_root).as_posix()


def main(project_root: Path) -> dict[str, object]:
    project = QlibxProject.open(project_root)
    module_path = install_example_source(Path(__file__).resolve().parent, project)
    signal = StoredSignalResult(
        signal_semantics="sample_rank_signal",
        observation_time=datetime(2025, 1, 2, 9, tzinfo=UTC),
        entries=(
            StoredSignalEntry(instrument="A000660", value=0.02),
            StoredSignalEntry(instrument="A005930", value=0.04),
        ),
    )
    published = require_complete(
        project.artifacts.publish_model(
            logical_identity="sample-strategy-extension-signal",
            artifact_type="stored_signal_result",
            artifact_schema_version=1,
            producer_id="sample.strategy-extension",
            payload=signal,
        ),
        "sample signal publication",
    )
    binding = StrategyArtifactBinding(
        consumer_role="ranked_signal",
        artifact_id=published.result.artifact_id,
    )
    validated = require_complete(
        project.validate_strategy_extension(
            StrategyExtensionValidationRequest(
                invocation_id="sample-strategy-extension-validation",
                strategy_id="sample.local-ranked-signal",
                module_path=module_path,
                evaluation_time=EVALUATION_TIME,
                config_fingerprint="sample-strategy-extension-validation-v1",
                artifact_bindings=(binding,),
            )
        ),
        "Strategy extension validation",
    )
    executed = require_complete(
        project.invoke_registered_strategy(
            validated.result.registration_artifact_id,
            StrategyInvocation(
                invocation_id="sample-strategy-extension-execution",
                evaluation_time=EVALUATION_TIME,
                config_fingerprint="sample-strategy-extension-execution-v1",
                artifact_bindings=(binding,),
            ),
        ),
        "registered Strategy execution",
    )
    result = executed.result
    return {
        "module_path": module_path,
        "registration_artifact_id": validated.result.registration_artifact_id,
        "strategy_artifact_id": result.artifact.artifact_id,
        "weights": {
            entry.instrument: entry.weight
            for entry in result.result.weights
        },
        "dependency_ids": sorted(
            edge.dependency_id for edge in result.artifact.dependencies
        ),
        "artifact_types": sorted(
            envelope.artifact_type
            for envelope in project.artifacts.list_envelopes()
        ),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(json.dumps(main(root), ensure_ascii=False, indent=2, sort_keys=True))