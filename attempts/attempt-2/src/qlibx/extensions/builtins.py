"""Deterministic built-in transforms that document the local contract."""

from collections import defaultdict

from qlibx.extensions.contracts import (
    NeutralizationInput,
    NeutralizationResult,
    NeutralizedValue,
)


def group_demean(
    extension_id: str,
    request: NeutralizationInput,
) -> NeutralizationResult:
    """Subtract each declared group's arithmetic mean with stable ordering."""

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in request.rows:
        grouped[row.group].append(row.value)
    means = {group: sum(values) / len(values) for group, values in grouped.items()}
    return NeutralizationResult(
        extension_id=extension_id,
        values=tuple(
            NeutralizedValue(
                instrument=row.instrument,
                value=row.value - means[row.group],
            )
            for row in request.rows
        ),
    )
