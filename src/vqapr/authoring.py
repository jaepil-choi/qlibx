"""Agent-first extension authoring/read/result contracts.

The sole public home for what an author subclasses (``Component`` and its roles ``DataModel``,
``StrategyModel``, ``Constraint``), receives (``DataCall``, ``StrategyCall``, ``ConstraintCall``,
``PanelWindow``, ``Observation``, ``EconomicAccountView``, ``AccountHistory``,
``ConstraintBounds``),
and returns (``Rows``, ``Hold``/``Rebalance``, ``ConstraintFinding``).

Every public declaration here is a frozen, keyword-only value unless shown otherwise by the
approved algebra (``Observation`` is positional; ``DataCall``, ``StrategyCall``, ``DataModel``,
``StrategyModel``, and ``Constraint`` are abstract call/extension contracts, not values). What an
author constructs and hands to the engine -- ``DatasetInput``, ``AccountHistoryInput``,
``ConstraintBounds``, ``Hold``, ``Rebalance``, ``ConstraintFinding`` -- is a strict pydantic
model (owner ruling 2026-09-08): a wrong type is refused rather than coerced, and the refusal is
a ``pydantic.ValidationError``, which is a ``ValueError``. Constructors reject duplicate names,
empty identifiers, naive datetimes, non-finite ``Decimal`` values, and author-supplied
framework-envelope fields. Incoming mappings are copied into read-only sorted views; incoming
sequences become detached tuples.

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
from typing import BinaryIO, Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from vqapr.account.history import ACCOUNT_FIELDS, INSTRUMENT_FIELDS, AccountHistory
from vqapr.data.lookback import CalendarLookback, InstantsLookback, Lookback, RowsLookback
from vqapr.data.panel import PanelWindow
from vqapr.data.requirements import DataRequirement
from vqapr.domain.shapes import CrossSection, Observation, Rows
from vqapr.domain.values import ModelMemory, require_tz_aware
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.optimize import QUANTUM
from vqapr.portfolio.weighting import rescale

__all__ = (
    "AccountHistory",
    "AccountHistoryInput",
    "CalendarLookback",
    "Component",
    "Constraint",
    "ConstraintBounds",
    "ConstraintCall",
    "ConstraintFinding",
    "DataCall",
    "DataModel",
    "DatasetInput",
    "EconomicAccountView",
    "Hold",
    "InstantsLookback",
    "Observation",
    "PanelWindow",
    "Rebalance",
    "RowsLookback",
    "StrategyCall",
    "StrategyModel",
    "TableSpec",
    "requirements_for",
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

_HISTORY_FIELDS = frozenset(ACCOUNT_FIELDS) | frozenset(INSTRUMENT_FIELDS)


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


def _copy_weights(values: object, *, name: str) -> CrossSection[Decimal]:
    """A validated, read-only cross-section of `Decimal` per instrument (record `183`).

    Every weight-shaped value on this surface -- a target, a bound, a position, a marked value
    -- is one instant's instrument -> value, and that shape has a name now. It is still a
    `Mapping`, so an author's `weights["A"]` and `weights.items()` are unchanged.
    """
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, Decimal] = {}
    for key, value in values.items():
        instrument_id = _identifier(key, name=f"{name} key")
        normalized[instrument_id] = _finite_decimal(value, name=f"{name}[{instrument_id!r}]")
    return CrossSection._trusted(dict(sorted(normalized.items())))


# The one configuration every authored value shares. Strict, so an `int` where a `Decimal` was
# declared is refused rather than widened; `arbitrary_types_allowed` because a weight-shaped
# field is stored as the `CrossSection` `_copy_weights` builds, which is the package's own type.
_VALUE_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True)


class DatasetInput(BaseModel):
    """One declared, aliasable read of a registered dataset."""

    model_config = _VALUE_CONFIG

    dataset_id: str
    fields: tuple[str, ...]
    lookback: Lookback

    @field_validator("dataset_id")
    @classmethod
    def _dataset_id(cls, value: str) -> str:
        return _identifier(value, name="dataset_id")

    @field_validator("fields", mode="before")
    @classmethod
    def _fields(cls, value: object) -> tuple[str, ...]:
        # Before, not after: a list of names is accepted and becomes the detached tuple.
        fields = _unique_identifiers(value, name="fields")
        _reject_reserved(fields, _ROW_RESERVED_FIELDS, name="fields")
        return fields


# `Observation` -- one row of the long shape -- is `vqapr.domain.shapes.Observation` since record
# `183`, re-exported here because it is what an author receives from `call.rows(alias)`.


class DataCall(ABC):
    """The complete, bounded capability surface for one DataModel invocation."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this invocation computes for."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `DataModel.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `DataModel.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """


def requirements_for(declaration: DatasetInput) -> tuple[DataRequirement, ...]:
    """One declared alias, as the engine's requirements: one per field (`docs/issues/049`).

    The single place the fan-out is written. Every role that declares reads derives its
    requirements through here, so a Model cannot declare one thing to preflight and read another
    at the callback.
    """
    if not isinstance(declaration, DatasetInput):
        raise TypeError("declaration must be an authoring.DatasetInput")
    return tuple(
        DataRequirement.of(declaration.dataset_id, field, lookback=declaration.lookback)
        for field in declaration.fields
    )


class Component(ABC):  # noqa: B024 - concrete roles add their abstract callbacks
    """An object the engine calls back on an event, with that event's time.

    **This is the one thing the four authored kinds are** (owner ruling, 2026-09-08; the review in
    `docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md`). A DataModel,
    a StrategyModel, a Constraint and an Exchange each *declare what they read* (`inputs()`), are
    *handed a bounded view of it at one instant* (their `Call`), *carry memory between callbacks*
    (`memory`), and *return one judgment* -- rows, a decision, bounds or a finding, fills. What
    differs between them is the event they answer and what their role is additionally handed:
    the account for a Strategy, the account and the projected bounds for a Constraint's
    `monitor`, the order batch for an Exchange. That list is the whole difference, and it is
    stated on each role rather than here.

    **The author's base class, so it lives on the author's surface.** An engine-side `models/`
    package once held it while `DataModel` and `StrategyModel` were defined here without it, so
    the two authored kinds shared no ancestor and an author who wrote against this module got a
    class the loader could not run (`docs/issues/036`). `Constraint` then stood outside the base
    for a reason that turned out to be wrong -- *"a constraint is a stateless predicate"* -- and
    copied `inputs()` and `requirements()` verbatim to get the same declaration. A rule such as
    *"out after three breaches"* needs to count, and counting is memory; the premise was the
    defect, not the copy.

    **Every role declares its reads here, in one place and one shape.** A first-time user once had
    to build a ten-row table of the ways authoring two roles differed; the owner ruled that
    *"the size of the current difference is itself the defect"*. `inputs()` is the one shape.

    `memory` is the small strict-JSON state a component carries between callbacks. The engine
    restores it before each callback and commits what the callback left, atomically with the
    callback's other effects; a fresh instance with its memory restored must decide the same. A
    DataModel that uses it becomes order-dependent (architecture 4.4); one that does not may be
    computed in any order. The engine relies on the same instance living for the whole run: it
    never builds one per callback.

    `Exchange` is not yet a subclass: it still reads through its own declaration and receives
    its inputs as arguments rather than a `Call`. It joins when the execution table becomes a
    registered dataset (campaign M4).
    """

    memory: ModelMemory = None

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this component performs. Empty by default.

        The alias is the author's own name for a read, and it is what `read(alias)` takes on the
        call. Declaring nothing is legitimate: a Model may derive its values from memory alone.

        **Evaluated before `memory` exists.** Registration and preflight call this on a fresh
        instance, before any `initial_model_memory` is applied or a snapshot restored, and the
        run refuses a model whose requirements then differ from the frozen ones. So the reads
        cannot depend on memory or on a run's per-model settings (`docs/issues/065`): a family
        of settings that changes WHAT is read is a family of registered components.

        Declaring nothing is legitimate and is what the shipped `NoShort` constraint does: a rule
        about a weight's sign opens no data. The loader used to require a non-empty
        `requirements()` from a Constraint, which made the one shipped constraint that needs no
        data the one shape it could not accept.
        """
        return {}

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Every observation requirement, derived from `inputs()` rather than written twice."""
        return tuple(
            requirement
            for declaration in self.inputs().values()
            for requirement in requirements_for(declaration)
        )


class DataModel(Component):
    """A Component whose result is values: data in, a dataset out, and no account in between.

    **What makes it a DataModel is that nothing it returns is executed** (architecture 4.4). It
    sees no account, passes through no venue, and its rows become a registered dataset that any
    number of runs may then read. The other role, `StrategyModel`, differs by exactly that.

    **A row is a dict**: `{"instrument": name, "<field>": value, ...}`, one per instrument, with
    the fields the materialization declared and nothing the package owns -- `available_at` is
    stamped by the framework, and a row that tries to carry one is refused. The shape of the
    dataset being produced is a declaration and lives with the materialization; what the model
    does is compute, and it says nothing about the schema twice.

    Reads arrive as `Observation` records through `call.read(alias)`, the same verb every role
    uses.
    """

    @abstractmethod
    def compute(self, call: DataCall) -> Rows:
        """Compute this instant's rows from the declared reads. One dict per instrument."""


# --------------------------------------------------------------------------------------
# StrategyModel algebra.
# --------------------------------------------------------------------------------------


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


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicAccountView:
    """A bounded, immutable snapshot of the committed Account for one callback.

    **`values` was missing, and its absence made a whole rule shape inexpressible.** This view
    carried `positions` -- quantities -- plus one aggregate `nav`, and a weight is
    `value / nav`. Quantities cannot become weights without prices, so no weight-based rule
    could be written against this type at all, which is what both shipped Constraints are. The
    gap went unnoticed because monitoring ran on the engine's `MarkBatch` instead, on the other
    side of the surface split this contract exists to remove.

    So `values` is the marked value per instrument. Quantities stay, because a rule about lot
    sizes or a short position asks about quantity and would otherwise have to divide back out.

    **`values` is `None` where the framework has no marks to offer, and that is not zero.** A
    Strategy callback fires before the occurrence it decides for is executed or valued, so what
    it sees is the previous valuation's marks -- committed, and therefore point-in-time -- and
    before the first valuation there are none; a monitoring Constraint fires against a marked
    account and always has them. An empty mapping would make `weight()` return a confident zero
    for every name and every weight rule report `passed`, so absence refuses instead.
    """

    cash: Decimal
    positions: Mapping[str, Decimal]
    nav: Decimal | None
    nav_observed_at: datetime | None
    values: Mapping[str, Decimal] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cash", _finite_decimal(self.cash, name="cash"))
        object.__setattr__(self, "positions", _copy_weights(self.positions, name="positions"))
        if self.values is not None:
            object.__setattr__(self, "values", _copy_weights(self.values, name="values"))
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

    def value(self, instrument_id: str) -> Decimal:
        """The marked value held, or `Decimal(0)` for a valid absent instrument."""
        checked = _identifier(instrument_id, name="instrument_id")
        if self.values is None:
            raise ValueError(
                "this view carries no marked values; it was built at an instant the framework "
                "had no marks to offer, and a zero here would be an answer rather than a gap"
            )
        return self.values.get(checked, Decimal(0))

    def weight(self, instrument_id: str) -> Decimal:
        """This instrument's share of NAV, signed.

        The one derivation every weight-based rule needs, written once here rather than in each
        Constraint that would otherwise divide by a NAV it had to reassemble. Refuses rather than
        returning zero when NAV is absent or zero: a weight against no NAV is not a small number,
        it is an undefined one, and a rule that silently measured zero would report `passed`.
        """
        if self.nav is None or not self.nav:
            raise ValueError(
                "weight is undefined without a non-zero nav; this view was built at an instant "
                "the account had not been marked"
            )
        return self.value(instrument_id) / self.nav

    def weights(self) -> CrossSection[Decimal]:
        """Every marked name's share of NAV, signed. The whole book as a weight vector."""
        if self.values is None:
            raise ValueError(
                "this view carries no marked values; it was built at an instant the framework "
                "had no marks to offer, and an empty book here would be an answer rather than a gap"
            )
        return CrossSection._trusted(
            {instrument_id: self.weight(instrument_id) for instrument_id in sorted(self.values)},
            self.nav_observed_at,
        )


class ConstraintBounds(BaseModel):
    """Frozen per-instrument target-weight bounds merged from every projected Constraint.

    Declared as any `Mapping[str, Decimal]`; held as the read-only `CrossSection` it validates
    into, so `bounds.lower_weights["A"]` reads the way it always did.
    """

    model_config = _VALUE_CONFIG

    lower_weights: CrossSection[Decimal]
    upper_weights: CrossSection[Decimal]

    def __init__(
        self, *, lower_weights: Mapping[str, Decimal], upper_weights: Mapping[str, Decimal]
    ) -> None:
        # The door's own signature: what an author passes is any mapping, what the field holds
        # is the cross-section it validated into. Written out so a type checker sees the former.
        super().__init__(lower_weights=lower_weights, upper_weights=upper_weights)

    @field_validator("lower_weights", "upper_weights", mode="before")
    @classmethod
    def _weights(cls, value: object, info: ValidationInfo) -> CrossSection[Decimal]:
        return _copy_weights(value, name=str(info.field_name))

    @model_validator(mode="after")
    def _same_names_ordered(self) -> Self:
        lower, upper = self.lower_weights, self.upper_weights
        if set(lower) != set(upper):
            raise ValueError("lower_weights and upper_weights must cover the same instruments")
        for instrument_id in lower:
            if lower[instrument_id] > upper[instrument_id]:
                raise ValueError("lower_weights must not exceed upper_weights")
        return self

    def lower_weight(self, instrument_id: str) -> Decimal:
        checked = _identifier(instrument_id, name="instrument_id")
        return self.lower_weights[checked]

    def upper_weight(self, instrument_id: str) -> Decimal:
        checked = _identifier(instrument_id, name="instrument_id")
        return self.upper_weights[checked]

    def detached(self) -> ConstraintBounds:
        """A fresh value with no caller-owned mapping aliases.

        Validation already copies into read-only views, so this is defensive rather than
        load-bearing -- and it is kept because `StrategyModelContext` calls it on a value it did
        not construct, where "already copied" is an assumption about someone else's code.
        """
        return ConstraintBounds(
            lower_weights=self.lower_weights, upper_weights=self.upper_weights
        )


class Hold(BaseModel):
    """A Strategy decision that intentionally emits no order.

    **This is the engine's decline type as well as the author's.** It absorbed
    `models.strategy_model.NoDecision` in record `125`: the two were the same frozen one-field
    dataclass with two names, and the adapter's whole contribution was `NoDecision(hold.reason)`.

    `reason` is prose, not an identifier. It was validated with `_identifier` here, which rejects
    whitespace -- so `Hold(reason="no name scored above zero")` was refused while the engine's
    `NoDecision` accepted the identical string. Merging two types means merging two validations,
    and the looser one is the correct one: a reason a human reads should be allowed spaces.
    """

    model_config = _VALUE_CONFIG

    reason: str

    @field_validator("reason")
    @classmethod
    def _prose(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must be a non-empty string")
        return value


def _as_decimal(value: Decimal | int | float | str, *, name: str) -> Decimal:
    """One conviction as an exact Decimal.

    `Decimal(str(v))` for a float rather than `Decimal(v)`: a float64 `0.1` is not one tenth, and
    binding the binary expansion here would put the error into every weight downstream.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be a Decimal, int, float, or string")
    try:
        return Decimal(str(value))
    except ArithmeticError as invalid:
        raise ValueError(f"{name} must be a finite number; got {value!r}") from invalid


def _relative_side(
    declared: Mapping[str, Decimal | int | float | str] | None, *, name: str
) -> dict[str, Decimal]:
    """One side of the book as positive relative convictions.

    A short is declared by WHICH MAPPING it appears in, never by its sign, so `short={"A": 2}`
    means twice as short rather than half as long. Accepting a negative here would give one
    intention two spellings that disagree.
    """
    if declared is None:
        return {}
    if not isinstance(declared, Mapping):
        raise TypeError(f"{name} must be a mapping of instrument to relative weight")
    side: dict[str, Decimal] = {}
    for instrument, raw in declared.items():
        conviction = _as_decimal(raw, name=f"{name}[{instrument!r}]")
        if not conviction.is_finite():
            raise ValueError(f"{name}[{instrument!r}] must be finite")
        if conviction <= 0:
            raise ValueError(
                f"{name}[{instrument!r}] must be positive: a side is chosen by which mapping the "
                f"name appears in, not by the sign of its weight"
            )
        side[_identifier(instrument, name="instrument")] = conviction
    return side


_MAX_OFFENDERS = 5
"""How many offending weights a `Rebalance` refusal quotes; the rest are counted."""


def _offenders(weights: Mapping[str, Decimal]) -> str:
    """`name=value` for the first few offending weights, and a count of the rest.

    Bounded the way `Failure.examples` is bounded: a thousand-name book that misses a bound on
    every name should say so in one line, not in a thousand.
    """
    shown = [f"{name}={value}" for name, value in list(weights.items())[:_MAX_OFFENDERS]]
    rest = len(weights) - len(shown)
    return ", ".join(shown) + (f", and {rest} more" if rest > 0 else "")


class Rebalance(BaseModel):
    """A Strategy decision naming one complete desired portfolio.

    Three ways in, and the direct constructor is the last of them:

    - `Rebalance.of(long=, short=, invested=)` -- relative conviction per side, split evenly.
    - `Rebalance.signed(weights, gross=)` -- signed weights, split as the signal produced them.
    - `Rebalance(target_weights=, cash_weight=, budget=)` -- everything stated, nothing derived.

    Weights are validated **to the last digit**: `sum(target_weights) + cash_weight` must equal
    one exactly, and a value off by a single ulp is refused by the same invariant that catches a
    real mistake. That is why the two constructors exist, and why anyone building this directly
    should quantise and settle through `vqapr.portfolio.weighting.rescale` on the canonical grid
    `vqapr.portfolio.optimize.QUANTUM` rather than by hand (`docs/issues/075`).

    `target_weights` takes any `Mapping[str, Decimal]` and is held as the read-only
    `CrossSection` it validates into.
    """

    model_config = _VALUE_CONFIG

    target_weights: CrossSection[Decimal]
    cash_weight: Decimal
    budget: Budget

    def __init__(
        self, *, target_weights: Mapping[str, Decimal], cash_weight: Decimal, budget: Budget
    ) -> None:
        # The door's own signature: any mapping in, the validated cross-section held. Written
        # out so a type checker accepts the dict every author and both constructors pass.
        super().__init__(target_weights=target_weights, cash_weight=cash_weight, budget=budget)

    @classmethod
    def of(
        cls,
        *,
        long: Mapping[str, Decimal | int | float | str] | None = None,
        short: Mapping[str, Decimal | int | float | str] | None = None,
        invested: Decimal | int | float | str = 1,
    ) -> Rebalance:
        """Build a portfolio from RELATIVE conviction, letting the package do the arithmetic.

        The author says which names they like and how much they like them relative to each other.
        Everything that follows -- normalising each side, splitting the invested fraction between
        the sides, rounding onto the canonical grid, and making the whole thing add up with cash
        -- is arithmetic with exactly one right answer, and a research author who does it by hand
        is spending attention on bookkeeping instead of on the signal.

        `invested` is GROSS exposure **bounded to `0 < invested <= 1`**, so a dollar-neutral
        long/short book at `invested=1` puts the whole book to work and still nets to zero; its
        cash is 1. A short-only book's cash exceeds 1, because selling short raises cash. Cash is
        always the NET residual, never `1 - invested`.

        **The bound and the even split compose, and together they set the ceiling.** Two sides
        each take `invested / 2`, so `invested=1` on a signed book is 0.5 long and 0.5 short --
        not 1.0 and -1.0. The most this constructor can express is therefore half of a textbook
        $1-long/$1-short book, and a published SMB or HML series quoted at that scale is twice
        what comes out of here. Read a factor return built this way as half-scale, or double it
        before comparing.

        Neither the bound nor the split is an accounting invariant. A `Rebalance` with weights
        `+1/-1` and cash 1 satisfies every downstream invariant -- the signed budget admits
        positions in `[-1, 1]` and cash in `[-1, 2]` -- so the ceiling is this constructor's, not
        the account's. Build the `Rebalance` directly to go past it.

        Two sides are currently split evenly, so a 130/30 cannot be expressed through this
        constructor either. Stated rather than implied, because the even split is a choice and not
        a law. **`Rebalance.signed` is the constructor for a book the signal splits**: it takes
        signed weights, normalises them to a gross of your choosing, and leaves the long/short
        ratio exactly as the signal produced it.

        Doing it by hand is also where the errors live: the sum must land on one EXACTLY, and a
        weight that misses by a single ulp is refused by the same invariant that catches a real
        mistake. Relative weights cannot make that error, because the author never states a total.

        `invested` is the fraction of NAV to put to work; the remainder stays in cash. Passing a
        short book implies a signed budget, and a long-only book keeps `LONG_ONLY`, so the budget
        follows from what was actually asked for rather than being declared a second time.

        The two budgets this makes, as values: a long-only book gets targets in `[0, 1]` and cash
        in `[0, 1]`; a signed book gets targets in `[-1, 1]` and cash in `[-1, 2]`, the upper bound
        being 2 because selling short raises cash.

        Quantising and settling belong to `vqapr.portfolio.weighting.rescale`, which this calls
        (`docs/issues/075`). Each side lands EXACTLY on its target, on the canonical grid
        `QUANTUM`, with the rounding residual on that side's largest position.
        """
        longs = _relative_side(long, name="long")
        shorts = _relative_side(short, name="short")
        if not longs and not shorts:
            raise ValueError("a Rebalance needs at least one long or short name")

        # A name on both sides is a contradiction, not a netting instruction. Silently letting the
        # short overwrite the long drops a leg the author wrote, and the resulting book is not
        # what either mapping asked for.
        both = sorted(set(longs) & set(shorts))
        if both:
            raise ValueError(
                f"cannot be long and short the same name: {', '.join(both)}. "
                "Net them yourself and declare the side you actually want"
            )

        share = _as_decimal(invested, name="invested")
        if not 0 < share <= 1:
            raise ValueError(
                f"invested must be greater than zero and no greater than one; got {share}. "
                "It is GROSS exposure and both sides split it evenly, so the most a signed book "
                "can reach through this constructor is 0.5 long and 0.5 short. A textbook "
                "$1-long/$1-short book is twice that and cannot be expressed here -- build the "
                "Rebalance directly if you need it."
            )

        # Both sides present means the book is signed and each side takes half the invested
        # fraction. One side alone takes all of it. Quantised here because it becomes a side
        # TARGET below, and `rescale` refuses a target that is not itself on the grid -- weights
        # on a grid cannot sum to a total that is off it.
        sides = (bool(longs), bool(shorts))
        per_side = (share / 2 if all(sides) else share).quantize(QUANTUM)
        if per_side == 0:
            raise ValueError(
                f"invested {share} is smaller than the canonical grid {QUANTUM} once split "
                f"between {'two sides' if all(sides) else 'the book'}, so every weight would "
                "round to zero. Ask for at least one grid step per side"
            )
        weights: dict[str, Decimal] = {}
        for names, sign in ((longs, Decimal(1)), (shorts, Decimal(-1))):
            if not names:
                continue
            total = sum(names.values(), Decimal(0))
            for instrument, conviction in names.items():
                weights[instrument] = sign * per_side * conviction / total

        # `rescale` owns quantising and settling, and this constructor stopped owning a second
        # copy of it (`docs/issues/075`). It quantises onto the grid FIRST and settles each side's
        # rounding residual afterwards, on that side's largest position by absolute size -- where
        # the crumb is proportionally smallest, and where it cannot move cash across a bound.
        #
        # Settling in CASH is the obvious-looking alternative and is wrong for a measurable
        # reason: a dollar-neutral signed book nets to zero, so its cash is 1, and three shorts at
        # -0.5/3 leave -1e-12, which pushes cash to 1.000000000001 -- one crumb ABOVE the
        # fully-uninvested bound. The book is arithmetically fine and the declaration is refused.
        #
        # PER SIDE, not per book, which is what changed here. Settling one book-wide residual on
        # the single largest position let a crumb from the SHORT side land on a LONG name, so a
        # book asking for `invested=1` could come out with gross 1.000000000002 -- and `invested`
        # is documented as gross exposure. Each side now lands exactly on its own target, so gross
        # is exact and the two sides of a neutral book cancel on the same grid steps.
        quantised = dict(
            rescale(
                dict(sorted(weights.items())),
                long=per_side if longs else Decimal(0),
                short=-per_side if shorts else Decimal(0),
                grid=QUANTUM,
            )
        )

        # Cash is what the book does NOT hold net, and for a signed book that is not
        # `1 - invested`. `invested` is GROSS exposure: a dollar-neutral long/short book puts the
        # whole invested fraction to work and still nets to zero, so its cash is 1. Computing cash
        # from the gross fraction produced a residual of ~1 and a refusal on a book that is
        # arithmetically perfect.
        #
        # Exact by construction now: every side landed on its target, so the sum is on the grid
        # and no second settle is needed here.
        cash = Decimal(1) - sum(quantised.values(), Decimal(0))
        if shorts:
            direction = PortfolioDirection.SIGNED
            bounds = (Decimal(-1), Decimal(1))
            # Cash can exceed 1 on a signed book, and pinning the upper bound at 1 made every
            # SHORT-ONLY book refuse -- 100% of them, with a message naming cash when the real
            # problem was a bound that cannot represent short-sale proceeds. Selling short raises
            # cash: a book that is only short holds MORE than its NAV in cash by exactly the
            # amount it shorted. The bound is widened to admit that rather than the arithmetic
            # being bent to fit a bound that was wrong.
            cash_bounds = (Decimal(-1), Decimal(2))
        else:
            direction = PortfolioDirection.LONG_ONLY
            bounds = (Decimal(0), Decimal(1))
            cash_bounds = (Decimal(0), Decimal(1))
        return cls(
            target_weights=quantised,
            cash_weight=cash,
            budget=Budget(
                direction=direction,
                cash_lower=cash_bounds[0],
                cash_upper=cash_bounds[1],
                target_lower=bounds[0],
                target_upper=bounds[1],
            ),
        )

    @classmethod
    def signed(
        cls,
        weights: Mapping[str, Decimal | int | float | str],
        *,
        gross: Decimal | int | float | str = 1,
    ) -> Rebalance:
        """Build a signed book from signed weights, split exactly as the signal produced them.

        This is the market-neutral residual book `docs/issues/075` was filed on, and the thing
        `of` structurally cannot say. `of` takes two mappings and splits `invested` EVENLY between
        them, so it tops out at half a textbook $1-long/$1-short book (`docs/issues/018`) and can
        never express a 130/30 or a book whose signal happened to find more shorts than longs.
        Here the ratio is the signal's: pass what the signal produced, say how large the book
        should be, and the long/short split falls out of the weights themselves.

        **The sign carries the side.** A negative weight is a short, which is the opposite
        convention to `of` -- there, the side is chosen by WHICH MAPPING a name appears in and a
        negative number is refused. The two constructors take different inputs, so they can afford
        different conventions; what they must not do is accept the same input and mean different
        things by it.

        `gross` is the sum of ABSOLUTE weights, so `gross=1` on a dollar-neutral book is 0.5 long
        and 0.5 short, and `gross=2` is the textbook $1/$1 book `of` cannot reach. It is not
        bounded at 1: leverage is a real declaration, and the budget below admits positions in
        `[-1, 1]` with cash in `[-1, 2]`, which is what actually constrains the book.

        Cash is the NET residual, `1 - sum(weights)` -- not `1 - gross`. A dollar-neutral book is
        fully invested and nets to zero, so its cash is 1; a book that is only short holds more
        than its NAV in cash by exactly what it shorted.

        A name whose weight is zero is kept as a flat position rather than dropped: a signal that
        scores a name at zero has said something about it, and silently removing the name would
        make the returned book disagree with the mapping the author passed.

        Quantising and settling are `vqapr.portfolio.weighting.rescale`'s, on the canonical grid,
        each side landing exactly on its own target.
        """
        if not isinstance(weights, Mapping) or not weights:
            raise TypeError("weights must be a non-empty mapping of instrument to signed weight")
        declared: dict[str, Decimal] = {}
        for instrument, raw in weights.items():
            value = _as_decimal(raw, name=f"weights[{instrument!r}]")
            if not value.is_finite():
                raise ValueError(f"weights[{instrument!r}] must be finite")
            declared[_identifier(instrument, name="instrument")] = value

        size = _as_decimal(gross, name="gross")
        if size <= 0:
            raise ValueError(
                f"gross must be greater than zero; got {size}. It is the sum of ABSOLUTE weights, "
                "so a dollar-neutral book at gross=1 is 0.5 long and 0.5 short"
            )

        total = sum((abs(value) for value in declared.values()), Decimal(0))
        if total == 0:
            raise ValueError(
                "a Rebalance needs at least one non-zero weight; every weight given was zero, "
                "and a book of nothing has no side to size"
            )

        # The two side targets, in the ratio the SIGNAL produced -- this is the whole point of
        # this constructor. Quantised because `rescale` refuses a target that is not itself on
        # the grid, which can leave `long + (-short)` one step away from `gross`; that is the
        # grid's own resolution and not a miscalculation.
        longs = sum((value for value in declared.values() if value > 0), Decimal(0))
        shorts = sum((value for value in declared.values() if value < 0), Decimal(0))
        long_target = (size * longs / total).quantize(QUANTUM)
        short_target = (size * shorts / total).quantize(QUANTUM)
        for name, side, target in (("long", longs, long_target), ("short", shorts, short_target)):
            if side != 0 and target == 0:
                raise ValueError(
                    f"the {name} side is {side} of a gross {size}, which is smaller than the "
                    f"canonical grid {QUANTUM} and would round the whole side to zero. Raise "
                    "gross, or drop the side from the weights"
                )

        book = dict(rescale(declared, long=long_target, short=short_target, grid=QUANTUM))
        return cls(
            target_weights=book,
            cash_weight=Decimal(1) - sum(book.values(), Decimal(0)),
            # SIGNED unconditionally, even for an all-positive mapping: the author reached for the
            # signed constructor and the next signal may find a short. A budget that flipped to
            # LONG_ONLY on the days a signal happened to find none would refuse the book on the
            # first day it did.
            budget=Budget(
                direction=PortfolioDirection.SIGNED,
                cash_lower=Decimal(-1),
                cash_upper=Decimal(2),
                target_lower=Decimal(-1),
                target_upper=Decimal(1),
            ),
        )

    @field_validator("target_weights", mode="before")
    @classmethod
    def _weights(cls, value: object) -> CrossSection[Decimal]:
        return _copy_weights(value, name="target_weights")

    @model_validator(mode="after")
    def _adds_up_inside_the_budget(self) -> Self:
        # The fields are already what they claim: a read-only cross-section of finite Decimals,
        # a finite cash weight, a Budget. What is checked here is the relation between them.
        weights, cash, budget = self.target_weights, self.cash_weight, self.budget
        # Every refusal here names the value it saw and the bound it crossed. These five said
        # only the rule -- `cash_weight is outside the declared budget` -- and an author whose
        # quantised shorts summed to -1.000000000001 had to reason the cash of 2.000000000001 and
        # the bound of 2 out by hand, in a run of eight strategies (`docs/issues/071`).
        if not budget.validates_cash(cash):
            raise ValueError(
                f"cash_weight {cash} is outside the declared budget "
                f"[{budget.cash_lower}, {budget.cash_upper}]"
            )
        if weights:
            outside = {
                name: value
                for name, value in weights.items()
                if not budget.validates_target(value)
            }
            if outside:
                raise ValueError(
                    "target_weights are outside the declared budget bounds "
                    f"[{budget.target_lower}, {budget.target_upper}]: {_offenders(outside)}"
                )
            if budget.direction is PortfolioDirection.LONG_ONLY:
                negative = {name: value for name, value in weights.items() if value < 0}
                if negative:
                    raise ValueError(
                        f"long_only budgets forbid negative target_weights: {_offenders(negative)}"
                    )
            total = sum(weights.values(), Decimal(0))
            if total + cash != 1:
                raise ValueError(
                    "target_weights plus cash_weight must equal one; got "
                    f"sum(target_weights) {total} + cash_weight {cash} = {total + cash}"
                )
        elif cash != 1:
            raise ValueError(
                f"an empty complete position set requires cash_weight equal to one; got {cash}"
            )
        return self


class StrategyCall(ABC):
    """The complete, bounded capability surface for one Strategy occurrence.

    `StrategyModelContext` is its one implementation, the way `DataModelContext` is of
    `DataCall`. What a Strategy receives beyond a DataModel is what its role needs and nothing
    else: the committed account, its own declared history, and the bounds every registered
    Constraint projected. Framework facts -- the account version, the intent id, what was read --
    are not here; the Flow stamps them onto the intent itself (record `125`).
    """

    @property
    @abstractmethod
    def occurrence_id(self) -> str:
        """Which occurrence this is. Kept in `memory`, it is how a cadence rule counts."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this occurrence decides at."""

    @property
    @abstractmethod
    def account(self) -> EconomicAccountView:
        """The committed Account: cash, positions, and the marks of its last valuation."""

    @property
    @abstractmethod
    def account_history(self) -> AccountHistory:
        """Committed account history, bounded by this Strategy's own `account_history()`."""

    @property
    @abstractmethod
    def constraint_bounds(self) -> ConstraintBounds:
        """The merged bounds projected from every registered Constraint."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `StrategyModel.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `StrategyModel.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """


class StrategyModel(Component):
    """User extension that decides what to hold; its memory owns cadence and path-dependent rules.

    One class (record `132`). Two carried this name: this one, which the scaffold taught and an
    author subclassed, and an engine one the Flow ran, with an adapter between them that built the
    author's class fresh per callback and translated every argument and return. The adapter is
    gone; what an author writes is what the engine calls.

    **State is `memory`, as for every Model** (architecture 4.4, 5.1.1): strict JSON the Flow
    snapshots after a successful callback and restores before the next. `save_payload` /
    `load_payload` carry what memory cannot -- a fitted network, a large array -- as opaque bytes
    under the same commit. A fresh instance with both restored decides the same, and the Flow
    relies on that: nothing else about `self` is promised across a run boundary.

    **Rows go to `self.recorder`**, set by the Flow for the duration of one callback and `None`
    outside it, into the tables `tables()` declared. Writing to an undeclared table refuses.
    """

    recorder: InvocationRecorder | None = None

    def tables(self) -> tuple[TableSpec, ...]:
        """Declare every table this Strategy may write during a callback. Empty by default."""
        return ()

    def account_history(self) -> AccountHistoryInput | None:
        """Declare which committed account values this Strategy reads back, and how far.

        `None` declares none: the run then retains only its current mark, so a Strategy that
        never looks at its own path costs nothing to carry one.
        """
        return None

    def save_payload(self, target: BinaryIO) -> None:
        """Persist private callback state that does not fit `memory` into Flow-owned staging.

        Preflight calls `save_payload` on a fresh instance, `load_payload` on another with those
        bytes, and `save_payload` again; the bytes must match before the first callback. So this
        must be deterministic -- no timestamp, no `id()`, no unordered set iteration.
        """

    def load_payload(self, source: BinaryIO) -> None:
        """Restore what `save_payload` wrote.

        A class with nothing to save yet must accept an EMPTY source: preflight round-trips the
        default `save_payload`, which writes no bytes, so an unguarded `pickle.load` refuses the
        run with `EOFError` before a single callback runs.
        """

    @abstractmethod
    def decide(self, call: StrategyCall) -> Hold | Rebalance:
        """Return the economic decision for this occurrence, and nothing else.

        `Hold` declines. `Rebalance` names one complete desired portfolio: weights, cash, and the
        budget they must satisfy. Everything an intent additionally carries -- its id, this
        Strategy's id, what was read, the account version seen -- is the Flow's to stamp, and a
        callback that tried to name any of it would be claiming authority it does not have.
        """


# --------------------------------------------------------------------------------------
# Constraint algebra.
# --------------------------------------------------------------------------------------


class ConstraintCall(ABC):
    """The bounded capability surface for one Constraint invocation.

    **An abstract contract, like `DataCall` and `StrategyCall`, and no longer a value.** It was a
    concrete frozen dataclass that nothing in `src/` ever built -- only tests -- while the engine
    handed a Constraint a `ModelWindow` and a tuple of instruments instead. `vqapr.calls`
    now supplies the one concrete implementation, the same way it does for the other two roles.

    **The account came off it.** It used to carry an `EconomicAccountView`, which meant `project`
    -- the member that runs before any decision exists, to say what the feasible set is -- was
    handed the committed account. Nothing needed it and the engine never offered it, so the
    authoring shape was granting authority the engine did not. Where the two contracts disagreed
    about how much a member may see, the narrower one is right (architecture 2.2, least
    authority): `monitor` receives the account as its own argument, and `project` cannot reach one.
    """

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen point-in-time cutoff this invocation is bounded to."""

    @property
    @abstractmethod
    def instruments(self) -> tuple[str, ...]:
        """Every instrument this projection must cover, in the run's declared order."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `Constraint.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `Constraint.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """


class ConstraintFinding(BaseModel):
    """One Constraint's complete, immutable result for one economic observation.

    **`offenders` is a field and not a `details` key**, because it is the one thing a refusal
    cannot be written without. `docs/implementations/086` is a run that stopped on a 20% cap and
    said only *"economic intent violates projected constraints"*, leaving a first-time user to
    re-run the strategy without the constraint and read the weight table to find out which name
    breached it.
    The refusal names them now, and it can only do that if every finding carries them under one
    name -- a convention inside a free-form mapping is not something a message can rely on.

    It also could not live there. `details` admits portable scalars only, so that a diagnostic
    mapping survives being written to a record and read back; a tuple is refused. Promoting the
    field keeps that rule intact instead of widening it for one caller.
    """

    model_config = _VALUE_CONFIG

    passed: bool
    measured: Decimal
    bound: Decimal
    excess: Decimal
    details: Mapping[str, object]
    offenders: tuple[str, ...] = ()

    @field_validator("offenders", mode="before")
    @classmethod
    def _named_once(cls, value: object) -> tuple[str, ...]:
        # Not `_unique_identifiers`, which requires at least one entry: an empty `offenders` is
        # the ordinary passing case and the most common value this field ever holds.
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise TypeError("offenders must be a sequence of instrument ids")
        offenders = tuple(_identifier(entry, name="offenders entry") for entry in value)
        if len(set(offenders)) != len(offenders):
            raise ValueError("offenders entries must be unique")
        return offenders

    @field_validator("details", mode="before")
    @classmethod
    def _portable(cls, value: object) -> Mapping[str, object]:
        details = _copy_values(value, name="details", reserved=_ENVELOPE_RESERVED_FIELDS)
        if len(details) > 32:
            raise ValueError("details must be bounded to 32 semantic keys")
        return details

    @field_validator("details")
    @classmethod
    def _read_only(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        # pydantic hands the mapping back as a dict; what an author reads is a view.
        return MappingProxyType(dict(value))


class Constraint(Component):
    """User extension contract: an economic predicate over the account.

    **A Component like the other roles** (owner ruling, 2026-09-08). It declares its reads with
    `inputs()` and may keep `memory` between callbacks -- *"out after three breaches"* is a rule
    that counts, and a rule that counts remembers. The engine restores that memory before
    `project` and before `monitor` and commits what each left, with the callback publication
    and the monitoring publication respectively. The earlier contract called a constraint a
    stateless predicate and kept it outside the base for that reason; the premise was wrong and
    the copies of `inputs()` and `requirements()` it forced are gone.

    **Two members, because a constraint does two things and they are different things.** `project`
    bounds construction before anything is decided -- best effort, the strategy builds the best
    portfolio the limits allow. `monitor` observes the committed account and says whether a limit
    was actually breached -- fact, not effort.

    **There is no member that scores the decision.** There was one, and it was removed rather than
    fixed. Two reasons, both recorded in `docs/vqapr-architecture.md` §5.7: it could not see the
    breach that matters most, because integer quantity conversion pushes a weight over a limit and
    that is unknowable before fills exist (`UC-CONSTRAINT-ADJUST-001`); and two scorers can
    disagree, which `docs/issues/014` measured -- the same rule read a signed weight in one member
    and an absolute one in the other, so a proposal passed the gate before execution and was
    reported as a violation by the check after it. One place to measure, and that ambiguity cannot
    arise.

    A decision that breaches a limit therefore does not stop a run. It is a breach, and breaches
    are observed where breaches are observed.

    **The id is declared once, here, and not repeated on every finding.** `constraint_id` says
    which rule this is and is checked at load against the id it was registered under, so a rule
    registered as `noshort` and answering to `no-short` is refused before a run is spent. What was
    removed is the *repetition*: a finding used to carry the id too, every author had to set it,
    and the framework compared it against the id it was already holding while it made the call.
    That is the shape record `125` removed from the Strategy callback -- get it wrong and the run
    refuses you, get it plausibly wrong and the run accepts you under another rule's identity.
    """

    @property
    @abstractmethod
    def constraint_id(self) -> str:
        """The id this rule answers to. Must equal the id it is registered under."""

    @property
    def tolerance(self) -> Decimal | None:
        """How far past a bound the realised book may land and still count as inside it.

        `None`, the default, leaves it to the framework: ``max(bound * 1%, 10bp of NAV)``. A book
        executes in whole lots and is marked after its fills, so the realised weight lands a
        little off the target the optimiser put on the grid; without a tolerance that residue is
        filed as a violation in the same counter as a real one (`docs/issues/086` -- 40 of 82
        rebalances, worst 0.01%p, beside one real breach of 4.89%p). Override with a `Decimal`
        share of NAV to tighten or loosen it. The comparison itself stays the author's:
        `monitor` returns `passed`, `measured`, `bound`, `excess` as before, and the framework
        judges the excess against this line once, for every constraint, and reports the verdict
        beside the author's -- `held` / `within_tolerance` / `breached` -- so nothing is hidden.
        """
        return None

    @abstractmethod
    def project(self, call: ConstraintCall) -> ConstraintBounds:
        """Project deterministic per-instrument bounds for the current PIT cutoff.

        Return a lower and an upper bound for EVERY instrument in `call.instruments`. Not the
        offenders and not a correction -- the box the optimiser must stay inside. A projection
        that misses an instrument on either side is refused, because a missing bound would
        silently widen the feasible set rather than fail.
        """

    @abstractmethod
    def monitor(
        self,
        call: ConstraintCall,
        account: EconomicAccountView,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        """Measure the committed account against bounds projected at a monitoring cutoff.

        The account arrives here and nowhere else. `account.weight(instrument_id)` is the
        derivation a weight-based rule wants; `positions` and `values` are there for a rule that
        asks about quantity or about money.
        """
