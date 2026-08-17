"""A shipped constraint capping any one name relative to its benchmark weight.

The cap is ``max(cap, benchmark_i)``: a name may always be held at its index weight, and the cap
governs how far above the index a single position may go. That is what makes the constraint usable
for enhanced-index construction, where holding the benchmark itself must never be a violation.

The benchmark arrives as ordinary registered point-in-time data through this constraint's own
``DataRequirement``, and is validated here through the allocation contract **before** any bound is
produced. Failing inside ``project()`` is deliberate: an invariant-violating benchmark must not
reach ``optimize()`` at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.findings import ConstraintFinding
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    validate_allocation,
)
from vqapr.portfolio.intents import EconomicPortfolioIntent
from vqapr.valuation.marks import MarkBatch

WEIGHT_FIELD = "benchmark_weight"


def _decimal_config(value: object, *, name: str) -> Decimal:
    """Parse a configured decimal from its string form, refusing anything lossy.

    Component configuration is ordinary model memory, which has no ``Decimal``, so a configured
    ``0.1`` would arrive as a binary float and quietly poison every exactness claim downstream. A
    decimal string is therefore the only accepted spelling.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} must be a decimal string so it parses exactly; got {type(value).__name__}"
        )
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError(f"{name} is not a valid decimal string: {value!r}") from error
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative; got {value!r}")
    return parsed


class SingleNameCap(Constraint):
    """Cap each instrument at ``max(cap, benchmark_weight)``."""

    def __init__(
        self,
        *,
        cap: str,
        benchmark_dataset_id: str,
        tolerance: str,
        constraint_id: str = "single-name-cap",
    ) -> None:
        if not isinstance(constraint_id, str) or not constraint_id:
            raise ValueError("constraint_id must be a non-empty string")
        if not isinstance(benchmark_dataset_id, str) or not benchmark_dataset_id:
            raise ValueError("benchmark_dataset_id must be a non-empty string")
        self._constraint_id = constraint_id
        self._cap = _decimal_config(cap, name="cap")
        self._tolerance = _decimal_config(tolerance, name="tolerance")
        self._benchmark_dataset_id = benchmark_dataset_id

    @property
    def constraint_id(self) -> str:
        return self._constraint_id

    @property
    def cap(self) -> Decimal:
        return self._cap

    def requirements(self) -> tuple[DataRequirement, ...]:
        return (
            DataRequirement.of(
                self._constraint_id,
                self._benchmark_dataset_id,
                fields=(WEIGHT_FIELD,),
                lookback=RowsLookback(1),
            ),
        )

    def _benchmark(self, window: ModelWindow, instruments: tuple[str, ...]) -> dict[str, Decimal]:
        batch = window.observations(self.requirements()[0])
        latest: dict[str, Decimal] = {}
        for row in batch.rows:
            weight = row[WEIGHT_FIELD]
            if weight is None:
                continue
            if not isinstance(weight, Decimal):
                raise TypeError(
                    f"{self._constraint_id}: benchmark weight for "
                    f"{row['instrument']!r} must be a Decimal"
                )
            latest[str(row["instrument"])] = weight

        # Validate before producing any bound so an invariant-violating benchmark cannot reach
        # optimize(); the coverage-scoped contract accepts a proper subset of the index.
        validate_allocation(
            latest,
            AllocationInvariants.of(
                sign=AllocationSign.LONG_ONLY,
                tolerance=self._tolerance,
                required_coverage=(),
            ),
            label=f"{self._constraint_id} benchmark",
        )
        return {instrument: latest.get(instrument, Decimal(0)) for instrument in instruments}

    def project(self, window: ModelWindow, instruments: tuple[str, ...]) -> ConstraintBounds:
        benchmark = self._benchmark(window, instruments)
        return ConstraintBounds(
            {instrument: Decimal(0) for instrument in instruments},
            {instrument: max(self._cap, benchmark[instrument]) for instrument in instruments},
        )

    def _worst(
        self, weights: Mapping[str, Decimal], bounds: ConstraintBounds
    ) -> tuple[Decimal, Decimal, tuple[str, ...]]:
        measured = Decimal(0)
        bound = self._cap
        offenders: list[str] = []
        for instrument, weight in sorted(weights.items()):
            ceiling = bounds.upper.get(instrument, self._cap)
            if weight > ceiling:
                offenders.append(instrument)
            if weight > measured:
                measured, bound = weight, ceiling
        return measured, bound, tuple(offenders)

    def validate_intended(
        self, intent: EconomicPortfolioIntent, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        weights = {
            target.instrument_id: target.weight
            for target in intent.targets
            if target.weight is not None
        }
        measured, bound, offenders = self._worst(weights, bounds)
        return ConstraintFinding(
            self._constraint_id,
            not offenders,
            measured,
            bound,
            max(measured - bound, Decimal(0)),
            {"stage": "intended", "offenders": offenders, "cap": self._cap},
        )

    def evaluate(
        self,
        window: ModelWindow,
        account: AccountSnapshot,
        marks: MarkBatch,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        nav = marks.total_value + account.cash
        weights = (
            {mark.instrument_id: abs(mark.value) / nav for mark in marks.marks} if nav > 0 else {}
        )
        measured, bound, offenders = self._worst(weights, bounds)
        return ConstraintFinding(
            self._constraint_id,
            not offenders,
            measured,
            bound,
            max(measured - bound, Decimal(0)),
            {
                "stage": "monitoring",
                "account_version": account.version,
                "offenders": offenders,
                "nav": nav,
            },
        )
