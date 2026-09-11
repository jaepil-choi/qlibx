"""What `vqapr show dataset` reads: a registered dataset's first rows, and how many there are.

Through the declared projection when the registration measured one, from the source file otherwise
-- or when the caller asks for the file's own rows. `items_are` says which was answered, so a reader
never has to infer it (`docs/issues/093`). The scan is the data layer's; which scan answers a
registered dataset is the workspace's, which holds the registration (record `277`). """

from __future__ import annotations

from dataclasses import dataclass

from vqapr.data import scan
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec


@dataclass(frozen=True, slots=True)
class DatasetPreview:
    """The first rows of a registered dataset and the two counts a reader pages against."""

    items_are: str
    """`projection` for the declared projection's rows, `source` for the file's own."""
    rows: list[dict[str, object]]
    rows_total: int
    """How many rows `rows` pages over."""
    source_rows_total: int
    """How many rows the source file holds, whichever was answered."""


def preview_dataset(
    source: SourceSpec, item: DatasetRegistration, *, limit: int, source_rows: bool
) -> DatasetPreview:
    """Read `item`'s first `limit` rows through its projection, or from `source` itself."""
    relation = (
        None
        if source_rows or item.aggregated is None
        else scan.projection_relation(
            source,
            instrument_field=item.instrument_field,
            available_at_field=item.available_at,
            fields=item.fields,
            aggregated=item.aggregated,
        )
    )
    rows = scan.head(source, limit=limit, relation=relation)
    return DatasetPreview(
        items_are="source" if relation is None else "projection",
        rows=rows,
        rows_total=scan.row_count(source, relation=relation),
        source_rows_total=scan.row_count(source),
    )
