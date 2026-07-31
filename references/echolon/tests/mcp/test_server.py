"""Tests for echolon-mcp server (Task 18)."""
import pytest


def test_mcp_server_module_importable():
    from echolon.mcp.server import build_server
    assert callable(build_server)


def test_mcp_server_registers_core_tools():
    """Server must expose validate_strategy, get_error_doc, list_indicators, etc."""
    from echolon.mcp.server import build_server
    import asyncio
    server = build_server()
    # FastMCP server exposes list_tools() — may be async. Handle both.
    tools_attr = server.list_tools()
    if asyncio.iscoroutine(tools_attr):
        tools = asyncio.run(tools_attr)
    else:
        tools = tools_attr
    tool_names = {t.name for t in tools}
    assert "validate_strategy" in tool_names
    assert "get_error_doc" in tool_names
    assert "list_indicators" in tool_names
    assert "list_patterns" in tool_names
    assert "list_templates" in tool_names
