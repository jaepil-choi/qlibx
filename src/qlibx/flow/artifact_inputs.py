"""Built-in artifact contracts available to Strategy input resolution."""

from qlibx.evidence import ArtifactContract
from qlibx.operations import StrategyResult
from qlibx.operations.artifacts import StoredSignalResult

STRATEGY_RESULT_CONTRACT = ArtifactContract(
    artifact_type="strategy_result",
    artifact_schema_version=1,
    payload_model=StrategyResult,
)

STORED_SIGNAL_CONTRACT = ArtifactContract(
    artifact_type="stored_signal_result",
    artifact_schema_version=1,
    payload_model=StoredSignalResult,
)