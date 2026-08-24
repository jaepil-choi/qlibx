"""Agent-first extension authoring/read/result contracts.

The sole public home for what an author subclasses (``DataModel``, ``StrategyModel``,
``Constraint``), receives (``DataCall``, ``StrategyCall``, ``ConstraintCall``,
``Observation``, ``EconomicAccountView``, ``DeclaredAccountHistory``, ``ConstraintBounds``),
and returns (``DerivedRow``, ``StrategyResult``, ``ConstraintFinding``).

Every public declaration here is a frozen, slotted, keyword-only value unless shown
otherwise by the approved algebra (``Observation`` is positional; ``DataCall``,
``StrategyCall``, ``DataModel``, ``StrategyModel``, and ``Constraint`` are abstract
call/extension contracts, not values). Constructors reject duplicate names, empty
identifiers, naive datetimes, non-finite ``Decimal`` values, and author-supplied
framework-envelope fields. Incoming mappings are copied into read-only sorted views;
incoming sequences become detached tuples.

This module is pure algebra: it declares contracts only. No runtime adapter, store,
catalog, or Flow wiring lives here.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.timestamps import at_local, require_tz_aware, shift_calendar
from vqapr.portfolio.budgets import Budget, PortfolioDirection

__all__ = (
    "AccountHistoryInput",
    "CalendarLookback",
    "Constraint",
    "ConstraintBounds",
    "ConstraintCall",
    "ConstraintFinding",
    "DataCall",
    "DataModel",
    "DatasetInput",
    "DeclaredAccountHistory",
    "DerivedRow",
    "DiagnosticTable",
    "EconomicAccountView",
    "Hold",
    "Observation",
    "Output",
    "Rebalance",
    "RowsLookback",
    "StrategyCall",
    "StrategyModel",
    "StrategyResult",
)


# --------------------------------------------------------------------------------------
# Shared validation helpers (implementation detail; not part of the public algebra).
# --------------------------------------------------------------------------------------

_ROW_RESERVED_FIELDS = frozenset({"available_at", "instrument"})
"""Reserved because `ModelWindow`/`Observation` rows already carry them as named fields."""

_ENVELOPE_RESERVED_FIELDS = frozenset(
    {
        "observed_at",
        "producer",
        "stage",
        "event_time",
        "sequence",
        "source_refs",
        "source_references",
        "lineage",
        "account_version",
        "version",
        "state_ref",
        "state_reference",
        "constraint_id",
        "correlation_id",
    }
)
"""Reserved because the framework stamps these identity/provenance facts itself."""

_HISTORY_ACCOUNT_FIELDS = ("nav", "cash")
_HISTORY_INSTRUMENT_FIELDS = ("quantity", "price", "observed_at")
_HISTORY_FIELDS = frozenset(_HISTORY_ACCOUNT_FIELDS) | frozenset(_HISTORY_INSTRUMENT_FIELDS)


def _finite_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _tz_aware(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    return require_tz_aware(value, name=name)


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


def _reject_reserved(names: Sequence[str], reserved: frozenset[str], *, name: str) -> None:
    collided = sorted(set(names) & reserved)
    if collided:
        raise ValueError(f"{name} must not use framework-reserved names: {collided}")


def _scalar(value: object, *, name: str) -> object:
    """Validate one portable value: finite float/Decimal, tz-aware datetime, else as-is."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} float values must be finite")
        return value
    if isinstance(value, Decimal):
        return _finite_decimal(value, name=name)
    if isinstance(value, datetime):
        return _tz_aware(value, name=name)
    if isinstance(value, date):
        return value
    raise TypeError(f"{name} values must be portable scalars; got {type(value).__name__}")


def _copy_values(
    values: object, *, name: str, reserved: frozenset[str] = frozenset()
) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or any(char.isspace() for char in key):
            raise ValueError(f"{name} keys must be non-empty strings without whitespace")
        normalized[key] = _scalar(value, name=f"{name}[{key!r}]")
    if reserved:
        _reject_reserved(tuple(normalized), reserved, name=name)
    return MappingProxyType(dict(sorted(normalized.items())))


def _copy_weights(values: object, *, name: str) -> Mapping[str, Decimal]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, Decimal] = {}
    for key, value in values.items():
        instrument_id = _identifier(key, name=f"{name} key")
        normalized[instrument_id] = _finite_decimal(value, name=f"{name}[{instrument_id!r}]")
    return MappingProxyType(dict(sorted(normalized.items())))


def _normalize_state(value: object) -> object:
    """Return a detached, strict-JSON-shaped copy of one call/decision state value.

    `previous_state`/`next_state` are the only permitted cross-callback author state
    (approved algebra), so they are restricted to strict JSON so replay never depends on
    an object identity the framework cannot serialize.
    """
    active: set[int] = set()

    def visit(item: object) -> object:
        if item is None or isinstance(item, (bool, str, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("state floats must be finite")
            return item
        if isinstance(item, list):
            identity = id(item)
            if identity in active:
                raise ValueError("state must not contain cycles")
            active.add(identity)
            try:
                return [visit(child) for child in item]
            finally:
                active.discard(identity)
        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise ValueError("state must not contain cycles")
            if any(not isinstance(key, str) for key in item):
                raise TypeError("state object keys must be strings")
            active.add(identity)
            try:
                return {key: visit(child) for key, child in item.items()}
            finally:
                active.discard(identity)
        raise TypeError(f"state must contain strict JSON values; got {type(item).__name__}")

    return visit(value)


# --------------------------------------------------------------------------------------
# Lookback declarations.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RowsLookback:
    """A past-only window of the N most recent rows per instrument."""

    rows: int

    def __post_init__(self) -> None:
        if not isinstance(self.rows, int) or isinstance(self.rows, bool):
            raise TypeError("rows must be an integer")
        if self.rows <= 0:
            raise ValueError("rows must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class CalendarLookback:
    """A past-only window bounded by a calendar amount in a declared IANA timezone."""

    years: int = 0
    months: int = 0
    days: int = 0
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        for name, value in (("years", self.years), ("months", self.months), ("days", self.days)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.years == self.months == self.days == 0:
            raise ValueError("calendar lookback requires at least one positive amount")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        # Reject an unknown zone eagerly, at declaration time; a bad zone must fail
        # before any callback runs rather than the first time it is used.
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from error

    def lower_bound(self, evaluation_time: datetime) -> datetime:
        """Return the clamped local calendar date at 00:00 in this lookback's timezone."""
        current = _tz_aware(evaluation_time, name="evaluation_time").astimezone(
            ZoneInfo(self.timezone)
        )
        shifted = shift_calendar(current, years=-self.years, months=-self.months, days=-self.days)
        return at_local(shifted.date(), datetime.min.time(), self.timezone)


type Lookback = RowsLookback | CalendarLookback


# --------------------------------------------------------------------------------------
# DataModel algebra.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetInput:
    """One declared, aliasable read of a registered dataset."""

    dataset_id: str
    fields: tuple[str, ...]
    lookback: RowsLookback | CalendarLookback

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _identifier(self.dataset_id, name="dataset_id"))
        fields = _unique_identifiers(self.fields, name="fields")
        _reject_reserved(fields, _ROW_RESERVED_FIELDS, name="fields")
        object.__setattr__(self, "fields", fields)
        if not isinstance(self.lookback, (RowsLookback, CalendarLookback)):
            raise TypeError("lookback must be a RowsLookback or CalendarLookback")


@dataclass(frozen=True, slots=True)
class Observation:
    """One PIT row returned from a declared, aliased read."""

    instrument_id: str
    available_at: datetime
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument_id", _identifier(self.instrument_id, name="instrument_id")
        )
        object.__setattr__(self, "available_at", _tz_aware(self.available_at, name="available_at"))
        object.__setattr__(self, "values", _copy_values(self.values, name="values"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Output:
    """A DataModel's declared semantic output schema."""

    semantic_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        fields = _unique_identifiers(self.semantic_fields, name="semantic_fields")
        _reject_reserved(fields, _ROW_RESERVED_FIELDS, name="semantic_fields")
        object.__setattr__(self, "semantic_fields", fields)


@dataclass(frozen=True, slots=True, kw_only=True)
class DerivedRow:
    """One semantic row a DataModel computed for one instrument."""

    instrument_id: str
    values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument_id", _identifier(self.instrument_id, name="instrument_id")
        )
        object.__setattr__(
            self,
            "values",
            _copy_values(self.values, name="values", reserved=_ROW_RESERVED_FIELDS),
        )


class DataCall(ABC):
    """The complete, bounded capability surface for one DataModel invocation."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this invocation computes for."""

    @abstractmethod
    def read(self, alias: str) -> tuple[Observation, ...]:
        """Return PIT observations for one alias declared in `DataModel.inputs()`."""


class DataModel(ABC):
    """User extension contract: declared PIT reads in, semantic rows out."""

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this model performs. Empty by default."""
        return {}

    @abstractmethod
    def output(self) -> Output:
        """Declare this model's semantic output schema."""

    @abstractmethod
    def compute(self, call: DataCall) -> tuple[DerivedRow, ...]:
        """Compute semantic rows for one frozen evaluation time."""


# --------------------------------------------------------------------------------------
# StrategyModel algebra.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class DiagnosticTable:
    """Preparation-time schema for one table of StrategyModel diagnostics."""

    table_id: str
    semantic_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "table_id", _identifier(self.table_id, name="table_id"))
        fields = _unique_identifiers(self.semantic_fields, name="semantic_fields")
        _reject_reserved(fields, _ENVELOPE_RESERVED_FIELDS, name="semantic_fields")
        object.__setattr__(self, "semantic_fields", fields)


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountHistoryInput:
    """A StrategyModel's declaration of which committed account history it reads."""

    fields: tuple[Literal["nav", "cash", "quantity", "price", "observed_at"], ...]
    lookback: RowsLookback

    def __post_init__(self) -> None:
        fields = _unique_identifiers(self.fields, name="fields")
        unknown = sorted(set(fields) - _HISTORY_FIELDS)
        if unknown:
            raise ValueError(
                f"unknown account history fields {unknown}; "
                f"account series are {_HISTORY_ACCOUNT_FIELDS} and "
                f"instrument panels are {_HISTORY_INSTRUMENT_FIELDS}"
            )
        object.__setattr__(self, "fields", fields)
        if not isinstance(self.lookback, RowsLookback):
            raise TypeError("lookback must be a RowsLookback")


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicAccountView:
    """A bounded, immutable snapshot of the committed Account for one callback."""

    cash: Decimal
    positions: Mapping[str, Decimal]
    nav: Decimal | None
    nav_observed_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", _finite_decimal(self.cash, name="cash"))
        object.__setattr__(self, "positions", _copy_weights(self.positions, name="positions"))
        if (self.nav is None) != (self.nav_observed_at is None):
            raise ValueError("nav and nav_observed_at must both be set or both be None")
        if self.nav is not None:
            object.__setattr__(self, "nav", _finite_decimal(self.nav, name="nav"))
            object.__setattr__(
                self,
                "nav_observed_at",
                _tz_aware(self.nav_observed_at, name="nav_observed_at"),
            )

    def quantity(self, instrument_id: str) -> Decimal:
        """The current quantity held, or `Decimal(0)` for a valid absent instrument."""
        checked = _identifier(instrument_id, name="instrument_id")
        return self.positions.get(checked, Decimal(0))


class DeclaredAccountHistory:
    """A bounded, read-only, oldest-first projection of committed account history.

    Built by the framework from exactly one `AccountHistoryInput` declaration (or none).
    Reading a field that was not declared, or reading it through the wrong accessor,
    raises rather than silently returning nothing.
    """

    __slots__ = ("_fields", "_lookback", "_panel", "_series")

    def __init__(
        self,
        *,
        fields: tuple[str, ...] = (),
        lookback: RowsLookback | None = None,
        series: Mapping[str, Sequence[Decimal]] | None = None,
        panel: Mapping[str, Mapping[str, Sequence[object]]] | None = None,
    ) -> None:
        if fields and lookback is None:
            raise ValueError("declared fields require a lookback")
        resolved_lookback = lookback if lookback is not None else RowsLookback(rows=1)
        if not isinstance(resolved_lookback, RowsLookback):
            raise TypeError("lookback must be a RowsLookback")
        normalized_fields = tuple(fields)
        if normalized_fields:
            normalized_fields = _unique_identifiers(normalized_fields, name="fields")
            unknown = sorted(set(normalized_fields) - _HISTORY_FIELDS)
            if unknown:
                raise ValueError(f"unknown account history fields {unknown}")

        rows = resolved_lookback.rows
        series_source = series or {}
        panel_source = panel or {}

        built_series: dict[str, tuple[Decimal, ...]] = {}
        for field in _HISTORY_ACCOUNT_FIELDS:
            if field not in normalized_fields:
                continue
            values = tuple(series_source.get(field, ()))[-rows:]
            built_series[field] = tuple(
                _finite_decimal(value, name=f"{field} history value") for value in values
            )

        built_panel: dict[str, Mapping[str, tuple[object, ...]]] = {}
        for field in _HISTORY_INSTRUMENT_FIELDS:
            if field not in normalized_fields:
                continue
            source = panel_source.get(field, {})
            if not isinstance(source, Mapping):
                raise TypeError(f"{field} panel must be a mapping")
            instrument_series: dict[str, tuple[object, ...]] = {}
            for instrument_id, values in source.items():
                checked_instrument = _identifier(instrument_id, name="instrument_id")
                trimmed = tuple(values)[-rows:]
                if field == "observed_at":
                    checked_values: tuple[object, ...] = tuple(
                        _tz_aware(value, name="observed_at") for value in trimmed
                    )
                else:
                    checked_values = tuple(
                        _finite_decimal(value, name=f"{field} panel value") for value in trimmed
                    )
                instrument_series[checked_instrument] = checked_values
            built_panel[field] = MappingProxyType(dict(sorted(instrument_series.items())))

        self._fields = normalized_fields
        self._lookback = resolved_lookback
        self._series = MappingProxyType(built_series)
        self._panel = MappingProxyType(built_panel)

    @property
    def fields(self) -> tuple[str, ...]:
        return self._fields

    @property
    def lookback(self) -> RowsLookback:
        return self._lookback

    def _require_declared(self, field: str, allowed: tuple[str, ...]) -> None:
        if field not in allowed:
            raise KeyError(f"{field!r} is not available through this accessor")
        if field not in self._fields:
            raise KeyError(
                f"{field!r} was not declared in this StrategyModel's AccountHistoryInput; "
                "a Model reads only what it declared"
            )

    def series(self, field: Literal["nav", "cash"]) -> tuple[Decimal, ...]:
        self._require_declared(field, _HISTORY_ACCOUNT_FIELDS)
        return self._series[field]

    def panel(
        self, field: Literal["quantity", "price", "observed_at"]
    ) -> Mapping[str, tuple[object, ...]]:
        self._require_declared(field, _HISTORY_INSTRUMENT_FIELDS)
        return self._panel[field]


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintBounds:
    """Frozen per-instrument target-weight bounds merged from every projected Constraint."""

    lower_weights: Mapping[str, Decimal]
    upper_weights: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        lower = _copy_weights(self.lower_weights, name="lower_weights")
        upper = _copy_weights(self.upper_weights, name="upper_weights")
        if set(lower) != set(upper):
            raise ValueError("lower_weights and upper_weights must cover the same instruments")
        for instrument_id in lower:
            if lower[instrument_id] > upper[instrument_id]:
                raise ValueError("lower_weights must not exceed upper_weights")
        object.__setattr__(self, "lower_weights", lower)
        object.__setattr__(self, "upper_weights", upper)

    def lower_weight(self, instrument_id: str) -> Decimal:
        checked = _identifier(instrument_id, name="instrument_id")
        return self.lower_weights[checked]

    def upper_weight(self, instrument_id: str) -> Decimal:
        checked = _identifier(instrument_id, name="instrument_id")
        return self.upper_weights[checked]


@dataclass(frozen=True, slots=True, kw_only=True)
class Hold:
    """A Strategy decision that intentionally emits no order."""

    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _identifier(self.reason, name="reason"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Rebalance:
    """A Strategy decision naming one complete desired portfolio."""

    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    budget: Budget

    def __post_init__(self) -> None:
        weights = _copy_weights(self.target_weights, name="target_weights")
        object.__setattr__(self, "target_weights", weights)
        cash = _finite_decimal(self.cash_weight, name="cash_weight")
        object.__setattr__(self, "cash_weight", cash)
        if not isinstance(self.budget, Budget):
            raise TypeError("budget must be a Budget")
        if not self.budget.validates_cash(cash):
            raise ValueError("cash_weight is outside the declared budget")
        if weights:
            if any(not self.budget.validates_target(value) for value in weights.values()):
                raise ValueError("target_weights are outside the declared budget bounds")
            if self.budget.direction is PortfolioDirection.LONG_ONLY and any(
                value < 0 for value in weights.values()
            ):
                raise ValueError("long_only budgets forbid negative target_weights")
            if sum(weights.values(), Decimal(0)) + cash != 1:
                raise ValueError("target_weights plus cash_weight must equal one")
        elif cash != 1:
            raise ValueError("an empty complete position set requires cash_weight equal to one")


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyResult:
    """A StrategyModel's complete, immutable callback result."""

    decision: Hold | Rebalance
    next_state: object
    diagnostics: Mapping[str, tuple[Mapping[str, object], ...]]

    def __post_init__(self) -> None:
        if not isinstance(self.decision, (Hold, Rebalance)):
            raise TypeError("decision must be a Hold or Rebalance")
        object.__setattr__(self, "next_state", _normalize_state(self.next_state))
        if not isinstance(self.diagnostics, Mapping):
            raise TypeError("diagnostics must be a mapping")
        normalized: dict[str, tuple[Mapping[str, object], ...]] = {}
        for table_id, rows in self.diagnostics.items():
            checked_table_id = _identifier(table_id, name="diagnostics table_id")
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
                raise TypeError(f"diagnostics[{checked_table_id!r}] must be a sequence of rows")
            normalized[checked_table_id] = tuple(
                _copy_values(
                    row,
                    name=f"diagnostics[{checked_table_id!r}] row",
                    reserved=_ENVELOPE_RESERVED_FIELDS,
                )
                for row in rows
            )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(sorted(normalized.items()))))


class StrategyCall(ABC):
    """The complete, bounded capability surface for one Strategy occurrence."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this occurrence decides at."""

    @property
    @abstractmethod
    def account(self) -> EconomicAccountView:
        """The committed Account, bounded to cash/positions/latest NAV."""

    @property
    @abstractmethod
    def previous_state(self) -> object:
        """The strict-JSON state this Strategy returned from its last accepted callback."""

    @property
    @abstractmethod
    def account_history(self) -> DeclaredAccountHistory:
        """Committed account history, bounded by this Strategy's own declaration."""

    @property
    @abstractmethod
    def constraint_bounds(self) -> ConstraintBounds:
        """The merged bounds projected from every registered Constraint."""

    @abstractmethod
    def read(self, alias: str) -> tuple[Observation, ...]:
        """Return PIT observations for one alias declared in `StrategyModel.inputs()`."""


class StrategyModel(ABC):
    """User extension whose only cross-callback state is `previous_state`/`next_state`."""

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this Strategy performs. Empty by default."""
        return {}

    def account_history(self) -> AccountHistoryInput | None:
        """Declare committed account history reads. `None` declares none are read."""
        return None

    def diagnostics(self) -> tuple[DiagnosticTable, ...]:
        """Declare every diagnostic table this Strategy may emit. Empty by default."""
        return ()

    @abstractmethod
    def decide(self, call: StrategyCall) -> StrategyResult:
        """Return this occurrence's complete Hold/Rebalance decision."""


# --------------------------------------------------------------------------------------
# Constraint algebra.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintCall:
    """The complete, bounded capability surface for one Constraint invocation."""

    evaluation_time: datetime
    account: EconomicAccountView
    instruments: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluation_time", _tz_aware(self.evaluation_time, name="evaluation_time")
        )
        if not isinstance(self.account, EconomicAccountView):
            raise TypeError("account must be an EconomicAccountView")
        instruments = _unique_identifiers(self.instruments, name="instruments")
        object.__setattr__(self, "instruments", instruments)

    def read(self, alias: str) -> tuple[Observation, ...]:
        """Return PIT observations for one alias declared in `Constraint.inputs()`.

        This pure-contract value carries no runtime store; the framework supplies a
        concrete, PIT-bound `ConstraintCall` at invocation time.
        """
        _identifier(alias, name="alias")
        raise NotImplementedError(
            "ConstraintCall.read requires a framework-provided runtime adapter"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintFinding:
    """One Constraint's complete, immutable result for one economic observation."""

    passed: bool
    measured: Decimal
    bound: Decimal
    excess: Decimal
    details: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a bool")
        object.__setattr__(self, "measured", _finite_decimal(self.measured, name="measured"))
        object.__setattr__(self, "bound", _finite_decimal(self.bound, name="bound"))
        object.__setattr__(self, "excess", _finite_decimal(self.excess, name="excess"))
        details = _copy_values(self.details, name="details", reserved=_ENVELOPE_RESERVED_FIELDS)
        if len(details) > 32:
            raise ValueError("details must be bounded to 32 semantic keys")
        object.__setattr__(self, "details", details)


class Constraint(ABC):
    """User extension contract: an immutable economic predicate over the account."""

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this Constraint performs. Empty by default."""
        return {}

    @abstractmethod
    def project(self, call: ConstraintCall) -> ConstraintBounds:
        """Project deterministic per-instrument bounds for the current PIT cutoff."""

    @abstractmethod
    def validate(self, decision: Rebalance, bounds: ConstraintBounds) -> ConstraintFinding:
        """Measure one complete intended Rebalance against the merged bounds."""

    @abstractmethod
    def monitor(self, call: ConstraintCall, bounds: ConstraintBounds) -> ConstraintFinding:
        """Measure the committed account against bounds projected at a monitoring cutoff."""
