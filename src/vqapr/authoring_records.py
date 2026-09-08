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

from vqapr.domain.shapes import Row, Rows, normalize_rows
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
    """Stage rows locally; only the Flow acceptance root may publish them."""

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
        self._rows: dict[str, list[Row]] = {spec.table_id: [] for spec in specs}

    def append(self, table_id: str, row: Mapping[str, object]) -> None:
        self.append_batch(table_id, (row,))

    def append_batch(self, table_id: str, rows: Sequence[Mapping[str, object]]) -> None:
        try:
            spec = self._specs[table_id]
        except KeyError as exc:
            # Names the repair and the declared set beside the breach (`docs/issues/019`): an
            # author who declared `ff3.formations` and wrote `ff3.formation` sees both spellings.
            declared = ", ".join(sorted(self._specs)) or "nothing"
            raise KeyError(
                f"undeclared recorder table {table_id!r}; a table is declared by returning a "
                f"TableSpec for it from StrategyModel.tables() -- declared here: {declared}"
            ) from exc
        normalized = normalize_rows(rows)
        declared = spec.field_set
        staged = self._rows[table_id]
        for row in normalized:
            # Key views compare and intersect as sets without allocating one per row. Both checks
            # keep their original order, so the failure a malformed row raises is unchanged.
            if row.keys() != declared:
                raise ValueError(f"row fields for {table_id} must exactly match declared fields")
            if not FLOW_ENVELOPE_FIELDS.isdisjoint(row.keys()):
                raise ValueError("Flow envelope fields are reserved")
            sequence = len(staged)
            staged.append(
                {
                    **row,
                    "run_id": self._run_id,
                    "producer_id": self._producer_id,
                    "stage": self._stage,
                    "event_time": self._event_time,
                    "sequence": sequence,
                }
            )

    def staged_rows(self) -> Mapping[str, Rows]:
        """Return detached rows for a candidate root; this never publishes them.

        Detached, not re-validated. Every row here was normalized by `append_batch` and has been
        owned by this recorder ever since, so a second `normalize_rows` pass would re-check values
        this class produced -- once per callback, over every row the callback appended.
        """
        return MappingProxyType(
            {table_id: tuple(dict(row) for row in rows) for table_id, rows in self._rows.items()}
        )

    def manifests(self) -> tuple[RecorderManifest, ...]:
        return tuple(
            RecorderManifest(spec.table_id, spec.fields, len(self._rows[spec.table_id]))
            for spec in self._specs.values()
        )
