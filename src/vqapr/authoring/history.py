"""The account history a StrategyModel declares, and the projection it receives.

Moved here from `account/history.py` by the layering campaign (record `192`). The two halves were
in different packages and each needed the other: `authoring` imported the field names and the
projection type, and `account/history.py` imported the declaration back under `TYPE_CHECKING` --
a cycle, deferred rather than resolved. Its own comment said as much:

    The declaration is `authoring`'s, and `authoring` imports this module for the field
    names and the projection type, so the type lives here as an annotation only.

They are one contract. `AccountHistoryInput` is what a StrategyModel declares and `AccountHistory`
is what it is then handed, and neither is meaningful without the other, so they live in one module
and the deferral is gone rather than relocated. The account package keeps the behaviour that
produces the marks; this is the shape the author sees.

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
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, field_validator

from vqapr.authoring._validation import _VALUE_CONFIG, _unique_identifiers
from vqapr.data.lookback import RowsLookback
from vqapr.domain.account_state import AccountMark

ACCOUNT_FIELDS = ("nav", "cash")
"""One value per marked instant."""

INSTRUMENT_FIELDS = ("quantity", "price", "observed_at")
"""One value per held instrument per marked instant.

`price` and `observed_at` are separate fields, not a pair. A Strategy that only needs the price
should not pay to retain when it was observed, and one that must tell a halt from a flat market
declares both. A field is a column, which is what it means in `DataRequirement` too.
"""

def retained_marks(declaration: AccountHistoryInput | None) -> int:
    """How many marks a run must keep resident to satisfy the Strategy's declaration.

    One, when nothing is declared: the current valuation is what `AccountState` itself needs to
    prove its NAV invariant. Everything beyond that is retained because somebody asked for it.
    """
    return declaration.lookback.rows if declaration is not None else 1


class AccountHistory:
    """A bounded, read-only view of committed marks, oldest first.

    Built per callback from marks already in memory, so a projection copies at most the declared
    window. It never recomputes account arithmetic -- every value here was published by the
    transition that committed it.
    """

    __slots__ = ("_declaration", "_marks")

    def __init__(
        self, marks: Sequence[AccountMark], declaration: AccountHistoryInput | None
    ) -> None:
        self._declaration = declaration
        rows = declaration.lookback.rows if declaration is not None else 0
        self._marks = tuple(marks[-rows:]) if rows else ()

    def __len__(self) -> int:
        return len(self._marks)

    def _require(self, field: str, allowed: tuple[str, ...]) -> None:
        if self._declaration is None or field not in self._declaration.fields:
            raise KeyError(
                f"{field!r} was not declared in this StrategyModel's account_history(); "
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


_HISTORY_FIELDS = frozenset(ACCOUNT_FIELDS) | frozenset(INSTRUMENT_FIELDS)
"""The closed set `AccountHistoryInput.fields` is checked against."""


class AccountHistoryInput(BaseModel):
    """A StrategyModel's declaration of which committed account history it reads."""

    model_config = _VALUE_CONFIG

    fields: tuple[Literal["nav", "cash", "quantity", "price", "observed_at"], ...]
    lookback: RowsLookback

    @field_validator("fields", mode="before")
    @classmethod
    def _known(cls, value: object) -> tuple[str, ...]:
        # Before the `Literal` check, so an unknown name is refused with the two lists it could
        # have come from rather than with the bare literal set.
        fields = _unique_identifiers(value, name="fields")
        unknown = sorted(set(fields) - _HISTORY_FIELDS)
        if unknown:
            raise ValueError(
                f"unknown account history fields {unknown}; "
                f"account series are {ACCOUNT_FIELDS} and "
                f"instrument panels are {INSTRUMENT_FIELDS}"
            )
        return fields
