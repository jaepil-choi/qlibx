"""YAML catalog and DuckDB-backed logical data loader."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import duckdb
import pandas as pd

from qlibx.config import read_yaml, require_mapping, require_string, require_strings
from qlibx.errors import QlibxError
from qlibx.project import Project

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class SourceSpec:
    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    name: str
    kind: Literal["table", "matrix"]
    sources: tuple[str, ...]
    query: str
    index: str | None = None
    columns: str | None = None
    values: str | None = None
    dtype: str | None = None
    time_field: str = "available_at"
    availability_field: str = "available_at"
    ticker_field: str = "ticker"


@dataclass(frozen=True, slots=True)
class MatrixAxes:
    """The three axis columns a matrix dataset must declare."""

    index: str
    columns: str
    values: str


def require_matrix_axes(spec: DatasetSpec) -> MatrixAxes:
    """Narrow a matrix dataset's axis declaration into a total value.

    The declaration comes from project YAML, so a missing axis is a config error an agent
    has to act on -- not an internal invariant. A bare ``assert`` would state it but
    disappear under ``python -O``, leaving an opaque pandas failure in its place.
    """
    missing = sorted(name for name in ("index", "columns", "values") if getattr(spec, name) is None)
    if missing:
        raise QlibxError(
            "MISSING",
            f"Matrix dataset {spec.name!r} does not declare: {missing}",
            action="Declare index, columns, and values for every matrix dataset.",
            context={"dataset": spec.name, "missing": missing},
        )
    return MatrixAxes(str(spec.index), str(spec.columns), str(spec.values))


@dataclass(frozen=True, slots=True)
class DataCatalog:
    project: Project
    sources: dict[str, SourceSpec]
    datasets: dict[str, DatasetSpec]
    fingerprint: str
    files: tuple[Path, ...]

    @classmethod
    def from_project(cls, project: Project) -> DataCatalog:
        root = project.paths.config / "data"
        base_path = root / "base.yaml"
        base = read_yaml(base_path)
        if base.get("schema_version") != 1:
            raise QlibxError(
                "UNSUPPORTED",
                "data/base.yaml schema_version must be 1",
                action="Use schema version 1.",
            )
        catalog = require_mapping(base.get("catalog"), "catalog")
        source_path = _fragment(root, require_string(catalog.get("source_file"), "source_file"))
        dataset_paths = tuple(
            _fragment(root, value)
            for value in require_strings(catalog.get("dataset_files"), "dataset_files")
        )
        roots = {
            name: project.contained(require_string(value, f"paths.{name}"))
            for name, value in require_mapping(base.get("paths"), "paths").items()
        }
        raw_sources = require_mapping(
            read_yaml(source_path).get("parquet_sources"), "parquet_sources"
        )
        sources = {name: _source(name, raw, roots, project) for name, raw in raw_sources.items()}
        declarations: dict[str, Any] = {}
        for path in dataset_paths:
            fragment = require_mapping(read_yaml(path).get("datasets"), f"{path}.datasets")
            duplicate = sorted(set(declarations) & set(fragment))
            if duplicate:
                raise QlibxError(
                    "INVALID",
                    f"Duplicate logical datasets: {duplicate}",
                    action="Declare each dataset in one YAML fragment.",
                )
            declarations.update(fragment)
        datasets = {name: _dataset(name, raw, sources) for name, raw in declarations.items()}
        files = (base_path, source_path, *dataset_paths)
        return cls(project, sources, datasets, _fingerprint(root, files), files)

    def describe(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "sources": {name: str(spec.path) for name, spec in self.sources.items()},
            "datasets": {name: asdict(spec) for name, spec in self.datasets.items()},
            "files": [str(path) for path in self.files],
        }


@dataclass(frozen=True, slots=True)
class ConfigDrivenDataLoader:
    catalog: DataCatalog

    @classmethod
    def from_project(cls, project: Project) -> ConfigDrivenDataLoader:
        return cls(DataCatalog.from_project(project))

    def load_table(
        self,
        name: str,
        *,
        as_of: str | date | datetime | pd.Timestamp,
        start: str | date | datetime | pd.Timestamp | None = None,
        end: str | date | datetime | pd.Timestamp | None = None,
        tickers: tuple[str, ...] | list[str] | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Load rows already available at ``as_of``.

        ``as_of`` is required because forgetting it is the one mistake in this package
        that produces a better-looking result instead of a failure. Code that genuinely
        needs unfiltered rows calls :meth:`load_full_history` and says why.
        """
        return self._load(name, as_of=as_of, start=start, end=end, tickers=tickers, limit=limit)

    def load_full_history(
        self,
        name: str,
        *,
        reason: str,
        start: str | date | datetime | pd.Timestamp | None = None,
        end: str | date | datetime | pd.Timestamp | None = None,
        tickers: tuple[str, ...] | list[str] | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Load rows without an availability cutoff, for a stated non-decision purpose.

        Registration, schema inventory and operator preview legitimately need every row.
        ``reason`` keeps that choice visible at the call site rather than hiding it in an
        omitted argument.
        """
        if not reason.strip():
            raise QlibxError(
                "MISSING",
                "load_full_history requires a non-empty reason",
                action="State why this read may ignore point-in-time availability.",
                context={"dataset": name},
            )
        return self._load(name, as_of=None, start=start, end=end, tickers=tickers, limit=limit)

    def _load(
        self,
        name: str,
        *,
        as_of: str | date | datetime | pd.Timestamp | None,
        start: str | date | datetime | pd.Timestamp | None,
        end: str | date | datetime | pd.Timestamp | None,
        tickers: tuple[str, ...] | list[str] | None,
        limit: int | None,
    ) -> pd.DataFrame:
        spec = self._require(name)
        query, parameters = _bounded_query(spec, start, end, tickers, limit, as_of)
        table = _execute(
            query, parameters, tuple(self.catalog.sources[item] for item in spec.sources)
        )
        for column in table.columns:
            if column in {"available_at", "date"} or column.endswith(("_at", "_date")):
                table[column] = pd.to_datetime(table[column], errors="raise")
        return table

    def load_matrix(
        self,
        name: str,
        *,
        as_of: str | date | datetime | pd.Timestamp,
        start: str | date | datetime | pd.Timestamp | None = None,
        end: str | date | datetime | pd.Timestamp | None = None,
        tickers: tuple[str, ...] | list[str] | None = None,
        like: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Pivot a matrix dataset from rows already available at ``as_of``."""
        table = self.load_table(name, as_of=as_of, start=start, end=end, tickers=tickers)
        return self._pivot(name, table, like=like)

    def load_full_history_matrix(
        self,
        name: str,
        *,
        reason: str,
        start: str | date | datetime | pd.Timestamp | None = None,
        end: str | date | datetime | pd.Timestamp | None = None,
        tickers: tuple[str, ...] | list[str] | None = None,
        like: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Pivot a matrix dataset without an availability cutoff, for a stated purpose."""
        table = self.load_full_history(name, reason=reason, start=start, end=end, tickers=tickers)
        return self._pivot(name, table, like=like)

    def _pivot(self, name: str, table: pd.DataFrame, *, like: pd.DataFrame | None) -> pd.DataFrame:
        spec = self._require(name)
        if spec.kind != "matrix":
            raise QlibxError(
                "INVALID",
                f"Dataset is not a matrix: {name}",
                action="Use load_table or choose a matrix dataset.",
            )
        axes = require_matrix_axes(spec)
        missing = sorted({axes.index, axes.columns, axes.values} - set(table.columns))
        if missing:
            raise QlibxError(
                "MISSING",
                f"Matrix query is missing columns: {missing}",
                action="Correct the YAML output contract or SQL.",
            )
        duplicate = table.duplicated([axes.index, axes.columns], keep=False)
        if duplicate.any():
            raise QlibxError(
                "INVALID",
                f"Found {int(duplicate.sum())} duplicate matrix-key rows",
                action="Resolve duplicates explicitly in SQL.",
            )
        matrix = table.pivot(index=axes.index, columns=axes.columns, values=axes.values)
        matrix = matrix.sort_index().sort_index(axis=1)
        if spec.dtype:
            matrix = matrix.astype(spec.dtype)
        return (
            matrix.reindex(index=like.index, columns=like.columns) if like is not None else matrix
        )

    def _require(self, name: str) -> DatasetSpec:
        try:
            return self.catalog.datasets[name]
        except KeyError as error:
            raise QlibxError(
                "NOT_FOUND",
                f"Unknown dataset {name!r}; available: {sorted(self.catalog.datasets)}",
                action="Choose a YAML-declared dataset.",
            ) from error


def _fragment(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise QlibxError(
            "BOUNDARY",
            f"Config fragment escapes data config: {path}",
            action="Keep fragments below config/qlibx/data.",
        )
    return path


def _identifier(value: str, field: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise QlibxError(
            "INVALID",
            f"{field} is not a valid identifier: {value!r}",
            action="Use letters, digits, and underscores.",
        )
    return value


def _source(name: str, raw: Any, roots: dict[str, Path], project: Project) -> SourceSpec:
    _identifier(name, "source")
    value = require_mapping(raw, f"parquet_sources.{name}")
    root_name = value.get("root", "canonical")
    if root_name not in roots:
        raise QlibxError(
            "NOT_FOUND",
            f"Unknown source root: {root_name!r}",
            action=f"Choose one of {sorted(roots)}.",
        )
    path = project.contained(roots[root_name] / require_string(value.get("path"), f"{name}.path"))
    return SourceSpec(name, path)


def _dataset(name: str, raw: Any, sources: dict[str, SourceSpec]) -> DatasetSpec:
    _identifier(name, "dataset")
    value = require_mapping(raw, f"datasets.{name}")
    kind = require_string(value.get("kind"), f"{name}.kind")
    if kind not in {"table", "matrix"}:
        raise QlibxError(
            "INVALID",
            f"Unsupported dataset kind: {kind}",
            action="Use table or matrix.",
        )
    source_names = require_strings(value.get("sources"), f"{name}.sources")
    missing = sorted(set(source_names) - set(sources))
    if missing:
        raise QlibxError(
            "NOT_FOUND",
            f"Dataset references unknown sources: {missing}",
            action="Declare them in sources.yaml.",
        )
    availability_field = _identifier(
        str(value.get("availability_field", "available_at")),
        "availability_field",
    )
    common = dict(
        name=name,
        kind=kind,
        sources=source_names,
        query=require_string(value.get("query"), f"{name}.query"),
        time_field=_identifier(
            str(value.get("time_field", availability_field)),
            "time_field",
        ),
        availability_field=availability_field,
        ticker_field=_identifier(str(value.get("ticker_field", "ticker")), "ticker_field"),
    )
    if kind == "table":
        return DatasetSpec(**common)
    return DatasetSpec(
        **common,
        index=_identifier(require_string(value.get("index"), f"{name}.index"), "index"),
        columns=_identifier(require_string(value.get("columns"), f"{name}.columns"), "columns"),
        values=_identifier(require_string(value.get("values"), f"{name}.values"), "values"),
        dtype=str(value["dtype"]) if value.get("dtype") is not None else None,
    )


def _bounded_query(
    spec: DatasetSpec,
    start: Any,
    end: Any,
    tickers: tuple[str, ...] | list[str] | None,
    limit: int | None,
    as_of: Any,
) -> tuple[str, tuple[Any, ...]]:
    predicates: list[str] = []
    parameters: list[Any] = []
    if start is not None:
        predicates.append(f'"{spec.time_field}" >= ?')
        parameters.append(pd.Timestamp(start).to_pydatetime())
    if end is not None:
        predicates.append(f'"{spec.time_field}" <= ?')
        parameters.append(pd.Timestamp(end).to_pydatetime())
    if as_of is not None:
        predicates.append(f'"{spec.availability_field}" <= ?')
        parameters.append(pd.Timestamp(as_of).to_pydatetime())
    if tickers is not None:
        selected = tuple(map(str, tickers))
        if not selected:
            raise QlibxError(
                "MISSING",
                "Ticker filter is empty",
                action="Omit it or provide tickers.",
            )
        predicates.append(f'"{spec.ticker_field}" in ({", ".join("?" for _ in selected)})')
        parameters.extend(selected)
    if limit is not None and limit <= 0:
        raise QlibxError(
            "INVALID",
            "limit must be positive",
            action="Provide a positive limit.",
        )
    query = f"select * from ({spec.query.rstrip().rstrip(';')}) logical_dataset"
    if predicates:
        query += " where " + " and ".join(predicates)
    if limit:
        # An unordered LIMIT returns whatever the scan reached first, so the same preview
        # can disagree with itself after a re-registration rewrites the parquet files.
        query += f' order by "{spec.availability_field}", "{spec.ticker_field}"'
        query += f" limit {int(limit)}"
    return query, tuple(parameters)


def _execute(
    query: str, parameters: tuple[Any, ...], sources: tuple[SourceSpec, ...]
) -> pd.DataFrame:
    with duckdb.connect(":memory:") as connection:
        for source in sources:
            if not source.path.exists():
                raise QlibxError(
                    "NOT_FOUND",
                    f"Missing source {source.name}: {source.path}",
                    action="Register or restore the declared canonical Parquet.",
                )
            path = source.path / "**" / "*.parquet" if source.path.is_dir() else source.path
            escaped = str(path).replace("\\", "/").replace("'", "''")
            connection.execute(
                f"create view \"{source.name}\" as select * from read_parquet('{escaped}')"
            )
        try:
            return connection.execute(query, parameters).fetchdf()
        except duckdb.Error as error:
            raise QlibxError(
                "INVALID",
                f"Configured query failed: {error}",
                action="Correct the YAML SQL or output contract.",
            ) from error


def _fingerprint(root: Path, files: tuple[Path, ...]) -> str:
    digest = sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
