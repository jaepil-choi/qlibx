"""B1-9 — MCP tool exposure for the 5 deterministic validators.

Tests:
1. All 5 new tool names appear in _registered().
2. Happy-path for all 4 strategy-dir validators against aluminum_baseline fixture.
3. Happy-path for validate_debug_completion with a valid artifact + log in tmp_path.
4. Negative-path for validate_debug_completion when the artifact file is missing.
5. Return-shape invariant (any_errors: bool, findings: list, each finding has
   code/message/context keys).
"""
import asyncio
import json
from pathlib import Path

import pytest

from echolon.mcp.server import build_server


# ---------------------------------------------------------------------------
# Helpers (mirror test_scaffold_component_tool.py)
# ---------------------------------------------------------------------------

def _get_tool_fn(name: str):
    server = build_server()
    tm = server._tool_manager
    tools = getattr(tm, "_tools", None) or getattr(tm, "tools", None)
    if tools is None:
        raise RuntimeError(f"FastMCP tool_manager shape unknown: {dir(tm)}")
    return tools[name].fn


def _registered() -> set[str]:
    server = build_server()
    tools = server.list_tools()
    if asyncio.iscoroutine(tools):
        tools = asyncio.run(tools)
    return {t.name for t in tools}


# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "baselines" / "aluminum_baseline"


# ---------------------------------------------------------------------------
# 1. Registration check
# ---------------------------------------------------------------------------

_EXPECTED_TOOL_NAMES = {
    "validate_debug_completion",
    "validate_component_protocol_signatures",
    "validate_component_integration",
    "validate_component_logging",
    "validate_parameter_access",
}


def test_validator_tools_all_registered():
    registered = _registered()
    for name in _EXPECTED_TOOL_NAMES:
        assert name in registered, f"Tool {name!r} not registered in MCP server"


# ---------------------------------------------------------------------------
# 2. Happy-path tests — 4 strategy-dir validators on aluminum_baseline fixture
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", [
    "validate_component_protocol_signatures",
    "validate_component_integration",
    "validate_component_logging",
    "validate_parameter_access",
])
def test_strategy_dir_validator_happy_path(tool_name):
    fn = _get_tool_fn(tool_name)
    result = fn(strategy_dir=str(_FIXTURE_DIR))
    assert isinstance(result, dict), f"{tool_name} should return a dict"
    assert result["any_errors"] is False, (
        f"{tool_name} reported errors on aluminum_baseline fixture:\n"
        f"{json.dumps(result, indent=2)}"
    )


# ---------------------------------------------------------------------------
# 3. Happy-path for validate_debug_completion
# ---------------------------------------------------------------------------

def test_validate_debug_completion_happy_path(tmp_path):
    artifact = tmp_path / "selected_robust_trial.json"
    artifact.write_text(json.dumps({
        "trial_number": 42,
        "params": {"rsi_period": 14},
        "metrics": {"sharpe_ratio": 1.5},
    }))

    log_file = tmp_path / "debug.log"
    log_file.write_text(
        "starting...\n"
        "STAGE 4 COMPLETE\n"
        "STAGE 5 COMPLETE\n"
        "FINAL SUCCESS\n"
    )

    fn = _get_tool_fn("validate_debug_completion")
    result = fn(artifact_path=str(artifact), log_path=str(log_file))

    assert isinstance(result, dict)
    assert result["any_errors"] is False, (
        f"Expected no errors but got:\n{json.dumps(result, indent=2)}"
    )
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# 4. Negative-path for validate_debug_completion — missing artifact
# ---------------------------------------------------------------------------

def test_validate_debug_completion_missing_artifact(tmp_path):
    artifact = tmp_path / "nonexistent_artifact.json"  # does not exist
    log_file = tmp_path / "debug.log"
    log_file.write_text("STAGE 4 COMPLETE\nSTAGE 5 COMPLETE\nFINAL SUCCESS\n", encoding="utf-8")

    fn = _get_tool_fn("validate_debug_completion")
    result = fn(artifact_path=str(artifact), log_path=str(log_file))

    assert result["any_errors"] is True
    codes = [f["code"] for f in result["findings"]]
    assert "STR-001" in codes, (
        f"Expected STR-001 finding for missing artifact; got codes: {codes}"
    )


# ---------------------------------------------------------------------------
# 5. Return-shape invariant
# ---------------------------------------------------------------------------

def test_return_shape_invariant(tmp_path):
    """validate_debug_completion (negative case) exercises the full finding shape."""
    artifact = tmp_path / "missing.json"  # does not exist
    log_file = tmp_path / "debug.log"
    log_file.write_text("some log content", encoding="utf-8")

    fn = _get_tool_fn("validate_debug_completion")
    result = fn(artifact_path=str(artifact), log_path=str(log_file))

    # Top-level shape
    assert "any_errors" in result, "result missing 'any_errors' key"
    assert "findings" in result, "result missing 'findings' key"
    assert isinstance(result["any_errors"], bool), "'any_errors' must be bool"
    assert isinstance(result["findings"], list), "'findings' must be list"

    # Per-finding shape
    assert len(result["findings"]) >= 1, "Expected at least one finding"
    for finding in result["findings"]:
        assert "code" in finding, f"finding missing 'code': {finding}"
        assert "message" in finding, f"finding missing 'message': {finding}"
        assert "context" in finding, f"finding missing 'context': {finding}"
        assert isinstance(finding["code"], str), "'code' must be str"
        assert isinstance(finding["message"], str), "'message' must be str"
        assert isinstance(finding["context"], dict), "'context' must be dict"
