"""Name-lookup tools must return an actionable error (with the valid list) for an
unknown name — not ``None``.

``get_skill`` / ``get_pattern`` / ``load_template`` previously returned ``None``
for an unknown name, which FastMCP serializes to an EMPTY content list. A
ChatCompletions client then can't extract a text part and drops the output for an
opaque placeholder (logging "tool outputs cannot be empty…"). Returning an error
dict that names the valid options instead lets the calling agent self-correct in
one turn.
"""
from __future__ import annotations

import pytest

from echolon.mcp.server import build_server
from echolon.native import patterns as _patterns
from echolon.native import skills as _skills
from echolon.native import templates as _templates


def _get_tool(server, name: str):
    for tool in server._tool_manager._tools.values():
        if tool.name == name:
            return tool
    raise KeyError(f"tool {name!r} not registered")


@pytest.fixture(scope="module")
def server():
    return build_server()


def test_get_skill_unknown_returns_error_with_available(server):
    out = _get_tool(server, "get_skill").fn(name="does_not_exist_xyz")
    assert out is not None  # was None -> empty MCP content -> placeholder + warning
    assert "error" in out
    assert "does_not_exist_xyz" in out["error"]
    assert _skills.list_skills()[0] in out["error"]  # the real valid names are listed


def test_get_pattern_unknown_returns_error_with_available(server):
    out = _get_tool(server, "get_pattern").fn(name="nope_pattern")
    assert out is not None and "error" in out
    assert "nope_pattern" in out["error"]
    assert _patterns.list_patterns()[0] in out["error"]


def test_load_template_unknown_returns_error_with_available(server):
    out = _get_tool(server, "load_template").fn(name="nope_template")
    assert out is not None and "error" in out
    assert "nope_template" in out["error"]
    assert _templates.list_templates()[0] in out["error"]


def test_known_name_still_returns_payload(server):
    out = _get_tool(server, "get_skill").fn(name=_skills.list_skills()[0])
    assert "error" not in out
    assert out["name"] == _skills.list_skills()[0]
