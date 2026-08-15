"""Exact-time execution input and the authoritative executable-session source."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Diagnosis, Failure, FailureFamily, VqaprError, collector
from vqapr.domain.identifiers import ExecutionInputId, execution_input_id
from vqapr.exchange.conventions import FillConvention

_STAGE = "execution_table.sessions"
_REGISTER_SCHEMA = "execution_input.register.schema"
_REGISTER_KEY = "execution_input.register.key"
_REGISTER_PRICE = "execution_input.register.price"
_REGISTER_TIME = "execution_input.register.time"
_RETRY = "fix the prepared execution parquet or binding, then retry"


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


@dataclass(frozen=True, slots=True)
class ExecutionInputRegistration:
    """Versionable workspace declaration for one exact-time execution input."""

    execution_input_id: ExecutionInputId
    table: ExecutionTableSpec
    fill: FillConvention

    def __post_init__(self) -> None:
        if not isinstance(self.table, ExecutionTableSpec):
            raise TypeError("table must be an ExecutionTableSpec")
        if not isinstance(self.fill, FillConvention):
            raise TypeError("fill must be a FillConvention")
        if self.fill.trade_price not in self.table.price_fields:
            raise ValueError(
                f"trade_price {self.fill.trade_price!r} must be declared in table.price_fields"
            )

    @classmethod
    def of(
        cls,
        raw_execution_input_id: str,
        table: ExecutionTableSpec,
        fill: FillConvention,
    ) -> ExecutionInputRegistration:
        return cls(execution_input_id(raw_execution_input_id), table, fill)


def _schema_failures(spec: ExecutionTableSpec, *, stage: str = _STAGE) -> tuple[Failure, ...]:
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
                    code=f"{stage}.field_type",
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
                    code=f"{stage}.price_type",
                    requirement=f"execution price {semantic!r} field {field!r} must be numeric",
                    observed="missing" if observed is None else str(observed),
                )
            )
    return tuple(failures)


def _schema_diagnosis(registration: ExecutionInputRegistration) -> Diagnosis:
    return Diagnosis(
        stage=_REGISTER_SCHEMA,
        family=FailureFamily.EXCHANGE,
        failures=_schema_failures(registration.table, stage=_REGISTER_SCHEMA),
        retry_precondition=_RETRY,
    )


def _key_diagnosis(registration: ExecutionInputRegistration) -> Diagnosis:
    table = registration.table
    result = scan.key_check(table.source, (table.trade_at_field, table.instrument_field))
    found = collector(_REGISTER_KEY, FailureFamily.EXCHANGE)
    identity = f"({table.trade_at_field}, {table.instrument_field})"
    if result.null_groups:
        found.add(
            Failure.bounded(
                code=f"{_REGISTER_KEY}.null",
                requirement=f"execution identity {identity} must not contain nulls",
                observed=f"{result.null_groups} key group(s) with a null",
                examples=result.null_examples,
                example_total=result.null_groups,
            )
        )
    if result.duplicate_groups:
        found.add(
            Failure.bounded(
                code=f"{_REGISTER_KEY}.duplicate",
                requirement=f"execution identity {identity} must be unique",
                observed=f"{result.duplicate_groups} duplicated key group(s)",
                examples=result.duplicate_examples,
                example_total=result.duplicate_groups,
            )
        )
    return found.done(retry=_RETRY)


def _price_diagnosis(registration: ExecutionInputRegistration) -> Diagnosis:
    table = registration.table
    semantic = registration.fill.trade_price
    physical = table.price_fields[semantic]
    result = scan.positive_finite_when_true(
        table.source,
        value_field=physical,
        condition_field=table.is_tradable_field,
        identity_fields=(table.trade_at_field, table.instrument_field),
    )
    found = collector(_REGISTER_PRICE, FailureFamily.EXCHANGE)
    if result.invalid_rows:
        found.add(
            Failure.bounded(
                code=f"{_REGISTER_PRICE}.invalid",
                requirement=(
                    f"selected execution price {semantic!r} field {physical!r} must be finite and "
                    "positive whenever is_tradable is true"
                ),
                observed=f"{result.invalid_rows} invalid tradable row(s)",
                examples=result.examples,
                example_total=result.invalid_rows,
            )
        )
    return found.done(retry=_RETRY)


def _time_diagnosis(registration: ExecutionInputRegistration) -> Diagnosis:
    table = registration.table
    values = scan.distinct_values(table.source, table.trade_at_field)
    found = collector(_REGISTER_TIME, FailureFamily.EXCHANGE)
    if not values:
        found.add(
            Failure.bounded(
                code=f"{_REGISTER_TIME}.empty",
                requirement="execution table must contain at least one execution instant",
            )
        )
        return found.done(retry=_RETRY)

    zone = ZoneInfo(registration.fill.timezone)
    mismatches = tuple(
        value.isoformat()
        for value in values
        if value.astimezone(zone).time() != registration.fill.local_time
    )
    if mismatches:
        found.add(
            Failure.bounded(
                code=f"{_REGISTER_TIME}.local_time_mismatch",
                requirement=(
                    f"every trade_at must occur at {registration.fill.local_time.isoformat()} "
                    f"in {registration.fill.timezone}"
                ),
                observed=f"{len(mismatches)} distinct execution instant(s) at another local time",
                examples=mismatches,
                example_total=len(mismatches),
            )
        )
    return found.done(retry=_RETRY)


def validate_execution_input(registration: ExecutionInputRegistration) -> Diagnosis:
    """Validate one prepared execution parquet before workspace mutation."""
    if not isinstance(registration, ExecutionInputRegistration):
        raise TypeError("registration must be an ExecutionInputRegistration")
    for check in (_schema_diagnosis, _key_diagnosis, _price_diagnosis, _time_diagnosis):
        diagnosis = check(registration)
        if not diagnosis.ok:
            return diagnosis
    return Diagnosis(stage=_REGISTER_TIME, family=FailureFamily.EXCHANGE)


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
