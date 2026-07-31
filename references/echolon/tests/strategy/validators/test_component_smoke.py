"""Tests for the bar-0 component smoke validator (validate_component_smoke).

Positive (no findings) over the three bundled templates — guards against
false positives, which would block valid strategies at the pre-flight gate.
Negative — a copied template whose entry reads an undeclared column base
must surface IND-007.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from echolon.strategy.validators.component_smoke import validate_component_smoke


_TEMPLATES = Path(__file__).resolve().parents[3] / "echolon" / "native" / "templates"


@pytest.mark.parametrize("template", ["minimal", "momentum_breakout", "rsi_mean_reversion"])
def test_bundled_templates_have_no_undeclared_reads(template: str) -> None:
    """Every shipped template declares every indicator its code reads — the
    smoke must produce zero IND-007 (no false positives)."""
    report = validate_component_smoke(_TEMPLATES / template)
    ind007 = [f for f in report.findings if f.code == "IND-007"]
    assert ind007 == [], f"{template} unexpectedly flagged: {[f.message for f in ind007]}"


def test_undeclared_column_read_is_flagged(tmp_path: Path) -> None:
    """Rename the entry's indicator read to a base the JSON never declared —
    the smoke must surface IND-007 for it."""
    broken = tmp_path / "broken"
    shutil.copytree(_TEMPLATES / "momentum_breakout", broken)

    entry = broken / "entry.py"
    txt = entry.read_text(encoding="utf-8")
    mutated = txt.replace("highest_high_", "high_")  # 'high' is not a declared base
    assert mutated != txt, "template column name changed — update this test"
    entry.write_text(mutated, encoding="utf-8")

    report = validate_component_smoke(broken)
    flagged = [f for f in report.findings if f.code == "IND-007"]
    assert flagged, "expected IND-007 for the undeclared 'high_*' read"
    assert any(f.context.get("indicator", "").startswith("high_") for f in flagged)


def test_missing_indicator_list_is_inconclusive(tmp_path: Path) -> None:
    """No strategy_indicator_list.json → nothing to check against → empty
    report (never raises)."""
    report = validate_component_smoke(tmp_path)
    assert report.findings == []


def test_ind007_is_documented() -> None:
    """The catalog + markdown must back the code the validator emits, so
    get_error_doc('IND-007') (which the agents call) does not KeyError."""
    from echolon.native.errors import get_error_doc

    doc = get_error_doc("IND-007")
    assert doc.code == "IND-007"
    assert doc.what
    assert doc.fix
