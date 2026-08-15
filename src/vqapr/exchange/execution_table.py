"""Exact-time execution input and the authoritative executable-session source."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Failure, FailureFamily, VqaprError

_STAGE = "execution_table.sessions"


def _field(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty field name")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionTableSpec:
    """Physical execution-table binding; this is not an observation registration."""

    source: SourceSpec
    trade_at_field: str
    instrument_field: str
    is_tradable_field: str
    price_fields: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceSpec):
            raise TypeError("source must be a SourceSpec")
        _field(self.trade_at_field, name="trade_at_field")
        _field(self.instrument_field, name="instrument_field")
        _field(self.is_tradable_field, name="is_tradable_field")
        if not isinstance(self.price_fields, Mapping) or not self.price_fields:
            raise ValueError("price_fields must declare at least one execution price")
        for semantic, physical in self.price_fields.items():
            _field(semantic, name="price_fields key")
            _field(physical, name=f"price_fields[{semantic!r}]")
        object.__setattr__(self, "price_fields", MappingProxyType(dict(self.price_fields)))


def _schema_failures(spec: ExecutionTableSpec) -> tuple[Failure, ...]:
    columns = scan.describe(spec.source)
    expected = {
        spec.trade_at_field: scan.ColumnType.TIMESTAMP_TZ,
        spec.instrument_field: scan.ColumnType.VARCHAR,
        spec.is_tradable_field: scan.ColumnType.BOOLEAN,
    }
    failures: list[Failure] = []
    for field, wanted in expected.items():
        observed = columns.get(field)
        if observed is not wanted:
            failures.append(
                Failure.bounded(
                    code=f"{_STAGE}.field_type",
                    requirement=f"execution field {field!r} must be {wanted}",
                    observed="missing" if observed is None else str(observed),
                )
            )
    numeric = {scan.ColumnType.INTEGER, scan.ColumnType.DOUBLE}
    for semantic, field in spec.price_fields.items():
        observed = columns.get(field)
        if observed not in numeric:
            failures.append(
                Failure.bounded(
                    code=f"{_STAGE}.price_type",
                    requirement=f"execution price {semantic!r} field {field!r} must be numeric",
                    observed="missing" if observed is None else str(observed),
                )
            )
    return tuple(failures)


def execution_session_times(spec: ExecutionTableSpec) -> tuple[datetime, ...]:
    """Return sorted distinct execution instants without exposing rows to a Model."""

    if not isinstance(spec, ExecutionTableSpec):
        raise TypeError("spec must be an ExecutionTableSpec")
    failures = _schema_failures(spec)
    if failures:
        raise VqaprError(
            stage=_STAGE,
            family=FailureFamily.EXCHANGE,
            failures=failures,
            mutation=False,
            retry_precondition="fix the execution table binding or parquet, then retry",
        )

    values = scan.distinct_values(spec.source, spec.trade_at_field)
    if any(value is None for value in values):
        raise VqaprError(
            stage=_STAGE,
            family=FailureFamily.EXCHANGE,
            failures=(
                Failure.bounded(
                    code=f"{_STAGE}.trade_at_null",
                    requirement="trade_at must be non-null for every execution row",
                ),
            ),
            mutation=False,
        )
    if not values:
        raise VqaprError(
            stage=_STAGE,
            family=FailureFamily.EXCHANGE,
            failures=(
                Failure.bounded(
                    code=f"{_STAGE}.empty",
                    requirement="execution table must contain at least one session",
                ),
            ),
            mutation=False,
        )
    return tuple(value.astimezone(UTC) for value in values)
