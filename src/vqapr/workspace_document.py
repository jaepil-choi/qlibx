"""The workspace document and the declaration document, as pydantic models.

One model per YAML section: the shape a section has on disk (`workspace.yaml`) and in a
declaration an author registers. Key sets, scalar types, enums, dates and times are the model's
field declarations; pydantic checks them, and `declarations.refusals_from` turns what it finds
into this package's refusals. Nothing here opens a file, resolves a path or looks another
section up -- a model is a shape, and the cross-reference checks stay with the workspace.

Record `145` (deletion campaign Step 4): these models replace the hand-written `_decode` /
`_encode` / `_detach_*` in `workspace_codec.py` and the `_require_keys` / `_mapping` / `_enum`
family in `declarations.py`, one section at a time. Where the stored shape and the domain
dataclass coincide, `to_domain` is a one-liner; where they differ (a dataset's measured span, an
agenda's occurrences, a run's initial account) the model is the one place the mapping is written.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration, Grain
from vqapr.data.scan import ColumnType, ProjectionSchema
from vqapr.data.sources import SourceSpec
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import RunDefinition, StrategyConfig, StrategyEntry
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig


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


class OccurrenceDocument(Document):
    """One occurrence of an agenda on disk: the local instant with its DST proof."""

    occurrence_id: str
    local_date: date
    local_time: time
    timezone: str
    fold: int
    offset: str

    def to_domain(self, role: OperationRole) -> OperationOccurrence:
        return OperationOccurrence(
            self.occurrence_id,
            role,
            LocalInstantDeclaration(
                self.local_date, self.local_time, self.timezone, self.fold, self.offset
            ),
        )

    @classmethod
    def from_domain(cls, occurrence: OperationOccurrence) -> OccurrenceDocument:
        local = occurrence.local_instant
        return cls(
            occurrence_id=occurrence.occurrence_id,
            local_date=local.local_date,
            local_time=local.local_time,
            timezone=local.timezone,
            fold=local.fold,
            offset=local.offset,
        )


class AgendaDocument(Document):
    """`agendas.<agenda_id>` on disk: explicit occurrences, and the two identities as written.

    The identities are derived from the content; they are stored so a reader can compare a run
    record's agenda identity against the document without rebuilding it. `to_domain` rebuilds
    the agenda and the caller checks the stored identities still match (the codec did; the
    workspace still does).
    """

    role: OperationRole
    timezone: str
    occurrences: list[OccurrenceDocument]
    provenance: str
    content_identity: str
    provenance_identity: str

    def to_domain(self, agenda_id: str) -> OperationAgenda:
        return OperationAgenda.from_occurrences(
            agenda_id=agenda_id,
            role=self.role,
            timezone=self.timezone,
            occurrences=[occurrence.to_domain(self.role) for occurrence in self.occurrences],
            provenance=self.provenance,
        )

    @classmethod
    def from_domain(cls, agenda: OperationAgenda) -> AgendaDocument:
        return cls(
            role=agenda.role,
            timezone=agenda.timezone,
            occurrences=[
                OccurrenceDocument.from_domain(occurrence) for occurrence in agenda.occurrences
            ],
            provenance=agenda.provenance,
            content_identity=agenda.content_identity,
            provenance_identity=agenda.provenance_identity,
        )


class StrategyConfigDocument(Document):
    """`strategy_configs.<component_id>`: the agenda the strategy runs on (record `138`)."""

    agenda_id: str
    agenda_role: OperationRole

    def to_domain(self, component: ComponentRef) -> StrategyConfig:
        return StrategyConfig(component, self.agenda_id, self.agenda_role)

    @classmethod
    def from_domain(cls, config: StrategyConfig) -> StrategyConfigDocument:
        return cls(agenda_id=str(config.agenda_id), agenda_role=config.agenda_role)


class AgendaReference(Document):
    """`valuation:` / `monitoring:` inside a run: which agenda, by id."""

    agenda_id: str


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


class RunDocument(Document):
    """`runs.<run_id>` on disk and in a declaration -- the same shape, so a run can be copied
    out of `workspace.yaml` into a declaration and back.

    A registered run is run-ready: everything `vqapr run` cannot execute without is required
    here, nullable only where `RunDefinition` keeps it optional for in-process callers.
    `monitoring` is the one optional key.
    """

    instruments: list[str]
    start: datetime | None
    end: datetime | None
    valuation: AgendaReference
    exchange: str | None
    execution_input: str | None
    initial_account: InitialAccountDocument | None
    strategies: dict[str, StrategyEntryDocument | None]
    monitoring: AgendaReference | None = None

    @model_validator(mode="after")
    def _at_least_one_strategy(self) -> RunDocument:
        if not self.strategies:
            raise ValueError("must name at least one strategy under `strategies:`")
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
        if body.get("monitoring") is None:
            body.pop("monitoring", None)
        if body.get("initial_account") is None:
            body.pop("initial_account", None)
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
                for name, entry in self.strategies.items()
            ),
            valuation=ValuationConfig(self.valuation.agenda_id, OperationRole.VALUATION),
            instruments=tuple(self.instruments),
            monitoring=(
                None
                if self.monitoring is None
                else MonitoringPolicy(self.monitoring.agenda_id, OperationRole.MONITORING)
            ),
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
            valuation=AgendaReference(agenda_id=str(definition.valuation.agenda_id)),
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
            },
            monitoring=(
                None
                if definition.monitoring is None
                else AgendaReference(agenda_id=str(definition.monitoring.agenda_id))
            ),
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


class AgendaDeclaration(Document):
    """`agendas.<agenda_id>` in a declaration: a cadence, not a list of occurrences.

    The days come from a registered dataset (`from_dataset`) or are listed (`sessions`) --
    exactly one of the two, which no required-key list can say, so the declaration reader
    checks the pair itself and reports it beside whatever else is missing.
    """

    role: Literal["strategy_callback", "valuation", "monitoring"]
    at: time
    timezone: str
    from_dataset: str | None = None
    sessions: list[date | datetime] | None = None
    provenance: str | None = None

    _lower = field_validator("role", mode="before")(_lowered)

    @field_validator("sessions", mode="before")
    @classmethod
    def _a_non_empty_list(cls, value: object) -> object:
        if value is not None and (not isinstance(value, list) or not value):
            raise ValueError("a non-empty list of dates")
        return value


class ComponentDeclaration(Document):
    """`components.<component_id>`: where the code is and what it is, in the CLI's spelling."""

    kind: Literal["datamodel", "strategy", "constraint", "exchange"]
    path: str
    object_name: str
    config: dict[str, Any] | None = None


class StrategyConfigDeclaration(Document):
    agenda_id: str


__all__ = [
    "AgendaDeclaration",
    "AgendaDocument",
    "AgendaReference",
    "ComponentDeclaration",
    "ComponentDocument",
    "DatasetDeclaration",
    "DatasetDocument",
    "Document",
    "ExecutionInputDeclaration",
    "ExecutionInputDocument",
    "FillDeclaration",
    "FillDocument",
    "InitialAccountDocument",
    "OccurrenceDocument",
    "RunDocument",
    "SourceDocument",
    "StrategyConfigDeclaration",
    "StrategyConfigDocument",
    "StrategyEntryDocument",
    "TableDeclaration",
]
