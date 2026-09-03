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

from datetime import datetime, time
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from vqapr.data.datasets import DatasetRegistration, Grain
from vqapr.data.scan import ColumnType, ProjectionSchema
from vqapr.data.sources import SourceSpec
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef


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


__all__ = [
    "ComponentDocument",
    "DatasetDocument",
    "Document",
    "ExecutionInputDocument",
    "FillDocument",
    "SourceDocument",
]
