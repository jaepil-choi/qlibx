"""Tests for echolon programmatic APIs (Phase 1 workstream C)."""
import re

import pytest
from pathlib import Path


def test_validate_strategy_importable():
    from echolon.native.validation import validate_strategy
    assert callable(validate_strategy)


def test_validate_strategy_returns_result(tmp_path):
    from echolon.native.validation import validate_strategy
    # Point at a template directory that should validate OK (or an empty dir that fails clean)
    result = validate_strategy(tmp_path)
    # Accept either VALID or a ValidationResult with errors — just that it returns something structured
    assert hasattr(result, "status") or hasattr(result, "errors") or isinstance(result, dict)


def test_get_error_doc_returns_doc():
    from echolon.native.errors import get_error_doc
    doc = get_error_doc("VAL-001")
    assert doc is not None
    # Doc should have at least 'what' or be parseable from docs/errors/VAL-001.md
    assert hasattr(doc, "what") or "what" in str(doc).lower() or isinstance(doc, dict)


def test_get_error_doc_raises_on_unknown_code():
    from echolon.native.errors import get_error_doc
    with pytest.raises((KeyError, ValueError, FileNotFoundError)):
        get_error_doc("ZZZ-999")


def test_indicator_catalog_lists_all():
    from echolon.indicators import catalog
    names = catalog.list_all()
    assert isinstance(names, list)
    # Echolon must ship at least a handful of canonical indicators
    assert any("rsi" in n.lower() or "atr" in n.lower() or "adx" in n.lower() for n in names)


def test_indicator_catalog_info_returns_structure():
    from echolon.indicators import catalog
    info = catalog.info("rsi")
    assert info is not None
    assert hasattr(info, "tier") or hasattr(info, "name") or isinstance(info, dict)


def test_patterns_list_and_get():
    from echolon.native import patterns
    names = patterns.list_patterns()
    assert isinstance(names, list)
    assert len(names) >= 1
    # Keys must be underscore-identifiers (no hyphens/spaces) so callers can use them
    # as natural Python identifiers in dict lookups.
    assert all(re.fullmatch(r"[a-z0-9_]+", n) for n in names), (
        f"pattern keys must be underscore-only identifiers, got: {names}"
    )
    first = names[0]
    p = patterns.get_pattern(first)
    assert p is not None
    # Parser must populate the semantic fields, not just return a hollow dataclass.
    assert p.when_to_use, f"pattern {first!r}: when_to_use is empty"
    assert p.key_idea, f"pattern {first!r}: key_idea is empty"
    assert p.common_errors, f"pattern {first!r}: common_errors is empty"


def test_templates_list_and_load():
    from echolon.native import templates
    names = templates.list_templates()
    assert isinstance(names, list)
    assert len(names) >= 1
    first = names[0]
    tpl = templates.load_template(first)
    assert tpl is not None
    # Template should expose file contents
    assert hasattr(tpl, "files") or isinstance(tpl, dict)
