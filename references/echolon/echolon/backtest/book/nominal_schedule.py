"""Immutable nominal-cycle schedules for daily book backtests.

The artifact embeds both the authoritative exchange calendar and the panel
union calendar.  Its rows are derived data: validation recomputes every row
from those embedded inputs and the fixed v1 policy rather than trusting a
publisher's dates or status labels.
"""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schedule import canonical_schedule_sha256


warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in .* shadows an attribute in parent "BaseModel"',
    category=UserWarning,
    module=__name__,
)


NOMINAL_CYCLE_SCHEMA = "futures-nominal-cycle-schedule/v1"
INTERVAL_CALENDAR_DAYS = 28
NOMINAL_WEEKDAY = 4
DECISION_RULE = "earliest_authoritative_session_on_or_after_nominal"
FILL_RULE = "earliest_authoritative_session_after_decision"
CATCH_UP_RULE = "authority_open_panel_missing_skip_no_catch_up"

SCHEDULED = "scheduled"
PANEL_DATA_MISSING = "panel_data_missing"
AUTHORITY_COVERAGE_MISSING = "authority_coverage_missing"
NO_DECISION = "no_decision"
NO_NEXT_CYCLE = "no_next_cycle"
NEXT_FILL_UNAVAILABLE = "next_fill_unavailable"


def canonical_session_list_sha256(sessions: Sequence[dt.date]) -> str:
    """Hash an ordered date list using canonical JSON UTF-8 bytes."""
    encoded = json.dumps(
        [session.isoformat() for session in sessions],
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def nominal_cycle_id(cadence_id: str, nominal_date: dt.date) -> str:
    """Return the stable identity for one cadence and nominal date."""
    encoded = json.dumps(
        [cadence_id, nominal_date.isoformat()],
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class NominalCycleScheduleRow(BaseModel):
    """One fully derived nominal decision/fill/exit cycle."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    cycle_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    nominal_date: dt.date
    decision_date: dt.date | None
    decision_status: Literal[
        "scheduled", "panel_data_missing", "authority_coverage_missing"
    ]
    catch_up_days: int | None = Field(default=None, ge=0)
    fill_date: dt.date | None
    fill_status: Literal[
        "scheduled",
        "panel_data_missing",
        "authority_coverage_missing",
        "no_decision",
    ]
    next_cycle_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    exit_fill_date: dt.date | None
    exit_fill_status: Literal[
        "scheduled", "no_next_cycle", "next_fill_unavailable"
    ]


class _NominalCycleSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["futures-nominal-cycle-schedule/v1"] = NOMINAL_CYCLE_SCHEMA
    source_panel_snapshot: str
    source_panel_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoritative_calendar_id: str
    authoritative_calendar_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoritative_coverage_basis: str
    authoritative_sessions: tuple[dt.date, ...]
    authoritative_sessions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_start: dt.date
    coverage_end: dt.date
    panel_union_sessions: tuple[dt.date, ...]
    panel_union_sessions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cadence_id: str
    nominal_anchor: dt.date
    nominal_start: dt.date
    nominal_end: dt.date
    interval_calendar_days: Literal[28] = INTERVAL_CALENDAR_DAYS
    nominal_weekday: Literal[4] = NOMINAL_WEEKDAY
    decision_rule: Literal[
        "earliest_authoritative_session_on_or_after_nominal"
    ] = DECISION_RULE
    fill_rule: Literal["earliest_authoritative_session_after_decision"] = FILL_RULE
    catch_up_rule: Literal[
        "authority_open_panel_missing_skip_no_catch_up"
    ] = CATCH_UP_RULE
    rows: tuple[NominalCycleScheduleRow, ...]

    @field_validator(
        "source_panel_snapshot",
        "authoritative_calendar_id",
        "authoritative_coverage_basis",
        "cadence_id",
    )
    @classmethod
    def _nonempty_trimmed_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("nominal-cycle identity text must be non-empty and trimmed")
        return value

    @field_validator("authoritative_sessions", "panel_union_sessions")
    @classmethod
    def _ordered_unique_sessions(
        cls, value: tuple[dt.date, ...]
    ) -> tuple[dt.date, ...]:
        if not value:
            raise ValueError("embedded session lists must be non-empty")
        if tuple(sorted(set(value))) != value:
            raise ValueError(
                "embedded session lists must be unique and strictly increasing"
            )
        return value

    @model_validator(mode="after")
    def _validate_payload(self) -> "_NominalCycleSchedulePayload":
        if self.coverage_end < self.coverage_start:
            raise ValueError("authoritative coverage_end must not precede coverage_start")
        if any(
            session < self.coverage_start or session > self.coverage_end
            for session in self.authoritative_sessions
        ):
            raise ValueError(
                "authoritative sessions must lie within the declared coverage bounds"
            )
        if (
            canonical_session_list_sha256(self.authoritative_sessions)
            != self.authoritative_sessions_sha256
        ):
            raise ValueError("authoritative session-list hash mismatch")
        if (
            canonical_session_list_sha256(self.panel_union_sessions)
            != self.panel_union_sessions_sha256
        ):
            raise ValueError("panel union session-list hash mismatch")
        if self.nominal_end < self.nominal_start:
            raise ValueError("nominal_end must not precede nominal_start")
        if self.nominal_start < self.nominal_anchor:
            raise ValueError("nominal_start must not precede the absolute nominal_anchor")
        if self.nominal_anchor.weekday() != self.nominal_weekday:
            raise ValueError("nominal_anchor does not have the declared nominal weekday")
        for label, value in (
            ("nominal_start", self.nominal_start),
            ("nominal_end", self.nominal_end),
        ):
            if value.weekday() != self.nominal_weekday:
                raise ValueError(f"{label} does not have the declared nominal weekday")
            if (value - self.nominal_anchor).days % self.interval_calendar_days:
                raise ValueError(f"{label} is not aligned to nominal_anchor")

        expected = _derive_nominal_cycle_rows(
            authoritative_sessions=self.authoritative_sessions,
            coverage_start=self.coverage_start,
            coverage_end=self.coverage_end,
            panel_union_sessions=self.panel_union_sessions,
            cadence_id=self.cadence_id,
            nominal_start=self.nominal_start,
            nominal_end=self.nominal_end,
        )
        if self.rows != expected:
            raise ValueError(
                "nominal-cycle rows do not match recomputation from embedded sessions "
                "and fixed policy"
            )

        scheduled_decisions: set[dt.date] = set()
        for row in self.rows:
            if row.decision_status == SCHEDULED:
                assert row.decision_date is not None
                if row.decision_date in scheduled_decisions:
                    raise ValueError(
                        "duplicate scheduled decision date across nominal cycles: "
                        f"{row.decision_date.isoformat()}"
                    )
                scheduled_decisions.add(row.decision_date)
        for row in self.rows:
            if row.fill_status == SCHEDULED and row.exit_fill_status == SCHEDULED:
                assert row.fill_date is not None
                assert row.exit_fill_date is not None
                if row.exit_fill_date <= row.fill_date:
                    raise ValueError(
                        "scheduled nominal-cycle holding window must have "
                        "exit_fill_date strictly after fill_date"
                    )
        return self


class NominalCycleSchedule(_NominalCycleSchedulePayload):
    """A sealed, self-contained nominal-cycle schedule artifact."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _verify_hash(self) -> "NominalCycleSchedule":
        actual = canonical_schedule_sha256(self)
        if self.sha256 != actual:
            raise ValueError(
                f"nominal-cycle schedule hash mismatch: expected {self.sha256}, "
                f"computed {actual}"
            )
        return self

    @classmethod
    def create(cls, **payload: Any) -> "NominalCycleSchedule":
        payload.pop("sha256", None)
        validated = _NominalCycleSchedulePayload.model_validate(payload)
        canonical_payload = validated.model_dump(mode="json")
        canonical_payload["sha256"] = canonical_schedule_sha256(canonical_payload)
        return cls.model_validate(canonical_payload)

    def rows_by_cycle_id(self) -> dict[str, NominalCycleScheduleRow]:
        """Return lossless exact lookup by the artifact's stable row identity."""
        return {row.cycle_id: row for row in self.rows}


def _derive_nominal_cycle_rows(
    *,
    authoritative_sessions: Sequence[dt.date],
    coverage_start: dt.date,
    coverage_end: dt.date,
    panel_union_sessions: Sequence[dt.date],
    cadence_id: str,
    nominal_start: dt.date,
    nominal_end: dt.date,
) -> tuple[NominalCycleScheduleRow, ...]:
    authority = tuple(authoritative_sessions)
    panel_dates = frozenset(panel_union_sessions)
    nominal_dates: list[dt.date] = []
    cursor = nominal_start
    while cursor <= nominal_end:
        nominal_dates.append(cursor)
        cursor += dt.timedelta(days=INTERVAL_CALENDAR_DAYS)

    preliminary: list[dict[str, Any]] = []
    for nominal_date in nominal_dates:
        cycle_id = nominal_cycle_id(cadence_id, nominal_date)
        decision_date: dt.date | None = None
        decision_status = AUTHORITY_COVERAGE_MISSING
        catch_up_days: int | None = None
        fill_date: dt.date | None = None
        fill_status = NO_DECISION

        if coverage_start <= nominal_date <= coverage_end:
            decision_index = bisect.bisect_left(authority, nominal_date)
            if (
                decision_index < len(authority)
                and authority[decision_index] <= coverage_end
            ):
                decision_date = authority[decision_index]
                catch_up_days = (decision_date - nominal_date).days
                if decision_date not in panel_dates:
                    decision_status = PANEL_DATA_MISSING
                else:
                    decision_status = SCHEDULED
                    fill_index = decision_index + 1
                    if fill_index >= len(authority) or authority[fill_index] > coverage_end:
                        fill_status = AUTHORITY_COVERAGE_MISSING
                    else:
                        fill_date = authority[fill_index]
                        fill_status = (
                            SCHEDULED if fill_date in panel_dates else PANEL_DATA_MISSING
                        )

        preliminary.append(
            {
                "cycle_id": cycle_id,
                "nominal_date": nominal_date,
                "decision_date": decision_date,
                "decision_status": decision_status,
                "catch_up_days": catch_up_days,
                "fill_date": fill_date,
                "fill_status": fill_status,
            }
        )

    rows: list[NominalCycleScheduleRow] = []
    for index, raw in enumerate(preliminary):
        if index + 1 >= len(preliminary):
            next_cycle_id = None
            exit_fill_date = None
            exit_fill_status = NO_NEXT_CYCLE
        else:
            next_row = preliminary[index + 1]
            next_cycle_id = str(next_row["cycle_id"])
            if next_row["fill_status"] == SCHEDULED:
                exit_fill_date = next_row["fill_date"]
                exit_fill_status = SCHEDULED
            else:
                exit_fill_date = None
                exit_fill_status = NEXT_FILL_UNAVAILABLE
        rows.append(
            NominalCycleScheduleRow(
                **raw,
                next_cycle_id=next_cycle_id,
                exit_fill_date=exit_fill_date,
                exit_fill_status=exit_fill_status,
            )
        )
    return tuple(rows)


def create_nominal_cycle_schedule(
    *,
    source_panel_snapshot: str,
    source_panel_manifest_sha256: str,
    authoritative_calendar_id: str,
    authoritative_calendar_source_sha256: str,
    authoritative_coverage_basis: str,
    authoritative_sessions: Sequence[dt.date],
    coverage_start: dt.date,
    coverage_end: dt.date,
    panel_union_sessions: Sequence[dt.date],
    cadence_id: str,
    nominal_anchor: dt.date,
    nominal_start: dt.date,
    nominal_end: dt.date,
    interval_calendar_days: Literal[28] = INTERVAL_CALENDAR_DAYS,
    nominal_weekday: Literal[4] = NOMINAL_WEEKDAY,
    decision_rule: Literal[
        "earliest_authoritative_session_on_or_after_nominal"
    ] = DECISION_RULE,
    fill_rule: Literal["earliest_authoritative_session_after_decision"] = FILL_RULE,
    catch_up_rule: Literal[
        "authority_open_panel_missing_skip_no_catch_up"
    ] = CATCH_UP_RULE,
) -> NominalCycleSchedule:
    """Derive, validate, hash, and seal one v1 nominal-cycle schedule."""
    authority = tuple(authoritative_sessions)
    panel_sessions = tuple(panel_union_sessions)
    rows = _derive_nominal_cycle_rows(
        authoritative_sessions=authority,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        panel_union_sessions=panel_sessions,
        cadence_id=cadence_id,
        nominal_start=nominal_start,
        nominal_end=nominal_end,
    )
    return NominalCycleSchedule.create(
        source_panel_snapshot=source_panel_snapshot,
        source_panel_manifest_sha256=source_panel_manifest_sha256,
        authoritative_calendar_id=authoritative_calendar_id,
        authoritative_calendar_source_sha256=authoritative_calendar_source_sha256,
        authoritative_coverage_basis=authoritative_coverage_basis,
        authoritative_sessions=authority,
        authoritative_sessions_sha256=canonical_session_list_sha256(authority),
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        panel_union_sessions=panel_sessions,
        panel_union_sessions_sha256=canonical_session_list_sha256(panel_sessions),
        cadence_id=cadence_id,
        nominal_anchor=nominal_anchor,
        nominal_start=nominal_start,
        nominal_end=nominal_end,
        interval_calendar_days=interval_calendar_days,
        nominal_weekday=nominal_weekday,
        decision_rule=decision_rule,
        fill_rule=fill_rule,
        catch_up_rule=catch_up_rule,
        rows=rows,
    )


def load_nominal_cycle_schedule(path: Path) -> NominalCycleSchedule:
    """Load and fully revalidate a sealed schedule JSON artifact."""
    return NominalCycleSchedule.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_nominal_cycle_schedule(path: Path, schedule: NominalCycleSchedule) -> Path:
    """Atomically publish once and refuse to replace an existing artifact."""
    validated = NominalCycleSchedule.model_validate(schedule.model_dump(mode="python"))
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        json.dumps(
            validated.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.unlink()
    return target
