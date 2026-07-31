"""Test that validate_strategy_full is importable as a plain function.

Task 0.1 of the coding-agent-workflow-redesign: the composition logic previously
only accessible via the MCP tool must be callable without a server/LLM round-trip.
"""
from echolon.strategy.validators.full import validate_strategy_full


def test_importable_validate_strategy_full_returns_contract_shape(tmp_path):
    out = validate_strategy_full(str(tmp_path))
    assert set(out) >= {"status", "any_errors", "total_findings", "findings", "invocations"}
    assert out["status"] in {"VALID", "INVALID"}
    assert isinstance(out["findings"], list)
