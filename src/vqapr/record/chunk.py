"""One table's rows from one publication, held as columns: what a recorder stages and the record
writer seals.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from vqapr.domain.rows import Row, Scalar

__all__ = [
    "RecordChunk",
]


@dataclass(frozen=True, slots=True)
class RecordChunk:
    """One table's rows from one publication, held as columns.

    Rows are collected as rows -- an author appends one per target, a valuation one per held
    name -- and travel as columns, because the writer wants columns for Arrow and every reader
    in between only counts or forwards them. Until record `221` a chunk of 3,000 rows was 3,000
    dicts, copied and re-wrapped at each hand-off from the recorder to the disk; now it is one
    tuple per column, made once. `rows()` gives the row view back for the in-memory readers.

    Every column holds the same number of cells. The cells are not checked here: the recorder
    checked them as they were appended, and a chunk built from rows by `from_rows` is the
    package's own (the fill journal, the writer's row-shaped door).
    """

    table_id: str
    columns: Mapping[str, tuple[Scalar, ...]]

    def __post_init__(self) -> None:
        if not isinstance(self.table_id, str) or not self.table_id:
            raise ValueError("table_id must be a non-empty string")
        if not isinstance(self.columns, Mapping):
            raise TypeError("columns must be a mapping of column name to cells")
        detached = {str(name): tuple(cells) for name, cells in self.columns.items()}
        if len({len(cells) for cells in detached.values()}) > 1:
            raise ValueError(
                f"every column of a {self.table_id!r} chunk holds the same number of rows"
            )
        object.__setattr__(self, "columns", MappingProxyType(detached))

    @property
    def row_count(self) -> int:
        return len(next(iter(self.columns.values()), ()))

    def rows(self) -> Iterator[Row]:
        """The row view: one dict per row, in column order."""
        names = tuple(self.columns)
        for cells in zip(*(self.columns[name] for name in names), strict=True):
            yield dict(zip(names, cells, strict=True))

    @classmethod
    def from_rows(cls, table_id: str, rows: Sequence[Mapping[str, object]]) -> RecordChunk:
        """A chunk from row-shaped input; a column a row lacks is null there."""
        materialized = tuple(rows)
        names = sorted({str(name) for row in materialized for name in row})
        return cls(
            table_id,
            {name: tuple(row.get(name) for row in materialized) for name in names},  # type: ignore[misc]
        )
