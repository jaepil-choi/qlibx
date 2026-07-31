"""Read-only discovery for user-owned Parquet and DuckDB data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb
import pyarrow.parquet as pq

from qlibx.errors import QlibxError
from qlibx.project import Project

SupportedFormat = Literal["parquet", "duckdb"]


@dataclass(frozen=True, slots=True)
class DataCandidate:
    path: str
    format: SupportedFormat
    size_bytes: int
    mutates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ColumnInspection:
    name: str
    dtype: str
    nullable: bool | None


@dataclass(frozen=True, slots=True)
class TableInspection:
    name: str
    rows: int | None
    columns: tuple[ColumnInspection, ...]
    sample: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DataInspection:
    path: str
    format: SupportedFormat
    tables: tuple[TableInspection, ...]
    unresolved_requirements: tuple[str, ...]
    required_user_questions: tuple[str, ...]
    read_only: bool = True
    mutates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_data(
    project: Project,
    path: str | Path | None = None,
    *,
    recursive: bool = True,
    limit: int = 100,
) -> tuple[DataCandidate, ...]:
    """Find supported user-source files without opening or changing them."""
    if limit <= 0:
        raise QlibxError(
            "DATA_REGISTRATION",
            "Discovery limit must be positive",
            expected="Provide a positive bounded file limit.",
        )
    root = _source_path(project, project.paths.source_data if path is None else path)
    if root.is_file():
        files = (root,)
    elif root.is_dir():
        iterator = root.rglob("*") if recursive else root.glob("*")
        files = tuple(item for item in iterator if item.is_file())
    else:
        raise QlibxError(
            "DATA_REGISTRATION",
            f"Discovery path does not exist: {root}",
            expected="Choose an existing path below the configured source_data root.",
        )
    candidates: list[DataCandidate] = []
    for candidate in sorted(files):
        if candidate.is_relative_to(project.paths.generated_data):
            continue
        format_name = _format(candidate)
        if format_name is None:
            continue
        candidates.append(
            DataCandidate(
                path=candidate.relative_to(project.root).as_posix(),
                format=format_name,
                size_bytes=candidate.stat().st_size,
            )
        )
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def inspect_data(
    project: Project,
    path: str | Path,
    *,
    table: str | None = None,
    sample_rows: int = 5,
) -> DataInspection:
    """Inspect schema and a bounded sample without assigning economic semantics."""
    if sample_rows < 0 or sample_rows > 100:
        raise QlibxError(
            "DATA_REGISTRATION",
            "sample_rows must be between 0 and 100",
            expected="Use a bounded sample between 0 and 100 rows.",
        )
    source = _source_path(project, path)
    if not source.is_file():
        raise QlibxError(
            "DATA_REGISTRATION",
            f"Inspection source does not exist: {source}",
            expected="Choose a discovered source file.",
        )
    format_name = _format(source)
    if format_name is None:
        raise QlibxError(
            "DATA_REGISTRATION",
            f"Unsupported source format: {source.suffix}",
            expected="Use a Parquet or DuckDB source.",
        )
    tables = (
        (_inspect_parquet(source, sample_rows),)
        if format_name == "parquet"
        else _inspect_duckdb(source, table, sample_rows)
    )
    return DataInspection(
        path=source.relative_to(project.root).as_posix(),
        format=format_name,
        tables=tables,
        unresolved_requirements=(
            "available_at source and rule",
            "ticker source column",
            "opaque information columns and output names",
            "primary key",
            "frequency",
            "timezone",
        ),
        required_user_questions=(
            "Which exact column and rule determine the earliest available datetime?",
            "Which exact column is the instrument ticker?",
            "Which source columns should be copied as opaque information?",
            "What primary key, frequency, and timezone should be declared?",
        ),
    )


def _inspect_parquet(path: Path, sample_rows: int) -> TableInspection:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    sample: tuple[dict[str, Any], ...] = ()
    if sample_rows:
        batches = parquet.iter_batches(batch_size=sample_rows)
        first = next(batches, None)
        if first is not None:
            sample = tuple(first.slice(0, sample_rows).to_pylist())
    columns = tuple(
        ColumnInspection(field.name, str(field.type), field.nullable) for field in schema
    )
    return TableInspection(path.stem, parquet.metadata.num_rows, columns, sample)


def _inspect_duckdb(
    path: Path, selected_table: str | None, sample_rows: int
) -> tuple[TableInspection, ...]:
    with duckdb.connect(str(path), read_only=True) as connection:
        available = tuple(
            row[0]
            for row in connection.execute(
                """select table_name from information_schema.tables
                where table_schema = 'main' order by table_name"""
            ).fetchall()
        )
        if selected_table is not None and selected_table not in available:
            raise QlibxError(
                "DATA_REGISTRATION",
                f"DuckDB table not found: {selected_table!r}; available: {list(available)}",
                expected="Choose an explicitly listed table.",
            )
        names = (selected_table,) if selected_table else available
        result: list[TableInspection] = []
        for name in names:
            escaped = name.replace('"', '""')
            description = connection.execute(f'select * from "{escaped}" limit 0').description
            columns = tuple(
                ColumnInspection(str(item[0]), str(item[1]), None) for item in description
            )
            sample = (
                tuple(
                    connection.execute(f'select * from "{escaped}" limit ?', [sample_rows])
                    .fetchdf()
                    .to_dict(orient="records")
                )
                if sample_rows
                else ()
            )
            result.append(TableInspection(name, None, columns, sample))
    return tuple(result)


def _source_path(project: Project, path: str | Path) -> Path:
    selected = project.contained(path)
    if not selected.is_relative_to(project.paths.source_data):
        raise QlibxError(
            "DATA_REGISTRATION",
            f"Source path is outside configured source_data: {selected}",
            expected="Inspect only user-owned files below the source_data root.",
        )
    return selected


def _format(path: Path) -> SupportedFormat | None:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return "parquet"
    if suffix in {".duckdb", ".ddb"}:
        return "duckdb"
    return None
