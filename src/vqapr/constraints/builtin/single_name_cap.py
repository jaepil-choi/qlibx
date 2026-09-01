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
"""The field this constraint reads on the benchmark dataset it is configured with."""


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
    """Cap each instrument's SIZE at ``max(cap, benchmark_weight)``, long or short.

    Size only. It says nothing about sign: shorting within the cap is permitted here, and
    forbidding it is `NoShort`'s job. Constraints intersect -- lower bounds take the max, upper
    bounds the min -- so declaring both gives long-only-with-a-cap without either rule knowing
    about the other, which is what makes long-only an emergent property of the set rather than
    something two constraints each half-enforce.
    """

    def __init__(
        self,
        *,
        cap: str,
        benchmark_dataset_id: str,
        tolerance: str,
        benchmark_weight_field: str = WEIGHT_FIELD,
        constraint_id: str = "single-name-cap",
    ) -> None:
        if not isinstance(constraint_id, str) or not constraint_id:
            raise ValueError("constraint_id must be a non-empty string")
        if not isinstance(benchmark_dataset_id, str) or not benchmark_dataset_id:
            raise ValueError("benchmark_dataset_id must be a non-empty string")
        if not isinstance(benchmark_weight_field, str) or not benchmark_weight_field:
            raise ValueError("benchmark_weight_field must be a non-empty string")
        self._constraint_id = constraint_id
        self._cap = _decimal_config(cap, name="cap")
        self._tolerance = _decimal_config(tolerance, name="tolerance")
        self._benchmark_dataset_id = benchmark_dataset_id
        self._weight_field = benchmark_weight_field

    @property
    def constraint_id(self) -> str:
        return self._constraint_id

    @property
    def cap(self) -> Decimal:
        return self._cap

    def requirements(self) -> tuple[DataRequirement, ...]:
        return (
            DataRequirement.of(
                self._benchmark_dataset_id, self._weight_field, lookback=RowsLookback(1)
            ),
        )

    def _benchmark(self, window: ModelWindow, instruments: tuple[str, ...]) -> dict[str, Decimal]:
        batch = window.observations(self.requirements()[0])
        latest: dict[str, Decimal] = {}
        for row in batch.rows:
            weight = row[self._weight_field]
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
        """The symmetric box: no name may be more than its ceiling, long or short.

        The lower bound mirrors the upper rather than flooring at zero. Flooring made this cap
        forbid a short outright, which is `NoShort`'s job -- and `NoShort`'s own docstring claims
        to be *the* projection that removes the short leg, a claim a second constraint quietly
        removing it makes false. It also made a signed book with a cap inexpressible: every
        constraint set containing this one was long-only whether or not anyone asked.

        Mirrored against the CEILING, not against `cap`. The ceiling is `max(cap, benchmark)`
        because a benchmark heavier than the cap is allowed to be held at its benchmark weight;
        the same reasoning applied to the other side gives the same magnitude with the other sign.

        Intersecting with `NoShort` yields `(0, ceiling)` exactly, so a long-only set is unchanged
        by this -- verified against `merged_constraint_bounds`, which takes the max of lower bounds
        and the min of uppers.
        """
        benchmark = self._benchmark(window, instruments)
        ceilings = {
            instrument: max(self._cap, benchmark[instrument]) for instrument in instruments
        }
        return ConstraintBounds({name: -ceiling for name, ceiling in ceilings.items()}, ceilings)

    def _worst(
        self, weights: Mapping[str, Decimal], bounds: ConstraintBounds
    ) -> tuple[Decimal, Decimal, tuple[str, ...]]:
        """The largest exposure and what bounded it, measured on SIZE.

        `abs` here, in the one place both judgments come through, is what makes them agree. This
        took the signed weight from `validate_intended` and the absolute one from `evaluate`, so a
        proposed `-0.30` passed the gate that runs before execution and was reported as a violation
        by the check that runs after it -- while the projection above had forbidden it outright.
        One rule, one book, three answers.
        """
        measured = Decimal(0)
        bound = self._cap
        offenders: list[str] = []
        for instrument, weight in sorted(weights.items()):
            ceiling = bounds.upper.get(instrument, self._cap)
            size = abs(weight)
            if size > ceiling:
                offenders.append(instrument)
            if size > measured:
                measured, bound = size, ceiling
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
