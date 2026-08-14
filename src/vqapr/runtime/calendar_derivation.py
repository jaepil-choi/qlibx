"""Pure application of user-selected calendar derivation rules.

This module accepts dates.  It never reads a dataset and never infers which
rule should be used.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum

from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.runtime.session_calendar import SessionCalendar

DERIVE_STAGE = "calendar.derive"
_RETRY = "fix the declared rule, dates, timezone, or session times, then derive again"
_DATE_REQUIREMENT = "calendar input must contain dates; timestamps and text are invalid"
_SESSION_REQUIREMENT = "timezone and wall times must form a valid calendar declaration"


class CalendarDerivationKind(StrEnum):
    """The closed set of supported date-selection rules."""

    ALL_INSTRUMENT_DATE_UNION = "all-instrument-date-union"
    REFERENCE_INSTRUMENT_DATES = "reference-instrument-dates"
    INDEX_SERIES_DATES = "index-series-dates"


class CalendarLimitation(StrEnum):
    """Machine-readable economic limitations recorded beside a derived calendar."""

    OBSERVED_UNION_DEFINES_SESSIONS = "observed-union-defines-sessions"
    REFERENCE_MISSING_REMOVES_SESSION = "reference-missing-removes-session"
    INDEX_COVERAGE_DEFINES_SESSIONS = "index-coverage-defines-sessions"


_LIMITATIONS = {
    CalendarDerivationKind.ALL_INSTRUMENT_DATE_UNION: (
        CalendarLimitation.OBSERVED_UNION_DEFINES_SESSIONS,
    ),
    CalendarDerivationKind.REFERENCE_INSTRUMENT_DATES: (
        CalendarLimitation.REFERENCE_MISSING_REMOVES_SESSION,
    ),
    CalendarDerivationKind.INDEX_SERIES_DATES: (
        CalendarLimitation.INDEX_COVERAGE_DEFINES_SESSIONS,
    ),
}


@dataclass(frozen=True, slots=True)
class CalendarDerivationRule:
    kind: CalendarDerivationKind
    selector: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CalendarDerivationKind):
            raise TypeError("kind must be a CalendarDerivationKind")
        needs_selector = self.kind is not CalendarDerivationKind.ALL_INSTRUMENT_DATE_UNION
        if needs_selector and (not isinstance(self.selector, str) or not self.selector.strip()):
            raise ValueError(f"{self.kind} requires a non-empty selector")
        if not needs_selector and self.selector is not None:
            raise ValueError("all-instrument-date-union does not accept a selector")

    @classmethod
    def all_instrument_date_union(cls) -> CalendarDerivationRule:
        return cls(CalendarDerivationKind.ALL_INSTRUMENT_DATE_UNION)

    @classmethod
    def reference_instrument(cls, instrument: str) -> CalendarDerivationRule:
        return cls(CalendarDerivationKind.REFERENCE_INSTRUMENT_DATES, instrument)

    @classmethod
    def index_series(cls, series: str) -> CalendarDerivationRule:
        return cls(CalendarDerivationKind.INDEX_SERIES_DATES, series)


@dataclass(frozen=True, slots=True)
class CalendarDerivationResult:
    calendar: SessionCalendar
    rule: CalendarDerivationRule
    limitations: tuple[CalendarLimitation, ...]


def _error(failure: Failure) -> VqaprError:
    return VqaprError(
        stage=DERIVE_STAGE,
        family=FailureFamily.CALENDAR,
        failures=(failure,),
        mutation=False,
        retry_precondition=_RETRY,
    )


def derive_calendar(
    dates: Iterable[date],
    *,
    rule: CalendarDerivationRule,
    timezone: str,
    session_close: time,
    session_open: time | None = None,
) -> CalendarDerivationResult:
    """Freeze selected dates under an explicit rule and explicit session times."""
    supplied = tuple(dates)
    invalid = [
        repr(value)
        for value in supplied
        if not isinstance(value, date) or isinstance(value, datetime)
    ]
    if invalid:
        raise _error(
            Failure.bounded(
                code=f"{DERIVE_STAGE}.invalid_date",
                requirement=_DATE_REQUIREMENT,
                observed=f"{len(invalid)} invalid value(s)",
                examples=invalid,
            )
        )
    if not supplied:
        raise _error(
            Failure.bounded(
                code=f"{DERIVE_STAGE}.empty",
                requirement="calendar derivation must produce at least one session date",
                observed="0 dates",
            )
        )

    try:
        calendar = SessionCalendar.of(
            supplied,
            timezone=timezone,
            session_close=session_close,
            session_open=session_open,
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            Failure.bounded(
                code=f"{DERIVE_STAGE}.session_contract",
                requirement=_SESSION_REQUIREMENT,
                observed=str(exc),
            )
        ) from exc

    return CalendarDerivationResult(
        calendar=calendar,
        rule=rule,
        limitations=_LIMITATIONS[rule.kind],
    )
