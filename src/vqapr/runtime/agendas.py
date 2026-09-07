"""Finite operation agenda declarations.

Agendas are resolved input, never a recurrence or calendar source.  Their local
clock proof is retained with each occurrence so the canonical UTC ordering is
reproducible across timezone transitions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.identifiers import AgendaId, OccurrenceId
from vqapr.domain.values import (
    LocalInstantDeclaration,
    declare_local_instant,
    require_tz_aware,
)


class OperationRole(StrEnum):
    STRATEGY_CALLBACK = "STRATEGY_CALLBACK"
    VALUATION = "VALUATION"
    MONITORING = "MONITORING"


_ROLE_PRIORITY = {
    OperationRole.STRATEGY_CALLBACK: 0,
    OperationRole.VALUATION: 1,
    OperationRole.MONITORING: 2,
}


def operation_role_priority(role: OperationRole) -> int:
    if not isinstance(role, OperationRole):
        raise TypeError("role must be an OperationRole")
    return _ROLE_PRIORITY[role]


def _identity(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_timezone(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timezone must be a non-empty IANA timezone name")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {value!r}") from exc
    return value


def _require_identifier(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"{name} must be a non-empty identifier without whitespace")
    return value


@dataclass(frozen=True, slots=True)
class OperationOccurrence:
    occurrence_id: OccurrenceId
    role: OperationRole
    local_instant: LocalInstantDeclaration
    _content_identity: str = field(default="", init=False, repr=False, compare=False)
    """Memo for `content_identity`, which is derived from frozen fields and cannot change.

    Deriving it costs a json encode and a sha256. `FrozenRun.identity` re-derives it for every
    occurrence of every agenda on each access, and a run reads that identity about sixteen times
    per callback, so recomputing made the run quadratic in its own length. Kept lazy rather than
    computed in `__post_init__` because decoding a workspace builds every occurrence and never
    asks any of them for an identity.
    """

    def __post_init__(self) -> None:
        _require_identifier(self.occurrence_id, name="occurrence_id")
        if not isinstance(self.role, OperationRole):
            raise TypeError("role must be an OperationRole")
        if not isinstance(self.local_instant, LocalInstantDeclaration):
            raise TypeError("local_instant must be a LocalInstantDeclaration")

    @property
    def evaluation_time(self) -> datetime:
        return self.local_instant.instant

    @property
    def utc_evaluation_time(self) -> datetime:
        return self.local_instant.utc_instant

    @property
    def content_identity(self) -> str:
        if not self._content_identity:
            object.__setattr__(
                self,
                "_content_identity",
                _identity(
                    {
                        "occurrence_id": self.occurrence_id,
                        "role": self.role,
                        "local_instant": self.local_instant.identity(),
                    }
                ),
            )
        return self._content_identity

    def sort_key(self) -> tuple[datetime, int, str]:
        return (
            self.utc_evaluation_time,
            operation_role_priority(self.role),
            self.occurrence_id,
        )


@dataclass(frozen=True, slots=True)
class OperationAgenda:
    agenda_id: AgendaId
    role: OperationRole
    timezone: str
    occurrences: tuple[OperationOccurrence, ...]
    provenance: str
    _content_identity: str = field(default="", init=False, repr=False, compare=False)
    _provenance_identity: str = field(default="", init=False, repr=False, compare=False)
    """Memos for the two derived identities. See `OperationOccurrence._content_identity`.

    `provenance_identity` is derived from `content_identity`, so leaving both uncached meant one
    provenance read re-hashed every occurrence twice.
    """

    def __post_init__(self) -> None:
        _require_identifier(self.agenda_id, name="agenda_id")
        if not isinstance(self.role, OperationRole):
            raise TypeError("role must be an OperationRole")
        _require_timezone(self.timezone)
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("provenance must be a non-empty string")
        occurrences = tuple(self.occurrences)
        if any(not isinstance(occurrence, OperationOccurrence) for occurrence in occurrences):
            raise TypeError("occurrences must contain OperationOccurrence values")
        if any(occurrence.role is not self.role for occurrence in occurrences):
            raise ValueError("every occurrence role must match the agenda role")
        if any(occurrence.local_instant.timezone != self.timezone for occurrence in occurrences):
            raise ValueError("every occurrence timezone must match the agenda timezone")
        occurrence_ids = [occurrence.occurrence_id for occurrence in occurrences]
        if len(set(occurrence_ids)) != len(occurrence_ids):
            raise ValueError("occurrence_id values must be unique within an agenda")
        object.__setattr__(
            self,
            "occurrences",
            tuple(sorted(occurrences, key=OperationOccurrence.sort_key)),
        )

    @property
    def content_identity(self) -> str:
        if not self._content_identity:
            object.__setattr__(
                self,
                "_content_identity",
                _identity(
                    {
                        "role": self.role,
                        "timezone": self.timezone,
                        "occurrences": [
                            occurrence.content_identity for occurrence in self.occurrences
                        ],
                    }
                ),
            )
        return self._content_identity

    @property
    def provenance_identity(self) -> str:
        if not self._provenance_identity:
            object.__setattr__(
                self,
                "_provenance_identity",
                _identity(
                    {
                        "agenda_id": self.agenda_id,
                        "provenance": self.provenance,
                        "content_identity": self.content_identity,
                    }
                ),
            )
        return self._provenance_identity

    def inclusive_slice(self, start: datetime, end: datetime) -> tuple[OperationOccurrence, ...]:
        require_tz_aware(start, name="start")
        require_tz_aware(end, name="end")
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        if start_utc > end_utc:
            raise ValueError("start must not be after end")
        return tuple(
            occurrence
            for occurrence in self.occurrences
            if start_utc <= occurrence.utc_evaluation_time <= end_utc
        )

    @classmethod
    def from_occurrences(
        cls,
        *,
        agenda_id: AgendaId,
        role: OperationRole,
        timezone: str,
        occurrences: Iterable[OperationOccurrence],
        provenance: str,
    ) -> OperationAgenda:
        return cls(
            agenda_id=agenda_id,
            role=role,
            timezone=timezone,
            occurrences=tuple(occurrences),
            provenance=provenance,
        )

    @classmethod
    def daily(
        cls,
        *,
        agenda_id: AgendaId,
        role: OperationRole,
        sessions: Iterable[datetime | date],
        at: time,
        timezone: str,
        provenance: str | None = None,
    ) -> OperationAgenda:
        """One occurrence per session, at the same venue-local wall time.

        `from_occurrences` is the constructor for an agenda whose occurrences are already known.
        The common case is not a list -- it is "every session this registered dataset has, at
        08:00 local", and turning one into the other is mechanical work that was being written by
        hand at every call site.

        Three things stop being the caller's to get right:

        - **The occurrence id.** Derived as ``{agenda_id}-{date}``. Two call sites inventing
          slightly different id schemes produce different identities for the same session, and a
          replay stops being comparable to the run it replays.
        - **fold and offset.** Derived from the zone rather than typed as constants. A hand-written
          ``0`` and ``"+09:00"`` is correct until the venue observes DST, after which it is wrong
          twice a year and right on every day anyone tests.
        - **Duplicate sessions.** A dataset can carry several rows for one day; the agenda takes
          the day once.

        `sessions` accepts datetimes, so the sessions a dataset actually has can be passed
        straight through from ``Workspace.evaluation_times``. Only their venue-local date is used:
        the time of day comes from ``at``, because when a row became available and when a decision
        is made are different facts.

        A wall time that does not exist, or happens twice, on any session is refused rather than
        resolved by guess. Declare those days through `from_occurrences`.
        """
        zone = ZoneInfo(timezone)
        days: list[date] = []
        seen: set[date] = set()
        for session in sessions:
            if isinstance(session, datetime):
                day = (
                    session.astimezone(zone).date()
                    if session.tzinfo is not None
                    else session.date()
                )
            elif isinstance(session, date):
                day = session
            else:
                raise TypeError("sessions must contain datetime or date values")
            if day not in seen:
                seen.add(day)
                days.append(day)
        occurrences = tuple(
            OperationOccurrence(
                f"{agenda_id}-{day.isoformat()}",
                role,
                declare_local_instant(day, at, timezone),
            )
            for day in sorted(days)
        )
        return cls(
            agenda_id=agenda_id,
            role=role,
            timezone=timezone,
            occurrences=occurrences,
            provenance=(
                provenance
                if provenance is not None
                else f"{len(occurrences)} sessions at {at.isoformat()} {timezone}"
            ),
        )
