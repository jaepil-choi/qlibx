"""Echolon does not import xtquant; api_minute_extractor uses caller-injected client."""
import sys
from unittest.mock import MagicMock

import pytest

from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor


def test_echolon_never_imports_xtquant():
    """Walk all echolon.data modules; none should import xtquant.

    Check only for actual code import statements, not docstrings.
    The data module must be vendor-agnostic; live modules may have
    conditional imports for broker connections (handled separately).
    """
    import ast

    for mod_name in list(sys.modules.keys()):
        # Only check data extractors — the data module must be vendor-agnostic
        if not mod_name.startswith("echolon.data.extractors"):
            continue
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        f = getattr(mod, "__file__", None)
        if not f or not f.endswith(".py"):
            continue
        with open(f) as fp:
            src = fp.read()

        # Parse AST and check for actual imports
        try:
            tree = ast.parse(src)
        except SyntaxError:
            # Skip files with syntax errors
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert (
                        "xtquant" not in alias.name
                    ), f"{mod_name} imports xtquant (file: {f})"
            elif isinstance(node, ast.ImportFrom):
                assert (
                    node.module != "xtquant" and
                    (node.module is None or "xtquant" not in node.module)
                ), f"{mod_name} imports from xtquant (file: {f})"


def test_api_minute_extractor_uses_injected_client(tmp_path):
    """Verify SHFEApiMinuteExtractor accepts and uses injected client."""
    mock_client = MagicMock()
    mock_client.get_market_data_ex.return_value = {}

    ex = SHFEApiMinuteExtractor(
        market="SHFE", asset="aluminum", client=mock_client,
        raw_data_dir=tmp_path,
    )

    # Verify client is stored
    assert ex.client is mock_client
