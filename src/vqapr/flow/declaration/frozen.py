"""The run, frozen: what preflight fixes once per run and once per member, and their identities.

Split out of `flow/declaration/run.py` (one-shape campaign Step 6, record 161): `run.py` is the
declaration -- what a document registers -- and this is what preflight makes of it. A `FrozenRun`
carries the run layer's identity and its one `FrozenStrategy`/`FrozenDataModel` carries its own.
Nothing here is declared or on disk as itself: identities are hashed from explicit payloads and
records pick fields by name, which is why these stay dataclasses rather than becoming pydantic
(ExecPlan M6, 6a).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

from vqapr.account.account import AccountMode
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.identifiers import AgendaId, ModelStateRef
from vqapr.domain.values import ModelMemory, normalize_memory
from vqapr.exchange.execution_table import ExecutionTable
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.project.run import (
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
        if not self.agenda_id:
            raise ValueError("agenda_id must be a non-empty AgendaId")
        if not self.timezone and self.content_identity:
            raise ValueError("an agenda identity requires a timezone")
        if self.content_identity and len(self.content_identity) != 64:
            raise ValueError("content_identity must be a SHA-256 identity")

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
        if self.agenda.agenda_id != self.config.agenda_id:
            raise ValueError("agenda must match the strategy config's agenda_id")
        _require_requirements("requirements", self.requirements)
        _require_requirements("constraint_requirements", self.constraint_requirements)
        memory = normalize_memory(self.initial_model_memory)
        object.__setattr__(self, "initial_model_memory", memory)
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
    value_fields: tuple[str, ...]
    requirements: tuple[DataRequirement, ...] = ()
    initial_model_memory: ModelMemory = None
    _identity: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.component.kind is not ComponentKind.DATA_MODEL:
            raise ValueError("component must identify a DATA_MODEL")
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
                        "output": list(self.value_fields),
                        "initial_model_memory": self.initial_model_memory,
                        "requirements": _encoded_requirements(self.requirements),
                    }
                ),
            )
        return self._identity


@dataclass(frozen=True, slots=True)
class FrozenRun:
    """Frozen owner declarations retained by a future preflight result.

    The run layer -- period, venue, data -- plus the one frozen model. `identity` is the
    run layer's alone, so adding a strategy to a run does not rename the rows the others wrote;
    `requirements`, `datasets` and `sources` are the union every strategy and constraint reads,
    which is the panel set (design §4.1).
    """

    run_id: str
    writes: str
    """The dataset this run publishes -- the run layer's, shared by no one
    (design §2): identity folds it, because two runs writing different names are two
    arrows even when everything else about them is the same."""
    strategy: FrozenStrategy | None = None
    datamodel: FrozenDataModel | None = field(default=None, kw_only=True)
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
        _require_id(self.writes, "writes")
        if (self.strategy is None) == (self.datamodel is None):
            raise ValueError("a frozen run holds one strategy or one datamodel, not both")
        if self.datamodel is not None and (
            self.exchange is not None
            or self.execution is not None
            or self.initial_account_snapshot is not None
        ):
            raise ValueError("a frozen datamodel run holds no venue, execution dataset or account")
        if self.exchange is not None and self.exchange.kind is not ComponentKind.EXCHANGE:
            raise ValueError("exchange must identify an EXCHANGE component")
        if (self.exchange is None) != (self.execution is None):
            raise ValueError("exchange and execution must be frozen together")
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
        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("sources must not contain duplicate source declarations")
        if source_ids != sorted(source_ids):
            raise ValueError("sources must be ordered by source_id")

    @property
    def kind(self) -> str:
        return "datamodel" if self.datamodel is not None else "strategy"

    @property
    def member(self) -> FrozenStrategy | FrozenDataModel:
        """The one model this run froze, whichever kind it holds."""
        one = self.strategy if self.strategy is not None else self.datamodel
        if one is None:  # pragma: no cover -- `__post_init__` refuses this
            raise ValueError(f"run {self.run_id!r} froze no model")
        return one

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
                        "writes": self.writes,
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
