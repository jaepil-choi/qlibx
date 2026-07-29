from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from qlibx import Project, QlibxError
from qlibx.agent import public_example
from qlibx.artifacts import ArtifactStore, record_decision_intermediates
from qlibx.execution import open_run_catalog, run_strategy_batch
from qlibx.extensions import (
    invoke_exposure_analyzer,
    invoke_report_renderer,
    invoke_signal_transform,
    load_extension,
)
from qlibx.reporting import (
    AnalysisSection,
    analyze_stored_run,
    compose_report,
    render_report,
)
from qlibx.research import ResearchCatalog
from qlibx.strategy import DecisionResult, IntermediateRecord


def audited_strategy(datasets, *, audit_path: str):
    path = Path(audit_path)
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(previous + "called\n", encoding="utf-8")
    return pd.DataFrame(0.5, index=datasets["returns"].index, columns=datasets["returns"].columns)


def test_installed_example_builds_valid_project_local_exponential_decay(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    source = project.paths.extensions / "exponential_decay.py"
    source.write_text(public_example("exponential_decay")["content"], encoding="utf-8")
    reference, implementation = load_extension(
        project,
        extension_id="local_decay",
        contract="signal_transform",
        contract_version="1",
        source=source,
        callable_name="apply",
    )
    dates = pd.date_range("2025-01-01", periods=3)
    values = pd.DataFrame({"A": [1.0, pd.NA, 3.0]}, index=dates, dtype="Float64")
    result = invoke_signal_transform(reference, implementation, values, span=2)
    assert result.index.equals(values.index)
    assert result.columns.equals(values.columns)
    assert pd.isna(result.iloc[1, 0])
    assert reference.source.is_relative_to(project.paths.extensions)
    assert reference.source_digest

    outside = project.paths.state / "outside.py"
    outside.write_text("def apply(values): return values\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the configured extension root"):
        load_extension(
            project,
            extension_id="outside",
            contract="signal_transform",
            contract_version="1",
            source=outside,
            callable_name="apply",
        )


def test_local_analyzer_and_renderer_share_public_artifact_contract(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    store = ArtifactStore.from_project(project)
    envelope = store.record(
        run_id="run-1",
        name="weights",
        value=pd.DataFrame({"A": [0.2, -0.1]}),
        artifact_type="signed_weight",
        producer_id="strategy.local",
        producer_version="1",
        implementation_digest="source-sha",
        data_semantics="signed ticker weight",
    )
    analyzer_source = project.paths.extensions / "analyzer.py"
    analyzer_source.write_text(
        "from qlibx.reporting import AnalysisSection\n"
        "def analyze(envelope, payload):\n"
        "    gross = float(payload.abs().sum().sum())\n"
        "    return AnalysisSection('local_exposure', '1', (envelope.artifact_id,), "
        "{'gross': gross})\n",
        encoding="utf-8",
    )
    analyzer_ref, analyzer = load_extension(
        project,
        extension_id="local_analyzer",
        contract="exposure_analyzer",
        contract_version="1",
        source=analyzer_source,
        callable_name="analyze",
    )
    section = invoke_exposure_analyzer(
        analyzer_ref,
        analyzer,
        envelope,
        store.load_payload(envelope.artifact_id),
    )
    assert section.data["gross"] == pytest.approx(0.3)

    renderer_source = project.paths.extensions / "renderer.py"
    renderer_source.write_text(
        "def render(document):\n"
        "    return '|'.join(section.section_id for section in document.sections)\n",
        encoding="utf-8",
    )
    renderer_ref, renderer = load_extension(
        project,
        extension_id="local_renderer",
        contract="report_renderer",
        contract_version="1",
        source=renderer_source,
        callable_name="render",
    )
    document = compose_report((section,), report_id="local-report")
    rendered = invoke_report_renderer(renderer_ref, renderer, document)
    assert rendered == b"local_exposure"
    output = render_report(
        document,
        tmp_path / "local-report.txt",
        renderer=lambda value: invoke_report_renderer(renderer_ref, renderer, value),
    )
    assert output.output.read_bytes() == b"local_exposure"


def test_complete_artifact_exports_imports_and_detects_corruption(tmp_path: Path) -> None:
    first = ArtifactStore.from_project(Project.initialize(tmp_path / "first"))
    envelope = first.record(
        run_id="run-1",
        name="signal",
        value=pd.DataFrame({"A": [1.0, 2.0]}),
        artifact_type="signal",
        producer_id="built-in",
        producer_version="1",
        implementation_digest="digest",
        time_range=("2025-01-01", "2025-01-02"),
        axis="date_by_ticker",
        unit="score",
        timezone="Asia/Seoul",
        data_semantics="point-in-time signal",
        coverage={"rows": 2},
    )
    bundle = first.export_bundle((envelope.artifact_id,), tmp_path / "bundle")
    second = ArtifactStore.from_project(Project.initialize(tmp_path / "second"))
    imported = second.import_bundle(bundle)
    assert imported[0].artifact_id == envelope.artifact_id
    pd.testing.assert_frame_equal(
        second.load_payload(envelope.artifact_id),
        first.load_payload(envelope.artifact_id),
    )

    incomplete = first.record(
        run_id="run-2",
        name="scratch",
        value={"partial": True},
        artifact_type="diagnostic",
        producer_id="worker",
        producer_version="1",
        implementation_digest="digest",
        data_semantics="incomplete scratch",
        status="incomplete",
    )
    with pytest.raises(QlibxError) as not_portable:
        first.export_bundle((incomplete.artifact_id,), tmp_path / "incomplete-bundle")
    assert not_portable.value.code == "QLIBX_ARTIFACT_NOT_PORTABLE"
    assert not_portable.value.context["status"] == "incomplete"

    payload = next((bundle / envelope.artifact_id).glob("payload.*"))
    payload.write_bytes(b"corrupt")
    third = ArtifactStore.from_project(Project.initialize(tmp_path / "third"))
    with pytest.raises(QlibxError) as corrupt:
        third.import_bundle(bundle)
    assert corrupt.value.code == "QLIBX_ARTIFACT_PAYLOAD_CORRUPT"
    assert corrupt.value.context["artifact_id"] == envelope.artifact_id


def test_strategy_intermediate_is_physical_and_reloadable_without_strategy(tmp_path: Path) -> None:
    store = ArtifactStore.from_project(Project.initialize(tmp_path))
    result = DecisionResult(
        "weight",
        pd.DataFrame({"A": [0.2]}),
        intermediates=(IntermediateRecord("pre_budget", 0, pd.DataFrame({"A": [0.1]})),),
        primary_result_id="decision-primary-1",
    )
    recorded = record_decision_intermediates(
        store,
        result,
        run_id="strategy-run-1",
        producer_id="strategy.local",
        producer_version="2",
        implementation_digest="source-digest",
    )
    assert recorded[0].payload_path.is_file()
    assert recorded[0].parent_artifact_ids == ("decision-primary-1",)
    reloaded = store.load_payload(recorded[0].artifact_id)
    assert reloaded.iloc[0, 0] == pytest.approx(0.1)


def test_stored_qlib_analysis_report_and_raw_access_do_not_rerun_strategy(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    config_path, audit_path, catalog_path = _small_public_run_config(tmp_path)
    run = run_strategy_batch(config_path, strategy_ids=("audited",), max_workers=1).runs[0]
    calls_before = audit_path.read_text(encoding="utf-8").splitlines()
    research = ResearchCatalog.from_project(project)
    state_before = _tree_digest(research.state)

    raw_orders = open_run_catalog(catalog_path).load_table(run.backtest_run_id, "orders")
    assert isinstance(raw_orders, pd.DataFrame)
    built_in = analyze_stored_run(catalog_path, run.backtest_run_id)
    local_section = AnalysisSection(
        "local_note",
        "1",
        (run.backtest_run_id,),
        {"note": "stored only"},
    )
    document = compose_report(
        (*built_in.sections, local_section),
        report_id="composed",
        include=("execution", "local_note", "performance"),
        order=("local_note", "performance", "execution"),
    )
    report = render_report(document, tmp_path / "report.html", renderer="html")
    assert report.output.exists()
    assert [section.section_id for section in document.sections] == [
        "local_note",
        "performance",
        "execution",
    ]
    assert audit_path.read_text(encoding="utf-8").splitlines() == calls_before
    assert _tree_digest(research.state) == state_before
    manifest = json.loads(report.manifest.read_text(encoding="utf-8"))
    assert manifest["artifact_role"] == "report_output_not_canonical_research_artifact"


def _small_public_run_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    dates = pd.bdate_range("2025-01-02", periods=3)
    data = tmp_path / "engine-data"
    data.mkdir()
    matrices = {
        "returns": pd.DataFrame({"A": [0.0, 0.01, -0.01]}, index=dates),
        "execution_price": pd.DataFrame({"A": [10.0, 10.0, 11.0]}, index=dates),
        "universe": pd.DataFrame({"A": [True, True, True]}, index=dates),
        "benchmark_weight": pd.DataFrame({"A": [0.0, 0.0, 0.0]}, index=dates),
    }
    datasets = {}
    for name, frame in matrices.items():
        path = data / f"{name}.parquet"
        frame.rename_axis(index="date", columns="ticker").stack(future_stack=True).rename(
            name
        ).reset_index().to_parquet(path, index=False)
        datasets[name] = {"path": str(path), "format": "parquet", "value_column": name}
    audit = tmp_path / "invocations.txt"
    catalog = tmp_path / "runs.duckdb"
    config = {
        "version": 1,
        "run_store": {"catalog_uri": str(catalog), "artifact_dir": str(tmp_path / "runs")},
        "data": {"datasets": datasets},
        "backtest": {
            "initial_cash": 1_000.0,
            "execution_price": "execution_price",
            "universe": "universe",
            "benchmark_weight": "benchmark_weight",
            "signal_lag": 0,
            "target_semantics": "long_only",
        },
        "strategies": {
            "audited": {
                "callable": f"{__name__}:audited_strategy",
                "datasets": {"returns": "returns"},
                "parameters": {"audit_path": str(audit)},
            }
        },
    }
    path = tmp_path / "engine.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path, audit, catalog


def _tree_digest(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (str(path.relative_to(root)), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
