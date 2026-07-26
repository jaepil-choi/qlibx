from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Literal

from qlib_extended.research.config import (
    optional_string,
    read_yaml_mapping,
    require_mapping,
    require_string,
    require_string_list,
)


DatasetKind = Literal["table", "matrix"]
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ParquetSourceSpec:
    name: str
    path: Path


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    kind: DatasetKind
    sources: tuple[str, ...]
    query: str
    index: str | None = None
    columns: str | None = None
    values: str | None = None
    dtype: str | None = None


@dataclass(frozen=True)
class DataCatalog:
    """Physical source와 logical dataset을 분리한 research catalog입니다."""

    sources: dict[str, ParquetSourceSpec]
    datasets: dict[str, DatasetSpec]
    config_fingerprint: str
    config_files: tuple[Path, ...]

    @classmethod
    def from_directory(cls, config_dir: Path) -> DataCatalog:
        resolved_dir = config_dir.resolve()
        base_path = resolved_dir / "base.yaml"
        base = read_yaml_mapping(base_path)
        if base.get("schema_version") != 1:
            raise ValueError("configs/data/base.yaml schema_version must be 1.")

        project_root = resolved_dir.parent.parent
        raw_paths = require_mapping(base.get("paths"), "paths")
        roots = {
            name: _resolve_path(project_root, require_string(value, f"paths.{name}"))
            for name, value in raw_paths.items()
        }
        raw_catalog = require_mapping(base.get("catalog"), "catalog")
        source_file = resolved_dir / require_string(
            raw_catalog.get("source_file"), "catalog.source_file"
        )
        dataset_files = [
            resolved_dir / relative
            for relative in require_string_list(
                raw_catalog.get("dataset_files"), "catalog.dataset_files"
            )
        ]

        source_fragment = read_yaml_mapping(source_file)
        raw_sources = require_mapping(
            source_fragment.get("parquet_sources"), "parquet_sources"
        )
        sources = {
            name: _build_source(name, value, roots)
            for name, value in raw_sources.items()
        }

        raw_datasets: dict[str, Any] = {}
        for dataset_file in dataset_files:
            fragment = read_yaml_mapping(dataset_file)
            datasets = require_mapping(fragment.get("datasets"), f"{dataset_file}.datasets")
            duplicate = sorted(set(raw_datasets) & set(datasets))
            if duplicate:
                raise ValueError(
                    f"Duplicate logical dataset across fragments {dataset_file}: {duplicate}"
                )
            raw_datasets.update(datasets)
        datasets = {
            name: _build_dataset(name, value, sources)
            for name, value in raw_datasets.items()
        }
        config_files = (base_path, source_file, *dataset_files)
        return cls(
            sources=sources,
            datasets=datasets,
            config_fingerprint=_fingerprint(config_files),
            config_files=tuple(path.resolve() for path in config_files),
        )

    def require_source(self, name: str) -> ParquetSourceSpec:
        try:
            return self.sources[name]
        except KeyError as error:
            raise KeyError(
                f"Missing parquet source: {name}. Available sources: {sorted(self.sources)}"
            ) from error

    def require_dataset(self, name: str) -> DatasetSpec:
        try:
            return self.datasets[name]
        except KeyError as error:
            raise KeyError(
                f"Missing dataset: {name}. Available datasets: {sorted(self.datasets)}"
            ) from error


def _build_source(
    name: str,
    value: Any,
    roots: dict[str, Path],
) -> ParquetSourceSpec:
    _validate_identifier(name, "parquet source")
    spec = require_mapping(value, f"parquet_sources.{name}")
    root_name = optional_string(spec.get("root"), f"parquet_sources.{name}.root")
    root_name = root_name or "preprocessed"
    if root_name not in roots:
        raise ValueError(
            f"parquet_sources.{name}.root must be one of {sorted(roots)}: {root_name!r}"
        )
    raw_path = Path(require_string(spec.get("path"), f"parquet_sources.{name}.path"))
    path = raw_path if raw_path.is_absolute() else roots[root_name] / raw_path
    return ParquetSourceSpec(name=name, path=path.resolve())


def _build_dataset(
    name: str,
    value: Any,
    sources: dict[str, ParquetSourceSpec],
) -> DatasetSpec:
    _validate_identifier(name, "dataset")
    spec = require_mapping(value, f"datasets.{name}")
    kind = require_string(spec.get("kind"), f"datasets.{name}.kind")
    if kind not in {"table", "matrix"}:
        raise ValueError(f"datasets.{name}.kind must be one of ['matrix', 'table'].")
    source_names = require_string_list(spec.get("sources"), f"datasets.{name}.sources")
    missing = [source for source in source_names if source not in sources]
    if missing:
        raise KeyError(f"datasets.{name} references missing parquet sources: {missing}")
    query = require_string(spec.get("query"), f"datasets.{name}.query")
    if kind == "table":
        return DatasetSpec(name=name, kind="table", sources=tuple(source_names), query=query)
    return DatasetSpec(
        name=name,
        kind="matrix",
        sources=tuple(source_names),
        query=query,
        index=require_string(spec.get("index"), f"datasets.{name}.index"),
        columns=require_string(spec.get("columns"), f"datasets.{name}.columns"),
        values=require_string(spec.get("values"), f"datasets.{name}.values"),
        dtype=optional_string(spec.get("dtype"), f"datasets.{name}.dtype"),
    )


def _resolve_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _validate_identifier(name: str, label: str) -> None:
    if not isinstance(name, str) or not IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError(f"{label} name must be a valid SQL identifier: {name!r}")


def _fingerprint(paths: tuple[Path, ...]) -> str:
    digest = sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
