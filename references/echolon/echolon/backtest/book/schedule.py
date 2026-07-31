"""Immutable execution-contract schedules for daily book backtests.

The schedule is deliberately policy-neutral: an upstream research system
selects each contract and records its rule, while Echolon validates the sealed
artifact and executes only the exact contract declared for a fill date.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import warnings
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in .* shadows an attribute in parent "BaseModel"',
    category=UserWarning,
    module=__name__,
)


EXECUTABLE_STATUS = "executable"
SCHEDULE_SCHEMA = "execution-contract-schedule/v1"


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return value


def canonical_schedule_sha256(payload: Mapping[str, Any] | BaseModel) -> str:
    """Hash canonical JSON after excluding only the top-level ``sha256``.

    Dates are encoded as ISO-8601 strings. Object keys are sorted, list order is
    preserved, insignificant whitespace is removed, NaN/Inf are forbidden, and
    UTF-8 bytes are hashed. This function accepts either an artifact model or a
    mapping so an upstream producer can share the exact recipe.
    """
    if isinstance(payload, BaseModel):
        raw = payload.model_dump(mode="json")
    else:
        raw = dict(payload)
    raw.pop("sha256", None)
    encoded = json.dumps(
        _canonical_json_value(raw),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExecutionContractScheduleRow(BaseModel):
    """One explicit contract decision for one fill date and instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    fill_date: dt.date
    instrument: str
    status: str
    contract: str | None
    source_date: dt.date | None
    source_volume: str | None = None
    source_open_interest: str | None = None

    @field_validator("instrument")
    @classmethod
    def _normalized_instrument(cls, value: str) -> str:
        if not value or value != value.strip() or value != value.lower():
            raise ValueError("instrument must be a non-empty normalized lowercase identifier")
        return value

    @field_validator("status")
    @classmethod
    def _normalized_status(cls, value: str) -> str:
        if (
            not value
            or value != value.strip()
            or value != value.lower()
            or not value.replace("_", "").isalnum()
        ):
            raise ValueError("status must be a non-empty lowercase code")
        return value

    @field_validator("contract")
    @classmethod
    def _normalized_contract(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("contract must be null or a non-empty trimmed identifier")
        return value

    @field_validator("source_volume", "source_open_interest", mode="before")
    @classmethod
    def _canonical_nonnegative_decimal(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(
                "source volume and open interest must be canonical decimal strings"
            )
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                "source volume and open interest must be canonical decimal strings"
            ) from exc
        if not number.is_finite() or number.is_signed():
            raise ValueError(
                "source volume and open interest must be finite and non-negative"
            )
        fixed = format(number, "f")
        if "." in fixed:
            integer, fraction = fixed.split(".", 1)
            fraction = fraction.rstrip("0")
        else:
            integer, fraction = fixed, ""
        integer = integer.lstrip("0") or "0"
        canonical = f"{integer}.{fraction}" if fraction else integer
        if value != canonical:
            raise ValueError(
                "source volume and open interest must use canonical fixed-point "
                "decimal strings"
            )
        return value

    @model_validator(mode="after")
    def _validate_semantics(self) -> "ExecutionContractScheduleRow":
        if self.source_date is not None and self.source_date >= self.fill_date:
            raise ValueError("source_date must be strictly before fill_date")
        if self.source_date is None and (
            self.source_volume is not None or self.source_open_interest is not None
        ):
            raise ValueError("source provenance requires source_date")
        if self.status == EXECUTABLE_STATUS:
            if self.contract is None or self.source_date is None:
                raise ValueError("executable rows require contract and source_date")
        elif self.contract is not None:
            raise ValueError("non-executable rows must not declare a contract")
        return self


class _ExecutionContractSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema: Literal["execution-contract-schedule/v1"] = SCHEDULE_SCHEMA
    source_panel_snapshot: str
    source_panel_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_rule: str
    availability_assumption: str
    instruments: tuple[str, ...]
    start: dt.date
    end: dt.date
    rows: tuple[ExecutionContractScheduleRow, ...]

    @field_validator(
        "source_panel_snapshot", "selection_rule", "availability_assumption"
    )
    @classmethod
    def _nonempty_trimmed_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("schedule identity and policy text must be non-empty and trimmed")
        return value

    @field_validator("instruments")
    @classmethod
    def _declared_instruments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("schedule instruments must be non-empty")
        if any(
            not instrument
            or instrument != instrument.strip()
            or instrument != instrument.lower()
            for instrument in value
        ):
            raise ValueError(
                "schedule instruments must be normalized lowercase identifiers"
            )
        if len(set(value)) != len(value):
            raise ValueError("schedule instruments must be unique")
        return value

    @model_validator(mode="after")
    def _validate_payload(self) -> "_ExecutionContractSchedulePayload":
        if self.end < self.start:
            raise ValueError("schedule end must be on or after start")
        if not self.rows:
            raise ValueError("schedule rows must be non-empty")

        instrument_rank = {
            instrument: rank for rank, instrument in enumerate(self.instruments)
        }
        seen: set[tuple[dt.date, str]] = set()
        prior_key: tuple[dt.date, int] | None = None
        for row in self.rows:
            if row.instrument not in instrument_rank:
                raise ValueError(
                    f"schedule row instrument {row.instrument!r} is not declared"
                )
            if row.fill_date < self.start or row.fill_date > self.end:
                raise ValueError("schedule row fill_date is outside the declared window")
            identity = (row.fill_date, row.instrument)
            if identity in seen:
                raise ValueError(
                    "duplicate schedule row for "
                    f"{row.fill_date.isoformat()} {row.instrument}"
                )
            seen.add(identity)
            key = (row.fill_date, instrument_rank[row.instrument])
            if prior_key is not None and key <= prior_key:
                raise ValueError(
                    "schedule rows must be strictly ordered by fill_date then "
                    "declared instrument order"
                )
            prior_key = key
        return self


class ExecutionContractSchedule(_ExecutionContractSchedulePayload):
    """A sealed, policy-neutral execution-contract schedule artifact.

    Structural completeness is validated against the panel union calendar by
    :class:`~echolon.backtest.book.engine.DailyBookBacktester` before any
    simulation state is mutated.
    """

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _verify_hash(self) -> "ExecutionContractSchedule":
        actual = canonical_schedule_sha256(self)
        if self.sha256 != actual:
            raise ValueError(
                f"execution contract schedule hash mismatch: expected {self.sha256}, "
                f"computed {actual}"
            )
        return self

    @classmethod
    def create(cls, **payload: Any) -> "ExecutionContractSchedule":
        """Validate a payload, compute its canonical hash, and seal it."""
        payload.pop("sha256", None)
        validated = _ExecutionContractSchedulePayload.model_validate(payload)
        canonical_payload = validated.model_dump(mode="json")
        canonical_payload["sha256"] = canonical_schedule_sha256(canonical_payload)
        return cls.model_validate(canonical_payload)

    def row_map(self) -> dict[tuple[dt.date, str], ExecutionContractScheduleRow]:
        """Return exact row lookup; constructor validation guarantees uniqueness."""
        return {(row.fill_date, row.instrument): row for row in self.rows}


def load_execution_contract_schedule(path: Path) -> ExecutionContractSchedule:
    """Load and validate a sealed JSON schedule artifact."""
    return ExecutionContractSchedule.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def write_execution_contract_schedule(
    path: Path, schedule: ExecutionContractSchedule
) -> Path:
    """Atomically publish one new schedule and refuse an existing target.

    A fully written, fsync'd temporary inode is hard-linked into place, making
    publication both atomic and exclusive. The sealed artifact is never
    silently overwritten.
    """
    validated = ExecutionContractSchedule.model_validate(
        schedule.model_dump(mode="python")
    )
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
