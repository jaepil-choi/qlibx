from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from qlibx import Project, QlibxError
from qlibx.config import read_yaml
from qlibx.data import (
    ConfigDrivenDataLoader,
    DataCatalog,
    data_requirements,
    plan_registration,
    register_dataset,
)


def test_yaml_registration_then_config_driven_table_and_matrix(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    source = tmp_path / "data" / "preprocessed" / "sample.parquet"
    source.parent.mkdir(parents=True)
    source_table = pa.table(
        {
            "event_date": pa.array(
                [datetime(2024, 1, 2), datetime(2024, 1, 2), datetime(2024, 1, 3)],
                type=pa.timestamp("us"),
            ),
            "instrument": ["A", "B", "A"],
            "value": [1.0, 2.0, 3.0],
        }
    )
    pq.write_table(source_table, source)
    before = _digest(source)
    _write_config(tmp_path)

    plan = plan_registration(project, "sample")
    assert plan.canonical_columns == ("available_at", "ticker", "value")
    result = register_dataset(project, "sample")

    assert _digest(source) == before
    assert result.information_values_preserved
    assert Path(result.provenance).is_relative_to(tmp_path / ".qlibx")
    assert not tuple((tmp_path / "config").rglob("*.json"))
    canonical = pq.read_table(result.output)
    assert canonical.column_names == ["available_at", "ticker", "value"]
    assert "event_date" not in canonical.column_names
    assert canonical["available_at"].to_pylist() == [
        datetime(2024, 1, 1),
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
    ]
    assert canonical["value"].equals(source_table["value"])

    loader = ConfigDrivenDataLoader.from_project(project)
    assert loader.catalog.datasets["sample_matrix"].time_field == "available_at"
    assert loader.catalog.datasets["sample_matrix"].availability_field == "available_at"
    table = loader.load_full_history(
        "sample_table", reason="registration smoke", end="2024-01-01", tickers=["B"]
    )
    matrix = loader.load_full_history_matrix("sample_matrix", reason="registration smoke")
    assert table[["ticker", "value"]].to_dict(orient="records") == [{"ticker": "B", "value": 2.0}]
    assert matrix.loc[pd.Timestamp("2024-01-01"), "B"] == 2.0
    assert matrix.loc[pd.Timestamp("2024-01-02"), "A"] == 3.0
    assert len(loader.catalog.fingerprint) == 64


def test_duplicate_yaml_key_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("a: 1\na: 2\n", encoding="utf-8")
    with pytest.raises(QlibxError, match="DATA_REGISTRATION") as duplicate:
        read_yaml(path, stage="DATA_REGISTRATION")
    # The duplicate is found inside PyYAML; the stage still has to survive down there.
    assert duplicate.value.stage == "DATA_REGISTRATION"


def test_missing_registration_mapping_is_agent_readable(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    source = tmp_path / "data" / "preprocessed" / "sample.parquet"
    source.parent.mkdir(parents=True)
    pq.write_table(pa.table({"event_date": [datetime(2024, 1, 1)], "instrument": ["A"]}), source)
    _write_config(tmp_path, missing_information=True)
    with pytest.raises(QlibxError, match="DATA_REGISTRATION") as raised:
        plan_registration(project, "sample")
    assert raised.value.context["requirements"]["required_axis"][0]["field"] == "available_at"


def test_catalog_rejects_duplicate_dataset_across_fragments(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    _write_config(tmp_path)
    extra = tmp_path / "config" / "qlibx" / "data" / "datasets" / "extra.yaml"
    extra.write_text(
        "datasets:\n  sample_table:\n    kind: table\n    sources: [sample]\n"
        "    query: select * from sample\n",
        encoding="utf-8",
    )
    base = tmp_path / "config" / "qlibx" / "data" / "base.yaml"
    base.write_text(base.read_text() + "    - datasets/extra.yaml\n", encoding="utf-8")
    with pytest.raises(QlibxError, match="DATA_REGISTRATION"):
        DataCatalog.from_project(project)


def test_requirements_have_only_generic_axis_and_information() -> None:
    requirement = data_requirements(("info_1", "info_2"))
    assert [item["field"] for item in requirement["required_axis"]] == [
        "available_at",
        "ticker",
    ]
    assert "price" not in str(requirement).lower()
    assert "factor" not in str(requirement).lower()


def test_repository_uses_yaml_config_driven_catalog_only() -> None:
    root = Path(__file__).parents[1]
    project = Project.load(root)
    catalog = DataCatalog.from_project(project)
    assert {"returns", "k200_membership", "industry_code"} <= set(catalog.datasets)
    assert {path.suffix for path in (root / "config").rglob("*") if path.is_file()} == {".yaml"}


def test_event_time_and_availability_cutoff_are_independent(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    canonical = project.paths.generated_data / "events.parquet"
    pd.DataFrame(
        {
            "available_at": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "event_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "ticker": ["A", "A"],
            "value": [1.0, 2.0],
        }
    ).to_parquet(canonical, index=False)
    data_root = project.paths.config / "data"
    (data_root / "datasets").mkdir(parents=True)
    (data_root / "base.yaml").write_text(
        """schema_version: 1
paths: {canonical: data/qlibx}
catalog:
  source_file: sources.yaml
  dataset_files: [datasets/events.yaml]
""",
        encoding="utf-8",
    )
    (data_root / "sources.yaml").write_text(
        "parquet_sources:\n  events: {root: canonical, path: events.parquet}\n",
        encoding="utf-8",
    )
    (data_root / "datasets" / "events.yaml").write_text(
        """datasets:
  values:
    kind: matrix
    sources: [events]
    query: select available_at, event_date, ticker, value from events
    index: event_date
    columns: ticker
    values: value
    time_field: event_date
    availability_field: available_at
""",
        encoding="utf-8",
    )
    loader = ConfigDrivenDataLoader.from_project(project)
    matrix = loader.load_matrix("values", as_of="2025-01-01", start="2025-01-02", end="2025-01-03")
    assert matrix.index.tolist() == [pd.Timestamp("2025-01-02")]
    assert matrix.iloc[0, 0] == 1.0

    # Forgetting the cutoff is the one mistake here that yields a better-looking result
    # instead of a failure, so omitting it must not be spellable.
    with pytest.raises(TypeError, match="as_of"):
        loader.load_table("values")  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="as_of"):
        loader.load_matrix("values")  # type: ignore[call-arg]

    unbounded = loader.load_full_history("values", reason="operator inspection")
    assert len(unbounded) > len(loader.load_table("values", as_of="2025-01-01"))
    with pytest.raises(QlibxError) as no_reason:
        loader.load_full_history("values", reason="   ")
    assert no_reason.value.stage == "DATA_REGISTRATION"


def _write_config(root: Path, *, missing_information: bool = False) -> None:
    config = root / "config" / "qlibx" / "data"
    datasets = config / "datasets"
    datasets.mkdir(parents=True)
    (config / "base.yaml").write_text(
        "schema_version: 1\npaths:\n  canonical: data/qlibx\n"
        "catalog:\n  source_file: sources.yaml\n  dataset_files:\n"
        "    - datasets/sample.yaml\n",
        encoding="utf-8",
    )
    (config / "registrations.yaml").write_text(
        "registrations:\n  sample:\n    source: data/preprocessed/sample.parquet\n"
        "    output: data/qlibx/sample.parquet\n    available_at:\n"
        "      source: event_date\n      offset_days: -1\n    ticker: instrument\n"
        "    information:\n"
        f"      value: {'missing' if missing_information else 'value'}\n"
        "    primary_key: [event_date, instrument]\n    frequency: daily\n"
        "    timezone: Asia/Seoul\n",
        encoding="utf-8",
    )
    (config / "sources.yaml").write_text(
        "parquet_sources:\n  sample:\n    path: sample.parquet\n",
        encoding="utf-8",
    )
    (datasets / "sample.yaml").write_text(
        "datasets:\n  sample_table:\n    kind: table\n    sources: [sample]\n"
        "    query: select available_at, ticker, value from sample\n"
        "  sample_matrix:\n    kind: matrix\n    sources: [sample]\n"
        "    query: select available_at, ticker, value from sample\n"
        "    index: available_at\n    columns: ticker\n    values: value\n"
        "    dtype: float64\n",
        encoding="utf-8",
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
