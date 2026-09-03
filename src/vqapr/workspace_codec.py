"""Every conversion between the workspace document and the objects it describes.

**Split out of `workspace.py` by record `117`, and this is the only split that was taken.** The
module held 2,227 lines; this is the half the plan called load-bearing, because `_encode`,
`_decode`, the requirement pair, the eight `_detach_*` helpers and the legacy document shapes
all land in one file, so a later step that retires a legacy shape discards a region rather than
hunting for it.

`_decode` is 429 lines because it validates forward references while decoding, which is what
makes a workspace that would not open refuse at read time rather than at the first command that
needed the missing declaration.

**Nothing here constructs a `Failure`.** That is what makes this split safe, and it is not an
accident of the code -- it was the deciding measurement. The refusal-code inventory in
`tests/characterization/refusal_codes.py` resolves a code by folding f-strings through at most
one or two levels of LOCAL, same-file helper indirection, and every workspace refusal reaches
`Failure.bounded` through the module-level `_workspace_error`. Moving anything that raises away
from that constructor makes the hop cross-module and opaque, and because the resolver unions all
callers of a parameter, one unresolvable caller collapses the whole set: an earlier attempt that
also moved `_workspace_error` and the stage constants out measured **0 codes added and 37
removed**. The file itself had warned about this for constants, at what was `workspace.py:120`.
So the refusing half stays with its constructor, and only the converting half moves.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal

import yaml
from pydantic import ValidationError

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data import datasets as datasets_module
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.scan import ColumnType, ProjectionSchema
from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import (
    ComponentId,
    DatasetId,
    ExecutionInputId,
    SourceId,
    component_id,
    execution_input_id,
    source_id,
)
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import RunDefinition, StrategyConfig, StrategyEntry
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace_document import SourceDocument

WORKSPACE_DIRECTORY = ".vqapr"
WORKSPACE_FILENAME = "workspace.yaml"
WORKSPACE_LOCK_FILENAME = ".workspace.lock"
"""Serialises the read-modify-write cycle a registration performs.

The write itself is already atomic -- a temporary file replaced into place -- but atomic writing
only guarantees a reader never sees half a file. It does not stop two processes from each reading
the same state, each adding their own declaration, and the second write erasing the first. Nothing
fails; a declaration is simply gone.

Running strategies in parallel is the normal case, not an edge one, so this belongs to the
framework. A user should not have to discover the failure and invent a lock protocol, and two
users inventing slightly different ones do not protect each other.
"""

WORKSPACE_LOCK_TIMEOUT = 30.0
WORKSPACE_LOCK_STALE_AFTER = 120.0

WORKSPACE_SWAP_ATTEMPTS = 10
WORKSPACE_SWAP_BACKOFF = 0.02
"""Retries for the two file operations a concurrent reader can make fail on Windows.

POSIX ``rename`` is unconditional, so a reader holding the old inode is simply left holding it and
the swap succeeds. Windows refuses instead: ``os.replace`` onto a path another process currently
has open fails with ``WinError 5``, and the reader's own ``open`` can fail with a sharing
violation for the moment the swap takes. Both surface as ``OSError``.

The workspace lock does not cover this. It serialises *writers* against each other, which is what
stops a lost update -- but a **reader** takes no lock, deliberately: a run reads the workspace on
every callback, and serialising that behind every registration would be a far worse trade. So a
writer can hold the lock, be the only writer, and still be refused by a reader that arrived
between its own read and its write.

Measured on this repository before the retry: 1 run in 10 with eight processes registering at
once, on both the read and the write side. The condition is a swap that completes in microseconds,
so outlasting it is the proportionate fix -- and a real permission problem still fails, because it
outlasts the retries.
"""

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_YAML_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
"""libyaml when the installed PyYAML was built with it, the pure-Python classes otherwise.

The workspace holds every agenda occurrence, so the file grows with run length rather than with
the number of declarations: a three-year daily agenda set is roughly 750 KB. Parsing that with
PyYAML's pure-Python loader costs about 1.1 s and emitting it about 0.5 s, against 0.24 s and
0.14 s through libyaml, and a registration pays both. The emitted bytes are identical between the
two dumpers for every document this module writes, which `tests/test_workspace.py` pins.
"""

_DECODE_CACHE_LIMIT = 8
_decode_cache: dict[str, tuple[dict, ...]] = {}
"""Decoded workspaces keyed by the sha256 of their exact text.

Every registration reads the file twice -- once through `Workspace.create`, once inside the
exclusive lock -- and a process usually makes several registrations in a row against a file that
only grows by one declaration each time. Keying on content rather than on path or mtime means a
hit is only possible for bytes that were already decoded, so no writer, in this process or
another, can be served a stale workspace.
"""
"""A lock older than this is assumed to belong to a process that died holding it.

Without this a crash leaves the workspace permanently unwritable, and the recovery step is
"delete a file we never told you about".
"""
OPEN_STAGE = "workspace.open"
REGISTER_STAGE = "workspace.dataset.register"
LOOKUP_STAGE = "workspace.dataset.lookup"
SPAN_STAGE = "dataset.register.span"
"""Deliberately the same string `data.datasets` declares, asserted below rather than imported.

A module-level literal is what lets the refusal-code inventory fold `f"{SPAN_STAGE}.absent"`
statically; an alias to another module's constant is opaque to that pass and the code would drop
out of the inventory silently. The assert keeps the two from drifting.
"""
assert SPAN_STAGE == datasets_module.SPAN_STAGE
SOURCE_LOOKUP_STAGE = "workspace.source.lookup"
WRITE_STAGE = "workspace.write"
EXECUTION_REGISTER_STAGE = "workspace.execution_input.register"
EXECUTION_LOOKUP_STAGE = "workspace.execution_input.lookup"
COMPONENT_LOOKUP_STAGE = "workspace.component.lookup"
AGENDA_REGISTER_STAGE = "workspace.agenda.register"
AGENDA_LOOKUP_STAGE = "workspace.agenda.lookup"
STRATEGY_REGISTER_STAGE = "workspace.strategy_config.register"
REMOVE_STAGE = "workspace.remove"
_CONSTRUCTION_TOKEN = object()


def _detach_registration(registration: DatasetRegistration) -> DatasetRegistration:
    builder = (
        DatasetRegistration.undeclared if registration.grain is None else DatasetRegistration.of
    )
    keywords = {} if registration.grain is None else {"grain": registration.grain}
    detached = builder(
        str(registration.dataset_id),
        str(registration.source),
        instrument_field=registration.instrument_field,
        available_at=registration.available_at,
        key_fields=registration.key_fields,
        fields=dict(registration.fields),
        **keywords,
    )
    # `of` takes neither the span nor the field types, because both are measured rather than
    # declared. Detaching must still carry the measurements across, or every read would hand back
    # a registration that had silently forgotten them -- and a re-registration of the identical
    # declaration would then read as a changed one.
    if registration.field_types is not None:
        detached = detached.with_schema(
            ProjectionSchema(registration.field_types, registration.aggregated)
        )
    return detached if registration.span is None else detached.with_span(*registration.span)


def _detach_execution_input(
    registration: ExecutionInputRegistration,
) -> ExecutionInputRegistration:
    table = registration.table
    fill = registration.fill
    return ExecutionInputRegistration.of(
        str(registration.execution_input_id),
        ExecutionTableSpec(
            source=table.source,
            trade_at_field=table.trade_at_field,
            instrument_field=table.instrument_field,
            is_tradable_field=table.is_tradable_field,
            price_fields=dict(table.price_fields),
        ),
        FillConvention(
            selector=fill.selector,
            local_time=fill.local_time,
            timezone=fill.timezone,
            trade_price=fill.trade_price,
            fold=fill.fold,
            offset=fill.offset,
        ),
    )


def _detach_component(ref: ComponentRef) -> ComponentRef:
    return ComponentRef.of(
        str(ref.component_id),
        ref.kind,
        ref.path,
        ref.object_name,
        config=dict(ref.config),
        fingerprint=ref.fingerprint,
    )


def _detach_agenda(agenda: OperationAgenda) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda.agenda_id,
        role=agenda.role,
        timezone=agenda.timezone,
        occurrences=tuple(
            OperationOccurrence(
                occurrence.occurrence_id,
                occurrence.role,
                LocalInstantDeclaration(
                    occurrence.local_instant.local_date,
                    occurrence.local_instant.local_time,
                    occurrence.local_instant.timezone,
                    occurrence.local_instant.fold,
                    occurrence.local_instant.offset,
                ),
            )
            for occurrence in agenda.occurrences
        ),
        provenance=agenda.provenance,
    )


def _detach_strategy_config(config: StrategyConfig) -> StrategyConfig:
    return StrategyConfig(_detach_component(config.component), config.agenda_id, config.agenda_role)


def _encoded_dataset(registration: DatasetRegistration) -> dict[str, object]:
    """One registration as it is written back.

    A quarantined registration -- one decoded from a document written before spans existed -- is
    written back in the SAME legacy shape it was read in, without a span. This is what makes the
    repair incremental: `register_dataset` rewrites the whole document, so inventing a span for
    the other stale entries would either fabricate a measurement nobody took or refuse the write
    and block the repair of the one dataset the caller actually fixed.

    A span-less registration that never came from disk cannot reach here: `register_dataset`
    refuses it before the document is assembled.

    **A registration whose field types were never derived is written back the same way**, and for
    the same reason. Those are the entries written before a field became an expression
    (`docs/issues/049`): their `fields` are bare columns and their projection is row-wise, which
    is what the decode below assumes, but nobody has run `DESCRIBE` over them and inventing types
    would be fabricating a measurement. So a document upgrades one entry at a time, as each
    dataset is registered again -- and until then it stays readable by the release that wrote it.
    """
    body: dict[str, object] = {
        "source": str(registration.source),
        "instrument_field": registration.instrument_field,
        "available_at": registration.available_at,
        "key_fields": list(registration.key_fields),
        "fields": dict(registration.fields),
    }
    if registration.grain is not None:
        body["grain"] = registration.grain.value
    if registration.field_types is not None:
        body["field_types"] = {
            name: str(column_type) for name, column_type in registration.field_types.items()
        }
        body["aggregated"] = registration.aggregated
    if registration.span is not None:
        body["span"] = [registration.span[0].isoformat(), registration.span[1].isoformat()]
    return body


def _encode(
    datasets: Mapping[DatasetId, DatasetRegistration],
    sources: Mapping[SourceId, SourceSpec],
    execution_inputs: Mapping[ExecutionInputId, ExecutionInputRegistration],
    components: Mapping[ComponentId, ComponentRef],
    agendas: Mapping[str, OperationAgenda],
    strategy_configs: Mapping[str, StrategyConfig],
    runs: Mapping[str, RunDefinition] | None = None,
) -> str:
    document = {
        "sources": {
            str(key): SourceDocument.from_domain(source).model_dump()
            for key, source in sorted(sources.items(), key=lambda item: str(item[0]))
        },
        "datasets": {
            str(key): _encoded_dataset(registration)
            for key, registration in sorted(datasets.items(), key=lambda item: str(item[0]))
        },
        "execution_inputs": {
            str(key): {
                "source": str(registration.table.source.source_id),
                "trade_at_field": registration.table.trade_at_field,
                "instrument_field": registration.table.instrument_field,
                "is_tradable_field": registration.table.is_tradable_field,
                "price_fields": dict(registration.table.price_fields),
                "fill": {
                    "selector": registration.fill.selector.value,
                    "local_time": registration.fill.local_time.isoformat(),
                    "timezone": registration.fill.timezone,
                    "trade_price": registration.fill.trade_price,
                    "fold": registration.fill.fold,
                    "offset": registration.fill.offset,
                },
            }
            for key, registration in sorted(execution_inputs.items(), key=lambda item: str(item[0]))
        },
        "components": {
            str(key): {
                "kind": str(ref.kind),
                "path": str(ref.path),
                "object_name": ref.object_name,
                "config": dict(ref.config),
                "fingerprint": ref.fingerprint,
            }
            for key, ref in sorted(components.items(), key=lambda item: str(item[0]))
        },
        "agendas": {
            key: {
                "role": str(agenda.role),
                "timezone": agenda.timezone,
                "occurrences": [
                    {
                        "occurrence_id": occurrence.occurrence_id,
                        "local_date": occurrence.local_instant.local_date.isoformat(),
                        "local_time": occurrence.local_instant.local_time.isoformat(),
                        "timezone": occurrence.local_instant.timezone,
                        "fold": occurrence.local_instant.fold,
                        "offset": occurrence.local_instant.offset,
                    }
                    for occurrence in agenda.occurrences
                ],
                "provenance": agenda.provenance,
                "content_identity": agenda.content_identity,
                "provenance_identity": agenda.provenance_identity,
            }
            for key, agenda in sorted(agendas.items())
        },
        # Keyed by the strategy's component id, carrying the agenda it names (record `138`).
        # The shape before it was keyed by agenda and carried the component; `_decode` reads
        # both for one release, and a document is written forward in this shape.
        "strategy_configs": {
            key: {
                "agenda_id": str(config.agenda_id),
                "agenda_role": str(config.agenda_role),
            }
            for key, config in sorted(strategy_configs.items())
        },
        "runs": {
            key: encoded_run(definition) for key, definition in sorted((runs or {}).items())
        },
    }
    for section in ("agendas", "strategy_configs", "runs"):
        if not document[section]:
            del document[section]
    return yaml.dump(document, Dumper=_YAML_DUMPER, allow_unicode=True, sort_keys=False)


def _decode_cached(text: str) -> tuple[dict, ...]:
    """`_decode`, memoized on the exact bytes, returning mappings the caller may keep.

    Callers merge a declaration into copies rather than mutating what they were handed, but the
    copies are handed out anyway: a cached section is a shared object, and one caller mutating it
    would silently rewrite another caller's view of the workspace.
    """
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cached = _decode_cache.get(key)
    if cached is None:
        cached = _decode(text)
        if len(_decode_cache) >= _DECODE_CACHE_LIMIT:
            _decode_cache.clear()
        _decode_cache[key] = cached
    return tuple(dict(section) for section in cached)


def _decode(
    text: str,
) -> tuple[
    dict[DatasetId, DatasetRegistration],
    dict[SourceId, SourceSpec],
    dict[ExecutionInputId, ExecutionInputRegistration],
    dict[ComponentId, ComponentRef],
    dict[str, OperationAgenda],
    dict[str, StrategyConfig],
    dict[str, RunDefinition],
]:
    document = yaml.load(text, Loader=_YAML_LOADER)
    required_roots = {"sources", "datasets"}
    optional_roots = {
        "execution_inputs",
        "components",
        "agendas",
        "strategy_configs",
        "runs",
        # Read and dropped (record `144`): a document written by 0.3.0 carries these two
        # sections, each restating an agenda's own role, and the next write omits them. A
        # section with no information is not a meaning kept in two spellings.
        "valuation_configs",
        "monitoring_policies",
    }
    if (
        not isinstance(document, dict)
        or not required_roots.issubset(document)
        or not set(document).issubset(required_roots | optional_roots)
    ):
        raise ValueError(
            "workspace root must contain sources and datasets, with optional execution_inputs "
            "components, agendas, strategy_configs and runs"
        )

    raw_sources = document["sources"]
    if not isinstance(raw_sources, dict):
        raise TypeError("sources must be a mapping")

    decoded_sources: dict[SourceId, SourceSpec] = {}
    for raw_id, raw_source in raw_sources.items():
        if not isinstance(raw_id, str):
            raise TypeError("every source_id must be a string")
        try:
            source = SourceDocument.model_validate(raw_source).to_domain(raw_id)
        except ValidationError as invalid:
            raise ValueError(
                f"source {raw_id!r}: {invalid.error_count()} invalid field(s)"
            ) from invalid
        decoded_sources[source.source_id] = source

    raw_datasets = document["datasets"]
    if not isinstance(raw_datasets, dict):
        raise TypeError("datasets must be a mapping")

    decoded: dict[DatasetId, DatasetRegistration] = {}
    declared = {"source", "instrument_field", "available_at", "key_fields", "fields"}
    derived = {"field_types", "aggregated"}
    # `grain` is optional on READ only: a document written before it existed still opens, and
    # its grain-less entries are unusable until registered again (`DatasetRegistration.undeclared`).
    expected = declared | derived | {"span", "grain"}

    # **Two measurements, two independent axes, four admissible shapes.** An entry declares five
    # keys and then carries whatever has been measured about it: the span (added by the release
    # that made it mandatory) and the derived field types (added when a field became an
    # expression, `docs/issues/049`). Neither is a declaration, so neither can be invented for an
    # entry that predates it, and an entry can lack either or both.
    #
    # An entry written before types were derived holds bare columns under `fields`, which is a
    # row-wise projection -- exactly what the defaults say -- so that shape decodes into today's
    # behaviour rather than into a repair. A span-less one is quarantined, below.

    # A registration written before spans existed is QUARANTINED, not rejected: it decodes into a
    # registration whose `span` is None, and the refusal is deferred to the moment somebody
    # actually reads it.
    #
    # Refusing here instead would deadlock the repair. The generic exact-set check below is
    # all-or-nothing across the whole document, and `Workspace.open` and `create` both read
    # before they write -- so a document-scoped refusal takes `list` offline (it cannot enumerate
    # what needs fixing) AND takes `register` offline (it must open before it can rewrite). The
    # refusal would be advertising a repair command that the refusal itself blocks, whose only
    # real exit is hand-editing YAML no message describes.
    #
    # Quarantine keeps the workspace readable and repairable while still tolerating nothing: a
    # span-less registration cannot be used (`dataset()` and `span()` refuse it) and cannot be
    # re-persisted with a span it never had.
    quarantined: set[str] = set()

    for raw_id, raw_registration in raw_datasets.items():
        if not isinstance(raw_id, str):
            raise TypeError("every dataset_id must be a string")
        if not isinstance(raw_registration, dict):
            raise ValueError(f"dataset {raw_id!r} must contain exactly {sorted(expected)}")
        present = set(raw_registration) - {"grain"}
        measured = present - declared
        if (
            not declared <= present
            or not measured <= derived | {"span"}
            or (measured & derived and measured & derived != derived)
        ):
            raise ValueError(f"dataset {raw_id!r} must contain exactly {sorted(expected)}")
        if "span" not in present:
            quarantined.add(raw_id)

        source = raw_registration["source"]
        instrument_field = raw_registration["instrument_field"]
        available_at = raw_registration["available_at"]
        key_fields = raw_registration["key_fields"]
        fields = raw_registration["fields"]
        if not all(isinstance(value, str) for value in (source, available_at)):
            raise TypeError(f"dataset {raw_id!r} scalar declarations must be strings")
        if instrument_field is not None and not isinstance(instrument_field, str):
            raise TypeError(f"dataset {raw_id!r} instrument_field must be a string or absent")
        if not isinstance(key_fields, list) or not all(
            isinstance(value, str) for value in key_fields
        ):
            raise TypeError(f"dataset {raw_id!r} key_fields must be a list of strings")
        if not isinstance(fields, dict) or not all(
            isinstance(name, str) and isinstance(column, str) for name, column in fields.items()
        ):
            raise TypeError(f"dataset {raw_id!r} fields must map strings to strings")
        raw_grain = raw_registration.get("grain")
        if raw_grain is None:
            registration = DatasetRegistration.undeclared(
                raw_id,
                source,
                instrument_field=instrument_field,
                available_at=available_at,
                key_fields=key_fields,
                fields=fields,
            )
        else:
            if not isinstance(raw_grain, str):
                raise TypeError(f"dataset {raw_id!r} grain must be a string")
            registration = DatasetRegistration.of(
                raw_id,
                source,
                instrument_field=instrument_field,
                available_at=available_at,
                key_fields=key_fields,
                fields=fields,
                grain=raw_grain,
            )
        if "field_types" in raw_registration:
            raw_types = raw_registration["field_types"]
            aggregated = raw_registration["aggregated"]
            if not isinstance(raw_types, dict) or set(raw_types) != set(registration.fields):
                raise TypeError(f"dataset {raw_id!r} field_types must type every declared field")
            if not isinstance(aggregated, bool):
                raise TypeError(f"dataset {raw_id!r} aggregated must be a bool")
            try:
                field_types = {name: ColumnType(value) for name, value in raw_types.items()}
            except ValueError as error:
                raise TypeError(f"dataset {raw_id!r} field_types must name column types") from error
            registration = registration.with_schema(ProjectionSchema(field_types, aggregated))
        if raw_id not in quarantined:
            raw_span = raw_registration["span"]
            if (
                not isinstance(raw_span, list)
                or len(raw_span) != 2
                or not all(isinstance(value, str) for value in raw_span)
            ):
                raise TypeError(f"dataset {raw_id!r} span must be a pair of ISO-8601 strings")
            registration = registration.with_span(
                *(datetime.fromisoformat(value) for value in raw_span)
            )
        if registration.source not in decoded_sources:
            raise ValueError(
                f"dataset {raw_id!r} references unregistered source {registration.source!r}"
            )
        decoded[registration.dataset_id] = registration
    raw_execution_inputs = document.get("execution_inputs", {})
    if not isinstance(raw_execution_inputs, dict):
        raise TypeError("execution_inputs must be a mapping")

    decoded_execution_inputs: dict[ExecutionInputId, ExecutionInputRegistration] = {}
    expected_execution = {
        "source",
        "trade_at_field",
        "instrument_field",
        "is_tradable_field",
        "price_fields",
        "fill",
    }
    expected_fill = {"selector", "local_time", "timezone", "trade_price", "fold", "offset"}
    legacy_fill = {"selector", "local_time", "timezone", "trade_price"}
    for raw_id, raw_registration in raw_execution_inputs.items():
        if not isinstance(raw_id, str):
            raise TypeError("every execution_input_id must be a string")
        if not isinstance(raw_registration, dict) or set(raw_registration) != expected_execution:
            raise ValueError(
                f"execution input {raw_id!r} must contain exactly {sorted(expected_execution)}"
            )
        raw_source = raw_registration["source"]
        if not isinstance(raw_source, str):
            raise TypeError(f"execution input {raw_id!r} source must be a string")
        source_key = source_id(raw_source)
        if source_key not in decoded_sources:
            raise ValueError(
                f"execution input {raw_id!r} references unregistered source {source_key!r}"
            )
        scalar_fields = (
            raw_registration["trade_at_field"],
            raw_registration["instrument_field"],
            raw_registration["is_tradable_field"],
        )
        if not all(isinstance(value, str) for value in scalar_fields):
            raise TypeError(f"execution input {raw_id!r} field declarations must be strings")
        price_fields = raw_registration["price_fields"]
        if not isinstance(price_fields, dict) or not all(
            isinstance(name, str) and isinstance(column, str)
            for name, column in price_fields.items()
        ):
            raise TypeError(f"execution input {raw_id!r} price_fields must map strings to strings")
        raw_fill = raw_registration["fill"]
        if not isinstance(raw_fill, dict):
            raise ValueError(f"execution input {raw_id!r} fill must be a mapping")
        if "offset_sessions" in raw_fill:
            raise ValueError(
                f"execution input {raw_id!r} fill offset_sessions is no longer supported"
            )
        if set(raw_fill) == legacy_fill:
            raise ValueError(
                f"execution input {raw_id!r} uses the old fill schema without fold and offset proof"
            )
        if set(raw_fill) != expected_fill:
            raise ValueError(
                f"execution input {raw_id!r} fill must contain exactly {sorted(expected_fill)}"
            )
        selector = raw_fill["selector"]
        local_time = raw_fill["local_time"]
        timezone = raw_fill["timezone"]
        trade_price = raw_fill["trade_price"]
        fold = raw_fill["fold"]
        offset = raw_fill["offset"]
        if not all(
            isinstance(value, str) for value in (selector, local_time, timezone, trade_price)
        ):
            raise TypeError(f"execution input {raw_id!r} fill scalar values must be strings")
        if fold is not None and (not isinstance(fold, int) or isinstance(fold, bool)):
            raise TypeError(f"execution input {raw_id!r} fill fold must be an integer or null")
        if offset is not None and not isinstance(offset, str):
            raise TypeError(f"execution input {raw_id!r} fill offset must be a string or null")
        try:
            parsed_selector = FillSelector(selector)
        except ValueError as error:
            raise ValueError(
                f"execution input {raw_id!r} selector must be a FillSelector value"
            ) from error
        try:
            parsed_time = time.fromisoformat(local_time)
        except ValueError as error:
            raise ValueError(
                f"execution input {raw_id!r} local_time must be an ISO time"
            ) from error

        registration = ExecutionInputRegistration.of(
            raw_id,
            ExecutionTableSpec(
                source=decoded_sources[source_key],
                trade_at_field=scalar_fields[0],
                instrument_field=scalar_fields[1],
                is_tradable_field=scalar_fields[2],
                price_fields=price_fields,
            ),
            FillConvention(
                selector=parsed_selector,
                local_time=parsed_time,
                timezone=timezone,
                trade_price=trade_price,
                fold=fold,
                offset=offset,
            ),
        )
        decoded_execution_inputs[registration.execution_input_id] = registration
    raw_components = document.get("components", {})
    if not isinstance(raw_components, dict):
        raise TypeError("components must be a mapping")
    decoded_components: dict[ComponentId, ComponentRef] = {}
    expected_component = {"kind", "path", "object_name", "config", "fingerprint"}
    for raw_id, raw_ref in raw_components.items():
        if not isinstance(raw_id, str):
            raise TypeError("every component_id must be a string")
        if not isinstance(raw_ref, dict) or set(raw_ref) != expected_component:
            raise ValueError(
                f"component {raw_id!r} must contain exactly {sorted(expected_component)}"
            )
        kind = raw_ref["kind"]
        path = raw_ref["path"]
        object_name = raw_ref["object_name"]
        config = raw_ref["config"]
        fingerprint = raw_ref["fingerprint"]
        if not all(isinstance(value, str) for value in (kind, path, object_name, fingerprint)):
            raise TypeError(f"component {raw_id!r} scalar declarations must be strings")
        if not isinstance(config, dict):
            raise TypeError(f"component {raw_id!r} config must be a mapping")
        ref = ComponentRef.of(
            raw_id,
            ComponentKind(kind),
            path,
            object_name,
            config=config,
            fingerprint=fingerprint,
        )
        decoded_components[ref.component_id] = ref

    raw_agendas = document.get("agendas", {})
    if not isinstance(raw_agendas, dict):
        raise TypeError("agendas must be a mapping")
    decoded_agendas: dict[str, OperationAgenda] = {}
    expected_agenda = {
        "role",
        "timezone",
        "occurrences",
        "provenance",
        "content_identity",
        "provenance_identity",
    }
    expected_occurrence = {
        "occurrence_id",
        "local_date",
        "local_time",
        "timezone",
        "fold",
        "offset",
    }
    for raw_id, raw_agenda in raw_agendas.items():
        if not isinstance(raw_id, str):
            raise TypeError("every agenda_id must be a string")
        if not isinstance(raw_agenda, dict) or set(raw_agenda) != expected_agenda:
            raise ValueError(f"agenda {raw_id!r} must contain exactly {sorted(expected_agenda)}")
        if not all(
            isinstance(raw_agenda[key], str)
            for key in ("role", "timezone", "provenance", "content_identity", "provenance_identity")
        ):
            raise TypeError(f"agenda {raw_id!r} scalar declarations must be strings")
        occurrences = raw_agenda["occurrences"]
        if not isinstance(occurrences, list):
            raise TypeError(f"agenda {raw_id!r} occurrences must be a list")
        decoded_occurrences: list[OperationOccurrence] = []
        for raw_occurrence in occurrences:
            if not isinstance(raw_occurrence, dict) or set(raw_occurrence) != expected_occurrence:
                expected_fields = sorted(expected_occurrence)
                raise ValueError(
                    f"agenda {raw_id!r} occurrence must contain exactly {expected_fields}"
                )
            if not all(
                isinstance(raw_occurrence[key], str)
                for key in ("occurrence_id", "local_date", "local_time", "timezone", "offset")
            ):
                raise TypeError(f"agenda {raw_id!r} occurrence scalar declarations must be strings")
            if not isinstance(raw_occurrence["fold"], int) or isinstance(
                raw_occurrence["fold"], bool
            ):
                raise TypeError(f"agenda {raw_id!r} occurrence fold must be an integer")
            decoded_occurrences.append(
                OperationOccurrence(
                    raw_occurrence["occurrence_id"],
                    OperationRole(raw_agenda["role"]),
                    LocalInstantDeclaration(
                        date.fromisoformat(raw_occurrence["local_date"]),
                        time.fromisoformat(raw_occurrence["local_time"]),
                        raw_occurrence["timezone"],
                        raw_occurrence["fold"],
                        raw_occurrence["offset"],
                    ),
                )
            )
        agenda = OperationAgenda.from_occurrences(
            agenda_id=raw_id,
            role=OperationRole(raw_agenda["role"]),
            timezone=raw_agenda["timezone"],
            occurrences=decoded_occurrences,
            provenance=raw_agenda["provenance"],
        )
        if (
            agenda.content_identity != raw_agenda["content_identity"]
            or agenda.provenance_identity != raw_agenda["provenance_identity"]
        ):
            raise ValueError(
                f"agenda {raw_id!r} identity declarations do not match its canonical content"
            )
        decoded_agendas[agenda.agenda_id] = agenda

    raw_strategy_configs = document.get("strategy_configs", {})
    if not isinstance(raw_strategy_configs, dict):
        raise TypeError("configuration sections must be mappings")
    decoded_strategy_configs: dict[str, StrategyConfig] = {}
    for raw_id, raw_config in raw_strategy_configs.items():
        if not isinstance(raw_id, str) or not isinstance(raw_config, dict):
            raise ValueError("strategy config must be keyed by a string and be a mapping")
        # Two shapes, one release apart (record `138`): keyed by component id carrying
        # `agenda_id`, or -- written before an agenda was shareable -- keyed by agenda id
        # carrying `component`. Either decodes to the same binding; the next write is forward.
        if set(raw_config) == {"agenda_id", "agenda_role"}:
            component, agenda_id = raw_id, raw_config["agenda_id"]
        elif set(raw_config) == {"component", "agenda_role"}:
            component, agenda_id = raw_config["component"], raw_id
        else:
            raise ValueError(
                "strategy config must contain exactly agenda_id and agenda_role (keyed by the "
                "strategy's component id)"
            )
        role = raw_config["agenda_role"]
        if not all(isinstance(value, str) for value in (component, agenda_id, role)):
            raise TypeError("strategy config fields must be strings")
        try:
            registered_component = decoded_components[component_id(component)]
        except KeyError as error:
            raise ValueError(
                f"strategy config {raw_id!r} references an unregistered component"
            ) from error
        config = StrategyConfig(registered_component, agenda_id, OperationRole(role))
        if (
            decoded_agendas.get(agenda_id) is None
            or decoded_agendas[agenda_id].role is not config.agenda_role
        ):
            raise ValueError(
                f"strategy config {raw_id!r} references an absent or mismatched agenda"
            )
        decoded_strategy_configs[component] = config
    raw_runs = document.get("runs", {})
    if not isinstance(raw_runs, dict):
        raise TypeError("runs must be a mapping")
    decoded_runs: dict[str, RunDefinition] = {}
    for raw_id, raw_run in raw_runs.items():
        if not isinstance(raw_id, str):
            raise TypeError("runs must be keyed by run id")
        definition = decoded_run(raw_id, raw_run)
        # Forward references, checked as every other section's are: a document naming an absent
        # component or agenda is refused at decode, so `remove` cannot leave one behind.
        for entry in definition.strategies:
            component = decoded_components.get(component_id(entry.component_id))
            if component is None or component.kind is not ComponentKind.STRATEGY_MODEL:
                raise ValueError(f"run {raw_id!r} names an unregistered strategy")
            if entry.component_id not in decoded_strategy_configs:
                raise ValueError(f"run {raw_id!r} names a strategy with no registered binding")
            for name in entry.constraints:
                constraint = decoded_components.get(component_id(name))
                if constraint is None or constraint.kind is not ComponentKind.CONSTRAINT:
                    raise ValueError(f"run {raw_id!r} names an unregistered constraint")
        if definition.exchange is not None:
            venue = decoded_components.get(component_id(definition.exchange))
            if venue is None or venue.kind is not ComponentKind.EXCHANGE:
                raise ValueError(f"run {raw_id!r} names an unregistered exchange")
        if (
            definition.execution_input_id is not None
            and execution_input_id(definition.execution_input_id) not in decoded_execution_inputs
        ):
            raise ValueError(f"run {raw_id!r} names an unregistered execution input")
        for binding in (definition.valuation, definition.monitoring):
            if binding is None:
                continue
            agenda = decoded_agendas.get(binding.agenda_id)
            if agenda is None or agenda.role is not binding.agenda_role:
                raise ValueError(f"run {raw_id!r} references an absent or mismatched agenda")
        decoded_runs[raw_id] = definition
    return (
        decoded,
        decoded_sources,
        decoded_execution_inputs,
        decoded_components,
        decoded_agendas,
        decoded_strategy_configs,
        decoded_runs,
    )


def encoded_run(definition: RunDefinition) -> dict[str, object]:
    """One registered run as the document writes it -- and as `vqapr new run` shows it.

    The same shape the declaration reader accepts, so a run can be copied out of `workspace.yaml`
    into a declaration and back.
    """
    body: dict[str, object] = {
        "instruments": list(definition.instruments),
        "start": None if definition.start is None else definition.start.isoformat(),
        "end": None if definition.end is None else definition.end.isoformat(),
        "valuation": {"agenda_id": str(definition.valuation.agenda_id)},
        "exchange": definition.exchange,
        "execution_input": definition.execution_input_id,
    }
    if definition.monitoring is not None:
        body["monitoring"] = {"agenda_id": str(definition.monitoring.agenda_id)}
    snapshot, mode = definition.initial_account_snapshot, definition.initial_account_mode
    if snapshot is not None and mode is not None:
        body["initial_account"] = {
            "cash": str(snapshot.cash),
            "mode": mode.name,
            "positions": {str(k): str(v) for k, v in sorted(snapshot.positions.items())},
            "version": snapshot.version,
        }
    strategies: dict[str, object] = {}
    for entry in definition.strategies:
        declared: dict[str, object] = {}
        if entry.constraints:
            declared["constraints"] = list(entry.constraints)
        if entry.initial_model_memory is not None:
            declared["initial_model_memory"] = entry.initial_model_memory
        strategies[entry.component_id] = declared
    body["strategies"] = strategies
    return body


def decoded_run(run_id: str, body: object) -> RunDefinition:
    """A `RunDefinition` from the document's shape; `TypeError`/`ValueError` name what is wrong.

    Ids are not resolved here: the workspace merge (`_merge_run`) and `_decode` below check that
    every id a run names is registered, so this is shape only.
    """
    if not isinstance(body, dict):
        raise TypeError(f"run {run_id!r} must be a mapping")
    unknown = set(body) - _RUN_KEYS
    if unknown:
        raise ValueError(f"run {run_id!r} has unknown keys: {', '.join(sorted(unknown))}")
    # A registered run is run-ready: the document form requires what `vqapr run` cannot execute
    # without, all at once, so a reader learns the whole set in one refusal rather than one per
    # retry. (`RunDefinition` itself keeps these optional for in-process callers.)
    missing = [key for key in _RUN_REQUIRED if key not in body]
    if missing:
        raise ValueError(
            f"run {run_id!r} must declare {', '.join(_RUN_REQUIRED)}; missing "
            f"{len(missing)} of {len(_RUN_REQUIRED)}: {', '.join(missing)}"
        )
    raw_strategies = body.get("strategies")
    if not isinstance(raw_strategies, dict) or not raw_strategies:
        raise ValueError(f"run {run_id!r} must name at least one strategy under `strategies:`")
    strategies = []
    for raw_component, declared in raw_strategies.items():
        declared = declared or {}
        if not isinstance(declared, dict) or set(declared) - {
            "constraints",
            "initial_model_memory",
        }:
            raise ValueError(
                f"run {run_id!r} strategy {raw_component!r} may declare only constraints and "
                "initial_model_memory"
            )
        constraints = declared.get("constraints") or ()
        if not isinstance(constraints, (list, tuple)):
            raise TypeError(
                f"run {run_id!r} strategy {raw_component!r} constraints must be a list"
            )
        strategies.append(
            StrategyEntry(
                str(raw_component),
                tuple(str(name) for name in constraints),
                declared.get("initial_model_memory"),
            )
        )
    valuation = body.get("valuation")
    if not isinstance(valuation, dict) or "agenda_id" not in valuation:
        raise ValueError(f"run {run_id!r} valuation must be a mapping with agenda_id")
    monitoring = body.get("monitoring")
    if monitoring is not None and (
        not isinstance(monitoring, dict) or "agenda_id" not in monitoring
    ):
        raise ValueError(f"run {run_id!r} monitoring must be a mapping with agenda_id")
    account = body.get("initial_account")
    snapshot: AccountSnapshot | None = None
    mode: AccountMode | None = None
    if account is not None:
        if not isinstance(account, dict) or "cash" not in account or "mode" not in account:
            raise ValueError(f"run {run_id!r} initial_account must declare cash and mode")
        try:
            mode = AccountMode[str(account["mode"]).upper()]
        except KeyError:
            raise ValueError(
                f"run {run_id!r} initial_account.mode must be one of: "
                f"{', '.join(member.name for member in AccountMode)}"
            ) from None
        positions = account.get("positions") or {}
        if not isinstance(positions, dict):
            raise TypeError(f"run {run_id!r} initial_account.positions must be a mapping")
        snapshot = AccountSnapshot(
            version=int(account.get("version", 0)),
            cash=Decimal(str(account["cash"])),
            positions={str(k): Decimal(str(v)) for k, v in positions.items()},
        )
    instruments = body.get("instruments")
    if not isinstance(instruments, (list, tuple)):
        raise TypeError(f"run {run_id!r} instruments must be a list")
    return RunDefinition(
        run_id=run_id,
        strategies=tuple(strategies),
        valuation=ValuationConfig(str(valuation["agenda_id"]), OperationRole.VALUATION),
        instruments=tuple(str(name) for name in instruments),
        monitoring=(
            None
            if monitoring is None
            else MonitoringPolicy(str(monitoring["agenda_id"]), OperationRole.MONITORING)
        ),
        exchange=None if body.get("exchange") is None else str(body["exchange"]),
        execution_input_id=(
            None if body.get("execution_input") is None else str(body["execution_input"])
        ),
        start=_run_instant(body.get("start"), f"run {run_id!r} start"),
        end=_run_instant(body.get("end"), f"run {run_id!r} end"),
        initial_account_snapshot=snapshot,
        initial_account_mode=mode,
    )


_RUN_REQUIRED = (
    "strategies",
    "valuation",
    "instruments",
    "start",
    "end",
    "exchange",
    "execution_input",
    "initial_account",
)
"""What a registered run cannot execute without; `monitoring` is the one optional key."""

_RUN_KEYS = frozenset(
    {
        "strategies",
        "valuation",
        "monitoring",
        "instruments",
        "start",
        "end",
        "exchange",
        "execution_input",
        "initial_account",
    }
)


def _run_instant(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{name} must be an ISO-8601 datetime with an offset") from error
    else:
        raise TypeError(f"{name} must be an ISO-8601 datetime with an offset")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset; a naive datetime is not one instant")
    return parsed
