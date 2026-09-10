"""A shipped compliance rule: no name larger than ``max(cap, benchmark_i)`` in the marked book.

The observing half of `vqapr.portfolio.bounds.single_name_cap`. The ceiling is the rule's own:
its `cap` is its own parameter and the benchmark arrives through its own `inputs()` declaration,
read as of the market-clock instant it observes at. Whether the strategy built inside the same
cap is not this rule's concern -- the two are compared in the report, and their disagreeing is
information rather than an error (design §7.2, owner decision).

The benchmark is validated through the allocation contract **before** any measurement is made:
a missing or invariant-violating benchmark fails the observation rather than assuming zero,
which would silently cap that name at `cap` on the strength of a gap in the data.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from vqapr.authoring import (
    Compliance,
    ComplianceCall,
    ComplianceFinding,
    DatasetInput,
    RowsLookback,
)
from vqapr.portfolio.allocation import (
    AllocationInvariants,
    AllocationSign,
    validate_allocation,
)

WEIGHT_FIELD = "benchmark_weight"
"""The field this rule reads on the benchmark dataset it is configured with."""

BENCHMARK_ALIAS = "benchmark"
"""This rule's one alias, as `inputs()` declares it and `call.read(alias, field)` reads it."""


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


class SingleNameCap(Compliance):
    """Report any name whose marked SIZE exceeds ``max(cap, benchmark_weight)``, long or short.

    Size only. It says nothing about sign: a short within the cap is not this rule's finding,
    and reporting it is `NoShort`'s job.
    """

    def __init__(
        self,
        *,
        cap: str,
        benchmark_dataset_id: str,
        tolerance: str,
        benchmark_weight_field: str = WEIGHT_FIELD,
        compliance_id: str = "single-name-cap",
    ) -> None:
        if not isinstance(compliance_id, str) or not compliance_id:
            raise ValueError("compliance_id must be a non-empty string")
        if not isinstance(benchmark_dataset_id, str) or not benchmark_dataset_id:
            raise ValueError("benchmark_dataset_id must be a non-empty string")
        if not isinstance(benchmark_weight_field, str) or not benchmark_weight_field:
            raise ValueError("benchmark_weight_field must be a non-empty string")
        self._compliance_id = compliance_id
        self._cap = _decimal_config(cap, name="cap")
        self._tolerance = _decimal_config(tolerance, name="tolerance")
        self._benchmark_dataset_id = benchmark_dataset_id
        self._weight_field = benchmark_weight_field

    @property
    def compliance_id(self) -> str:
        return self._compliance_id

    @property
    def cap(self) -> Decimal:
        return self._cap

    def inputs(self) -> Mapping[str, DatasetInput]:
        """One alias, declared the way every other extension point declares its reads."""
        return {
            BENCHMARK_ALIAS: DatasetInput(
                dataset_id=self._benchmark_dataset_id,
                fields=(self._weight_field,),
                lookback=RowsLookback(rows=1),
            )
        }

    def _benchmark(self, call: ComplianceCall) -> dict[str, Decimal]:
        # The newest benchmark weight per name inside the declared window: a panel read, and
        # `latest()` is exactly the cross-section a one-row lookback means.
        latest: dict[str, Decimal] = {}
        for instrument, weight in call.read(BENCHMARK_ALIAS, self._weight_field).latest().items():
            # A DOUBLE field arrives as `float`, as its dataset declared
            # (`docs/issues/archive/088`); the bound is stated in Decimal, so cross once here,
            # through `str`.
            if isinstance(weight, bool) or not isinstance(weight, int | float | Decimal):
                raise TypeError(
                    f"{self._compliance_id}: benchmark weight for {instrument!r} must be a "
                    f"number; got {type(weight).__name__}"
                )
            latest[instrument] = weight if isinstance(weight, Decimal) else Decimal(str(weight))

        validate_allocation(
            latest,
            AllocationInvariants.of(
                sign=AllocationSign.LONG_ONLY,
                tolerance=self._tolerance,
                required_coverage=(),
            ),
            label=f"{self._compliance_id} benchmark",
        )
        return {instrument: latest.get(instrument, Decimal(0)) for instrument in call.instruments}

    def ceilings(self, call: ComplianceCall) -> dict[str, Decimal]:
        """`max(cap, benchmark_i)` per instrument, as of the instant observed."""
        benchmark = self._benchmark(call)
        return {
            instrument: max(self._cap, benchmark[instrument]) for instrument in call.instruments
        }

    def _worst(
        self, weights: Mapping[str, Decimal], ceilings: Mapping[str, Decimal]
    ) -> tuple[Decimal, Decimal, tuple[str, ...]]:
        """The largest exposure and what bounded it, measured on SIZE (`abs`)."""
        measured = Decimal(0)
        bound = self._cap
        offenders: list[str] = []
        for instrument, weight in sorted(weights.items()):
            ceiling = ceilings.get(instrument, self._cap)
            size = abs(weight)
            if size > ceiling:
                offenders.append(instrument)
            if size > measured:
                measured, bound = size, ceiling
        return measured, bound, tuple(offenders)

    def observe(self, call: ComplianceCall) -> ComplianceFinding:
        """The realised book as weights, taken from the view rather than rebuilt from marks.

        `call.account.weights()` is `value / nav` per name; `nav` is `cash` plus the marked total.
        An account with no NAV has no weights. An empty book measures zero against the cap, which
        is what "nothing is held" means for a concentration rule.
        """
        ceilings = self.ceilings(call)
        weights = call.account.weights() if call.account.nav else {}
        measured, bound, offenders = self._worst(weights, ceilings)
        return ComplianceFinding(
            passed=not offenders,
            measured=measured,
            bound=bound,
            excess=max(measured - bound, Decimal(0)),
            details={"nav": call.account.nav if call.account.nav is not None else Decimal(0)},
            offenders=offenders,
        )
