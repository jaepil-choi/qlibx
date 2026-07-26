from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from qlib_extended.research.catalog import ParquetSourceSpec


class DuckDBParquetQueryEngine:
    """필요한 local Parquet source만 view로 등록해 query합니다."""

    def execute(
        self,
        query: str,
        sources: tuple[ParquetSourceSpec, ...] | list[ParquetSourceSpec],
    ) -> pd.DataFrame:
        for source in sources:
            if not source.path.exists():
                raise FileNotFoundError(
                    f"Missing parquet source: {source.name} ({source.path})"
                )
        with duckdb.connect(database=":memory:") as connection:
            for source in sources:
                _register_source(connection, source)
            return connection.execute(query).fetchdf()


def _register_source(
    connection: duckdb.DuckDBPyConnection,
    source: ParquetSourceSpec,
) -> None:
    path = _duckdb_parquet_path(source.path)
    connection.execute(
        f'create view "{source.name}" as select * from read_parquet({_sql_string(path)})'
    )


def _duckdb_parquet_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_dir():
        resolved = resolved / "**" / "*.parquet"
    return str(resolved).replace("\\", "/")


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
