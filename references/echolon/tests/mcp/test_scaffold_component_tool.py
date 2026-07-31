"""Phase A5 — scaffold_component MCP tool.

Tool signature + registration + happy-path (per kind) + failure-path assertions
via the in-process FastMCP tool manager (stdio smoke lives in test_stdio_smoke.py).
"""
import asyncio
from pathlib import Path

import pytest

from echolon.mcp.server import build_server


# ---------------------------------------------------------------------------
# Helpers (mirrors test_generate_strategy_params_tool.py)
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
# 1. Registration check
# ---------------------------------------------------------------------------

def test_scaffold_component_tool_registered():
    assert "scaffold_component" in _registered()


# ---------------------------------------------------------------------------
# 2. Happy path — parametrized over all 5 kinds
# ---------------------------------------------------------------------------

_EXPECTED_FILES = {
    "entry":    "entry.py",
    "exit":     "exit.py",
    "risk":     "risk.py",
    "sizer":    "sizer.py",
    "strategy": "strategy.py",
}


@pytest.mark.parametrize("kind", ["entry", "exit", "risk", "sizer", "strategy"])
def test_scaffold_component_happy_path(kind, tmp_path):
    fn = _get_tool_fn("scaffold_component")
    result = fn(kind=kind, strategy_dir=str(tmp_path))

    assert result["success"] is True, f"Expected success but got: {result}"
    assert result["kind"] == kind
    assert result["error"] is None

    expected_file = tmp_path / _EXPECTED_FILES[kind]
    assert expected_file.exists(), f"Expected {expected_file} to be created"
    assert expected_file.stat().st_size > 0, "Scaffolded file should be non-empty"

    assert result["output_path"] == str(expected_file)

    # File must be a valid Python stub — at minimum it should be non-empty
    content = expected_file.read_text(encoding="utf-8")
    assert len(content) > 0


# ---------------------------------------------------------------------------
# 3. Unknown kind
# ---------------------------------------------------------------------------

def test_scaffold_component_rejects_unknown_kind(tmp_path):
    fn = _get_tool_fn("scaffold_component")
    result = fn(kind="invalid", strategy_dir=str(tmp_path))

    assert result["success"] is False
    assert result["error"] == "unknown_kind"
    assert result["kind"] == "invalid"
    assert result["output_path"] is None
    # message should hint at valid values
    assert "entry" in result["message"]


# ---------------------------------------------------------------------------
# 4. File-exists refusal (force=False)
# ---------------------------------------------------------------------------

def test_scaffold_component_refuses_existing_file_without_force(tmp_path):
    fn = _get_tool_fn("scaffold_component")

    # First call — should succeed
    first = fn(kind="entry", strategy_dir=str(tmp_path))
    assert first["success"] is True

    # Second call without force — must refuse
    second = fn(kind="entry", strategy_dir=str(tmp_path))
    assert second["success"] is False
    assert second["error"] == "file_exists"
    assert second["output_path"] is None


# ---------------------------------------------------------------------------
# 5. File-exists with force=True — overwrites
# ---------------------------------------------------------------------------

def test_scaffold_component_overwrites_with_force(tmp_path):
    fn = _get_tool_fn("scaffold_component")

    # First scaffold
    first = fn(kind="entry", strategy_dir=str(tmp_path))
    assert first["success"] is True

    # Manually corrupt the file
    entry_file = tmp_path / "entry.py"
    entry_file.write_text("# manually edited sentinel", encoding="utf-8")

    # Force overwrite
    third = fn(kind="entry", strategy_dir=str(tmp_path), force=True)
    assert third["success"] is True
    assert third["error"] is None

    content = entry_file.read_text(encoding="utf-8")
    assert "manually edited sentinel" not in content
    assert len(content) > 50  # real scaffold is much larger than the sentinel
