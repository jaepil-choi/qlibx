"""Finite operation agenda declarations.

Agendas are resolved input, never a recurrence or calendar source.  Their local
clock proof is retained with each occurrence so the canonical UTC ordering is
reproducible across timezone transitions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.identifiers import AgendaId, OccurrenceId
from vqapr.domain.timestamps import LocalInstantDeclaration, require_tz_aware


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
        return _identity(
            {
                "occurrence_id": self.occurrence_id,
                "role": self.role,
                "local_instant": self.local_instant.identity(),
            }
        )

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
        return _identity(
            {
                "role": self.role,
                "timezone": self.timezone,
                "occurrences": [occurrence.content_identity for occurrence in self.occurrences],
            }
        )

    @property
    def provenance_identity(self) -> str:
        return _identity(
            {
                "agenda_id": self.agenda_id,
                "provenance": self.provenance,
                "content_identity": self.content_identity,
            }
        )

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
