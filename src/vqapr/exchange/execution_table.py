"""Passive exact-time execution input for target selection and venue snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import (
    Diagnosis,
    Failure,
    FailureSource,
    Stage,
    Status,
    collector,
)
from vqapr.domain.identifiers import ExecutionInputId, execution_input_id
from vqapr.domain.values import side_of
from vqapr.exchange.conventions import ExactExecutionTarget, ExecutionHorizon, FillConvention
from vqapr.exchange.listings import ExchangeRulesView

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

    def spoken(self) -> list[str]:
        """The point-in-time meaning of this declaration, in two sentences (`docs/issues/027`).

        One for the table's clock, one for the fill -- the fill's four fields (selector, wall
        time, zone, price) mean nothing apart, so they are one sentence rather than four.
        """
        fill = self.fill
        return [
            f"execution input {self.execution_input_id!r}: a row is a fact about the instant in "
            f"{self.table.trade_at_field!r}; a decision fills at a later row, never at its own",
            f"execution input {self.execution_input_id!r}: a decision fills on the "
            f"{fill.selector.value.lower()} session at {fill.local_time.isoformat()} "
            f"{fill.timezone}, "
            f"at that row's {fill.trade_price!r}",
        ]

    def build_horizon(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        session: object | None = None,
    ) -> ExecutionHorizon:
        """The run's candidate instants, read once from this table by this fill convention."""
        return self.fill.build_horizon(
            self.table.source,
            trade_at_field=self.table.trade_at_field,
            start_time=start_time,
            end_time=end_time,
            session=session,
        )

    def select_target(
        self,
        *,
        decision_time: datetime,
        end_time: datetime,
        horizon: ExecutionHorizon | None = None,
    ) -> ExactExecutionTarget | None:
        """When a decision at `decision_time` fills, by this table's binding and this convention."""
        return self.fill.select_target(
            self.table.source,
            trade_at_field=self.table.trade_at_field,
            execution_input_id=self.execution_input_id,
            decision_time=decision_time,
            end_time=end_time,
            horizon=horizon,
        )

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
                    code="execution_input.field_type",
                    status=Status.INVALID,
                    requirement=f"execution field {field!r} must be {wanted}",
                    observed="missing" if observed is None else str(observed),
                    fix=(
                        f"add column {field!r} to the execution source with type {wanted}, or "
                        "point the field at a column that already has it"
                    ),
                    source=FailureSource(file=str(spec.source.path), key_path=field),
                )
            )
    # DECIMAL is admitted here and refused on a dataset (`docs/issues/088`): an execution price
    # never reaches a model, it is read once at the boundary and converted explicitly
    # (`Decimal(str(row["price"]))` below), so the money side keeps whichever exact type the
    # venue table carries.
    numeric = {scan.ColumnType.INTEGER, scan.ColumnType.DOUBLE, scan.ColumnType.DECIMAL}
    for semantic, field in spec.price_fields.items():
        observed = columns.get(field)
        if observed not in numeric:
            failures.append(
                Failure.bounded(
                    code="execution_input.price_type",
                    status=Status.INVALID,
                    requirement=f"execution price {semantic!r} field {field!r} must be numeric",
                    observed="missing" if observed is None else str(observed),
                    fix=(
                        f"add numeric column {field!r} to the execution source, or point price "
                        f"{semantic!r} at a column that already carries a numeric price"
                    ),
                    source=FailureSource(file=str(spec.source.path), key_path=field),
                )
            )
    return tuple(failures)


def _schema_diagnosis(registration: ExecutionInputRegistration) -> Diagnosis:
    return Diagnosis(
        stage=Stage.REGISTER,
        failures=_schema_failures(registration.table),
        retry_precondition=_RETRY,
    )


def _key_diagnosis(registration: ExecutionInputRegistration) -> Diagnosis:
    table = registration.table
    result = scan.key_check(table.source, (table.trade_at_field, table.instrument_field))
    found = collector(Stage.REGISTER)
    identity = f"({table.trade_at_field}, {table.instrument_field})"
    if result.null_groups:
        found.add(
            Failure.bounded(
                code="execution_input.key_null",
                status=Status.INVALID,
                requirement=f"execution identity {identity} must not contain nulls",
                observed=f"{result.null_groups} key group(s) with a null",
                examples=result.null_examples,
                example_total=result.null_groups,
                source=FailureSource(file=str(table.source.path), key_path=identity),
                fix=(
                    f"drop or repair the rows whose {identity} is null, or declare an identity "
                    "whose columns are always present"
                ),
            )
        )
    if result.duplicate_groups:
        found.add(
            Failure.bounded(
                code="execution_input.key_duplicate",
                status=Status.INVALID,
                requirement=f"execution identity {identity} must be unique",
                observed=f"{result.duplicate_groups} duplicated key group(s)",
                examples=result.duplicate_examples,
                example_total=result.duplicate_groups,
                source=FailureSource(file=str(table.source.path), key_path=identity),
                fix=(
                    f"deduplicate the source on {identity}, or widen the identity until it "
                    "identifies one row"
                ),
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
    found = collector(Stage.REGISTER)
    if result.invalid_rows:
        found.add(
            Failure.bounded(
                code="execution_input.price_invalid",
                status=Status.INVALID,
                requirement=(
                    f"selected execution price {semantic!r} field {physical!r} must be finite and "
                    "positive whenever is_tradable is true"
                ),
                observed=f"{result.invalid_rows} invalid tradable row(s)",
                examples=result.examples,
                example_total=result.invalid_rows,
                source=FailureSource(file=str(table.source.path), key_path=physical),
                fix=(
                    f"repair {physical!r} to be finite and positive on every row where "
                    f"{table.is_tradable_field!r} is true, or exclude those rows from the source"
                ),
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
    return Diagnosis(stage=Stage.REGISTER)


@dataclass(frozen=True, slots=True)
class ExactExecutionRow:
    """One requested instrument at an exact selected instant.

    ``reference`` is a second declared price the venue asked for, and is ``None`` when the venue
    asked for none. It exists because some venue regimes are computed rather than supplied: a KRX
    price limit is the previous close times a declared rate, so the venue needs that number but
    the user must not be asked to work out what it implies. The user registers a column; the venue
    owns the rule.
    """

    trade_at: datetime
    instrument: str
    is_tradable: bool
    price: Decimal | None
    reference: Decimal | None = None


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
    reference_price: str | None = None,
    session: scan.ScanSession | None = None,
) -> ExactExecutionSnapshot:
    """Fetch the exact price field for the target/held union without any fallback.

    ``reference_price`` names a second declared price the venue requires. It is read in the same
    exact query, so it is the same row at the same instant -- a reference read separately could
    come from a different session and silently move a venue's limit band.
    """

    if not isinstance(spec, ExecutionTableSpec):
        raise TypeError("spec must be an ExecutionTableSpec")
    if target_at.tzinfo is None:
        raise ValueError("target_at must be timezone-aware")
    if trade_price not in spec.price_fields:
        raise ValueError(f"unknown execution price {trade_price!r}")
    if reference_price is not None and reference_price not in spec.price_fields:
        raise ValueError(f"unknown reference price {reference_price!r}")
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
        session=session,
        fields={
            "is_tradable": spec.is_tradable_field,
            "price": spec.price_fields[trade_price],
            **(
                {"reference": spec.price_fields[reference_price]}
                if reference_price is not None
                else {}
            ),
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
            reference=(
                None
                if row.get("reference") is None
                else Decimal(str(row["reference"]))
            ),
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


def requested_rows(
    snapshot: ExactExecutionSnapshot, requests: Sequence[Any]
) -> dict[str, ExactExecutionRow]:
    """The snapshot rows a batch asked about, checked against the snapshot's own contract.

    Lifted here from both execution profiles, where it stood twice byte for byte under two names
    (`AcademicExchange._validate_snapshot` and `KrxExchange._rows`). Two copies of one contract
    check drift the first time only one is edited, and issue `002` named that as the thing most
    likely to go wrong between the profiles.

    A FUNCTION rather than a shared base class, deliberately. What this checks is a property of
    `ExactExecutionSnapshot` -- no duplicate requested instrument, a boolean tradability, a
    positive finite price when tradable -- and none of it is venue policy. The profiles genuinely
    differ on quantity, cost, shorting and account access, and a base class inviting those to be
    shared is what issue `002` warns against. `load_exchange` also refuses a subclass whose
    `execute` is not its profile's, so a shared `execute` would blur which semantics a subclass
    claims.
    """
    requested = {request.instrument_id for request in requests}
    if set(snapshot.duplicate_instruments) & requested:
        raise ValueError("execution snapshot has duplicate requested instruments")
    rows: dict[str, ExactExecutionRow] = {}
    for row in snapshot.rows:
        if row.instrument not in requested:
            continue
        if row.instrument in rows:
            raise ValueError("execution snapshot has duplicate requested instruments")
        if not isinstance(row.is_tradable, bool):
            raise ValueError(f"invalid tradability for {row.instrument!r}")
        if row.is_tradable and (
            not isinstance(row.price, Decimal) or not row.price.is_finite() or row.price <= 0
        ):
            raise ValueError(f"invalid tradable price for {row.instrument!r}")
        rows[row.instrument] = row
    return rows


def validate_requests(
    rules: ExchangeRulesView,
    requests: Sequence[Any],
    rows: Mapping[str, ExactExecutionRow],
    account: Any,
) -> None:
    """Refuse a batch whose requests the venue's own listings do not permit.

    The third and last piece lifted out of both profiles (after `requested_rows` and
    `accepted_requests`, issue `002`): the request loop that stood as
    `AcademicExchange._validate_rules` and `KrxExchange._validate`. Same six checks -- a finite
    quantity, a listing, a positive finite selected price on a tradable row, a side, the position
    change, the quantity -- with the last two in opposite order and under different words. The
    `permits_quantity` docstring records the bug that drift produced: one profile stopped checking
    the minimum and the other did not, because the check was spelled twice.

    Every question here is put to the LISTING (`TradeRule.permits_position`,
    `TradeRule.permits_quantity`); this only walks the batch and phrases the refusal. Position is
    checked before quantity, so an order that is both a short and off the unit is refused as the
    short: the access class is the venue's standing declaration about the instrument, the unit
    is a detail of this size.
    """
    for request in requests:
        quantity = request.delta_quantity
        if not isinstance(quantity, Decimal) or not quantity.is_finite():
            raise ValueError(f"invalid requested quantity for {request.instrument_id!r}")
        rule = rules.listing(request.instrument_id)
        row = rows.get(request.instrument_id)
        if (
            row is not None
            and row.is_tradable
            and (
                not isinstance(request.execution_price, Decimal)
                or not request.execution_price.is_finite()
                or request.execution_price <= 0
            )
        ):
            raise ValueError(f"invalid selected price for {request.instrument_id!r}")
        if side_of(quantity) is None:
            continue
        held = account.positions.get(request.instrument_id, Decimal("0"))
        if not rule.permits_position(held, quantity):
            if rule.tradable:
                # The listing's own declaration, not a rule bolted onto a profile: selling a held
                # position is always fine, and only a resulting short is refused.
                raise ValueError(
                    f"{rule.access.value} listing does not support short selling "
                    f"{request.instrument_id!r}"
                )
            raise ValueError(
                f"{rule.access.value} listing does not permit this position change for "
                f"{request.instrument_id!r}"
            )
        if not rule.permits_quantity(abs(quantity)):
            unit = "divisible" if rule.fractional_allowed else f"step {rule.quantity_step}"
            raise ValueError(
                f"quantity violates listing rule for {request.instrument_id!r}: {abs(quantity)} "
                f"(minimum {rule.minimum_quantity}, {unit})"
            )


def accepted_requests(orders: Any, account: Any, snapshot: Any) -> tuple[Any, ...]:
    """The batch's requests in stable identity order, after the checks every profile makes.

    The other half of the duplication issue `002` measured: eleven lines standing byte for byte in
    both profiles' `execute`. Types, the account-version match, and one request per instrument are
    preconditions on the CALL rather than decisions about a venue, so they belong beside the types
    they check.

    Returns the sorted requests instead of validating in place, because sorting is the last of the
    shared steps and every caller needs its result -- returning it is what stops the sort itself
    from being the twelfth duplicated line.
    """
    from vqapr.account.snapshot import AccountSnapshot
    from vqapr.orders.batches import OrderBatch

    if not isinstance(orders, OrderBatch):
        raise TypeError("orders must be an OrderBatch")
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    if not isinstance(snapshot, ExactExecutionSnapshot):
        raise TypeError("snapshot must be an ExactExecutionSnapshot")
    if orders.account_version != account.version:
        raise ValueError("OrderBatch account_version does not match AccountSnapshot version")
    requests = tuple(sorted(orders.requests, key=lambda request: request.instrument_id))
    if len({request.instrument_id for request in requests}) != len(requests):
        raise ValueError("an OrderBatch may contain each instrument only once")
    return requests
