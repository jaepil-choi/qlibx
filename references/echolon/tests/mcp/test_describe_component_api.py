"""Tests for the ``describe_component_api`` MCP tool.

This tool returns the live ``BaseComponent`` + ``IMarketData`` API surface
via ``inspect.signature()`` so callers (LLM coding agents) can discover
the canonical method names BEFORE writing component code, instead of
hallucinating from training-data priors.

The tool is drift-free by construction: it reads the live classes, so
if a method changes signature in echolon's source the tool's output
changes with it. These tests exercise that property.
"""
import asyncio

import pytest

from echolon.mcp.server import build_server


def _get_tool_fn(name: str):
    server = build_server()
    tool_manager = server._tool_manager
    if hasattr(tool_manager, "_tools"):
        tools = tool_manager._tools
    elif hasattr(tool_manager, "tools"):
        tools = tool_manager.tools
    else:
        raise RuntimeError(f"Unexpected FastMCP tool_manager shape: {dir(tool_manager)}")
    return tools[name].fn


def _registered_tool_names() -> set[str]:
    server = build_server()
    tools = server.list_tools()
    if asyncio.iscoroutine(tools):
        tools = asyncio.run(tools)
    return {t.name for t in tools}


def test_describe_component_api_is_registered():
    assert "describe_component_api" in _registered_tool_names()


@pytest.fixture
def api():
    return _get_tool_fn("describe_component_api")()


def test_top_level_keys_present(api):
    assert "BaseComponent" in api
    assert "IMarketData" in api


def test_imarketdata_lists_get_current_bar_with_correct_signature(api):
    methods = api["IMarketData"]["methods"]
    by_name = {m["name"]: m for m in methods}
    # Critical anti-hallucination signature:
    #   `current_bar` is NOT an attribute — it's `get_current_bar()` returning a dict.
    assert "get_current_bar" in by_name, (
        f"get_current_bar missing from IMarketData; got: {list(by_name)}"
    )
    sig = by_name["get_current_bar"]["signature"]
    assert "Dict[str, float]" in sig or "dict" in sig.lower(), (
        f"get_current_bar signature should advertise dict return; got: {sig}"
    )


def test_basecomponent_override_methods_are_the_4_components(api):
    override_names = {m["name"] for m in api["BaseComponent"]["override_methods"]}
    # Each component file overrides exactly one of these.
    assert override_names == {"generate_signal", "should_exit", "can_trade", "calculate_size"}, (
        f"override_methods should be exactly the 4 BaseComponent stubs; got: {sorted(override_names)}"
    )


def test_basecomponent_helper_methods_include_known_callables(api):
    helper_names = {m["name"] for m in api["BaseComponent"]["helper_methods"]}
    # Helpers strategies actually call.
    for required in ("get_current_price", "get_current_bar", "get_indicator", "get_param"):
        assert required in helper_names, (
            f"{required} missing from BaseComponent helpers; "
            f"got a sample of: {sorted(list(helper_names))[:20]}"
        )


def test_basecomponent_does_not_expose_invented_attributes(api):
    """Pin the negative case: things agents have hallucinated must not appear."""
    all_names = (
        {m["name"] for m in api["BaseComponent"]["override_methods"]}
        | {m["name"] for m in api["BaseComponent"]["helper_methods"]}
        | {p["name"] for p in api["BaseComponent"]["properties"]}
    )
    # `indicators` was previously listed; it's a real method on BaseComponent
    # (`get_indicators(self) -> tuple`), so testing for `self.indicators` as
    # a hallucination would be wrong. The verified hallucinations are:
    hallucinations = {"current_bar", "bar_index", "current_bar_index"}
    leaked = hallucinations & all_names
    assert not leaked, (
        f"BaseComponent unexpectedly exposes hallucinated names: {leaked}. "
        f"If this is intentional, update the trading-api-core skill pitfalls "
        f"section accordingly."
    )


def test_signatures_are_strings(api):
    """Smoke check: every method entry has a string signature, not a Signature object."""
    for source, methods in [
        ("BaseComponent.override_methods", api["BaseComponent"]["override_methods"]),
        ("BaseComponent.helper_methods", api["BaseComponent"]["helper_methods"]),
        ("IMarketData.methods", api["IMarketData"]["methods"]),
    ]:
        for m in methods:
            assert isinstance(m["signature"], str), (
                f"{source}: {m['name']} signature is {type(m['signature'])} not str"
            )
            assert m["signature"].startswith("("), (
                f"{source}: {m['name']} signature doesn't start with '(': {m['signature']!r}"
            )
