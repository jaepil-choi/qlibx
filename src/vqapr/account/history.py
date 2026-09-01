"""Bounded projections of what the Account already committed.

A Strategy that wants to act on its own realised path -- stop-loss, cooldown, drawdown -- needs
the account's recent history. Two rules make that affordable.

**Declared, like data.** A consumer states which fields it reads and how far back, exactly as it
declares a `DataRequirement`. There is no unbounded read: the lookback is required, so a
projection costs the declared window rather than the run so far. An open-ended read would be
O(history) per callback and therefore quadratic over a run, which is the cost shape the framework
works to keep out of the hot path.

**Retained only if declared.** The declaration is also what the run keeps in memory. A run whose
Strategy declares nothing retains one mark -- the current valuation -- and nothing else. Full
history belongs in the recorder, which streams it to parquet instead of holding it resident.

The fields are fixed because a fixed set is what makes "asked for something outside it" fail
before the run starts rather than during it. Every field here is a value `commit` and `mark`
already computed; history adds no arithmetic of its own, so it cannot disagree with the account
it describes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from vqapr.data.lookback import RowsLookback

ACCOUNT_FIELDS = ("nav", "cash")
"""One value per marked instant."""

INSTRUMENT_FIELDS = ("quantity", "price", "observed_at")
"""One value per held instrument per marked instant.

`price` and `observed_at` are separate fields, not a pair. A Strategy that only needs the price
should not pay to retain when it was observed, and one that must tell a halt from a flat market
declares both. A field is a column, which is what it means in `DataRequirement` too.
"""

_FIELDS = frozenset(ACCOUNT_FIELDS) | frozenset(INSTRUMENT_FIELDS)


@dataclass(frozen=True, slots=True)
class AccountRequirement:
    """One consumer's declared read of the Account's own record.

    There is no `dataset_id`: a run has exactly one account, so there is nothing to select.
    There is no `scope` either -- the field names carry it. `nav` exists once per instant and
    `quantity` exists per instrument, so a scope argument could only ever contradict the fields
    it accompanies.
    """

    consumer_id: str
    fields: tuple[str, ...]
    lookback: RowsLookback

    @staticmethod
    def of(consumer_id: str, *, fields: Sequence[str], lookback: RowsLookback):
        return AccountRequirement(consumer_id, tuple(fields), lookback)

    def __post_init__(self) -> None:
        if not isinstance(self.consumer_id, str) or not self.consumer_id.strip():
            raise ValueError("consumer_id must be a non-empty identifier")
        if not isinstance(self.fields, tuple) or not self.fields:
            raise ValueError("an account requirement must declare at least one field")
        unknown = tuple(sorted(set(self.fields) - _FIELDS))
        if unknown:
            raise ValueError(
                f"unknown account history fields {unknown}; "
                f"account series are {ACCOUNT_FIELDS} and instrument panels are {INSTRUMENT_FIELDS}"
            )
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("account requirement fields must be unique")
        if not isinstance(self.lookback, RowsLookback):
            raise TypeError("lookback must be a RowsLookback")


def retained_marks(requirements: Sequence[AccountRequirement]) -> int:
    """How many marks a run must keep resident to satisfy every declaration.

    One, when nothing is declared: the current valuation is what `AccountState` itself needs to
    prove its NAV invariant. Everything beyond that is retained because somebody asked for it.
    """
    return max((requirement.lookback.rows for requirement in requirements), default=1)


class AccountHistory:
    """A bounded, read-only view of committed marks, oldest first.

    Built per callback from marks already in memory, so a projection copies at most the declared
    window. It never recomputes account arithmetic -- every value here was published by the
    transition that committed it.
    """

    __slots__ = ("_marks", "_requirement")

    def __init__(self, marks: Sequence[object], requirement: AccountRequirement | None) -> None:
        self._requirement = requirement
        rows = requirement.lookback.rows if requirement is not None else 0
        self._marks = tuple(marks[-rows:]) if rows else ()

    def __len__(self) -> int:
        return len(self._marks)

    def _require(self, field: str, allowed: tuple[str, ...]) -> None:
        if self._requirement is None or field not in self._requirement.fields:
            raise KeyError(
                f"{field!r} was not declared in this consumer's AccountRequirement; "
                "a Model reads only what it declared"
            )
        if field not in allowed:
            raise KeyError(f"{field!r} is not available through this projection")

    def series(self, field: str) -> tuple[object, ...]:
        """Account-level values, oldest first. At most `lookback.rows` of them."""
        self._require(field, ACCOUNT_FIELDS)
        if field == "nav":
            return tuple(mark.nav for mark in self._marks)
        # NAV is cash plus marked value, and the transition that published each mark proved it,
        # so cash is recovered rather than recomputed.
        return tuple(mark.nav - mark.marks.total_value for mark in self._marks)

    def panel(self, field: str) -> Mapping[str, tuple[object, ...]]:
        """Per-instrument values, oldest first.

        An instrument absent from a mark contributes nothing at that instant rather than a
        fabricated zero: it was either not held or not priced, and both are facts the caller can
        see in the length of its series.
        """
        self._require(field, INSTRUMENT_FIELDS)
        panel: dict[str, list[object]] = {}
        for mark in self._marks:
            observed = mark.observed_at_by_instrument or {}
            for value in mark.marks.marks:
                if field == "quantity":
                    item: object = value.quantity
                elif field == "price":
                    item = value.price
                else:
                    item = observed.get(value.instrument_id, mark.marked_at)
                panel.setdefault(value.instrument_id, []).append(item)
        return MappingProxyType(
            {instrument: tuple(values) for instrument, values in sorted(panel.items())}
        )
