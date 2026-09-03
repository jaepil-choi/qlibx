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

import yaml
from pydantic import BaseModel, ValidationError

from vqapr.data import datasets as datasets_module
from vqapr.data.datasets import DatasetRegistration
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
from vqapr.exchange.execution_table import ExecutionInputRegistration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import RunDefinition, StrategyConfig
from vqapr.runtime.agendas import OperationAgenda
from vqapr.workspace_document import (
    AgendaDocument,
    ComponentDocument,
    DatasetDocument,
    ExecutionInputDocument,
    RunDocument,
    SourceDocument,
    StrategyConfigDocument,
)

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
            str(key): DatasetDocument.from_domain(registration).model_dump(mode="json")
            for key, registration in sorted(datasets.items(), key=lambda item: str(item[0]))
        },
        "execution_inputs": {
            str(key): ExecutionInputDocument.from_domain(registration).model_dump(mode="json")
            for key, registration in sorted(execution_inputs.items(), key=lambda item: str(item[0]))
        },
        "components": {
            str(key): ComponentDocument.from_domain(ref).model_dump(mode="json")
            for key, ref in sorted(components.items(), key=lambda item: str(item[0]))
        },
        "agendas": {
            key: AgendaDocument.from_domain(agenda).model_dump(mode="json")
            for key, agenda in sorted(agendas.items())
        },
        # Keyed by the strategy's component id, carrying the agenda it names (record `138`).
        # The shape before it was keyed by agenda and carried the component; `_decode` reads
        # both for one release, and a document is written forward in this shape.
        "strategy_configs": {
            key: StrategyConfigDocument.from_domain(config).model_dump(mode="json")
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
        raise ValueError(
            f"{kind} {raw_id!r}{': ' + where if where else ''} {words}"
        ) from invalid


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
        source = _decoded("source", raw_id, SourceDocument, raw_source).to_domain(raw_id)
        decoded_sources[source.source_id] = source

    raw_datasets = document["datasets"]
    if not isinstance(raw_datasets, dict):
        raise TypeError("datasets must be a mapping")

    decoded: dict[DatasetId, DatasetRegistration] = {}
    for raw_id, raw_registration in raw_datasets.items():
        if not isinstance(raw_id, str):
            raise TypeError("every dataset_id must be a string")
        registration = _decoded("dataset", raw_id, DatasetDocument, raw_registration).to_domain(
            raw_id
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
    for raw_id, raw_registration in raw_execution_inputs.items():
        if not isinstance(raw_id, str):
            raise TypeError("every execution_input_id must be a string")
        model = _decoded("execution input", raw_id, ExecutionInputDocument, raw_registration)
        source_key = source_id(model.source)
        if source_key not in decoded_sources:
            raise ValueError(
                f"execution input {raw_id!r} references unregistered source {source_key!r}"
            )
        registration = model.to_domain(raw_id, decoded_sources[source_key])
        decoded_execution_inputs[registration.execution_input_id] = registration
    raw_components = document.get("components", {})
    if not isinstance(raw_components, dict):
        raise TypeError("components must be a mapping")
    decoded_components: dict[ComponentId, ComponentRef] = {}
    for raw_id, raw_ref in raw_components.items():
        if not isinstance(raw_id, str):
            raise TypeError("every component_id must be a string")
        ref = _decoded("component", raw_id, ComponentDocument, raw_ref).to_domain(raw_id)
        decoded_components[ref.component_id] = ref

    raw_agendas = document.get("agendas", {})
    if not isinstance(raw_agendas, dict):
        raise TypeError("agendas must be a mapping")
    decoded_agendas: dict[str, OperationAgenda] = {}
    for raw_id, raw_agenda in raw_agendas.items():
        if not isinstance(raw_id, str):
            raise TypeError("every agenda_id must be a string")
        model = _decoded("agenda", raw_id, AgendaDocument, raw_agenda)
        agenda = model.to_domain(raw_id)
        if (
            agenda.content_identity != model.content_identity
            or agenda.provenance_identity != model.provenance_identity
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
        if set(raw_config) == {"component", "agenda_role"}:
            component, raw_config = raw_config["component"], {
                "agenda_id": raw_id,
                "agenda_role": raw_config["agenda_role"],
            }
        else:
            component = raw_id
        model = _decoded("strategy config", raw_id, StrategyConfigDocument, raw_config)
        try:
            registered_component = decoded_components[component_id(str(component))]
        except KeyError as error:
            raise ValueError(
                f"strategy config {raw_id!r} references an unregistered component"
            ) from error
        config = model.to_domain(registered_component)
        if (
            decoded_agendas.get(config.agenda_id) is None
            or decoded_agendas[config.agenda_id].role is not config.agenda_role
        ):
            raise ValueError(
                f"strategy config {raw_id!r} references an absent or mismatched agenda"
            )
        decoded_strategy_configs[str(component)] = config
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
    return RunDocument.from_domain(definition).model_dump(mode="json")


def decoded_run(run_id: str, body: object) -> RunDefinition:
    """A `RunDefinition` from the document's shape; `TypeError`/`ValueError` name what is wrong.

    Ids are not resolved here: the workspace merge (`_merge_run`) and `_decode` above check that
    every id a run names is registered, so this is shape only.
    """
    if not isinstance(body, dict):
        raise TypeError(f"run {run_id!r} must be a mapping")
    return _decoded("run", run_id, RunDocument, body).to_domain(run_id)
