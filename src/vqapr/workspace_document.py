"""The workspace document and the declaration document, as pydantic models.

One model per YAML section: the shape a section has on disk (`workspace.yaml`) and in a
declaration an author registers. Key sets, scalar types, enums, dates and times are the model's
field declarations; pydantic checks them, and `declarations.refusals_from` turns what it finds
into this package's refusals. Nothing here opens a file, resolves a path or looks another
section up -- a model is a shape, and the cross-reference checks stay with the workspace.

Record `145` (deletion campaign Step 4): these models replaced the hand-written `_decode` /
`_encode` / `_detach_*` of the former `workspace_codec.py` and the `_require_keys` / `_mapping` /
`_enum` family in `declarations.py`, one section at a time, and the codec file was deleted. The
legacy document shapes a released workspace can still carry (an old fill schema, the agenda-keyed
strategy config, the two retired sections) are all declared in this one file, so a later release
that retires one discards a region rather than hunting for it. Where the stored shape and the domain
dataclass coincide, `to_domain` is a one-liner; where they differ (a dataset's measured span, an
agenda's occurrences, a run's initial account) the model is the one place the mapping is written.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    ValidationError,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.datasets import DatasetRegistration, Grain
from vqapr.data.scan import ColumnType, ProjectionSchema
from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import component_id, dataset_id, execution_input_id, source_id
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import DataModelEntry, RunDefinition, StrategyEntry


class Document(BaseModel):
    """Every section model: frozen, and an unknown key is a refusal rather than a warning."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)


class SourceDocument(Document):
    """`sources.<source_id>` on disk, and the inline `source:` block of a dataset declaration.

    `path` is a string here: on disk it is whatever the registration recorded, in a declaration
    it is relative to the declaration file, and resolving it is the declaration reader's job.
    """

    path: str
    hive_partitioned: bool = False

    def to_domain(self, source_id: str) -> SourceSpec:
        return SourceSpec.of(source_id, self.path, hive_partitioned=self.hive_partitioned)

    @classmethod
    def from_domain(cls, source: SourceSpec) -> SourceDocument:
        return cls(path=str(source.path), hive_partitioned=source.hive_partitioned)


class DatasetDocument(Document):
    """`datasets.<dataset_id>` on disk: five declared keys, then whatever has been measured.

    Two measurements on two independent axes, four admissible shapes. `span` is added by the
    release that made it mandatory; `field_types` + `aggregated` were added when a field became
    an expression (`docs/issues/049`). Neither is a declaration, so neither can be invented for an
    entry that predates it: an entry without `span` decodes into a QUARANTINED registration --
    enumerable, removable, re-registrable, refused on read -- rather than into a refusal that
    would take `list` and `register` offline together (the deadlock `test_workspace.py` pins).
    `grain` is optional on read for the same reason (`DatasetRegistration.undeclared`).

    Absent measurements are written back absent, so a document upgrades one entry at a time.
    """

    source: str
    instrument_field: str | None
    available_at: str
    key_fields: list[str]
    fields: dict[str, str]
    grain: Grain | None = None
    field_types: dict[str, ColumnType] | None = None
    aggregated: bool | None = None
    span: tuple[datetime, datetime] | None = None

    @model_validator(mode="after")
    def _measurements_travel_together(self) -> DatasetDocument:
        if (self.field_types is None) != (self.aggregated is None):
            raise ValueError(
                "field_types and aggregated are one measurement; declare both or neither"
            )
        if self.field_types is not None and set(self.field_types) != set(self.fields):
            raise ValueError("field_types must type every declared field")
        return self

    @model_serializer(mode="wrap")
    def _absent_measurements_stay_absent(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        body = handler(self)
        for measured in ("grain", "field_types", "aggregated", "span"):
            if body.get(measured) is None:
                del body[measured]
        if "span" in body:
            body["span"] = [self.span[0].isoformat(), self.span[1].isoformat()]  # type: ignore[index]
        return body

    def to_domain(self, dataset_id: str) -> DatasetRegistration:
        declared = dict(
            instrument_field=self.instrument_field,
            available_at=self.available_at,
            key_fields=self.key_fields,
            fields=self.fields,
        )
        registration = (
            DatasetRegistration.undeclared(dataset_id, self.source, **declared)
            if self.grain is None
            else DatasetRegistration.of(dataset_id, self.source, grain=self.grain, **declared)
        )
        if self.field_types is not None:
            registration = registration.with_schema(
                ProjectionSchema(self.field_types, bool(self.aggregated))
            )
        if self.span is not None:
            registration = registration.with_span(*self.span)
        return registration

    @classmethod
    def from_domain(cls, registration: DatasetRegistration) -> DatasetDocument:
        return cls(
            source=str(registration.source),
            instrument_field=registration.instrument_field,
            available_at=registration.available_at,
            key_fields=list(registration.key_fields),
            fields=dict(registration.fields),
            grain=registration.grain,
            field_types=(
                None if registration.field_types is None else dict(registration.field_types)
            ),
            aggregated=None if registration.field_types is None else registration.aggregated,
            span=registration.span,
        )


class FillDocument(Document):
    """`execution_inputs.<id>.fill`: which session instant, which price, and the DST proof."""

    selector: FillSelector
    local_time: time
    timezone: str
    trade_price: str
    fold: int | None = None
    offset: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _the_two_shapes_this_is_not(cls, raw: object) -> object:
        # Named refusals for the two shapes an old document can carry, kept from the codec they
        # replace: `Workspace._read` surfaces these sentences as the requirement itself.
        if isinstance(raw, dict):
            if "offset_sessions" in raw:
                raise ValueError("fill offset_sessions is no longer supported")
            if set(raw) == {"selector", "local_time", "timezone", "trade_price"}:
                raise ValueError("uses the old fill schema without fold and offset proof")
        return raw

    def to_domain(self) -> FillConvention:
        return FillConvention(
            selector=self.selector,
            local_time=self.local_time,
            timezone=self.timezone,
            trade_price=self.trade_price,
            fold=self.fold,
            offset=self.offset,
        )

    @classmethod
    def from_domain(cls, fill: FillConvention) -> FillDocument:
        return cls(
            selector=fill.selector,
            local_time=fill.local_time,
            timezone=fill.timezone,
            trade_price=fill.trade_price,
            fold=fill.fold,
            offset=fill.offset,
        )


class ExecutionInputDocument(Document):
    """`execution_inputs.<execution_input_id>` on disk."""

    source: str
    trade_at_field: str
    instrument_field: str
    is_tradable_field: str
    price_fields: dict[str, str]
    fill: FillDocument

    def to_domain(self, execution_input_id: str, source: SourceSpec) -> ExecutionInputRegistration:
        return ExecutionInputRegistration.of(
            execution_input_id,
            ExecutionTableSpec(
                source=source,
                trade_at_field=self.trade_at_field,
                instrument_field=self.instrument_field,
                is_tradable_field=self.is_tradable_field,
                price_fields=self.price_fields,
            ),
            self.fill.to_domain(),
        )

    @classmethod
    def from_domain(cls, registration: ExecutionInputRegistration) -> ExecutionInputDocument:
        table = registration.table
        return cls(
            source=str(table.source.source_id),
            trade_at_field=table.trade_at_field,
            instrument_field=table.instrument_field,
            is_tradable_field=table.is_tradable_field,
            price_fields=dict(table.price_fields),
            fill=FillDocument.from_domain(registration.fill),
        )


class ComponentDocument(Document):
    """`components.<component_id>` on disk: where the code is, what it is, and its fingerprint."""

    kind: ComponentKind
    path: str
    object_name: str
    config: dict[str, Any]
    fingerprint: str

    def to_domain(self, component_id: str) -> ComponentRef:
        return ComponentRef.of(
            component_id,
            self.kind,
            self.path,
            self.object_name,
            config=self.config,
            fingerprint=self.fingerprint,
        )

    @classmethod
    def from_domain(cls, ref: ComponentRef) -> ComponentDocument:
        return cls(
            kind=ref.kind,
            path=str(ref.path),
            object_name=ref.object_name,
            config=dict(ref.config),
            fingerprint=ref.fingerprint,
        )


class InitialAccountDocument(Document):
    """`runs.<id>.initial_account`: the declaration every strategy's own Account starts from."""

    cash: Decimal
    mode: AccountMode
    positions: dict[str, Decimal] = {}
    version: int = 0

    @field_validator("mode", mode="before")
    @classmethod
    def _by_name_as_written(cls, value: object) -> object:
        # Written and read by member NAME (`LONG_ONLY`), which is what the template shows and
        # `vqapr new run` derives its comment from; the enum's value is the lower-case spelling.
        if isinstance(value, str):
            try:
                return AccountMode[value.upper()]
            except KeyError:
                return value
        return value

    @field_serializer("mode")
    def _name(self, mode: AccountMode) -> str:
        return mode.name

    @field_serializer("cash")
    def _cash(self, cash: Decimal) -> str:
        return str(cash)

    @field_serializer("positions")
    def _positions(self, positions: dict[str, Decimal]) -> dict[str, str]:
        return {name: str(quantity) for name, quantity in sorted(positions.items())}


class StrategyEntryDocument(Document):
    """`runs.<id>.strategies.<component_id>`: constraints and opening memory, both optional."""

    constraints: list[str] = []
    initial_model_memory: Any = None

    @model_serializer(mode="wrap")
    def _only_what_was_declared(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        body = handler(self)
        if not body.get("constraints"):
            body.pop("constraints", None)
        if body.get("initial_model_memory") is None:
            body.pop("initial_model_memory", None)
        return body


class DataModelEntryDocument(Document):
    """`runs.<id>.datamodels.<component_id>`: the dataset this datamodel writes (record `148`)."""

    dataset_id: str
    value_fields: list[str]
    initial_model_memory: Any = None

    @model_serializer(mode="wrap")
    def _only_what_was_declared(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        body = handler(self)
        if body.get("initial_model_memory") is None:
            body.pop("initial_model_memory", None)
        return body


class RunDocument(Document):
    """`runs.<run_id>` on disk and in a declaration -- the same shape, so a run can be copied
    out of `workspace.yaml` into a declaration and back.

    A registered run is run-ready: everything `vqapr run` cannot execute without is required
    here, nullable only where `RunDefinition` keeps it optional for in-process callers. The
    sessions come from exactly one of `sessions_from` (a registered dataset's days) or `sessions`.
    """

    instruments: list[str]
    start: datetime | None
    end: datetime | None
    timezone: str
    at: time
    exchange: str | None = None
    execution_input: str | None = None
    initial_account: InitialAccountDocument | None = None
    strategies: dict[str, StrategyEntryDocument | None] | None = None
    datamodels: dict[str, DataModelEntryDocument] | None = None
    sessions_from: str | None = None
    sessions: list[date] | None = None

    @model_validator(mode="after")
    def _one_kind_and_one_session_source(self) -> RunDocument:
        if bool(self.strategies) == bool(self.datamodels):
            raise ValueError(
                "must name at least one model under exactly one of `strategies:` or "
                "`datamodels:` (record 148: a run holds one kind)"
            )
        if self.datamodels:
            declared = [
                key
                for key, value in (
                    ("exchange", self.exchange),
                    ("execution_input", self.execution_input),
                    ("initial_account", self.initial_account),
                )
                if value is not None
            ]
            if declared:
                raise ValueError(
                    f"a datamodel run declares no {', '.join(declared)}: a datamodel sees no "
                    "account and passes through no venue"
                )
        if (self.sessions_from is None) == (self.sessions is None):
            raise ValueError(
                "must declare exactly one of sessions_from (a registered dataset's days) or "
                "sessions (a list of dates)"
            )
        if self.sessions is not None and not self.sessions:
            raise ValueError("sessions must list at least one date")
        return self

    @field_validator("start", "end")
    @classmethod
    def _one_instant(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("must include a UTC offset; a naive datetime is not one instant")
        return value

    @model_serializer(mode="wrap")
    def _monitoring_only_when_declared(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        body = handler(self)
        optionals = ("sessions_from", "sessions", "initial_account", "strategies", "datamodels")
        for optional in optionals:
            if body.get(optional) is None:
                body.pop(optional, None)
        if "strategies" in body:
            body["strategies"] = {
                name: (entry or {}) for name, entry in body["strategies"].items()
            }
        return body

    def to_domain(self, run_id: str) -> RunDefinition:
        account = self.initial_account
        return RunDefinition(
            run_id=run_id,
            strategies=tuple(
                StrategyEntry(
                    name,
                    tuple(entry.constraints) if entry else (),
                    entry.initial_model_memory if entry else None,
                )
                for name, entry in (self.strategies or {}).items()
            ),
            datamodels=tuple(
                DataModelEntry(
                    name,
                    entry.dataset_id,
                    tuple(entry.value_fields),
                    entry.initial_model_memory,
                )
                for name, entry in (self.datamodels or {}).items()
            ),
            instruments=tuple(self.instruments),
            timezone=self.timezone,
            at=self.at,
            sessions_from=self.sessions_from,
            sessions=tuple(self.sessions or ()),
            exchange=self.exchange,
            execution_input_id=self.execution_input,
            start=self.start,
            end=self.end,
            initial_account_snapshot=(
                None
                if account is None
                else AccountSnapshot(
                    version=account.version, cash=account.cash, positions=account.positions
                )
            ),
            initial_account_mode=None if account is None else account.mode,
        )

    @classmethod
    def from_domain(cls, definition: RunDefinition) -> RunDocument:
        snapshot, mode = definition.initial_account_snapshot, definition.initial_account_mode
        return cls(
            instruments=list(definition.instruments),
            start=definition.start,
            end=definition.end,
            timezone=definition.timezone,
            at=definition.at,  # type: ignore[arg-type]
            sessions_from=definition.sessions_from,
            sessions=list(definition.sessions) or None,
            exchange=definition.exchange,
            execution_input=definition.execution_input_id,
            initial_account=(
                None
                if snapshot is None or mode is None
                else InitialAccountDocument(
                    cash=snapshot.cash,
                    mode=mode,
                    positions=dict(snapshot.positions),
                    version=snapshot.version,
                )
            ),
            strategies={
                entry.component_id: StrategyEntryDocument(
                    constraints=list(entry.constraints),
                    initial_model_memory=entry.initial_model_memory,
                )
                for entry in definition.strategies
            }
            or None,
            datamodels={
                entry.component_id: DataModelEntryDocument(
                    dataset_id=entry.dataset_id,
                    value_fields=list(entry.value_fields),
                    initial_model_memory=entry.initial_model_memory,
                )
                for entry in definition.datamodels
            }
            or None,
        )


# ---------------------------------------------------------------------------------------------
# The declaration document: what an author writes and `vqapr register` reads. Same sections,
# fewer keys (nothing measured, nothing derived) and, for a dataset and an execution input, the
# source written inline because the two register as a pair. Enum values are the lower-case names
# the templates show; `Literal` here so a wrong one is refused with the permitted set, and the
# domain enum is looked up by name in `to_domain`.
# ---------------------------------------------------------------------------------------------


def _lowered(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


class DatasetDeclaration(Document):
    """`datasets.<dataset_id>` in a declaration: the projection, and the file, inline."""

    source_id: str
    path: str
    hive_partitioned: bool = False
    instrument_field: str | None = None
    available_at: str
    key_fields: list[str]
    fields: dict[str, str]
    grain: Grain | None = None
    """Optional on the model only so that `declarations._require_grain_key` can refuse its
    absence with the sentence that says what changed (design §7-3), before the model is asked."""


class TableDeclaration(Document):
    """`execution_inputs.<id>.table`: the venue table and its file, inline."""

    source_id: str
    path: str
    hive_partitioned: bool = False
    trade_at_field: str
    instrument_field: str
    is_tradable_field: str
    price_fields: dict[str, str]


class FillDeclaration(Document):
    """`execution_inputs.<id>.fill` as declared: no DST proof yet, `at` for the wall time."""

    selector: Literal["same_day", "next_eligible"]
    at: time
    timezone: str
    trade_price: str

    _lower = field_validator("selector", mode="before")(_lowered)


class ExecutionInputDeclaration(Document):
    table: TableDeclaration
    fill: FillDeclaration


class ComponentDeclaration(Document):
    """`components.<component_id>`: where the code is and what it is, in the CLI's spelling."""

    kind: Literal["datamodel", "strategy", "constraint", "exchange"]
    path: str
    object_name: str
    config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------------------------
# The whole document, and the two functions between its text and the workspace's state.
# ---------------------------------------------------------------------------------------------

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_YAML_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
"""libyaml when the installed PyYAML was built with it, the pure-Python classes otherwise.

The workspace holds every agenda occurrence, so the file grows with run length rather than with
the number of declarations: a three-year daily agenda set is roughly 750 KB. Parsing that with
PyYAML's pure-Python loader costs about 1.1 s and emitting it about 0.5 s, against 0.24 s and
0.14 s through libyaml, and a registration pays both. The emitted bytes are identical between the
two dumpers for every document this module writes, which `tests/test_workspace.py` pins.
"""

_READ_CACHE_LIMIT = 8
_read_cache: dict[str, tuple[dict, ...]] = {}
"""Decoded workspaces keyed by the sha256 of their exact text.

Every registration reads the file twice -- once through `Workspace.create`, once inside the
exclusive lock -- and a process usually makes several registrations in a row against a file that
only grows by one declaration each time. Keying on content rather than on path or mtime means a
hit is only possible for bytes that were already decoded, so no writer, in this process or
another, can be served a stale workspace.
"""


class WorkspaceDocument(Document):
    """`workspace.yaml` whole: seven sections, two of them required, and two read and dropped.

    Four sections are read and dropped, so a document written by 0.3.0 opens: `valuation_configs`
    and `monitoring_policies` (record `144`, each restated an agenda's own role) and `agendas` and
    `strategy_configs` (record `148`: a run declares its sessions and wall times itself, and the
    model is called every session). A 0.3.0 `runs:` entry, which named agendas instead, is
    refused at open naming the run and the keys it now needs.
    """

    sources: dict[str, SourceDocument]
    datasets: dict[str, DatasetDocument]
    execution_inputs: dict[str, ExecutionInputDocument] = {}
    components: dict[str, ComponentDocument] = {}
    runs: dict[str, RunDocument] = {}
    valuation_configs: Any = None
    monitoring_policies: Any = None
    agendas: Any = None
    strategy_configs: Any = None


def _decoded[M: BaseModel](kind: str, raw_id: str, model: type[M], raw: object) -> M:
    """One section entry through its model, or a `ValueError` that names the entry and the fault.

    The document read path has one refusal, `workspace.open.invalid`, and `Workspace._read`
    reads the sentence of a few faults out of it (an old fill schema, a retired key). So the
    first error's own words are kept in the sentence, prefixed with which entry they are about.
    """
    try:
        return model.model_validate(raw)
    except ValidationError as invalid:
        first = invalid.errors(include_url=False)[0]
        where = ".".join(str(part) for part in first["loc"])
        words = str(first["msg"]).removeprefix("Value error, ")
        raise ValueError(f"{kind} {raw_id!r}{': ' + where if where else ''} {words}") from invalid


def read_workspace(text: str) -> tuple[dict, ...]:
    """The document's text as the workspace's seven state mappings, memoized on the exact bytes.

    Copies of the cached sections are returned: callers merge a declaration into copies rather
    than mutating what they were handed, but a cached section is a shared object and one caller
    mutating it would silently rewrite another caller's view of the workspace.
    """
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cached = _read_cache.get(key)
    if cached is None:
        cached = _linked(yaml.load(text, Loader=_YAML_LOADER))
        if len(_read_cache) >= _READ_CACHE_LIMIT:
            _read_cache.clear()
        _read_cache[key] = cached
    return tuple(dict(section) for section in cached)


def _linked(raw: object) -> tuple[dict, ...]:
    """Every section through its model, then every forward reference checked.

    A document naming an absent source, component or agenda is refused at read time rather than
    at the first command that needs the missing declaration, which is also what lets `remove`
    check references against one snapshot and never leave a dangling one behind.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            "workspace root must contain sources and datasets, with optional execution_inputs, "
            "components and runs"
        )
    document = _decoded("workspace", "root", WorkspaceDocument, raw)

    sources = {}
    for raw_id, entry in document.sources.items():
        source = entry.to_domain(raw_id)
        sources[source.source_id] = source

    datasets = {}
    for raw_id, entry in document.datasets.items():
        registration = entry.to_domain(raw_id)
        if registration.source not in sources:
            raise ValueError(
                f"dataset {raw_id!r} references unregistered source {registration.source!r}"
            )
        datasets[registration.dataset_id] = registration

    execution_inputs = {}
    for raw_id, entry in document.execution_inputs.items():
        source_key = source_id(entry.source)
        if source_key not in sources:
            raise ValueError(
                f"execution input {raw_id!r} references unregistered source {source_key!r}"
            )
        registration = entry.to_domain(raw_id, sources[source_key])
        execution_inputs[registration.execution_input_id] = registration

    components = {}
    for raw_id, entry in document.components.items():
        ref = entry.to_domain(raw_id)
        components[ref.component_id] = ref

    runs = {}
    for raw_id, entry in document.runs.items():
        definition = entry.to_domain(raw_id)
        for strategy in definition.strategies:
            component = components.get(component_id(strategy.component_id))
            if component is None or component.kind is not ComponentKind.STRATEGY_MODEL:
                raise ValueError(f"run {raw_id!r} names an unregistered strategy")
            for name in strategy.constraints:
                constraint = components.get(component_id(name))
                if constraint is None or constraint.kind is not ComponentKind.CONSTRAINT:
                    raise ValueError(f"run {raw_id!r} names an unregistered constraint")
        for datamodel in definition.datamodels:
            component = components.get(component_id(datamodel.component_id))
            if component is None or component.kind is not ComponentKind.DATA_MODEL:
                raise ValueError(f"run {raw_id!r} names an unregistered datamodel")
        if definition.exchange is not None:
            venue = components.get(component_id(definition.exchange))
            if venue is None or venue.kind is not ComponentKind.EXCHANGE:
                raise ValueError(f"run {raw_id!r} names an unregistered exchange")
        if (
            definition.execution_input_id is not None
            and execution_input_id(definition.execution_input_id) not in execution_inputs
        ):
            raise ValueError(f"run {raw_id!r} names an unregistered execution input")
        if (
            definition.sessions_from is not None
            and dataset_id(definition.sessions_from) not in datasets
        ):
            raise ValueError(f"run {raw_id!r} takes its sessions from an unregistered dataset")
        runs[raw_id] = definition

    return (datasets, sources, execution_inputs, components, runs)


def write_workspace(
    datasets: Mapping[Any, DatasetRegistration],
    sources: Mapping[Any, SourceSpec],
    execution_inputs: Mapping[Any, ExecutionInputRegistration],
    components: Mapping[Any, ComponentRef],
    runs: Mapping[str, RunDefinition] | None = None,
) -> str:
    """The workspace's state as the document's text, sections sorted by id, empty ones omitted."""

    def by_id(items):
        return sorted(items, key=lambda item: str(item[0]))

    document = WorkspaceDocument(
        sources={str(k): SourceDocument.from_domain(v) for k, v in by_id(sources.items())},
        datasets={str(k): DatasetDocument.from_domain(v) for k, v in by_id(datasets.items())},
        execution_inputs={
            str(k): ExecutionInputDocument.from_domain(v)
            for k, v in by_id(execution_inputs.items())
        },
        components={str(k): ComponentDocument.from_domain(v) for k, v in by_id(components.items())},
        runs={k: RunDocument.from_domain(v) for k, v in sorted((runs or {}).items())},
    )
    body = document.model_dump(
        mode="json",
        exclude={"valuation_configs", "monitoring_policies", "agendas", "strategy_configs"},
    )
    if not body["runs"]:
        del body["runs"]
    return yaml.dump(body, Dumper=_YAML_DUMPER, allow_unicode=True, sort_keys=False)



__all__ = [
    "ComponentDeclaration",
    "ComponentDocument",
    "DataModelEntryDocument",
    "DatasetDeclaration",
    "DatasetDocument",
    "Document",
    "ExecutionInputDeclaration",
    "ExecutionInputDocument",
    "FillDeclaration",
    "FillDocument",
    "InitialAccountDocument",
    "RunDocument",
    "SourceDocument",
    "StrategyEntryDocument",
    "TableDeclaration",
    "WorkspaceDocument",
    "read_workspace",
    "write_workspace",
]
