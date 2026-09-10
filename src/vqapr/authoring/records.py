"""What an author declares to record, and the write-only recorder that stages it.

The authoring contract's third piece, beside `authoring.py` (the four Components and the values
they exchange) and `authoring_lookback.py`. A `StrategyModel` returns `TableSpec`s from
`tables()` and writes rows into the `InvocationRecorder` the engine hands it; only the Flow's
acceptance root publishes what was staged. Both were `evidence/tables.py` and
`evidence/recorder.py` until record `188`: `evidence/` grouped three files by *who reads them*
rather than by what they are, and these two are one thing -- a declaration and the buffer that
enforces it -- so they are one module.

`vqapr.authoring` re-exports both, which is how an author imports them.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from vqapr.domain.shapes import RecordChunk, Rows, Scalar, normalize_column, normalize_scalar
from vqapr.domain.values import require_tz_aware

FLOW_ENVELOPE_FIELDS = frozenset({"run_id", "producer_id", "stage", "event_time", "sequence"})


@dataclass(frozen=True, slots=True)
class TableSpec:
    """A closed user-column declaration for one write-only recorder table."""

    table_id: str
    fields: tuple[str, ...]
    field_set: frozenset[str] = field(default=frozenset(), init=False, compare=False, repr=False)
    """`fields` as a set, so the recorder does not rebuild one per appended row.

    A callback appends one row per target, and the row-shape check compares two sets. Building the
    declared side once per spec instead of once per row removes an allocation from the innermost
    recorder loop.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.table_id, str) or not self.table_id.strip():
            raise ValueError("table_id must be a non-empty string")
        if not isinstance(self.fields, tuple):
            raise TypeError("fields must be a tuple of field names")
        if not self.fields:
            raise ValueError("fields must not be empty")
        if any(not isinstance(field, str) or not field.strip() for field in self.fields):
            raise ValueError("fields must contain non-empty strings")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("fields must be unique")
        # These are names a human reads back later. Control and format characters are invisible, so
        # they cannot help a reader and can only disguise one name as another -- including as a
        # package-owned one. A field called `run_id` carrying a zero-width character would slip past
        # the reserved-name check below and sit beside the real envelope column; the same disguise
        # one level down from the table id. Refusing both here closes it at the validation boundary
        # instead of leaving every consumer to normalise defensively.
        hidden = sorted(
            {
                ch
                for name in (self.table_id, *self.fields)
                for ch in name
                if unicodedata.category(ch) in {"Cc", "Cf"}
            }
        )
        if hidden:
            raise ValueError(
                "table_id and fields must not contain control or format characters: "
                f"{[hex(ord(ch)) for ch in hidden]}"
            )
        declared = frozenset(self.fields)
        reserved = sorted(declared & FLOW_ENVELOPE_FIELDS)
        if reserved:
            raise ValueError(f"Flow envelope fields are reserved: {reserved}")
        object.__setattr__(self, "field_set", declared)


@dataclass(frozen=True, slots=True)
class RecorderManifest:
    """The immutable publication description for one declared table."""

    table_id: str
    fields: tuple[str, ...]
    row_count: int


class InvocationRecorder:
    """Stage rows locally; only the Flow acceptance root may publish them.

    Rows are collected as rows and travel as columns (record `221`). An author appends one row
    per target; the framework's own tables -- one `vqapr.account` row per held name at every
    market-clock instant -- append whole columns. Either way what is staged is one list per
    declared field, and `staged_chunks` hands it over as `RecordChunk`s with the envelope
    columns beside it, which is the shape the run state forwards and the record writer types.

    The field names are checked once, by `TableSpec`; a row is held to *those* names by one set
    comparison, and only its cells are looked at. Until `221` every row's names were re-checked
    for whitespace as if the declaration had not happened, and on a 3,000-name book that check
    was a third of a run's wall clock.
    """

    def __init__(
        self,
        tables: Sequence[TableSpec],
        *,
        run_id: str,
        producer_id: str,
        stage: str,
        event_time: datetime,
    ) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(producer_id, str) or not producer_id:
            raise ValueError("producer_id must be a non-empty string")
        if not isinstance(stage, str) or not stage:
            raise ValueError("stage must be a non-empty string")
        require_tz_aware(event_time, name="event_time")
        specs = tuple(tables)
        if any(not isinstance(spec, TableSpec) for spec in specs):
            raise TypeError("tables must contain TableSpec values")
        if len({spec.table_id for spec in specs}) != len(specs):
            raise ValueError("table IDs must be unique")
        self._specs = {spec.table_id: spec for spec in specs}
        self._run_id = run_id
        self._producer_id = producer_id
        self._stage = stage
        self._event_time = event_time
        self._columns: dict[str, dict[str, list[Scalar]]] = {
            spec.table_id: {name: [] for name in spec.fields} for spec in specs
        }

    def _spec(self, table_id: str) -> TableSpec:
        try:
            return self._specs[table_id]
        except KeyError as exc:
            # Names the repair and the declared set beside the breach (`docs/issues/archive/019`):
            # an author who declared `ff3.formations` and wrote `ff3.formation` sees both spellings.
            declared = ", ".join(sorted(self._specs)) or "nothing"
            raise KeyError(
                f"undeclared recorder table {table_id!r}; a table is declared by returning a "
                f"TableSpec for it from StrategyModel.tables() -- declared here: {declared}"
            ) from exc

    def _require_declared_fields(self, table_id: str, names: object, *, what: str) -> None:
        if names != self._specs[table_id].field_set:
            if not FLOW_ENVELOPE_FIELDS.isdisjoint(names):  # type: ignore[arg-type]
                raise ValueError("Flow envelope fields are reserved")
            raise ValueError(f"{what} for {table_id} must exactly match declared fields")

    def append(self, table_id: str, row: Mapping[str, object]) -> None:
        self.append_batch(table_id, (row,))

    def append_batch(self, table_id: str, rows: Sequence[Mapping[str, object]]) -> None:
        """Stage rows: each held to the declared field set, each cell a portable scalar."""
        spec = self._spec(table_id)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise TypeError("rows must be a sequence of mappings")
        staged = self._columns[table_id]
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise TypeError(f"row {index} must be a mapping")
            self._require_declared_fields(table_id, row.keys(), what="row fields")
            for name in spec.fields:
                staged[name].append(normalize_scalar(row[name]))

    def append_columns(self, table_id: str, columns: Mapping[str, Sequence[object]]) -> None:
        """Stage rows given as columns: one sequence per declared field, all the same length.

        The framework's door for its own tables. A valuation of a 3,000-name book is 3,000 rows
        that differ in four cells and share the rest; built as columns they are seven tuples,
        and checked as columns (`normalize_column`) by type rather than by cell.
        """
        spec = self._spec(table_id)
        if not isinstance(columns, Mapping):
            raise TypeError("columns must be a mapping of field name to cells")
        self._require_declared_fields(table_id, columns.keys(), what="columns")
        normalized = {
            name: normalize_column(columns[name], name=f"{table_id}.{name}") for name in spec.fields
        }
        if len({len(cells) for cells in normalized.values()}) > 1:
            raise ValueError(f"columns for {table_id} must hold the same number of rows")
        staged = self._columns[table_id]
        for name, cells in normalized.items():
            staged[name].extend(cells)

    def _row_count(self, table_id: str) -> int:
        # A spec has at least one field, so the first column's length is the table's.
        return len(next(iter(self._columns[table_id].values())))

    def staged_chunks(self) -> tuple[RecordChunk, ...]:
        """What this recorder staged, one chunk per declared table, envelope columns included.

        Detached and never re-validated: every cell here passed `append_batch` or
        `append_columns`. `sequence` numbers the rows of one table within this recorder; the
        other four envelope columns are the recorder's own facts, the same on every row.
        """
        chunks: list[RecordChunk] = []
        for spec in self._specs.values():
            staged = self._columns[spec.table_id]
            count = self._row_count(spec.table_id)
            chunks.append(
                RecordChunk(
                    spec.table_id,
                    {
                        **{name: tuple(cells) for name, cells in staged.items()},
                        "run_id": (self._run_id,) * count,
                        "producer_id": (self._producer_id,) * count,
                        "stage": (self._stage,) * count,
                        "event_time": (self._event_time,) * count,
                        "sequence": tuple(range(count)),
                    },
                )
            )
        return tuple(chunks)

    def staged_rows(self) -> Mapping[str, Rows]:
        """The staged rows as rows, by table: the view a test reads. The run state takes chunks."""
        return MappingProxyType(
            {chunk.table_id: tuple(chunk.rows()) for chunk in self.staged_chunks()}
        )

    def manifests(self) -> tuple[RecorderManifest, ...]:
        return tuple(
            RecorderManifest(spec.table_id, spec.fields, self._row_count(spec.table_id))
            for spec in self._specs.values()
        )
