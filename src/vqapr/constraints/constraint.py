"""The explicit extension contract for immutable economic Constraints."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.findings import ConstraintFinding
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.portfolio.intents import EconomicPortfolioIntent
from vqapr.valuation.marks import MarkBatch


def _bound(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class ConstraintBounds:
    """Frozen instrument-level bounds projected from one constraint declaration."""

    lower: Mapping[str, Decimal]
    upper: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.lower, Mapping) or not isinstance(self.upper, Mapping):
            raise TypeError("constraint bounds must be mappings")
        lower = dict(self.lower)
        upper = dict(self.upper)
        if set(lower) != set(upper):
            raise ValueError("constraint lower and upper bounds must cover the same instruments")
        for instrument in lower:
            if not isinstance(instrument, str) or not instrument:
                raise ValueError("constraint bound instruments must be non-empty strings")
            _bound(lower[instrument], name=f"lower[{instrument!r}]")
            _bound(upper[instrument], name=f"upper[{instrument!r}]")
            if lower[instrument] > upper[instrument]:
                raise ValueError("constraint lower bounds must not exceed upper bounds")
        object.__setattr__(self, "lower", MappingProxyType(lower))
        object.__setattr__(self, "upper", MappingProxyType(upper))

    def detached(self) -> ConstraintBounds:
        """Return a fresh immutable value with no caller-owned mapping aliases."""
        return ConstraintBounds(self.lower, self.upper)


class Constraint(ABC):
    """One immutable economic predicate used for projection, intent, and monitoring.

    Implementations declare every PIT input, project bounds for the current
    window, validate the intended portfolio, and monitor the actual marked
    account.  They may not mutate any supplied value and every finding must use
    this instance's stable ``constraint_id``.
    """

    @property
    @abstractmethod
    def constraint_id(self) -> str:
        """Stable identity fixed by the loaded constraint instance."""

    @abstractmethod
    def requirements(self) -> tuple[DataRequirement, ...]:
        """Return all declared PIT requirements needed by this constraint."""

    @abstractmethod
    def project(self, window: ModelWindow, instruments: tuple[str, ...]) -> ConstraintBounds:
        """Project deterministic bounds for the current PIT window."""

    @abstractmethod
    def validate_intended(
        self, intent: EconomicPortfolioIntent, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        """Measure the frozen intended economic payload against this projection."""

    @abstractmethod
    def evaluate(
        self,
        window: ModelWindow,
        account: AccountSnapshot,
        marks: MarkBatch,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        """Measure one marked account against bounds projected at this monitoring cutoff."""
