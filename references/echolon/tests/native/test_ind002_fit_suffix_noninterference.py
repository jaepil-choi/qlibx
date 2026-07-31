"""Item 2 TDD: IND-002 must not fire for vintage-suffixed regime columns.

A strategy that declares ``market_regime__fit20240101`` in its indicator list
and uses ``self.get_market_regime()`` in entry.py must NOT receive an IND-002
"regime column undeclared" error, because the fit-suffix base ``market_regime``
IS in KNOWN_REGIME_COLUMNS.

If this test FAILS, the fix is: expand the fit-suffix base into ``declared``
inside ``_get_declared_indicator_names``.
"""
import json
from pathlib import Path

import pytest

from echolon.native.validation.indicator_validator import validate_indicator_names


def test_ind002_no_interference_for_fit_suffix_regime_column(tmp_path: Path):
    """market_regime__fit20240101 declared → no IND-002 for get_market_regime()."""
    # Write the indicator list with a vintage-suffixed regime column
    indicator_list = {"market_regime__fit20240101": {}}
    (tmp_path / "strategy_indicator_list.json").write_text(
        json.dumps(indicator_list), encoding="utf-8"
    )

    # Write entry.py that uses the dedicated regime accessor
    (tmp_path / "entry.py").write_text(
        "class Entry:\n    def run(self):\n        return self.get_market_regime()\n",
        encoding="utf-8",
    )

    errors = validate_indicator_names(tmp_path)

    ind002_errors = [e for e in errors if hasattr(e, "code") and e.code == "IND-002"]
    assert not ind002_errors, (
        f"Expected no IND-002 for a vintage-suffixed declaration, got: "
        + "\n".join(str(e) for e in ind002_errors)
    )


def test_ind002_accepts_literal_fit_suffix_column_kwarg(tmp_path: Path):
    indicator_list = {"market_regime__fit20240101": {}}
    (tmp_path / "strategy_indicator_list.json").write_text(
        json.dumps(indicator_list), encoding="utf-8"
    )
    (tmp_path / "entry.py").write_text(
        "class Entry:\n"
        "    def run(self):\n"
        "        return self.get_market_regime(column='market_regime__fit20240101')\n",
        encoding="utf-8",
    )

    errors = validate_indicator_names(tmp_path)

    assert not [e for e in errors if getattr(e, "code", None) == "IND-002"]


def test_ind002_flags_undeclared_literal_column_kwarg(tmp_path: Path):
    indicator_list = {"market_regime": {}}
    (tmp_path / "strategy_indicator_list.json").write_text(
        json.dumps(indicator_list), encoding="utf-8"
    )
    (tmp_path / "entry.py").write_text(
        "class Entry:\n"
        "    def run(self):\n"
        "        return self.get_market_regime(column='custom_regime')\n",
        encoding="utf-8",
    )

    errors = validate_indicator_names(tmp_path)

    assert any(
        e.code == "IND-002" and "custom_regime" in (e.fix or "")
        for e in errors
    )
