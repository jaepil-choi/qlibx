"""Agent-first materialization declaration and result contracts.

``vqapr.materialization`` is the sole public home for the caller's evaluation-time/instrument
declaration and the result view a completed materialization returns. A ``DataModel`` (declared in
``vqapr.authoring``) owns its own semantic output schema; nothing here lets a caller repeat or
override the fields a model declares through ``authoring.Output``.

Every public declaration is a frozen, slotted, keyword-only value. Constructors reject empty or
duplicate identifiers, naive datetimes, and out-of-order/duplicate evaluation times. This module
declares algebra only: no store, catalog, fingerprint, or Project wiring lives here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from vqapr.authoring import DerivedRow
from vqapr.domain.timestamps import require_tz_aware

__all__ = (
    "Materialization",
    "MaterializationInvocation",
    "MaterializationResult",
)


# --------------------------------------------------------------------------------------
# Shared validation helpers (implementation detail; not part of the public algebra).
# --------------------------------------------------------------------------------------


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


def _unique_identifiers(values: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of strings")
    normalized = tuple(_identifier(value, name=f"{name} entry") for value in values)
    if not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} entries must be unique")
    return normalized


def _tz_aware(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    return require_tz_aware(value, name=name)


def _strictly_increasing_instants(values: object, *, name: str) -> tuple[datetime, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of datetimes")
    normalized = tuple(_tz_aware(value, name=f"{name} entry") for value in values)
    if not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    for earlier, later in pairwise(normalized):
        # Aware datetimes compare correctly across differing tzinfo, so a direct `<=`
        # already enforces strict chronological order regardless of zone.
        if later <= earlier:
            raise ValueError(f"{name} must be strictly increasing")
    return normalized


# --------------------------------------------------------------------------------------
# Materialization declaration.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Materialization:
    """A caller's complete declaration of when and for whom a DataModel must compute.

    ``output_dataset_id`` is a caller semantic selection binding this materialization's rows to
    a catalog dataset id; it is not an authority identity. ``evaluation_times`` and
    ``instruments`` are the complete, explicit universe the framework evaluates against — there
    is no inferred calendar or discovered universe.
    """

    output_dataset_id: str
    evaluation_times: tuple[datetime, ...]
    instruments: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "output_dataset_id", _identifier(self.output_dataset_id, name="output_dataset_id")
        )
        object.__setattr__(
            self,
            "evaluation_times",
            _strictly_increasing_instants(self.evaluation_times, name="evaluation_times"),
        )
        object.__setattr__(
            self, "instruments", _unique_identifiers(self.instruments, name="instruments")
        )


# --------------------------------------------------------------------------------------
# Materialization result view.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializationInvocation:
    """One frozen DataModel evaluation and the semantic rows it produced.

    ``rows`` are exactly the ``authoring.DerivedRow`` values the model returned for this
    evaluation time; the framework neither adds nor removes rows here. A row's instrument must be
    unique within this invocation — a model cannot emit two rows for the same instrument at the
    same evaluation time.
    """

    evaluation_time: datetime
    rows: tuple[DerivedRow, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluation_time", _tz_aware(self.evaluation_time, name="evaluation_time")
        )
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, DerivedRow) for row in self.rows
        ):
            raise TypeError("rows must be a tuple of authoring.DerivedRow")
        instrument_ids = tuple(row.instrument_id for row in self.rows)
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("rows must not repeat an instrument_id within one evaluation time")


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializationResult:
    """A completed materialization's ordered, immutable evaluation record.

    ``invocations`` carries exactly one entry per evaluated instant, ordered strictly by
    ``evaluation_time``. This is a result view, not a store handle: it carries no fingerprint,
    provenance, or catalog reference, which stay framework-internal.
    """

    output_dataset_id: str
    invocations: tuple[MaterializationInvocation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "output_dataset_id", _identifier(self.output_dataset_id, name="output_dataset_id")
        )
        if not isinstance(self.invocations, tuple) or any(
            not isinstance(invocation, MaterializationInvocation) for invocation in self.invocations
        ):
            raise TypeError("invocations must be a tuple of MaterializationInvocation")
        if not self.invocations:
            raise ValueError("invocations must contain at least one entry")
        instants = tuple(invocation.evaluation_time for invocation in self.invocations)
        for earlier, later in pairwise(instants):
            if later <= earlier:
                raise ValueError("invocations must be strictly ordered by evaluation_time")
