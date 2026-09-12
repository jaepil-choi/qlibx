"""The execution table a run fills against, bound to the price the run chose, and its exact reads.

**The execution table is data** (owner ruling, 2026-09-08; record `185`): it is a registered
dataset like any other, carrying an execution role -- which of its fields says whether a name
was tradable -- and **the run picks the price**. The same table fills one run at the close and
another at the open; nothing is registered twice. What this module holds is the frozen binding
preflight makes of that choice (`ExecutionTable`: the dataset's physical columns, the fill
convention with the run's `trade_price`), the checks a bound table must pass, and the exact-at
read the venue is handed (`ExactExecutionSnapshot`). Until record `185` the table was its own
registration (`execution_inputs:`), with the price inside it, so changing the price meant a
second registration (architecture §17.7).
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pyarrow.compute as pc

from vqapr.data import scan
from vqapr.data.source import SourceSpec
from vqapr.domain.fill import ExactExecutionTarget, ExecutionHorizon, FillRule
from vqapr.domain.identifiers import DatasetId, dataset_id

_BARE_COLUMN = re.compile(r"[^\W\d]\w*", re.UNICODE)


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
class ExecutionTable:
    """The execution dataset a run fills against, bound to the run's fill convention.

    Built by preflight from the registered dataset (its execution role names the tradable flag;
    its numeric fields are the candidate prices) and the run's `execution:` block (which price,
    which session instant). Frozen into the run: two runs of one table at different prices are
    two different frozen inputs, which is what makes them comparable (architecture §17.7).
    """

    dataset_id: DatasetId
    table: ExecutionTableSpec
    fill: FillRule

    def spoken(self) -> list[str]:
        """The point-in-time meaning of this binding, in two sentences (`docs/issues/archive/027`).

        One for the table's clock, one for the fill rule and its price (design §3.5).
        """
        fill = self.fill
        return [
            f"execution dataset {self.dataset_id!r}: a row is a fact about the instant in "
            f"{self.table.trade_at_field!r}; a decision fills at a later row, never at its own",
            f"execution dataset {self.dataset_id!r}: a decision fills at {fill.describe()}, "
            f"at that row's {fill.trade_price!r}",
        ]

    def build_horizon(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        session: scan.ScanSession | None = None,
    ) -> ExecutionHorizon:
        """The run's candidate instants, read once from this table by this fill convention."""
        return ExecutionHorizon.of(
            scan.candidate_instants(
                self.table.source,
                trade_at_field=self.table.trade_at_field,
                decision_time=start_time,
                end_time=end_time,
                session=session,
            )
        )

    def select_target(
        self,
        *,
        decision_time: datetime,
        end_time: datetime,
        horizon: ExecutionHorizon | None = None,
    ) -> ExactExecutionTarget | None:
        """When a decision at `decision_time` fills, by this table's binding and this convention."""
        if horizon is None:
            horizon = ExecutionHorizon.of(
                scan.candidate_instants(
                    self.table.source,
                    trade_at_field=self.table.trade_at_field,
                    decision_time=decision_time,
                    end_time=end_time,
                )
            )
        return self.fill.select_target(
            dataset_id=self.dataset_id,
            decision_time=decision_time,
            end_time=end_time,
            horizon=horizon,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.table, ExecutionTableSpec):
            raise TypeError("table must be an ExecutionTableSpec")
        if not isinstance(self.fill, FillRule):
            raise TypeError("fill must be a FillRule")
        if self.fill.trade_price not in self.table.price_fields:
            raise ValueError(
                f"trade_price {self.fill.trade_price!r} must be one of the execution dataset's "
                f"numeric fields: {', '.join(sorted(self.table.price_fields)) or '(none)'}"
            )

    @classmethod
    def of(
        cls,
        raw_dataset_id: str,
        table: ExecutionTableSpec,
        fill: FillRule,
    ) -> ExecutionTable:
        return cls(dataset_id(raw_dataset_id), table, fill)


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
class ExecutionSnapshotSummary:
    """A snapshot's partitions and how many rows it held: what the fill's evidence keeps of it.

    The rows are the venue's data and are read again from the table; keeping one row per name
    per fill on the run's lineage held instants x names objects until the run ended (record
    `224`). The partitions are the facts the fill was judged on and stay.
    """

    target_at: datetime
    rows: int
    duplicate_instruments: tuple[str, ...]
    missing_target_instruments: tuple[str, ...]
    missing_held_instruments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExactExecutionSnapshot:
    """Exact rows plus explicit absence partitions for execution and later NAV checks."""

    target_at: datetime
    rows: tuple[ExactExecutionRow, ...]
    duplicate_instruments: tuple[str, ...]
    missing_target_instruments: tuple[str, ...]
    missing_held_instruments: tuple[str, ...]

    def summary(self) -> ExecutionSnapshotSummary:
        return ExecutionSnapshotSummary(
            target_at=self.target_at,
            rows=len(self.rows),
            duplicate_instruments=self.duplicate_instruments,
            missing_target_instruments=self.missing_target_instruments,
            missing_held_instruments=self.missing_held_instruments,
        )


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

    if target_at.tzinfo is None:
        raise ValueError("target_at must be timezone-aware")
    if trade_price not in spec.price_fields:
        raise ValueError(f"unknown execution price {trade_price!r}")
    if reference_price is not None and reference_price not in spec.price_fields:
        raise ValueError(f"unknown reference price {reference_price!r}")
    target = tuple(dict.fromkeys(target_instruments))
    held = tuple(dict.fromkeys(held_instruments))
    if not all((*target, *held)):
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
    return _partitioned(
        tuple(_exact_row(row) for row in rows), target_at=target_at, target=target, held=held
    )


def _partitioned(
    rows: tuple[ExactExecutionRow, ...],
    *,
    target_at: datetime,
    target: tuple[str, ...],
    held: tuple[str, ...],
) -> ExactExecutionSnapshot:
    """The snapshot's partitions from the rows one instant yielded, whichever read made them."""
    requested = tuple(dict.fromkeys((*target, *held)))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.instrument] = counts.get(row.instrument, 0) + 1
    present = set(counts)
    return ExactExecutionSnapshot(
        target_at=target_at.astimezone(UTC),
        rows=rows,
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


_WINDOW_ROWS = 200_000
"""How many rows one window read aims for: instants per query = this over the instrument count,
so a 3,000-name minute table reads about a sixth of a day per query and a 300-name one a
day and a half. Bounded by rows rather than instants because the rows are what sit in memory."""


class ExecutionSnapshots:
    """The execution table read ahead in windows of the market clock, served one instant at a time.

    `exact_execution_snapshot` reads one instant with one query, and on a minute table that is
    390 queries a day, each carrying an `IN` list of every name -- 17 s of a 3,000-name day
    (`experiments/exp_221_the_market_clock_cost/`). The market clock is a static merge, so its
    instants are known before the first one is walked (record `206`); this reads them ahead,
    `window` instants per query for the run's whole instrument set, and slices one instant's rows
    out on request. What comes back is what `exact_execution_snapshot` returns for that instant
    -- the same rows, the same absence partitions -- and an instant off the clock, or a name the
    window was not read for, falls through to it, so a caller cannot tell the two apart except by
    the query count.
    """

    __slots__ = (
        "_fields",
        "_instants",
        "_instrument_set",
        "_instruments",
        "_offsets",
        "_reference_price",
        "_session",
        "_spec",
        "_table",
        "_trade_price",
        "_window",
    )

    def __init__(
        self,
        spec: ExecutionTableSpec,
        *,
        instants: Sequence[datetime],
        instruments: Sequence[str],
        trade_price: str,
        reference_price: str | None = None,
        session: scan.ScanSession | None = None,
        window: int | None = None,
    ) -> None:
        if trade_price not in spec.price_fields:
            raise ValueError(f"unknown execution price {trade_price!r}")
        if reference_price is not None and reference_price not in spec.price_fields:
            raise ValueError(f"unknown reference price {reference_price!r}")
        ordered = tuple(dict.fromkeys(instruments))
        if not all(ordered):
            raise ValueError("instruments must be non-empty strings")
        for instant in instants:
            if instant.tzinfo is None:
                raise ValueError("market-clock instants must be timezone-aware")
        self._spec = spec
        self._session = session
        self._instants = tuple(sorted({instant.astimezone(UTC) for instant in instants}))
        self._instruments = ordered
        self._instrument_set = frozenset(ordered)
        self._trade_price = trade_price
        self._reference_price = reference_price
        self._fields = {
            "is_tradable": spec.is_tradable_field,
            "price": spec.price_fields[trade_price],
            **(
                {"reference": spec.price_fields[reference_price]}
                if reference_price is not None
                else {}
            ),
        }
        self._window = (
            window if window is not None else max(1, _WINDOW_ROWS // max(1, len(ordered)))
        )
        self._table: Any = None
        self._offsets: dict[datetime, tuple[int, int]] = {}

    def at(
        self,
        target_at: datetime,
        *,
        target_instruments: Sequence[str],
        held_instruments: Sequence[str],
        with_reference: bool = True,
    ) -> ExactExecutionSnapshot:
        """The venue's rows at `target_at` for the target and held names, as the exact read gives.

        `with_reference` leaves the reference price off the rows, the way a read that never
        asked for one would (the held book's valuation asks for none).
        """
        if target_at.tzinfo is None:
            raise ValueError("target_at must be timezone-aware")
        target = tuple(dict.fromkeys(target_instruments))
        held = tuple(dict.fromkeys(held_instruments))
        if not all((*target, *held)):
            raise ValueError("instruments must be non-empty strings")
        requested = frozenset((*target, *held))
        instant = target_at.astimezone(UTC)
        if not requested <= self._instrument_set or not self._ensure(instant):
            return exact_execution_snapshot(
                self._spec,
                target_at=target_at,
                target_instruments=target,
                held_instruments=held,
                trade_price=self._trade_price,
                reference_price=self._reference_price if with_reference else None,
                session=self._session,
            )
        start, stop = self._offsets[instant]
        # Column by column, not row by row: the slice's `trade_at` is `instant` on every row by
        # construction, so it is never converted, and the typed row is built straight from the
        # three (or four) cells that vary. `to_pylist` on a row dict cost more than the query it
        # replaced (measured while writing record `222`).
        window = self._table.slice(start, stop - start)
        names = window.column("instrument").to_pylist()
        tradable = window.column("is_tradable").to_pylist()
        prices = window.column("price").to_pylist()
        references = (
            window.column("reference").to_pylist()
            if with_reference and "reference" in self._fields
            else [None] * len(names)
        )
        rows = tuple(
            ExactExecutionRow(
                trade_at=instant,
                instrument=str(name),
                is_tradable=bool(flag),
                price=None if price is None else Decimal(str(price)),
                reference=None if reference is None else Decimal(str(reference)),
            )
            for name, flag, price, reference in zip(
                names, tradable, prices, references, strict=True
            )
            if name in requested
        )
        return _partitioned(rows, target_at=target_at, target=target, held=held)

    def _ensure(self, instant: datetime) -> bool:
        """Have the window holding `instant` read; `False` when the instant is not on the clock."""
        if instant in self._offsets:
            return True
        index = bisect_left(self._instants, instant)
        if index >= len(self._instants) or self._instants[index] != instant:
            return False
        span = self._instants[index : index + self._window]
        self._table = scan.execution_window_table(
            self._spec.source,
            trade_at_field=self._spec.trade_at_field,
            instrument_field=self._spec.instrument_field,
            since=span[0],
            until=span[-1],
            instruments=self._instruments,
            fields=self._fields,
            session=self._session,
        )
        # Every instant of the span is now known, including those the table has no row at. The
        # rows are ordered by instant, so each distinct instant is one contiguous run and
        # `value_counts` -- which keeps first-appearance order -- gives the runs' lengths without
        # converting a single row's timestamp to Python.
        offsets: dict[datetime, tuple[int, int]] = dict.fromkeys(span, (0, 0))
        counted = pc.value_counts(self._table.column("trade_at"))  # type: ignore[attr-defined]
        start = 0
        for at, count in zip(
            counted.field("values").to_pylist(), counted.field("counts").to_pylist(), strict=True
        ):
            if not isinstance(at, datetime):
                raise TypeError(f"trade_at must be a datetime, got {type(at).__name__}")
            offsets[at.astimezone(UTC)] = (start, start + count)
            start += count
        self._offsets = offsets
        return True


def _exact_row(row: Mapping[str, object]) -> ExactExecutionRow:
    """One scanned row as the typed row a venue reads.

    The scan hands its columns back untyped. The trade-at column is `TIMESTAMPTZ`, so a value
    that is not a datetime is a table whose declared field is not one, refused by name.
    """
    trade_at = row["trade_at"]
    if not isinstance(trade_at, datetime):
        raise TypeError(f"trade_at must be a datetime, got {type(trade_at).__name__}")
    return ExactExecutionRow(
        trade_at=trade_at.astimezone(UTC),
        instrument=str(row["instrument"]),
        is_tradable=bool(row["is_tradable"]),
        price=None if row["price"] is None else Decimal(str(row["price"])),
        reference=(None if row.get("reference") is None else Decimal(str(row["reference"]))),
    )






