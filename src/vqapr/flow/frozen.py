"""The run, frozen: what preflight fixes once per run and once per member, and their identities.

Split out of `flow/run.py` (one-shape campaign Step 6, record 161): `run.py` is the declaration
-- what a document registers -- and this is what preflight makes of it. A `FrozenRun` shares the
run layer's identity across every strategy; each `FrozenStrategy`/`FrozenDataModel` carries its
own. Nothing here is declared or on disk as itself: identities are hashed from explicit payloads
and records pick fields by name, which is why these stay dataclasses rather than becoming
pydantic (ExecPlan M6, 6a).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.identifiers import AgendaId, ModelStateRef
from vqapr.domain.values import ModelMemory, normalize_memory
from vqapr.exchange.execution_table import ExecutionTable
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import (
    FINGERPRINT_PREFIX,
    ConstraintSet,
    StrategyConfig,
    _encoded_requirements,
    _identity,
    _model_state_ref,
    _require_account,
    _require_id,
    _require_instruments,
    _require_period,
    _require_requirements,
    _require_value_fields,
)


@dataclass(frozen=True, slots=True)
class FrozenAgenda:
    """A resolved owner agenda identity and its inclusive run slice."""

    agenda_id: AgendaId
    occurrences: tuple[OperationOccurrence, ...]
    timezone: str = ""
    content_identity: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.occurrences, tuple):
            raise TypeError("occurrences must be a tuple of OperationOccurrence values")
        if not isinstance(self.timezone, str):
            raise TypeError("timezone must be an IANA timezone name")
        if not self.timezone and self.content_identity:
            raise ValueError("an agenda identity requires a timezone")
        if not isinstance(self.content_identity, str) or (
            self.content_identity and len(self.content_identity) != 64
        ):
            raise TypeError("content_identity must be a SHA-256 identity")
        for occurrence in self.occurrences:
            if not isinstance(occurrence, OperationOccurrence):
                raise TypeError("occurrences must contain OperationOccurrence values")

    def encoded(self) -> tuple[str, list[tuple[str, str, str, int, str]]]:
        """What a model's identity folds of its agenda: the sessions' CONTENT, not their name.

        The zone and each occurrence's local instant. Not the agenda id or the occurrence ids:
        since record `148` the agenda is derived from the run (`<run_id>.sessions`, occurrences
        `<run_id>.sessions-<date>`), so folding those would make the same strategy on the same
        sessions a different identity under every run id -- which is the run's identity, not
        the strategy's (owner ruling, 2026-09-03). Not a role either (record `182`): the one
        agenda has none, and the `STRATEGY_CALLBACK` a datamodel run's identity used to fold
        named a role that run never had.
        """
        return (
            self.timezone,
            [occurrence.local_instant.identity() for occurrence in self.occurrences],
        )


def merged_occurrences(*agendas: FrozenAgenda | None) -> tuple[OperationOccurrence, ...]:
    """The deterministic static dispatch order of several agendas: one sorted merge."""
    return tuple(
        sorted(
            (
                occurrence
                for agenda in agendas
                if agenda is not None
                for occurrence in agenda.occurrences
            ),
            key=OperationOccurrence.sort_key,
        )
    )


@dataclass(frozen=True, slots=True)
class FrozenStrategy:
    """One strategy's layer of a frozen run: what is its own and not the run's.

    Its identity folds the component fingerprint, its constraints, its agenda slice, its opening
    memory and what it reads. Two strategies in one run differ here and nowhere else.
    """

    config: StrategyConfig
    constraints: ConstraintSet
    agenda: FrozenAgenda
    requirements: tuple[DataRequirement, ...] = ()
    constraint_requirements: tuple[DataRequirement, ...] = ()
    initial_model_memory: ModelMemory = None
    initial_payload: bytes = b""
    initial_model_state_ref: ModelStateRef = field(init=False)
    _identity: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        if not isinstance(self.constraints, ConstraintSet):
            raise TypeError("constraints must be a ConstraintSet")
        if not isinstance(self.agenda, FrozenAgenda):
            raise TypeError("agenda must be a FrozenAgenda")
        if self.agenda.agenda_id != self.config.agenda_id:
            raise ValueError("agenda must match the strategy config's agenda_id")
        _require_requirements("requirements", self.requirements)
        _require_requirements("constraint_requirements", self.constraint_requirements)
        memory = normalize_memory(self.initial_model_memory)
        object.__setattr__(self, "initial_model_memory", memory)
        if not isinstance(self.initial_payload, bytes):
            raise TypeError("initial_payload must be bytes")
        object.__setattr__(self, "initial_payload", bytes(self.initial_payload))
        object.__setattr__(
            self, "initial_model_state_ref", _model_state_ref(memory, self.initial_payload)
        )

    @property
    def component_id(self) -> str:
        return str(self.config.component.component_id)

    @property
    def record_ref(self) -> str:
        """The name of this strategy's record directory: `<component_id>@<fingerprint[:8]>`.

        Content-addressed by the REGISTERED fingerprint, which folds the file bytes, the object
        name and the config: a condition tweaked in `config` makes a new directory beside the
        old one, which is what makes "how many times was this strategy tweaked" a directory count
        (architecture §17.4).
        """
        return f"{self.component_id}@{self.config.component.fingerprint[:FINGERPRINT_PREFIX]}"

    @property
    def identity(self) -> str:
        if not self._identity:
            object.__setattr__(
                self,
                "_identity",
                _identity(
                    {
                        "strategy": (
                            self.component_id,
                            self.config.component.fingerprint,
                        ),
                        "constraints": [
                            (constraint.component_id, constraint.fingerprint)
                            for constraint in self.constraints.constraints
                        ],
                        "agenda": self.agenda.encoded(),
                        "initial_model_memory": self.initial_model_memory,
                        "initial_model_state_ref": self.initial_model_state_ref.digest,
                        "initial_payload": self.initial_payload.hex(),
                        "requirements": _encoded_requirements(self.requirements),
                        "constraint_requirements": _encoded_requirements(
                            self.constraint_requirements
                        ),
                    }
                ),
            )
        return self._identity


@dataclass(frozen=True, slots=True)
class FrozenDataModel:
    """One datamodel's layer of a frozen run: the component, its agenda slice, and its output.

    The datamodel counterpart of `FrozenStrategy`, minus what a datamodel has none of: no
    constraints, no account, no payload. Its identity folds the component fingerprint, the
    agenda slice, the output declaration, its opening memory and what it reads.
    """

    component: ComponentRef
    agenda: FrozenAgenda
    dataset_id: str
    value_fields: tuple[str, ...]
    requirements: tuple[DataRequirement, ...] = ()
    initial_model_memory: ModelMemory = None
    _identity: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.component, ComponentRef):
            raise TypeError("component must be a ComponentRef")
        if self.component.kind is not ComponentKind.DATA_MODEL:
            raise ValueError("component must identify a DATA_MODEL")
        if not isinstance(self.agenda, FrozenAgenda):
            raise TypeError("agenda must be a FrozenAgenda")
        _require_id(self.dataset_id, "dataset_id")
        _require_value_fields(self.value_fields)
        _require_requirements("requirements", self.requirements)
        object.__setattr__(
            self, "initial_model_memory", normalize_memory(self.initial_model_memory)
        )

    @property
    def component_id(self) -> str:
        return str(self.component.component_id)

    @property
    def record_ref(self) -> str:
        """The name of this datamodel's record directory: `<component_id>@<fingerprint[:8]>`."""
        return f"{self.component_id}@{self.component.fingerprint[:FINGERPRINT_PREFIX]}"

    @property
    def identity(self) -> str:
        if not self._identity:
            object.__setattr__(
                self,
                "_identity",
                _identity(
                    {
                        "datamodel": (self.component_id, self.component.fingerprint),
                        "agenda": self.agenda.encoded(),
                        "output": (self.dataset_id, list(self.value_fields)),
                        "initial_model_memory": self.initial_model_memory,
                        "requirements": _encoded_requirements(self.requirements),
                    }
                ),
            )
        return self._identity


@dataclass(frozen=True, slots=True)
class FrozenRun:
    """Frozen owner declarations retained by a future preflight result.

    The run layer -- what every strategy shares -- plus the frozen strategies. `identity` is the
    run layer's alone, so adding a strategy to a run does not rename the rows the others wrote;
    `requirements`, `datasets` and `sources` are the union every strategy and constraint reads,
    which is the panel set (design §4.1).
    """

    run_id: str
    strategies: tuple[FrozenStrategy, ...]
    datamodels: tuple[FrozenDataModel, ...] = field(default=(), kw_only=True)
    exchange: ComponentRef | None = None
    execution: ExecutionTable | None = None
    start: datetime | None = None
    end: datetime | None = None
    initial_account_snapshot: AccountSnapshot | None = None
    initial_account_mode: AccountMode | None = None
    instruments: tuple[str, ...] = ()
    instrument_set: frozenset[str] = field(init=False, repr=False, compare=False)
    requirements: tuple[DataRequirement, ...] = ()
    datasets: tuple[DatasetRegistration, ...] = ()
    sources: tuple[SourceSpec, ...] = ()
    _identity: str = field(default="", init=False, repr=False, compare=False)
    """Memo for `identity`, which every frozen field already determines.

    A run reads this about sixteen times per callback, and deriving it walks every occurrence of
    every agenda. Recomputing therefore cost O(occurrences) per callback -- quadratic in run
    length -- to produce a string that cannot change once `__post_init__` returns.
    """

    def __post_init__(self) -> None:
        _require_id(self.run_id, "run_id")
        if not isinstance(self.strategies, tuple) or any(
            not isinstance(layer, FrozenStrategy) for layer in self.strategies
        ):
            raise TypeError("strategies must contain FrozenStrategy values")
        if not isinstance(self.datamodels, tuple) or any(
            not isinstance(layer, FrozenDataModel) for layer in self.datamodels
        ):
            raise TypeError("datamodels must contain FrozenDataModel values")
        if bool(self.strategies) == bool(self.datamodels):
            raise ValueError("a frozen run holds strategies or datamodels, at least one, not both")
        ids = [layer.component_id for layer in (*self.strategies, *self.datamodels)]
        if len(set(ids)) != len(ids):
            raise ValueError("a frozen run holds each model at most once")
        if self.datamodels and (
            self.exchange is not None
            or self.execution is not None
            or self.initial_account_snapshot is not None
        ):
            raise ValueError("a frozen datamodel run holds no venue, execution dataset or account")
        if self.exchange is not None:
            if not isinstance(self.exchange, ComponentRef):
                raise TypeError("exchange must be a ComponentRef or None")
            if self.exchange.kind is not ComponentKind.EXCHANGE:
                raise ValueError("exchange must identify an EXCHANGE component")
        if (self.exchange is None) != (self.execution is None):
            raise ValueError("exchange and execution must be frozen together")
        if self.execution is not None and not isinstance(self.execution, ExecutionTable):
            raise TypeError("execution must be an ExecutionTable or None")
        _require_period(self.start, self.end, "frozen")
        object.__setattr__(
            self,
            "initial_account_snapshot",
            _require_account(self.initial_account_snapshot, self.initial_account_mode, "frozen"),
        )
        # The uniqueness check needs this set anyway; keeping it turns per-callback universe
        # membership from a linear tuple scan into a hash lookup.
        object.__setattr__(self, "instrument_set", _require_instruments(self.instruments))
        _require_requirements("requirements", self.requirements)
        if not isinstance(self.datasets, tuple) or not all(
            isinstance(dataset, DatasetRegistration) for dataset in self.datasets
        ):
            raise TypeError("datasets must be a tuple of DatasetRegistration values")
        dataset_ids = [dataset.dataset_id for dataset in self.datasets]
        if len(set(dataset_ids)) != len(dataset_ids) or dataset_ids != sorted(dataset_ids):
            raise ValueError("datasets must be unique and ordered by dataset_id")
        object.__setattr__(
            self,
            "datasets",
            tuple(
                # Detaching copies the MEASUREMENTS too, not just the declaration. `aggregated`
                # decides which query the read path composes, so a copy that dropped it would
                # read a grouped registration row-wise -- the same rows, silently ungrouped, with
                # no error anywhere. `span` is carried for the same reason
                # this copy exists at all: a frozen run must describe what was registered.
                # By keyword: `grain` joined the registration between `fields` and `span`
                # (record `137`), and a positional rebuild put the span into it.
                DatasetRegistration(
                    dataset_id=dataset.dataset_id,
                    source=dataset.source,
                    instrument_field=dataset.instrument_field,
                    available_at=dataset.available_at,
                    key_fields=dataset.key_fields,
                    fields=MappingProxyType(dict(dataset.fields)),
                    grain=dataset.grain,
                    span=dataset.span,
                    field_types=None
                    if dataset.field_types is None
                    else MappingProxyType(dict(dataset.field_types)),
                    aggregated=dataset.aggregated,
                )
                for dataset in self.datasets
            ),
        )
        if not isinstance(self.sources, tuple) or not all(
            isinstance(source, SourceSpec) for source in self.sources
        ):
            raise TypeError("sources must be a tuple of SourceSpec values")
        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("sources must not contain duplicate source declarations")
        if source_ids != sorted(source_ids):
            raise ValueError("sources must be ordered by source_id")

    @property
    def kind(self) -> str:
        return "datamodel" if self.datamodels else "strategy"

    @property
    def members(self) -> tuple[FrozenStrategy | FrozenDataModel, ...]:
        return (*self.strategies, *self.datamodels)

    def strategy(self, component_id: str) -> FrozenStrategy:
        for layer in self.strategies:
            if layer.component_id == component_id:
                return layer
        raise KeyError(
            f"run {self.run_id!r} froze no strategy {component_id!r}; it holds "
            f"{', '.join(layer.component_id for layer in self.members)}"
        )

    def datamodel(self, component_id: str) -> FrozenDataModel:
        for layer in self.datamodels:
            if layer.component_id == component_id:
                return layer
        raise KeyError(
            f"run {self.run_id!r} froze no datamodel {component_id!r}; it holds "
            f"{', '.join(layer.component_id for layer in self.members)}"
        )

    def member(self, component_id: str) -> FrozenStrategy | FrozenDataModel:
        return self.datamodel(component_id) if self.datamodels else self.strategy(component_id)

    def dispatch_order(
        self, layer: FrozenStrategy | FrozenDataModel
    ) -> tuple[OperationOccurrence, ...]:
        """The static occurrences one model's flow dispatches: its sessions, at `at`.

        Since record `148` a run has one agenda: the book is valued at the instant the venue
        fills and monitored right after each commit, so there is nothing else to merge in.
        """
        return merged_occurrences(layer.agenda)

    @property
    def identity(self) -> str:
        """Canonical identity of the run layer: what every strategy in this run shares."""
        if not self._identity:
            object.__setattr__(self, "_identity", self._derive_identity())
        return self._identity

    def _derive_identity(self) -> str:
        snapshot = self.initial_account_snapshot
        mode = self.initial_account_mode
        if (snapshot is None) != (mode is None):
            raise RuntimeError("initial account snapshot and mode were frozen apart")
        return _identity(
            {
                "run_id": self.run_id,
                "exchange": (
                    (self.exchange.component_id, self.exchange.fingerprint)
                    if self.exchange is not None
                    else None
                ),
                "execution": (
                    {
                        "dataset_id": self.execution.dataset_id,
                        "source": (
                            self.execution.table.source.source_id,
                            str(self.execution.table.source.path),
                            self.execution.table.source.hive_partitioned,
                        ),
                        "table": (
                            self.execution.table.trade_at_field,
                            self.execution.table.instrument_field,
                            self.execution.table.is_tradable_field,
                            tuple(sorted(self.execution.table.price_fields.items())),
                        ),
                        "fill": self.execution.fill.declaration_identity,
                    }
                    if self.execution is not None
                    else None
                ),
                "start": self.start.astimezone(UTC).isoformat() if self.start is not None else None,
                "end": self.end.astimezone(UTC).isoformat() if self.end is not None else None,
                "initial_account": (
                    (
                        mode.value,
                        snapshot.version,
                        str(snapshot.cash),
                        tuple(
                            (instrument, str(quantity))
                            for instrument, quantity in snapshot.positions.items()
                        ),
                    )
                    if snapshot is not None and mode is not None
                    else None
                ),
                "instruments": self.instruments,
                "requirements": _encoded_requirements(self.requirements),
                "datasets": [
                    (
                        dataset.dataset_id,
                        dataset.source,
                        dataset.instrument_field,
                        dataset.available_at,
                        dataset.key_fields,
                        tuple(sorted(dataset.fields.items())),
                    )
                    for dataset in self.datasets
                ],
                "sources": [
                    (source.source_id, str(source.path), source.hive_partitioned)
                    for source in self.sources
                ],
            }
        )
