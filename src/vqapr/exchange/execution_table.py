"""Passive exact-time execution input for target selection and venue snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Diagnosis, Failure, FailureFamily, collector
from vqapr.domain.identifiers import ExecutionInputId, execution_input_id
from vqapr.exchange.conventions import FillConvention

_REGISTER_SCHEMA = "execution_input.register.schema"
_REGISTER_KEY = "execution_input.register.key"
_REGISTER_PRICE = "execution_input.register.price"
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


def _schema_failures(
    spec: ExecutionTableSpec,
    *,
    stage: str = _REGISTER_SCHEMA,
) -> tuple[Failure, ...]:
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


def validate_execution_input(registration: ExecutionInputRegistration) -> Diagnosis:
    """Validate one prepared execution parquet before workspace mutation."""
    if not isinstance(registration, ExecutionInputRegistration):
        raise TypeError("registration must be an ExecutionInputRegistration")
    for check in (_schema_diagnosis, _key_diagnosis, _price_diagnosis):
        diagnosis = check(registration)
        if not diagnosis.ok:
            return diagnosis
    return Diagnosis(stage=_REGISTER_PRICE, family=FailureFamily.EXCHANGE)


@dataclass(frozen=True, slots=True)
class ExactExecutionRow:
    """One requested instrument at an exact selected instant."""

    trade_at: datetime
    instrument: str
    is_tradable: bool
    price: Decimal | None


@dataclass(frozen=True, slots=True)
class ExactExecutionSnapshot:
    """Exact rows plus explicit absence partitions for execution and later NAV checks."""

    target_at: datetime
    rows: tuple[ExactExecutionRow, ...]
    duplicate_instruments: tuple[str, ...]
    missing_target_instruments: tuple[str, ...]
    missing_held_instruments: tuple[str, ...]


def exact_execution_snapshot(
    spec: ExecutionTableSpec,
    *,
    target_at: datetime,
    target_instruments: Sequence[str],
    held_instruments: Sequence[str],
    trade_price: str,
) -> ExactExecutionSnapshot:
    """Fetch the exact price field for the target/held union without any fallback."""

    if not isinstance(spec, ExecutionTableSpec):
        raise TypeError("spec must be an ExecutionTableSpec")
    if target_at.tzinfo is None:
        raise ValueError("target_at must be timezone-aware")
    if trade_price not in spec.price_fields:
        raise ValueError(f"unknown execution price {trade_price!r}")
    target = tuple(dict.fromkeys(target_instruments))
    held = tuple(dict.fromkeys(held_instruments))
    if any(not isinstance(instrument, str) or not instrument for instrument in (*target, *held)):
        raise ValueError("instruments must be non-empty strings")
    requested = tuple(dict.fromkeys((*target, *held)))
    rows = scan.exact_snapshot_rows(
        spec.source,
        trade_at_field=spec.trade_at_field,
        instrument_field=spec.instrument_field,
        target_at=target_at,
        instruments=requested,
        fields={
            "is_tradable": spec.is_tradable_field,
            "price": spec.price_fields[trade_price],
        },
    )
    counts: dict[str, int] = {}
    for row in rows:
        instrument = str(row["instrument"])
        counts[instrument] = counts.get(instrument, 0) + 1
    present = set(counts)
    exact_rows = tuple(
        ExactExecutionRow(
            trade_at=row["trade_at"].astimezone(UTC),
            instrument=str(row["instrument"]),
            is_tradable=bool(row["is_tradable"]),
            price=None if row["price"] is None else Decimal(str(row["price"])),
        )
        for row in rows
    )
    return ExactExecutionSnapshot(
        target_at=target_at.astimezone(UTC),
        rows=exact_rows,
        duplicate_instruments=tuple(
            instrument for instrument in requested if counts.get(instrument, 0) > 1
        ),
        missing_target_instruments=tuple(
            instrument for instrument in target if instrument not in present
        ),
        missing_held_instruments=tuple(
            instrument for instrument in held if instrument not in present
        ),
    )
