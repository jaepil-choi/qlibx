"""Fresh-instance invocation boundary over `vqapr.authoring`.

Private runtime adapter turning one immutable `StrategyModel` declaration plus an
injected PIT observation resolver into a validated, private "prepared" result.

**The DataModel half is gone (record `129`).** It served `authoring.DataModel`, which the
loader refused outright, so nothing outside its own tests ever reached it.
It (1) validates declared input aliases and the DataModel `Output`/StrategyModel
`DiagnosticTable` schemas before any callback runs, and checks returned rows/
diagnostics against those exact schemas; (2) builds exactly one fresh `model_class`
instance per invocation from a detached config, so an author's mutable `self` can never
leak across invocations; and (3) exposes a bounded `DataCall`/`StrategyCall` that
rejects an undeclared alias, delegates every `read(alias)` to an *injected* resolver
(this module never resolves PIT data itself), detaches the returned `Observation`
tuples, and records the alias/dataset/observation count actually accessed.

A callback exception is never caught here: it propagates unchanged and no candidate is
returned for that invocation. No store, Flow, publication, accepted-intent
UUID/provenance, or account version lives here. Nothing in this module is public API.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from vqapr.authoring import (
    AccountHistoryInput,
    ConstraintBounds,
    DatasetInput,
    DeclaredAccountHistory,
    DiagnosticTable,
    EconomicAccountView,
    Hold,
    Observation,
    Rebalance,
    StrategyCall,
    StrategyModel,
    StrategyResult,
)
from vqapr.models.memory import ModelMemory, normalize_memory

__all__ = (
    "AccessToken",
    "AccountHistoryResolver",
    "ObservationResolver",
    "PreparedStrategyInvocation",
    "prepare_strategy_invocation",
)


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    """One recorded fact about a `read(alias)` call: alias, dataset, observation count.

    Never carries the observations themselves.
    """

    alias: str
    dataset_id: str
    observation_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "alias", _identifier(self.alias, name="alias"))
        object.__setattr__(self, "dataset_id", _identifier(self.dataset_id, name="dataset_id"))
        count = self.observation_count
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("observation_count must be an integer")
        if count < 0:
            raise ValueError("observation_count must be non-negative")


type ObservationResolver = Callable[[str, DatasetInput, datetime], tuple[Observation, ...]]
"""Injected PIT resolver: `(alias, declaration, evaluation_time) -> observations`.

The caller-supplied resolver is the sole authority for turning a declared alias into
observations; this module never resolves PIT data itself.
"""


type AccountHistoryResolver = Callable[[AccountHistoryInput], DeclaredAccountHistory]
"""Injected committed-account-history resolver: `declaration -> bounded view`.

Called only when the StrategyModel declares an `AccountHistoryInput`. A Strategy that
declares `None` receives an empty `DeclaredAccountHistory`, so every accessor raises:
undeclared history is unreadable rather than silently empty.
"""


def _fresh_instance(cls: type, config: Mapping[str, object]) -> object:
    """Construct one new `cls` instance from a detached copy of `config`."""
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    return cls(**dict(config))


def _validated_inputs(inputs: object) -> Mapping[str, DatasetInput]:
    """Check every declared alias is a well-formed identifier naming a `DatasetInput`."""
    if not isinstance(inputs, Mapping):
        raise TypeError("inputs() must return a mapping")
    checked: dict[str, DatasetInput] = {}
    for alias, declaration in inputs.items():
        checked_alias = _identifier(alias, name="input alias")
        if not isinstance(declaration, DatasetInput):
            raise TypeError(f"inputs()[{checked_alias!r}] must be a DatasetInput")
        checked[checked_alias] = declaration
    return MappingProxyType(checked)


def _validated_diagnostic_tables(tables: object) -> Mapping[str, DiagnosticTable]:
    if not isinstance(tables, tuple) or any(
        not isinstance(table, DiagnosticTable) for table in tables
    ):
        raise TypeError("diagnostics() must return a tuple of authoring.DiagnosticTable")
    table_ids = tuple(table.table_id for table in tables)
    if len(set(table_ids)) != len(table_ids):
        raise ValueError("diagnostics() table_id values must be unique")
    return MappingProxyType({table.table_id: table for table in tables})


def _detached_observations(
    alias: str, declaration: DatasetInput, observations: object
) -> tuple[Observation, ...]:
    """Return a fresh, owned tuple of one resolver's observations for `alias`."""
    if not isinstance(observations, tuple) or any(
        not isinstance(observation, Observation) for observation in observations
    ):
        raise TypeError(
            f"resolver({alias!r}, {declaration.dataset_id!r}, ...) must return a tuple of "
            "authoring.Observation"
        )
    return tuple(observations)


class _BoundedReader:
    """Shared `read(alias)`: rejects an undeclared alias, delegates to the injected
    resolver, detaches the returned observations, and records one `AccessToken`.

    Mixed into the concrete `DataCall`/`StrategyCall` adapters below; provides their
    `read`/`access_tokens`/`evaluation_time` behavior directly, with no delegation.
    """

    __slots__ = ("_evaluation_time", "_inputs", "_resolver", "_tokens")

    def __init__(
        self,
        *,
        evaluation_time: datetime,
        inputs: Mapping[str, DatasetInput],
        resolver: ObservationResolver,
    ) -> None:
        self._evaluation_time = evaluation_time
        self._inputs = inputs
        self._resolver = resolver
        self._tokens: list[AccessToken] = []

    @property
    def evaluation_time(self) -> datetime:
        return self._evaluation_time

    def read(self, alias: str) -> tuple[Observation, ...]:
        if not isinstance(alias, str):
            raise TypeError("alias must be a string")
        declaration = self._inputs.get(alias)
        if declaration is None:
            raise KeyError(
                f"{alias!r} was not declared in inputs(); a Model reads only what it declared"
            )
        observations = _detached_observations(
            alias, declaration, self._resolver(alias, declaration, self._evaluation_time)
        )
        self._tokens.append(
            AccessToken(
                alias=alias, dataset_id=declaration.dataset_id,
                observation_count=len(observations),
            )
        )
        return observations

    def access_tokens(self) -> tuple[AccessToken, ...]:
        return tuple(self._tokens)


class _PrivateStrategyCall(_BoundedReader, StrategyCall):
    """A concrete, bounded `StrategyCall` for exactly one Strategy invocation."""

    __slots__ = ("_account", "_account_history", "_constraint_bounds", "_previous_state")

    def __init__(
        self,
        *,
        evaluation_time: datetime,
        account: EconomicAccountView,
        previous_state: object,
        account_history: DeclaredAccountHistory,
        constraint_bounds: ConstraintBounds,
        inputs: Mapping[str, DatasetInput],
        resolver: ObservationResolver,
    ) -> None:
        super().__init__(evaluation_time=evaluation_time, inputs=inputs, resolver=resolver)
        self._account = account
        self._previous_state = previous_state
        self._account_history = account_history
        self._constraint_bounds = constraint_bounds

    @property
    def account(self) -> EconomicAccountView:
        return self._account

    @property
    def previous_state(self) -> object:
        return self._previous_state

    @property
    def account_history(self) -> DeclaredAccountHistory:
        return self._account_history

    @property
    def constraint_bounds(self) -> ConstraintBounds:
        return self._constraint_bounds


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedStrategyInvocation:
    """A validated, private result of one fresh-instance Strategy invocation: only the
    `decision`, normalized `next_state`, declared `diagnostics`, and `access_tokens`.
    """

    decision: Hold | Rebalance
    next_state: ModelMemory
    diagnostics: Mapping[str, tuple[Mapping[str, object], ...]]
    access_tokens: tuple[AccessToken, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decision, (Hold, Rebalance)):
            raise TypeError("decision must be a Hold or Rebalance")
        object.__setattr__(self, "next_state", normalize_memory(self.next_state))
        if not isinstance(self.diagnostics, Mapping):
            raise TypeError("diagnostics must be a mapping")
        object.__setattr__(
            self, "diagnostics", MappingProxyType(dict(sorted(self.diagnostics.items())))
        )
        if not isinstance(self.access_tokens, tuple) or any(
            not isinstance(token, AccessToken) for token in self.access_tokens
        ):
            raise TypeError("access_tokens must be a tuple of AccessToken")


def _validate_decision_invariants(decision: Hold | Rebalance) -> None:
    """Re-affirm the Hold/Rebalance invariants `authoring`'s own constructors enforce."""
    if isinstance(decision, Hold):
        if not decision.reason:
            raise ValueError("Hold.reason must be non-empty")
        return
    if isinstance(decision, Rebalance):
        total = decision.cash_weight + sum(
            decision.target_weights.values(), decision.cash_weight * 0
        )
        if total != 1:
            raise ValueError("Rebalance target_weights plus cash_weight must equal one")
        return
    raise TypeError("decision must be a Hold or Rebalance")


def _validated_diagnostics(
    result_diagnostics: Mapping[str, tuple[Mapping[str, object], ...]],
    tables_by_id: Mapping[str, DiagnosticTable],
) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    unknown_tables = sorted(set(result_diagnostics) - set(tables_by_id))
    if unknown_tables:
        # Naming the repair, not just the breach. `diagnostics` reads as a convenience on
        # `StrategyResult` -- its docstring introduces it as saving typing for the common case --
        # so an author who emits a table reasonably expects it to be recorded. It must be declared
        # first, and nothing said so until the run had already been spent.
        declared = sorted(tables_by_id)
        raise ValueError(
            f"decide() emitted undeclared diagnostic tables: {unknown_tables}. "
            f"Declare each one by returning it from StrategyModel.diagnostics(), which currently "
            f"declares {declared or 'nothing'}; a table must be declared there before decide() "
            f"may emit it."
        )
    for table_id, rows in result_diagnostics.items():
        expected_fields = set(tables_by_id[table_id].semantic_fields)
        for row in rows:
            if set(row) != expected_fields:
                raise ValueError(
                    f"diagnostics[{table_id!r}] row does not match its declared schema"
                )
    return result_diagnostics


def _resolved_account_history(
    declaration: object, history_resolver: AccountHistoryResolver | None
) -> DeclaredAccountHistory:
    """Turn one `account_history()` declaration into its bounded view.

    `None` declares that no committed history is read, and yields an empty view whose
    accessors all raise. A declaration requires a resolver: the framework, not the
    author, owns the committed history, so a declared read with nothing to serve it is
    a wiring error rather than an empty result.
    """
    if declaration is None:
        return DeclaredAccountHistory()
    if not isinstance(declaration, AccountHistoryInput):
        raise TypeError("account_history() must return an AccountHistoryInput or None")
    if history_resolver is None:
        raise ValueError(
            "this StrategyModel declared an AccountHistoryInput but no history_resolver "
            "was supplied to serve it"
        )
    history = history_resolver(declaration)
    if not isinstance(history, DeclaredAccountHistory):
        raise TypeError("history_resolver must return an authoring.DeclaredAccountHistory")
    if set(history.fields) != set(declaration.fields):
        raise ValueError(
            "history_resolver returned fields that do not match the declaration: "
            f"declared {sorted(declaration.fields)}, served {sorted(history.fields)}"
        )
    if history.lookback != declaration.lookback:
        raise ValueError(
            "history_resolver returned a lookback that does not match the declaration"
        )
    return history


def _validated_bounds_cover(bounds: ConstraintBounds, instruments: tuple[str, ...]) -> None:
    """A callback's bounds must cover exactly the universe passed to that callback."""
    universe = _unique_instruments(instruments)
    lower = set(bounds.lower_weights)
    upper = set(bounds.upper_weights)
    if lower != universe or upper != universe:
        missing = sorted(universe - (lower & upper))
        extra = sorted((lower | upper) - universe)
        raise ValueError(
            "constraint_bounds must cover exactly the callback universe; "
            f"missing {missing}, unexpected {extra}"
        )


def _unique_instruments(instruments: object) -> set[str]:
    if not isinstance(instruments, tuple):
        raise TypeError("instruments must be a tuple of instrument_id")
    checked = tuple(_identifier(item, name="instrument_id") for item in instruments)
    if len(set(checked)) != len(checked):
        raise ValueError("instruments must not repeat an instrument_id")
    return set(checked)


def prepare_strategy_invocation(
    model_class: type[StrategyModel],
    config: Mapping[str, object],
    *,
    evaluation_time: datetime,
    account: EconomicAccountView,
    instruments: tuple[str, ...],
    constraint_bounds: ConstraintBounds,
    previous_state: object = None,
    history_resolver: AccountHistoryResolver | None = None,
    resolver: ObservationResolver,
) -> PreparedStrategyInvocation:
    """Instantiate `model_class` exactly once, read only declared aliases, and validate
    `decide()`'s diagnostics against the declared `DiagnosticTable` schemas.
    `Hold`/`Rebalance` are already validated by `authoring`; this re-affirms those
    invariants at the boundary. Any exception raised by `inputs()`, `account_history()`,
    `diagnostics()`, or `decide()` propagates unchanged.

    `instruments` and `constraint_bounds` are required: the plan's economic-explicitness
    rule means a callback's bound set is declared, never defaulted to an empty one that
    would silently constrain nothing.
    """
    if not isinstance(model_class, type) or not issubclass(model_class, StrategyModel):
        raise TypeError("model_class must be a subclass of vqapr.authoring.StrategyModel")
    if not isinstance(evaluation_time, datetime):
        raise TypeError("evaluation_time must be a datetime")
    if not isinstance(account, EconomicAccountView):
        raise TypeError("account must be an authoring.EconomicAccountView")
    if not isinstance(constraint_bounds, ConstraintBounds):
        raise TypeError("constraint_bounds must be an authoring.ConstraintBounds")
    if not callable(resolver):
        raise TypeError("resolver must be callable")
    if history_resolver is not None and not callable(history_resolver):
        raise TypeError("history_resolver must be callable or None")
    _validated_bounds_cover(constraint_bounds, instruments)

    instance = _fresh_instance(model_class, config)
    if not isinstance(instance, StrategyModel):
        raise TypeError("model_class must construct a vqapr.authoring.StrategyModel instance")

    inputs = _validated_inputs(instance.inputs())
    resolved_history = _resolved_account_history(instance.account_history(), history_resolver)
    tables_by_id = _validated_diagnostic_tables(instance.diagnostics())

    call = _PrivateStrategyCall(
        evaluation_time=evaluation_time,
        account=account,
        previous_state=normalize_memory(previous_state),
        account_history=resolved_history,
        constraint_bounds=constraint_bounds,
        inputs=inputs,
        resolver=resolver,
    )
    result = instance.decide(call)
    if not isinstance(result, StrategyResult):
        raise TypeError("decide() must return an authoring.StrategyResult")

    _validate_decision_invariants(result.decision)
    diagnostics = _validated_diagnostics(result.diagnostics, tables_by_id)

    return PreparedStrategyInvocation(
        decision=result.decision,
        next_state=result.next_state,
        diagnostics=diagnostics,
        access_tokens=call.access_tokens(),
    )
