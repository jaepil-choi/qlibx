"""Phase B1 — echolon-mcp exposes 5 catalog-backed indicator tools.

Tools:
  - list_indicators(cluster: str | None = None) -> list[str]
  - indicator_info(name: str) -> dict | None
  - indicator_params(name: str) -> list[dict] | None
  - validate_indicator_list(payload_json: str) -> dict
  - suggest_similar(name: str, limit: int = 5) -> list[str]

Tests drive tool functions through their raw callable (pulled off the server's
registered tool map), which matches how FastMCP dispatches stdio calls.
"""
import asyncio
import json

import pytest

from echolon.mcp.server import build_server


def _get_tool_fn(name: str):
    """Return the raw Python callable registered under `name`.

    FastMCP stores registered tools in server._tool_manager._tools (private, but
    the tests need call-site access to verify behavior without spawning stdio).
    """
    server = build_server()
    tool_manager = server._tool_manager
    if hasattr(tool_manager, "_tools"):
        tools = tool_manager._tools
    elif hasattr(tool_manager, "tools"):
        tools = tool_manager.tools
    else:
        raise RuntimeError(f"Unexpected FastMCP tool_manager shape: {dir(tool_manager)}")
    tool = tools[name]
    return tool.fn


def _registered_tool_names() -> set[str]:
    server = build_server()
    tools = server.list_tools()
    if asyncio.iscoroutine(tools):
        tools = asyncio.run(tools)
    return {t.name for t in tools}


def test_five_new_tools_are_registered():
    names = _registered_tool_names()
    for expected in (
        "list_indicators",
        "indicator_info",
        "indicator_params",
        "validate_indicator_list",
        "suggest_similar",
    ):
        assert expected in names, f"missing tool: {expected}"


def test_list_indicators_without_filter_returns_many():
    fn = _get_tool_fn("list_indicators")
    names = fn()
    assert isinstance(names, list)
    assert len(names) >= 170


def test_list_indicators_with_has_lookback_filter():
    """Phase F-5: list_indicators(has_lookback=True) replaces cluster filter."""
    fn = _get_tool_fn("list_indicators")
    lookback = fn(has_lookback=True)
    assert "rsi" in lookback
    assert "atr" in lookback
    assert "obv" not in lookback  # obv has no period param


def test_indicator_info_enriched_from_catalog():
    """Phase F-5: cluster + output_columns dropped; has_lookback added."""
    fn = _get_tool_fn("indicator_info")
    info = fn("rsi")
    assert info is not None
    assert info["name"] == "rsi"
    assert info["has_lookback"] is True
    assert info["function"] == "rsi"
    assert info["file"] == "ta_lib"
    assert any(p["name"] == "timeperiod" for p in info["params"])


def test_indicator_info_unknown_returns_none():
    fn = _get_tool_fn("indicator_info")
    assert fn("definitely_not_an_indicator") is None


def test_indicator_params_returns_list_of_dicts():
    fn = _get_tool_fn("indicator_params")
    params = fn("rsi")
    assert isinstance(params, list)
    names = [p["name"] for p in params]
    assert "timeperiod" in names


def test_indicator_params_unknown_returns_none():
    fn = _get_tool_fn("indicator_params")
    assert fn("unknown_indicator_xyz") is None


def test_validate_indicator_list_valid_payload():
    fn = _get_tool_fn("validate_indicator_list")
    result = fn(json.dumps({"rsi": {"timeperiod": [10, 20]}, "obv": {}}))
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_indicator_list_unknown_name():
    fn = _get_tool_fn("validate_indicator_list")
    result = fn(json.dumps({"fake_rsi": {}}))
    assert result["valid"] is False
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["field"] == "fake_rsi"
    assert "rsi" in err["suggestion"]
    assert err["code"] == "IND-004"


def test_validate_indicator_list_bad_json():
    fn = _get_tool_fn("validate_indicator_list")
    result = fn("this isn't JSON at all {]")
    assert result["valid"] is False
    assert len(result["errors"]) >= 1
    # parse errors surface as structured errors rather than raising
    assert any("json" in e["message"].lower() or "parse" in e["message"].lower() for e in result["errors"])


def test_suggest_similar_exact_match():
    fn = _get_tool_fn("suggest_similar")
    results = fn("rsi")
    assert "rsi" in results


def test_suggest_similar_respects_limit():
    fn = _get_tool_fn("suggest_similar")
    results = fn("rsi", limit=2)
    assert len(results) <= 2
