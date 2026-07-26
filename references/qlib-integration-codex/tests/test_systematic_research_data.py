from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qlib_extended.research import ConfigDrivenDataLoader, DataCatalog


def test_config_loader_reads_logical_table_and_matrix(tmp_path: Path) -> None:
    config_dir, parquet_path = _write_minimal_catalog(tmp_path)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03"]),
            "ticker": ["A", "B", "A"],
            "value": [1.0, 2.0, 3.0],
        }
    ).to_parquet(parquet_path, index=False)

    loader = ConfigDrivenDataLoader.from_directory(config_dir)
    table = loader.load_table("sample_table")
    matrix = loader.load_matrix("sample_matrix")

    assert list(table.columns) == ["date", "ticker", "value"]
    assert isinstance(table["date"].dtype, pd.DatetimeTZDtype) is False
    assert matrix.index.equals(pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"))
    assert matrix.columns.tolist() == ["A", "B"]
    assert matrix.loc[pd.Timestamp("2024-01-02"), "B"] == 2.0
    assert matrix.dtypes.eq("float64").all()
    assert len(loader.catalog.config_fingerprint) == 64


def test_matrix_alignment_is_explicit(tmp_path: Path) -> None:
    config_dir, parquet_path = _write_minimal_catalog(tmp_path)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "ticker": ["A", "B"],
            "value": [1.0, 2.0],
        }
    ).to_parquet(parquet_path, index=False)
    like = pd.DataFrame(
        0.0,
        index=pd.DatetimeIndex(["2024-01-03", "2024-01-04"], name="date"),
        columns=pd.Index(["B", "C"], name="ticker"),
    )

    matrix = ConfigDrivenDataLoader.from_directory(config_dir).load_matrix(
        "sample_matrix", like=like
    )

    assert matrix.index.equals(like.index)
    assert matrix.columns.equals(like.columns)
    assert matrix.loc[pd.Timestamp("2024-01-03"), "B"] == 2.0
    assert pd.isna(matrix.loc[pd.Timestamp("2024-01-04"), "C"])


def test_duplicate_yaml_key_fails(tmp_path: Path) -> None:
    config_dir, _ = _write_minimal_catalog(tmp_path)
    (config_dir / "sources.yaml").write_text(
        "parquet_sources:\n"
        "  sample:\n"
        "    path: sample.parquet\n"
        "  sample:\n"
        "    path: other.parquet\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate YAML key"):
        DataCatalog.from_directory(config_dir)


def test_duplicate_dataset_across_fragments_fails(tmp_path: Path) -> None:
    config_dir, _ = _write_minimal_catalog(tmp_path)
    (config_dir / "base.yaml").write_text(
        _base_yaml(["datasets/sample.yaml", "datasets/duplicate.yaml"]),
        encoding="utf-8",
    )
    (config_dir / "datasets" / "duplicate.yaml").write_text(
        "datasets:\n"
        "  sample_table:\n"
        "    kind: table\n"
        "    sources: [sample]\n"
        "    query: select date, ticker, value from sample\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate logical dataset"):
        DataCatalog.from_directory(config_dir)


def test_missing_source_file_fails_on_query(tmp_path: Path) -> None:
    config_dir, _ = _write_minimal_catalog(tmp_path)
    loader = ConfigDrivenDataLoader.from_directory(config_dir)

    with pytest.raises(FileNotFoundError, match="Missing parquet source: sample"):
        loader.load_table("sample_table")


def test_duplicate_matrix_keys_fail(tmp_path: Path) -> None:
    config_dir, parquet_path = _write_minimal_catalog(tmp_path)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "ticker": ["A", "A"],
            "value": [1.0, 2.0],
        }
    ).to_parquet(parquet_path, index=False)

    loader = ConfigDrivenDataLoader.from_directory(config_dir)
    with pytest.raises(ValueError, match="duplicate date/ticker rows"):
        loader.load_matrix("sample_matrix")


def test_table_dataset_cannot_be_loaded_as_matrix(tmp_path: Path) -> None:
    config_dir, parquet_path = _write_minimal_catalog(tmp_path)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"]),
            "ticker": ["A"],
            "value": [1.0],
        }
    ).to_parquet(parquet_path, index=False)

    loader = ConfigDrivenDataLoader.from_directory(config_dir)
    with pytest.raises(ValueError, match="Dataset is not a matrix"):
        loader.load_matrix("sample_table")


def test_repository_research_catalog_resolves_declared_datasets() -> None:
    config_dir = Path(__file__).parents[1] / "configs" / "data"
    catalog = DataCatalog.from_directory(config_dir)

    expected = {
        "adjusted_return",
        "benchmark_weight",
        "consensus_valuation",
        "financial_quarterly_items",
        "industry_code",
    }
    assert expected.issubset(catalog.datasets)
    assert all(source.path.exists() for source in catalog.sources.values())
    assert len(catalog.config_fingerprint) == 64


def _write_minimal_catalog(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    config_dir = project / "configs" / "data"
    dataset_dir = config_dir / "datasets"
    data_dir = project / "data" / "preprocessed"
    dataset_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (config_dir / "base.yaml").write_text(
        _base_yaml(["datasets/sample.yaml"]), encoding="utf-8"
    )
    (config_dir / "sources.yaml").write_text(
        "parquet_sources:\n"
        "  sample:\n"
        "    root: preprocessed\n"
        "    path: sample.parquet\n",
        encoding="utf-8",
    )
    (dataset_dir / "sample.yaml").write_text(
        "datasets:\n"
        "  sample_table:\n"
        "    kind: table\n"
        "    sources: [sample]\n"
        "    query: select date, ticker, value from sample\n"
        "  sample_matrix:\n"
        "    kind: matrix\n"
        "    sources: [sample]\n"
        "    query: select date, ticker, value from sample\n"
        "    index: date\n"
        "    columns: ticker\n"
        "    values: value\n"
        "    dtype: float64\n",
        encoding="utf-8",
    )
    return config_dir, data_dir / "sample.parquet"


def _base_yaml(dataset_files: list[str]) -> str:
    files = "\n".join(f"    - {path}" for path in dataset_files)
    return (
        "schema_version: 1\n"
        "paths:\n"
        "  preprocessed: data/preprocessed\n"
        "catalog:\n"
        "  source_file: sources.yaml\n"
        "  dataset_files:\n"
        f"{files}\n"
    )
