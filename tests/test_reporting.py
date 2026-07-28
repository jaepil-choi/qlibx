from __future__ import annotations

import json
from pathlib import Path

from qlibx.reporting import BacktestAnalysis, render_analysis


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
