"""Phase F-10b/c/d — coverage for the new MCP tools.

Verifies the FastMCP server registers + serves the four tools added in F-10:

  * ``list_skills`` / ``get_skill``  (F-10b)
  * ``get_doc``                       (F-10c)
  * ``validate_strategy_full``        (F-10d)

Plus regression: ``get_error_doc`` now returns ``long_form_markdown`` and
``example`` (F-10a parser-resilience fields).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from echolon.mcp.server import build_server


def _get_tool(server, name: str):
    """Pull the registered async tool callable out of FastMCP's manager."""
    for tool in server._tool_manager._tools.values():
        if tool.name == name:
            return tool
    raise KeyError(f"tool {name!r} not registered")


@pytest.fixture(scope="module")
def server():
    return build_server()


# ---------------------------------------------------------------------------
# F-10a: get_error_doc surfaces long_form_markdown + example
# ---------------------------------------------------------------------------


def test_get_error_doc_returns_long_form_markdown(server) -> None:
    tool = _get_tool(server, "get_error_doc")
    out = tool.fn(code="VAL-001")
    assert "long_form_markdown" in out
    assert out["long_form_markdown"]
    # what / why come from the registry, not from markdown
    from echolon.errors import ERROR_CATALOG
    assert out["what"] == ERROR_CATALOG["VAL-001"]["what"]
    assert out["why"] == ERROR_CATALOG["VAL-001"]["why"]


def test_get_error_doc_returns_example_for_convention_b_codes(server) -> None:
    """Convention-B codes (## Example header) populate the new ``example`` field."""
    tool = _get_tool(server, "get_error_doc")
    out = tool.fn(code="BT-001")
    assert "example" in out
    assert out["example"], "BT-001 has a ## Example section; it should be parsed"


# ---------------------------------------------------------------------------
# F-10b: list_skills + get_skill
# ---------------------------------------------------------------------------


def test_list_skills_returns_dicts_with_descriptions(server) -> None:
    tool = _get_tool(server, "list_skills")
    out = tool.fn()
    assert isinstance(out, list) and out
    by_name = {s["name"]: s for s in out}
    assert "quick_start" in by_name
    assert by_name["quick_start"]["description"], (
        "frontmatter description should be parsed and surfaced"
    )


def test_get_skill_returns_full_body(server) -> None:
    tool = _get_tool(server, "get_skill")
    out = tool.fn(name="quick_start")
    assert out is not None
    assert out["name"] == "quick_start"
    assert out["body"].startswith("---"), "body retains YAML frontmatter"
    assert not out["body_no_frontmatter"].startswith("---"), (
        "body_no_frontmatter strips the frontmatter block"
    )
    assert out["description"]


def test_get_skill_unknown_returns_actionable_error(server) -> None:
    # An unknown name returns an actionable error (with the valid list), NOT None
    # — None serializes to empty MCP content and gets dropped for a placeholder.
    tool = _get_tool(server, "get_skill")
    out = tool.fn(name="not_a_real_skill")
    assert out is not None and "error" in out
    assert "not_a_real_skill" in out["error"]


# ---------------------------------------------------------------------------
# F-10c: get_doc — generic markdown fetcher constrained to echolon/native/
# ---------------------------------------------------------------------------


def test_get_doc_returns_skills_index(server) -> None:
    tool = _get_tool(server, "get_doc")
    out = tool.fn(path="skills/SKILLS.md")
    assert "body" in out
    assert "Echolon Skills Index" in out["body"]
    assert "error" not in out


def test_get_doc_returns_errors_readme(server) -> None:
    tool = _get_tool(server, "get_doc")
    out = tool.fn(path="errors/codes/README.md")
    assert "body" in out
    assert out["body"]


def test_get_doc_refuses_path_traversal(server) -> None:
    tool = _get_tool(server, "get_doc")
    out = tool.fn(path="../../setup.py")
    assert out.get("error") in {"path_outside_native", "not_markdown", "file_not_found"}


def test_get_doc_refuses_absolute_path(server) -> None:
    tool = _get_tool(server, "get_doc")
    out = tool.fn(path="/etc/passwd")
    assert out["error"] == "path_outside_native"


def test_get_doc_refuses_non_markdown(server) -> None:
    tool = _get_tool(server, "get_doc")
    out = tool.fn(path="errors/codes/STR-001.md/../__init__.py")
    # Either path_outside_native, file_not_found, or not_markdown depending on resolution
    assert "error" in out


def test_get_doc_returns_file_not_found_for_unknown(server) -> None:
    tool = _get_tool(server, "get_doc")
    out = tool.fn(path="skills/does_not_exist.md")
    assert out["error"] == "file_not_found"


# ---------------------------------------------------------------------------
# F-10d: validate_strategy_full composes 5 validators
# ---------------------------------------------------------------------------


def test_validate_strategy_full_on_clean_template(server, tmp_path) -> None:
    """A copy of the bundled minimal template should pass every validator."""
    import shutil
    src = (
        Path(__file__).resolve().parents[2]
        / "echolon" / "native" / "templates" / "minimal"
    )
    dest = tmp_path / "clean_strategy"
    shutil.copytree(src, dest)
    tool = _get_tool(server, "validate_strategy_full")
    out = tool.fn(strategy_dir=str(dest))
    assert "status" in out and "any_errors" in out and "findings" in out
    assert "invocations" in out
    invocations = {item["validator"] for item in out["invocations"]}
    assert "validate_strategy" in invocations
    assert "validate_component_protocol_signatures" in invocations
    assert "validate_component_integration" in invocations
    assert "validate_component_logging" in invocations
    assert "validate_parameter_access" in invocations
    # Bundled minimal template is by-construction conformant.
    assert out["status"] == "VALID", f"expected VALID, got findings={out['findings']}"


def test_validate_strategy_full_aggregates_findings_from_multiple_validators(server, tmp_path) -> None:
    """Strategy missing required files should surface STR-001 from
    validate_strategy AND structural failures from the other validators
    (e.g. validate_component_integration can't import a non-existent
    module). The composed tool merges all of them."""
    bare_dir = tmp_path / "broken"
    bare_dir.mkdir()
    tool = _get_tool(server, "validate_strategy_full")
    out = tool.fn(strategy_dir=str(bare_dir))
    assert out["any_errors"] is True
    assert out["status"] == "INVALID"
    assert out["total_findings"] >= 1
    codes = {f.get("code") for f in out["findings"]}
    assert "STR-001" in codes, f"expected STR-001, got {codes}"
