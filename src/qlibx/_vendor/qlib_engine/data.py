from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from .config import ConfigurationError, DatasetConfig, ProjectConfig
from .hashing import file_hash, stable_hash


class MatrixCatalog:
    """Load explicitly declared long-form Parquet datasets as date-by-ticker matrices."""

    def __init__(self, project: ProjectConfig) -> None:
        self._datasets = project.datasets
        self._cache: dict[str, pd.DataFrame] = {}

    def load(self, name: str) -> pd.DataFrame:
        if name in self._cache:
            return self._cache[name].copy()
        if name not in self._datasets:
            raise ConfigurationError(f"unknown logical dataset: {name}")
        spec = self._datasets[name]
        matrix = _read_matrix(name, spec)
        self._cache[name] = matrix
        return matrix.copy()

    def fingerprint(self, names: Iterable[str]) -> str:
        rows = {}
        for name in sorted(set(names)):
            if name not in self._datasets:
                raise ConfigurationError(f"unknown logical dataset: {name}")
            spec = self._datasets[name]
            if not spec.path.exists():
                raise ConfigurationError(f"dataset file does not exist: {spec.path}")
            rows[name] = {
                "format": spec.format,
                "value_column": spec.value_column,
                "content_hash": file_hash(spec.path),
            }
        return stable_hash(rows)


def _read_matrix(name: str, spec: DatasetConfig) -> pd.DataFrame:
    if not spec.path.exists():
        raise ConfigurationError(f"dataset file does not exist: {spec.path}")
    table = pd.read_parquet(spec.path)
    required = {"date", "ticker", spec.value_column}
    missing = sorted(required.difference(table.columns))
    if missing:
        raise ConfigurationError(f"dataset {name} is missing columns: {missing}")
    selected = table.loc[:, ["date", "ticker", spec.value_column]].copy()
    selected["date"] = pd.to_datetime(selected["date"])
    if selected.duplicated(["date", "ticker"]).any():
        raise ConfigurationError(f"dataset {name} has duplicate date/ticker rows")
    matrix = selected.pivot(index="date", columns="ticker", values=spec.value_column)
    matrix.index = pd.DatetimeIndex(matrix.index, name="date")
    matrix.columns = pd.Index(matrix.columns.astype(str), name="ticker")
    matrix = matrix.sort_index().sort_index(axis=1)
    if matrix.empty:
        raise ConfigurationError(f"dataset {name} must not be empty")
    return matrix
