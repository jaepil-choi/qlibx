"""Agent-first extension authoring/read/result contracts.

The sole public home for what an author subclasses (``DataModel``, ``StrategyModel``,
``Constraint``), receives (``DataCall``, ``StrategyCall``, ``ConstraintCall``,
``Observation``, ``EconomicAccountView``, ``AccountHistory``, ``ConstraintBounds``),
and returns (``Rows``, ``Hold``/``Rebalance``, ``ConstraintFinding``).

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
from typing import BinaryIO, Literal

from vqapr.account.history import ACCOUNT_FIELDS, INSTRUMENT_FIELDS, AccountHistory
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.domain.rows import Rows
from vqapr.domain.timestamps import require_tz_aware
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.models.memory import ModelMemory
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.optimize import QUANTUM

__all__ = (
    "AccountHistory",
    "AccountHistoryInput",
    "CalendarLookback",
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
    "Model",
    "Observation",
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


def _copy_weights(values: object, *, name: str) -> Mapping[str, Decimal]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, Decimal] = {}
    for key, value in values.items():
        instrument_id = _identifier(key, name=f"{name} key")
        normalized[instrument_id] = _finite_decimal(value, name=f"{name}[{instrument_id!r}]")
    return MappingProxyType(dict(sorted(normalized.items())))


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
        if not isinstance(self.lookback, (RowsLookback, CalendarLookback, InstantsLookback)):
            raise TypeError("lookback must be a RowsLookback, CalendarLookback or InstantsLookback")


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


class DataCall(ABC):
    """The complete, bounded capability surface for one DataModel invocation."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this invocation computes for."""

    @abstractmethod
    def read(self, alias: str) -> tuple[Observation, ...]:
        """Return PIT observations for one alias declared in `DataModel.inputs()`."""


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


class Model(ABC):  # noqa: B024 - concrete Model roles add abstract callbacks
    """What every Model role shares: a declaration of reads, and portable memory.

    **The author's base class, so it lives on the author's surface.** It used to live in
    `models/model.py` while an authoring `DataModel` and `StrategyModel` were defined here without
    it -- which is why the two authored kinds shared no ancestor, and why an author who wrote
    against this module got a class the loader could not run (`docs/issues/036`). `models/model.py`
    re-exports this one.

    **Both roles declare their reads here, in one place and one shape.** A first-time user once had
    to build a ten-row table of the ways authoring the two roles differed; the owner ruled that
    *"the size of the current difference is itself the defect"*. `inputs()` is the one shape.

    `memory` is the small strict-JSON state a Model carries between invocations. A DataModel that
    uses it becomes order-dependent (architecture 4.4); one that does not may be computed in any
    order.
    """

    memory: ModelMemory = None

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this Model performs. Empty by default.

        The alias is the author's own name for a read, and it is what `read(alias)` takes on the
        call. Declaring nothing is legitimate: a Model may derive its values from memory alone.
        """
        return {}

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Every observation requirement, derived from `inputs()` rather than written twice."""
        return tuple(
            requirement
            for declaration in self.inputs().values()
            for requirement in requirements_for(declaration)
        )


class DataModel(Model):
    """A Model whose result is values: data in, a dataset out, and no account in between.

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
                f"account series are {ACCOUNT_FIELDS} and "
                f"instrument panels are {INSTRUMENT_FIELDS}"
            )
        object.__setattr__(self, "fields", fields)
        if not isinstance(self.lookback, RowsLookback):
            raise TypeError("lookback must be a RowsLookback")


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

    def weights(self) -> Mapping[str, Decimal]:
        """Every marked name's share of NAV, signed. The whole book as a weight vector."""
        if self.values is None:
            raise ValueError(
                "this view carries no marked values; it was built at an instant the framework "
                "had no marks to offer, and an empty book here would be an answer rather than a gap"
            )
        return MappingProxyType(
            {instrument_id: self.weight(instrument_id) for instrument_id in sorted(self.values)}
        )


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

    def detached(self) -> ConstraintBounds:
        """A fresh value with no caller-owned mapping aliases.

        `__post_init__` already copies into read-only views, so this is defensive rather than
        load-bearing -- and it is kept because `StrategyModelContext` calls it on a value it did
        not construct, where "already copied" is an assumption about someone else's code.
        """
        return ConstraintBounds(
            lower_weights=self.lower_weights, upper_weights=self.upper_weights
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Hold:
    """A Strategy decision that intentionally emits no order.

    **This is the engine's decline type as well as the author's.** It absorbed
    `models.strategy_model.NoDecision` in record `125`: the two were the same frozen one-field
    dataclass with two names, and the adapter's whole contribution was `NoDecision(hold.reason)`.

    `reason` is prose, not an identifier. It was validated with `_identifier` here, which rejects
    whitespace -- so `Hold(reason="no name scored above zero")` was refused while the engine's
    `NoDecision` accepted the identical string. Merging two types means merging two validations,
    and the looser one is the correct one: a reason a human reads should be allowed spaces.
    """

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")


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


@dataclass(frozen=True, slots=True, kw_only=True)
class Rebalance:
    """A Strategy decision naming one complete desired portfolio."""

    target_weights: Mapping[str, Decimal]
    cash_weight: Decimal
    budget: Budget

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
        a law.

        Doing it by hand is also where the errors live: the sum must land on one EXACTLY, and a
        weight that misses by a single ulp is refused by the same invariant that catches a real
        mistake. Relative weights cannot make that error, because the author never states a total.

        `invested` is the fraction of NAV to put to work; the remainder stays in cash. Passing a
        short book implies a signed budget, and a long-only book keeps `LONG_ONLY`, so the budget
        follows from what was actually asked for rather than being declared a second time.
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
        # fraction. One side alone takes all of it.
        sides = (bool(longs), bool(shorts))
        per_side = share / 2 if all(sides) else share
        weights: dict[str, Decimal] = {}
        for names, sign in ((longs, Decimal(1)), (shorts, Decimal(-1))):
            if not names:
                continue
            total = sum(names.values(), Decimal(0))
            for instrument, conviction in names.items():
                weights[instrument] = sign * per_side * conviction / total

        # Round onto the canonical grid, then settle the rounding residual ON THE BOOK rather than
        # in cash.
        #
        # Cash looks like the natural place for it -- it is the line nobody expressed a view about
        # -- and that is wrong here for a measurable reason. A dollar-neutral signed book nets to
        # zero, so cash is 1; three shorts at -0.5/3 do not divide evenly, and the leftover
        # -1e-12 pushes cash to 1.000000000001, one crumb ABOVE the fully-uninvested bound. The
        # book is arithmetically fine and the declaration is refused.
        #
        # So the residual goes back to the largest position by absolute size, where it is a
        # relatively smaller perturbation than anywhere else and where it cannot move cash across
        # a bound. `invested` is then honoured exactly, which is what the author actually asked
        # for.
        quantised = {
            instrument: value.quantize(QUANTUM) for instrument, value in sorted(weights.items())
        }

        # Cash is what the book does NOT hold net, and for a signed book that is not
        # `1 - invested`. `invested` is GROSS exposure: a dollar-neutral long/short book puts the
        # whole invested fraction to work and still nets to zero, so its cash is 1. Computing cash
        # from the gross fraction produced a residual of ~1 and a refusal on a book that is
        # arithmetically perfect.
        #
        # So cash is the net residual, and the rounding crumb is settled on the largest position
        # rather than in cash -- where, for that same neutral book, a -1e-12 leftover would push
        # cash one step past fully-uninvested and be refused for a rounding artifact.
        exact = sum(weights.values(), Decimal(0))
        cash = (Decimal(1) - exact).quantize(QUANTUM)
        residual = Decimal(1) - cash - sum(quantised.values(), Decimal(0))
        if residual and quantised:
            anchor = max(quantised, key=lambda name: (abs(quantised[name]), name))
            quantised[anchor] += residual
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
    def read(self, alias: str) -> tuple[Observation, ...]:
        """Return PIT observations for one alias declared in `StrategyModel.inputs()`."""


class StrategyModel(Model):
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
        """Persist private callback state that does not fit `memory` into Flow-owned staging."""

    def load_payload(self, source: BinaryIO) -> None:
        """Restore what `save_payload` wrote."""

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
    handed a Constraint a `ModelWindow` and a tuple of instruments instead. `models/contexts.py`
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
    def read(self, alias: str) -> tuple[Observation, ...]:
        """Return PIT observations for one alias declared in `Constraint.inputs()`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintFinding:
    """One Constraint's complete, immutable result for one economic observation.

    **`offenders` is a field and not a `details` key**, because it is the one thing a refusal
    cannot be written without. `docs/issues/086` is a run that stopped on a 20% cap and said only
    *"economic intent violates projected constraints"*, leaving a first-time user to re-run the
    strategy without the constraint and read the weight table to find out which name breached it.
    The refusal names them now, and it can only do that if every finding carries them under one
    name -- a convention inside a free-form mapping is not something a message can rely on.

    It also could not live there. `details` admits portable scalars only, so that a diagnostic
    mapping survives being written to a record and read back; a tuple is refused. Promoting the
    field keeps that rule intact instead of widening it for one caller.
    """

    passed: bool
    measured: Decimal
    bound: Decimal
    excess: Decimal
    details: Mapping[str, object]
    offenders: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a bool")
        # Not `_unique_identifiers`, which requires at least one entry: an empty `offenders` is
        # the ordinary passing case and the most common value this field ever holds.
        if not isinstance(self.offenders, Sequence) or isinstance(self.offenders, (str, bytes)):
            raise TypeError("offenders must be a sequence of instrument ids")
        offenders = tuple(
            _identifier(value, name="offenders entry") for value in self.offenders
        )
        if len(set(offenders)) != len(offenders):
            raise ValueError("offenders entries must be unique")
        object.__setattr__(self, "offenders", offenders)
        object.__setattr__(self, "measured", _finite_decimal(self.measured, name="measured"))
        object.__setattr__(self, "bound", _finite_decimal(self.bound, name="bound"))
        object.__setattr__(self, "excess", _finite_decimal(self.excess, name="excess"))
        details = _copy_values(self.details, name="details", reserved=_ENVELOPE_RESERVED_FIELDS)
        if len(details) > 32:
            raise ValueError("details must be bounded to 32 semantic keys")
        object.__setattr__(self, "details", details)


class Constraint(ABC):
    """User extension contract: an immutable economic predicate over the account.

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

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this Constraint performs. Empty by default.

        Declaring nothing is legitimate and is what the shipped `NoShort` does: a rule about a
        weight's sign opens no data. The loader used to require a non-empty `requirements()` here,
        which made the one shipped constraint that needs no data the one shape it could not accept.
        """
        return {}

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Every observation requirement, derived from `inputs()` -- `Model.requirements()`,
        spelled the same way for the role that is not a Model.

        Not a Model because `Model` carries `memory`, and a constraint is a stateless predicate
        that must not have any. The fan-out is shared; the state is not.
        """
        return tuple(
            requirement
            for declaration in self.inputs().values()
            for requirement in requirements_for(declaration)
        )

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
