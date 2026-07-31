from __future__ import annotations

import json
from pathlib import Path

import pytest

from qlibx.errors import QlibxError
from qlibx.reporting import (
    AnalysisSection,
    BacktestAnalysis,
    compose_report,
    render_analysis,
    render_report,
)


def test_renderer_uses_typed_analysis_and_writes_manifest(tmp_path: Path) -> None:
    analysis = BacktestAnalysis(
        "backtest-1",
        "stored_backtest_summary",
        "1",
        {"final_nav": 1_234.0, "orders": 10},
    )
    report = render_analysis(analysis, tmp_path / "report.json")
    rendered = json.loads(report.output.read_text(encoding="utf-8"))
    manifest = json.loads(report.manifest.read_text(encoding="utf-8"))
    assert rendered["sections"][0]["data"] == {"final_nav": 1234.0, "orders": 10}
    assert manifest["report_id"] == "analysis-backtest-1"
    assert manifest["output_digest"] == report.digest


def _section(section_id: str) -> AnalysisSection:
    return AnalysisSection(section_id, "1", (), {"value": 1.0})


def test_composition_failures_name_the_reporting_stage_and_show_the_alternatives() -> None:
    """A composition mistake is the caller's, and the caller can fix it -- so it gets a stage.

    Before this contract the same mistakes raised bare `ValueError`, which told an agent
    neither which step of the journey it was in nor what the valid section ids were.
    """
    sections = (_section("performance"), _section("execution"))

    with pytest.raises(QlibxError) as unknown:
        compose_report(sections, report_id="r1", include=["performace"])
    assert unknown.value.stage == "REPORTING"
    assert unknown.value.context["available"] == ["execution", "performance"]

    with pytest.raises(QlibxError) as ordering:
        compose_report(sections, report_id="r1", order=["performance"])
    assert ordering.value.stage == "REPORTING"
    assert ordering.value.context["missing_from_order"] == ["execution"]


def test_an_unsupported_renderer_reports_the_ones_that_exist(tmp_path: Path) -> None:
    """Named-lookup failures share one shape, so `context['available']` always holds the options."""
    document = compose_report((_section("performance"),), report_id="r1")
    with pytest.raises(QlibxError) as failure:
        render_report(document, tmp_path / "report.pdf", renderer="pdf")
    assert failure.value.stage == "REPORTING"
    assert failure.value.context["available"] == ["html", "json"]
