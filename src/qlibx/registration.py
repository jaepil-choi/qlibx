"""Generic YAML-driven source-to-canonical Parquet registration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from qlibx.config import read_yaml, require_mapping, require_string, require_strings
from qlibx.errors import QlibxError
from qlibx.project import Project
from qlibx.serialization import digest_file as _digest


@dataclass(frozen=True, slots=True)
class AvailabilitySpec:
    source: str
    offset_days: int


@dataclass(frozen=True, slots=True)
class RegistrationSpec:
    dataset_id: str
    source: Path
    output: Path
    available_at: AvailabilitySpec
    ticker: str
    information: dict[str, str]
    primary_key: tuple[str, ...]
    frequency: str
    timezone: str


@dataclass(frozen=True, slots=True)
class RegistrationPlan:
    dataset_id: str
    source: str
    output: str
    source_sha256: str
    source_rows: int
    source_columns: tuple[str, ...]
    canonical_columns: tuple[str, ...]
    availability: dict[str, Any]
    assumptions_required: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    dataset_id: str
    output: str
    provenance: str
    source_sha256: str
    output_sha256: str
    rows: int
    columns: tuple[str, ...]
    coverage_start: str | None
    coverage_end: str | None
    information_values_preserved: bool


def data_requirements(information_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "canonical_shape": "available_at_ticker_long_table",
        "required_axis": [
            {
                "field": "available_at",
                "meaning": "earliest datetime at which the row may be used",
                "mapping": "source column or user-approved calendar-day offset",
            },
            {
                "field": "ticker",
                "meaning": "instrument identifier",
                "mapping": "exact source column",
            },
        ],
        "information": [
            {
                "field": field,
                "meaning": (
                    "opaque user-defined information; qlibx does not interpret or transform it"
                ),
            }
            for field in information_fields
        ],
        "agent_action": (
            "Inspect the source read-only, show the exact availability/ticker/information mapping "
            "to the user, and author YAML only after ambiguity is resolved."
        ),
    }


def load_registration_specs(project: Project) -> dict[str, RegistrationSpec]:
    path = project.paths.config / "data" / "registrations.yaml"
    raw = require_mapping(read_yaml(path).get("registrations"), "registrations")
    return {name: _build_spec(project, name, value) for name, value in raw.items()}


def plan_registration(project: Project, dataset_id: str) -> RegistrationPlan:
    spec = _require_spec(project, dataset_id)
    if not spec.source.is_file():
        raise QlibxError(
            "QLIBX_REGISTRATION_SOURCE_MISSING",
            f"Missing source: {spec.source}",
            action="Correct registrations.yaml after read-only discovery.",
        )
    parquet = pq.ParquetFile(spec.source)
    available = set(parquet.schema_arrow.names)
    required = tuple(
        dict.fromkeys(
            (
                spec.available_at.source,
                spec.ticker,
                *spec.information.values(),
                *spec.primary_key,
            )
        )
    )
    missing = sorted(set(required) - available)
    if missing:
        raise QlibxError(
            "QLIBX_REGISTRATION_MAPPING_MISSING",
            f"Mapped source columns do not exist: {missing}",
            action="Discuss the exact column mapping with the user; qlibx will not guess.",
            context={"requirements": data_requirements(tuple(spec.information))},
        )
    return RegistrationPlan(
        dataset_id=dataset_id,
        source=str(spec.source),
        output=str(spec.output),
        source_sha256=_digest(spec.source),
        source_rows=parquet.metadata.num_rows,
        source_columns=required,
        canonical_columns=("available_at", "ticker", *spec.information),
        availability={
            "source": spec.available_at.source,
            "offset_days": spec.available_at.offset_days,
            "timezone": spec.timezone,
            "frequency": spec.frequency,
        },
        assumptions_required=(
            "The user confirms the availability offset and ticker mapping.",
            "Every information column is copied without semantic interpretation or value changes.",
        ),
    )


def register_dataset(project: Project, dataset_id: str) -> RegistrationResult:
    spec = _require_spec(project, dataset_id)
    plan = plan_registration(project, dataset_id)
    selected_sources = tuple(
        dict.fromkeys(
            (
                spec.available_at.source,
                spec.ticker,
                *spec.information.values(),
                *spec.primary_key,
            )
        )
    )
    source_table = pq.read_table(spec.source, columns=list(selected_sources))
    _validate_primary_key(source_table, spec.primary_key)
    event = source_table[spec.available_at.source]
    if pa.types.is_date(event.type):
        event = pc.cast(event, pa.timestamp("us"))
    if not pa.types.is_timestamp(event.type):
        raise QlibxError(
            "QLIBX_AVAILABILITY_SOURCE_NOT_DATETIME",
            f"Availability source must be date/timestamp, got {event.type}",
            action="Map a real temporal column or create one outside qlibx.",
        )
    available_at = pc.add(event, pa.scalar(timedelta(days=spec.available_at.offset_days)))
    arrays: list[pa.Array | pa.ChunkedArray] = [available_at, source_table[spec.ticker]]
    names = ["available_at", "ticker"]
    for logical, source in spec.information.items():
        arrays.append(source_table[source])
        names.append(logical)
    canonical = pa.table(arrays, names=names)
    spec.output.parent.mkdir(parents=True, exist_ok=True)
    staging = spec.output.with_name(f".{spec.output.name}.{uuid4().hex}.staging")
    try:
        pq.write_table(canonical, staging, compression="zstd")
        if _digest(spec.source) != plan.source_sha256:
            raise QlibxError(
                "QLIBX_SOURCE_CHANGED_DURING_REGISTRATION",
                "Source changed during registration",
                action="Inspect again and retry from a new plan.",
            )
        staging.replace(spec.output)
    finally:
        staging.unlink(missing_ok=True)
    coverage_start = pc.min(available_at).as_py() if canonical.num_rows else None
    coverage_end = pc.max(available_at).as_py() if canonical.num_rows else None
    provenance_dir = project.paths.state / "registrations"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    provenance = provenance_dir / f"{dataset_id}.json"
    payload = {
        "schema_version": 1,
        "spec": {
            **asdict(spec),
            "source": str(spec.source),
            "output": str(spec.output),
        },
        "source_sha256": plan.source_sha256,
        "output_sha256": _digest(spec.output),
        "rows": canonical.num_rows,
        "columns": names,
        "coverage_start": str(coverage_start) if coverage_start else None,
        "coverage_end": str(coverage_end) if coverage_end else None,
        "information_values_preserved": True,
    }
    provenance.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return RegistrationResult(
        dataset_id=dataset_id,
        output=str(spec.output),
        provenance=str(provenance),
        source_sha256=plan.source_sha256,
        output_sha256=payload["output_sha256"],
        rows=canonical.num_rows,
        columns=tuple(names),
        coverage_start=payload["coverage_start"],
        coverage_end=payload["coverage_end"],
        information_values_preserved=True,
    )


def _build_spec(project: Project, name: str, raw: Any) -> RegistrationSpec:
    value = require_mapping(raw, f"registrations.{name}")
    availability = require_mapping(value.get("available_at"), f"{name}.available_at")
    offset = availability.get("offset_days")
    if not isinstance(offset, int):
        raise QlibxError(
            "QLIBX_AVAILABILITY_OFFSET_REQUIRED",
            f"{name}.available_at.offset_days must be an integer",
            action="Ask the user for the explicit calendar-day availability rule.",
        )
    information = require_mapping(value.get("information"), f"{name}.information")
    if not information or not all(isinstance(item, str) for item in information.values()):
        raise QlibxError(
            "QLIBX_INFORMATION_MAPPING_REQUIRED",
            f"{name}.information must map output names to source columns",
            action="Select opaque information columns explicitly.",
        )
    if {"available_at", "ticker"} & set(information):
        raise QlibxError(
            "QLIBX_INFORMATION_AXIS_COLLISION",
            "Information names cannot replace available_at or ticker",
            action="Keep the canonical axis reserved.",
        )
    source = project.contained(require_string(value.get("source"), f"{name}.source"))
    output = project.contained(require_string(value.get("output"), f"{name}.output"))
    if not output.is_relative_to(project.paths.generated_data):
        raise QlibxError(
            "QLIBX_OUTPUT_OUTSIDE_GENERATED_DATA",
            f"Registration output is outside data/qlibx: {output}",
            action="Place processed Parquet below the configured generated_data root.",
        )
    return RegistrationSpec(
        dataset_id=name,
        source=source,
        output=output,
        available_at=AvailabilitySpec(
            require_string(availability.get("source"), f"{name}.available_at.source"),
            offset,
        ),
        ticker=require_string(value.get("ticker"), f"{name}.ticker"),
        information={str(key): str(item) for key, item in information.items()},
        primary_key=require_strings(value.get("primary_key"), f"{name}.primary_key"),
        frequency=require_string(value.get("frequency"), f"{name}.frequency"),
        timezone=require_string(value.get("timezone"), f"{name}.timezone"),
    )


def _require_spec(project: Project, dataset_id: str) -> RegistrationSpec:
    specs = load_registration_specs(project)
    try:
        return specs[dataset_id]
    except KeyError as error:
        raise QlibxError(
            "QLIBX_REGISTRATION_UNKNOWN",
            f"Unknown registration {dataset_id!r}; available: {sorted(specs)}",
            action="Choose a YAML-declared registration.",
        ) from error


def _validate_primary_key(table: pa.Table, primary_key: tuple[str, ...]) -> None:
    nulls = {name: table[name].null_count for name in primary_key if table[name].null_count}
    if nulls:
        raise QlibxError(
            "QLIBX_PRIMARY_KEY_NULL",
            f"Primary key contains nulls: {nulls}",
            action="Resolve source keys outside qlibx.",
        )
    unique = table.select(primary_key).group_by(list(primary_key)).aggregate([]).num_rows
    if unique != table.num_rows:
        raise QlibxError(
            "QLIBX_PRIMARY_KEY_DUPLICATE",
            f"Found {table.num_rows - unique} duplicate primary-key rows",
            action="Resolve duplicates explicitly outside qlibx.",
        )
