from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from qlib_extended.research.catalog import DataCatalog
from qlib_extended.research.matrix import align_matrix_like, table_to_matrix
from qlib_extended.research.query import DuckDBParquetQueryEngine


@dataclass(frozen=True)
class ConfigDrivenDataLoader:
    """Logical dataset key만으로 research table/matrix를 로드합니다."""

    catalog: DataCatalog
    query_engine: DuckDBParquetQueryEngine

    @classmethod
    def from_directory(cls, config_dir: Path) -> ConfigDrivenDataLoader:
        return cls(
            catalog=DataCatalog.from_directory(config_dir),
            query_engine=DuckDBParquetQueryEngine(),
        )

    def load_table(self, name: str) -> pd.DataFrame:
        spec = self.catalog.require_dataset(name)
        sources = tuple(self.catalog.require_source(source) for source in spec.sources)
        table = self.query_engine.execute(spec.query, sources)
        return _normalize_dates(table)

    def load_matrix(
        self,
        name: str,
        *,
        like: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        spec = self.catalog.require_dataset(name)
        if spec.kind != "matrix":
            raise ValueError(f"Dataset is not a matrix: {name}")
        matrix = table_to_matrix(self.load_table(name), spec)
        return align_matrix_like(matrix, like) if like is not None else matrix

    def load_matrices(
        self,
        names: list[str] | tuple[str, ...],
        *,
        like: pd.DataFrame | None = None,
    ) -> dict[str, pd.DataFrame]:
        return {name: self.load_matrix(name, like=like) for name in names}


def _normalize_dates(table: pd.DataFrame) -> pd.DataFrame:
    result = table.copy()
    for column in result.columns:
        if column == "date" or column.endswith("_date") or column == "fiscal_period":
            result[column] = pd.to_datetime(result[column], errors="coerce")
    return result
