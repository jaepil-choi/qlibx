"""Invocation-local, write-only diagnostic recorder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from vqapr.domain.rows import Row, Rows, normalize_rows
from vqapr.domain.timestamps import require_tz_aware
from vqapr.evidence.tables import FLOW_ENVELOPE_FIELDS, TableSpec


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
            raise KeyError(f"undeclared recorder table: {table_id}") from exc
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
