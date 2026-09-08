"""Finite operation agenda declarations.

Moved from `runtime/agendas.py` (one-shape Step 7, record 162): an occurrence is a value a Model
is handed (`calls.py` imports it), so it lives with the other values, below `flow/`.

Agendas are resolved input, never a recurrence or calendar source.  Their local
clock proof is retained with each occurrence so the canonical UTC ordering is
reproducible across timezone transitions.

**An occurrence has no role and an agenda no provenance** (record `182`). Both were the clothes
of the time an agenda was a registered declaration one of three roles could own; since record
`148` the one agenda is derived from the run, every run kind walks the same occurrences, and
what an occurrence dispatches to is decided by the loop that handles it (`flow/loop.py`), not
by a field on the occurrence. The role priority that ordered occurrences of different roles at
one instant had no reachable input -- an agenda is single-role by construction -- and
`provenance` was computed, verified and carried with no reader
(`docs/code-review/2026-09-08-the-agenda-carries-a-role-nobody-chose.md`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.identifiers import AgendaId, OccurrenceId, occurrence_id
from vqapr.domain.values import (
    LocalInstantDeclaration,
    declare_local_instant,
    require_tz_aware,
)

SCHEDULED_PRIORITY = 0
"""The second term of a scheduled occurrence's sort key. A due event (`flow/loop.py`) sorts at
`-1`, ahead of every occurrence at the same instant: what was decided earlier is settled before
anything new is decided there."""


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
                        "local_instant": self.local_instant.identity(),
                    }
                ),
            )
        return self._content_identity

    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.utc_evaluation_time, SCHEDULED_PRIORITY, self.occurrence_id)


@dataclass(frozen=True, slots=True)
class OperationAgenda:
    agenda_id: AgendaId
    timezone: str
    occurrences: tuple[OperationOccurrence, ...]
    _content_identity: str = field(default="", init=False, repr=False, compare=False)
    """Memo for the derived identity. See `OperationOccurrence._content_identity`."""

    def __post_init__(self) -> None:
        _require_identifier(self.agenda_id, name="agenda_id")
        _require_timezone(self.timezone)
        occurrences = tuple(self.occurrences)
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
                        "timezone": self.timezone,
                        "occurrences": [
                            occurrence.content_identity for occurrence in self.occurrences
                        ],
                    }
                ),
            )
        return self._content_identity

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
    def daily(
        cls,
        *,
        agenda_id: AgendaId,
        sessions: Iterable[datetime | date],
        at: time,
        timezone: str,
    ) -> OperationAgenda:
        """One occurrence per session, at the same venue-local wall time.

        The constructor takes occurrences that are already known. The common case is not a list --
        it is "every session this registered dataset has, at 08:00 local", and turning one into
        the other is mechanical work that was being written by hand at every call site.

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
        resolved by guess. There is no remedy inside the run declaration: a run names one `at` for
        every session, so a venue whose clock skips or repeats that wall time on some day needs a
        different `at`, or sessions that avoid the day.
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
                occurrence_id(f"{agenda_id}-{day.isoformat()}"),
                declare_local_instant(day, at, timezone),
            )
            for day in sorted(days)
        )
        return cls(agenda_id=agenda_id, timezone=timezone, occurrences=occurrences)
