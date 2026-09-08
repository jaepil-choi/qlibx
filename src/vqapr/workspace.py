"""한 project가 명령 사이에 축적하는 선언 집합.

workspace는 선언을 보관하고 조회할 뿐 검증하지 않는다. dataset의 물리 스키마와 logical key가
유효한지는 ``data.datasets.validate``가 판정한 뒤 이 경계로 들어온다.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import yaml

from vqapr._internal import atomic, filelock
from vqapr.data import scan
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.domain.identifiers import (
    ComponentId,
    DatasetId,
    SourceId,
    component_id,
    dataset_id,
    source_id,
)
from vqapr.domain.values import require_tz_aware
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.declaration.run import RunDefinition
from vqapr.workspace_document import read_workspace, write_workspace

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
_CONSTRUCTION_TOKEN = object()


class _State(NamedTuple):
    """Everything `workspace.yaml` holds, as one value.

    A tuple, so every `*state` unpacking in this module still works; named,
    so a merge can say `state.agendas` and `state._replace(agendas=...)` instead of threading
    eight positional mappings through every signature. What it encodes is unchanged.
    """

    datasets: dict[DatasetId, DatasetRegistration]
    sources: dict[SourceId, SourceSpec]
    components: dict[ComponentId, ComponentRef]
    runs: dict[str, RunDefinition]
    """Registered runs (record `139`): the reusable configuration `vqapr run <run-id>` executes."""


class Workspace:
    """명시적으로 선택한 project root의 등록 선언 모음.

    현재 작업 디렉터리나 process-global provider를 보지 않는다. 호출자가 project root를 전달하고,
    이후 run은 이 mutable workspace를 다시 읽지 않는 frozen input을 별도로 만들어야 한다.
    """

    __slots__ = (
        "_components",
        "_datasets",
        "_runs",
        "_sources",
        "project_root",
    )

    def __init__(
        self,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration] | None = None,
        sources: Mapping[SourceId, SourceSpec] | None = None,
        components: Mapping[ComponentId, ComponentRef] | None = None,
        runs: Mapping[str, RunDefinition] | None = None,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError("construct a workspace with Workspace.create() or Workspace.open()")
        self.project_root = Path(project_root)
        self._datasets = {
            key: value for key, value in (datasets or {}).items()
        }
        self._sources = dict(sources or {})
        self._components = {
            key: value for key, value in (components or {}).items()
        }
        # A `RunDefinition` is frozen and holds only ids and values, so it needs no detaching.
        self._runs = dict(runs or {})

    @classmethod
    def _from_state(
        cls,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
        components: Mapping[ComponentId, ComponentRef],
        runs: Mapping[str, RunDefinition],
    ) -> Workspace:
        return cls(
            project_root,
            datasets,
            sources,
            components,
            runs,
            _token=_CONSTRUCTION_TOKEN,
        )

    @property
    def path(self) -> Path:
        return self.project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME

    @classmethod
    def create(cls, project_root: str | Path) -> Workspace:
        """새 project workspace를 만들거나 이미 있으면 그대로 연다."""
        candidate = cls._from_state(project_root, {}, {}, {}, {})
        if candidate.path.exists():
            return cls.open(project_root)
        candidate._write({}, {}, {}, {})
        return candidate

    @classmethod
    def open(cls, project_root: str | Path) -> Workspace:
        """기존 workspace 전체를 읽는다. 없거나 손상됐으면 일부 상태를 반환하지 않는다."""
        candidate = cls._from_state(project_root, {}, {}, {}, {})
        return cls._from_state(project_root, *candidate._read())

    @classmethod
    def transaction(cls, project_root: str | Path | Workspace) -> Transaction:
        """Start applying several registrations as one write.

        Handed an open `Workspace` rather than a root, the transaction stages against THAT
        object and refreshes it on commit, so a caller who holds a workspace sees what it just
        registered -- the guarantee the direct `Workspace.register_*` doors gave and the one
        door keeps (one-shape campaign Step 5, decision D3).

        The transaction stages every registration against a snapshot of the workspace -- or
        against nothing, where no workspace exists yet -- so a later declaration can look up an
        earlier one, and every refusal a registration can raise fires at staging time. Nothing on
        disk is touched until `commit()`, which takes the lock once, re-reads, replays the staged
        merges against what is actually there, and writes once. A document refused at its k-th
        item therefore leaves the workspace exactly as it found it; a valid document costs one
        lock, one read and one write however many items it declares.
        """
        if isinstance(project_root, Workspace):
            return Transaction(project_root)
        candidate = cls._from_state(project_root, {}, {}, {}, {})
        fresh = not candidate.path.exists()
        return Transaction(cls._from_state(project_root, *candidate._read_or_empty()), fresh=fresh)

    def _state(self) -> _State:
        return _State(
            self._datasets,
            self._sources,
            self._components,
            self._runs,
        )

    def _read_or_empty(self) -> _State:
        """The document on disk, or the empty document where none has been written yet.

        `register` is the first command typed in an empty directory; a transaction that refused to
        start there would send the reader to create a workspace by hand, which is the substitution
        `workspace.open.missing` exists to avoid.
        """
        if not self.path.exists():
            return _State({}, {}, {}, {})
        return self._read()

    @property
    def datasets(self) -> tuple[DatasetRegistration, ...]:
        """dataset_id 순으로 정렬된 detached 선언들."""
        return tuple(self._datasets[key] for key in sorted(self._datasets))

    @property
    def sources(self) -> tuple[SourceSpec, ...]:
        """source_id 순으로 정렬된 detached 물리 선언들."""
        return tuple(self._sources[key] for key in sorted(self._sources))

    @property
    def components(self) -> tuple[ComponentRef, ...]:
        """component_id 순으로 정렬된 detached project-local component references."""
        return tuple(self._components[key] for key in sorted(self._components))

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        """등록된 선언 하나를 조회한다."""
        try:
            key = dataset_id(raw_dataset_id)
        except ValueError as error:
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="dataset.reference_invalid",
                status=Status.INVALID,
                requirement="dataset lookup requires a valid dataset_id",
                observed=str(error),
                fix="pass a valid dataset_id string to Workspace.dataset()",
                retry="use a valid dataset_id, then retry",
                cause=error,
            ) from error
        try:
            registration = self._datasets[key]
        except KeyError as error:
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="dataset.unregistered",
                status=Status.MISSING,
                requirement=f"dataset {key!r} must be registered in this workspace",
                observed=f"registered datasets: {', '.join(sorted(self._datasets)) or '(none)'}",
                fix=(
                    f"register dataset {key!r}, or look up one of the registered datasets "
                    "listed above"
                ),
                retry="register the dataset, then retry",
                cause=error,
            ) from error
        # Point of use, which is where a quarantined registration is refused. Decode admits it so
        # the workspace stays enumerable and repairable; USING it is what must not happen, since
        # every consumer downstream of here treats a registration as complete.
        _require_span(str(key), registration)
        return registration

    def span(self, raw_dataset_id: str) -> tuple[datetime, datetime]:
        """The first and last instant the registered dataset carries.

        Reads the registration, never the file. `evaluation_times` above answers a neighbouring
        question by scanning, which is right when a caller needs every session; a caller that only
        needs the endpoints should not pay for a full read to learn two values registration
        already measured. That is the whole reason the span is persisted rather than derived.
        """
        # `dataset` already refuses a quarantined registration, so reaching the return means the
        # span is present.
        span = self.dataset(raw_dataset_id).span
        assert span is not None
        return span

    def instruments(self, raw_dataset_id: str) -> tuple[str, ...]:
        """Every instrument the registered dataset carries, sorted.

        Reading a registered dataset must not require knowing where it is stored or in what
        format. Without this, a caller resolves the dataset to a source, the source to a path,
        and the path to parquet -- binding its own code to a storage decision the framework
        declares is not part of its contract.

        A dataset registered without an `instrument_field` has no instrument axis, so it carries
        no instruments to enumerate and this returns nothing. That is not an empty answer standing
        in for a missing one: the rows of a factor series or an index level are not instruments,
        which is the fact `instrument_field` being absent states (`docs/issues/038`).
        """
        registration = self.dataset(raw_dataset_id)
        if registration.instrument_field is None:
            return ()
        spec = self.source(str(registration.source))
        return tuple(
            str(value)
            for value in scan.distinct_values(spec, registration.instrument_field)
            if value is not None
        )

    def evaluation_times(self, raw_dataset_id: str) -> tuple[datetime, ...]:
        """Every distinct ``available_at`` the registered dataset carries, sorted.

        This is what a caller needs to build an agenda from the sessions a dataset actually has,
        rather than assuming a calendar the data may not match.
        """
        registration = self.dataset(raw_dataset_id)
        spec = self.source(str(registration.source))
        values = scan.distinct_values(spec, registration.available_at)
        instants: list[datetime] = []
        for value in values:
            if value is None:
                continue
            if not isinstance(value, datetime):
                raise _workspace_error(
                    stage=Stage.LOOKUP,
                    code="dataset.reference_invalid",
                    status=Status.INVALID,
                    requirement=f"dataset {raw_dataset_id!r} available_at must be a timestamp",
                    observed=type(value).__name__,
                    fix="re-register the dataset with a timestamp-typed available_at column",
                    retry="register the dataset with a timestamp available_at, then retry",
                )
            instants.append(require_tz_aware(value, name="available_at"))
        return tuple(sorted(instants))

    def source(self, raw_source_id: str) -> SourceSpec:
        """등록된 물리 source 선언 하나를 조회한다."""
        try:
            key = source_id(raw_source_id)
        except ValueError as error:
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="source.reference_invalid",
                status=Status.INVALID,
                requirement="source lookup requires a valid source_id",
                observed=str(error),
                fix="pass a valid source_id string to Workspace.source()",
                retry="use a valid source_id, then retry",
                cause=error,
            ) from error
        try:
            return self._sources[key]
        except KeyError as error:
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="source.unregistered",
                status=Status.MISSING,
                requirement=f"source {key!r} must be registered in this workspace",
                observed=f"registered sources: {', '.join(sorted(self._sources)) or '(none)'}",
                fix=f"register a dataset against source_id {key!r} first",
                retry="register a dataset with that source, then retry",
                cause=error,
            ) from error

    def component(self, raw_component_id: str) -> ComponentRef:
        """등록된 project-local component reference 하나를 조회한다."""
        try:
            key = component_id(raw_component_id)
        except ValueError as error:
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="component.reference_invalid",
                status=Status.INVALID,
                requirement="component lookup requires a valid component_id",
                observed=str(error),
                fix="pass a valid component_id string to Workspace.component()",
                retry="use a valid component_id, then retry",
                cause=error,
            ) from error
        try:
            return self._components[key]
        except KeyError as error:
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="component.unregistered",
                status=Status.MISSING,
                requirement=f"component {key!r} must be registered in this workspace",
                observed=(
                    f"registered components: {', '.join(sorted(self._components)) or '(none)'}"
                ),
                fix=f"register component {key!r}, or use one of the ids listed above",
                retry="register the component, then retry",
                cause=error,
            ) from error

    @property
    def run_definitions(self) -> tuple[RunDefinition, ...]:
        """Every registered run, ordered by run id."""
        return tuple(self._runs[key] for key in sorted(self._runs))

    def run_definition(self, raw_run_id: str) -> RunDefinition:
        """One registered run by id: what `vqapr run <run-id>` freezes and executes."""
        return self._config_lookup(raw_run_id, self._runs, "run", noun="run_id")

    # ------------------------------------------------------------------------------------------
    # Merges: one registration folded into one state. Pure in the sense that matters -- they read
    # the state they are given and return a new one, and they neither lock nor write -- so the
    # same function serves a single `register_*` and a whole document applied as one transaction.
    # Every refusal a registration can raise lives here, once.
    # ------------------------------------------------------------------------------------------

    def _merge_dataset(
        self, state: _State, registration: DatasetRegistration, source: SourceSpec
    ) -> tuple[_State, bool]:
        if registration.source != source.source_id:
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="dataset.source_mismatch",
                status=Status.CONFLICT,
                requirement="DatasetRegistration.source must match SourceSpec.source_id",
                observed=(
                    f"registration source={registration.source!r}, source spec={source.source_id!r}"
                ),
                fix="pass a DatasetRegistration and SourceSpec that name the same source_id",
                retry="bind the dataset and physical source to the same source_id, then retry",
            )

        if registration.span is None:
            # Refused, not measured here. This method is a metadata write and opens no source; the
            # span comes from the full read `validate` already performs, so measuring again would
            # be a second scan of the same file and would turn persistence into an I/O operation.
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="dataset.span_absent",
                status=Status.INVALID,
                requirement="every registration must carry a span measured while it validated",
                observed=f"dataset {str(registration.dataset_id)!r} carries no measured span",
                fix=(
                    "call vqapr.public.register_dataset instead of "
                    "Workspace.register_dataset directly"
                ),
                retry=(
                    "register through vqapr.public.register_dataset, which validates the source "
                    "which measures the span while it validates"
                ),
            )

        key = registration.dataset_id
        source_key = source.source_id
        existing_source = state.sources.get(source_key)
        if existing_source is not None and existing_source != source:
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="dataset.source_conflict",
                status=Status.CONFLICT,
                requirement=(
                    f"source_id {source_key!r} must keep its existing "
                    "physical declaration"
                ),
                observed="a different SourceSpec is already registered",
                fix=(
                    f"reuse the registered SourceSpec for {source_key!r}, or register "
                    "under a new source_id"
                ),
                retry="use the existing source declaration or choose a new source_id",
            )

        existing = state.datasets.get(key)
        if existing is not None and (
            existing.span is None or existing.grain is None or existing.field_types is None
        ):
            # A quarantined registration is being repaired. It differs from its replacement
            # only in what has been MEASURED about it -- the span it never carried, the
            # grouping verdict -- or in a declaration that did not exist when it was written:
            # the grain (record `137`) and, since record `173`, the field types; the conflict
            # check below would read any of these as a changed declaration and refuse the
            # repair it advertises. Compare on the half that has always been declared, and let
            # the measurements and the later declarations be the things that change.
            repaired = replace(
                existing,
                grain=registration.grain if existing.grain is None else existing.grain,
                span=registration.span,
                field_types=registration.field_types,
                aggregated=registration.aggregated,
            )
            if repaired != registration:
                raise _workspace_error(
                    stage=Stage.REGISTER,
                    code="dataset.registered",
                    status=Status.CONFLICT,
                    requirement=(
                        f"dataset_id {key!r} must keep its existing declaration "
                        "or use a new identity"
                    ),
                    observed=(
                        "a different declaration is already registered; repairing a "
                        "span-less registration may add the span but must not change "
                        "anything else"
                    ),
                    fix=(
                        f"match the quarantined declaration for {key!r} exactly, or "
                        "register under a new dataset_id"
                    ),
                    retry="use the existing declaration or choose a new dataset_id",
                )
            existing = None

        if existing is not None:
            if existing == registration and existing_source == source:
                return state, False
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="dataset.registered",
                status=Status.CONFLICT,
                requirement=(
                    f"dataset_id {key!r} must keep its existing declaration "
                    "or use a new identity"
                ),
                observed="a different declaration is already registered",
                fix=(
                    f"keep the registered declaration for {key!r} unchanged, or "
                    "choose a new dataset_id"
                ),
                retry="use the existing declaration or choose a new dataset_id",
            )

        return (
            state._replace(
                datasets={**state.datasets, key: registration},
                sources={**state.sources, source_key: source},
            ),
            True,
        )

    def _merge_component(self, state: _State, ref: ComponentRef) -> tuple[_State, bool]:
        key = ref.component_id
        existing = state.components.get(key)
        if existing is not None and existing == ref:
            return state, False
        # An edited source replaces its registration in place, under the same id.
        #
        # This used to refuse and name a NEW component_id as the repair, while `loading.py` --
        # meeting the same edit -- said "re-register the component", which is what this refused.
        # The two pointed at each other, and `docs/implementations/057` names that shape as
        # worse than a generic error.
        #
        # The real cost was never one command: a new id needed a new strategy_configs binding
        # and a spec edit, four steps for a one-line change, and the workspace accumulated
        # `mom`, `mom-eb04...`, `mom-91c7...` for one strategy. Keeping the id also makes "this
        # strategy ran 47 times across 12 fingerprints" countable, which a new id per edit
        # scatters across twelve ids where nothing counts it.
        #
        # Provenance is not weakened. A finished run pins the fingerprint it ran under in its
        # own frozen record, so what a past run used is testified to by that run, not by
        # whichever registration currently holds the id.
        return state._replace(components={**state.components, key: ref}), True

    def _merge_run(self, state: _State, definition: RunDefinition) -> tuple[_State, bool]:
        """Fold one run into the document, refusing any id it names that is not registered."""
        self._require_run_references(state, definition)
        return self._merge_declaration(
            state, "runs", definition.run_id, definition, noun="run_id"
        )

    def _require_run_references(self, state: _State, definition: RunDefinition) -> None:
        def component(component_id: str, kind: ComponentKind, role: str) -> None:
            ref = state.components.get(ComponentId(component_id))
            if ref is None or ref.kind is not kind:
                raise self._reference_error(
                    f"run {definition.run_id!r} names {role} {component_id!r}, which must be "
                    f"a registered {kind.value} component",
                    fix=(
                        f"register {component_id!r} as a {kind.value}, or name a registered one"
                        if ref is None
                        else f"{component_id!r} is registered as {ref.kind.value}; name a "
                        f"registered {kind.value}, or register {component_id!r} as one"
                    ),
                )

        for entry in definition.strategies:
            component(entry.component_id, ComponentKind.STRATEGY_MODEL, "strategy")
            for name in entry.constraints:
                component(name, ComponentKind.CONSTRAINT, "constraint")
        for entry in definition.datamodels:
            component(entry.component_id, ComponentKind.DATA_MODEL, "datamodel")
        if definition.exchange is not None:
            component(definition.exchange, ComponentKind.EXCHANGE, "exchange")
        if definition.execution is not None:
            venue_table = state.datasets.get(dataset_id(definition.execution.dataset))
            if venue_table is None:
                raise self._reference_error(
                    f"run {definition.run_id!r} fills against dataset "
                    f"{definition.execution.dataset!r}, which must be registered",
                    fix=(
                        f"register dataset {definition.execution.dataset!r} with an execution "
                        "role first"
                    ),
                )
            if venue_table.execution is None:
                raise self._reference_error(
                    f"run {definition.run_id!r} fills against dataset "
                    f"{definition.execution.dataset!r}, which declares no execution role",
                    fix=(
                        f"register {definition.execution.dataset!r} again with "
                        "`execution: {is_tradable: <field>}`, or fill against a dataset that "
                        "has one"
                    ),
                )
        if (
            definition.sessions_from is not None
            and dataset_id(definition.sessions_from) not in state.datasets
        ):
            raise self._reference_error(
                f"run {definition.run_id!r} takes its sessions from dataset "
                f"{definition.sessions_from!r}, which must be registered",
                fix=f"register dataset {definition.sessions_from!r} first, or list `sessions`",
            )

    @staticmethod
    def _merge_declaration(
        state: _State,
        section: str,
        key: str,
        value: object,
        *,
        noun: str = "run_id",
    ) -> tuple[_State, bool]:
        """One keyed declaration folded into its section: idempotent, conflict, or new.

        `noun` is what the key IS -- `agenda_id` for the agenda-keyed sections, `component_id`
        for strategy configs -- so a refusal names the thing the author wrote (`docs/issues/040`
        measured a refusal that named an agenda the author never touched).
        """
        declarations: Mapping[str, object] = getattr(state, section)
        existing = declarations.get(key)
        if existing is not None:
            if existing == value:
                return state, False
            observed = "a different declaration is already registered"
            if noun == "component_id":
                observed = (
                    f"strategy {key!r} is already bound to agenda "
                    f"{getattr(existing, 'agenda_id', '?')!r}"
                )
            fix = (
                f"keep the registered declaration for {key!r} unchanged, or choose a new {noun}"
            )
            if noun == "run_id":
                # A run definition is the provenance of a result, so one id pointing at two
                # configurations would be a lie -- but a component replaces in place, and the
                # skill's "editing what you registered is the ordinary loop" reads as the rule
                # for both. The author who edits a run during setup (start date, universe, the
                # strategy list) hits this refusal, and its two options were the two things they
                # did not want. The third option ships, and the refusal now names it
                # (`docs/issues/084`).
                fix += (
                    f", or withdraw it first with `vqapr rm run-definition {key}` and register "
                    "the edited declaration again"
                )
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="run.registered",
                status=Status.CONFLICT,
                requirement=(
                    f"{noun} {key!r} must keep its existing declaration or use a new identity"
                ),
                observed=observed,
                fix=fix,
                retry=f"use the existing declaration or choose a new {noun}",
            )
        updated = {**declarations, key: value}
        return state._replace(**{section: updated}), True

    @property
    def roster_path(self) -> Path:
        """Where the registered instrument roster's pointer lives.

        A sidecar beside `workspace.yaml` rather than a section inside it. Every `register_*`
        performs a read-modify-write of the whole document under an exclusive lock, so a
        three-thousand-entry roster living in that document would be rewritten on every unrelated
        registration and would make each diff unreadable. It also keeps the roster out of the
        8-tuple every workspace signature threads, which is a change nobody reading a diff of
        this file would want to audit.
        """
        return self.path.parent / "instruments.json"

    def _write_roster(self, payload: Mapping[str, object]) -> None:
        import json

        self.roster_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def registered_instruments(self) -> dict[str, object] | None:
        """The roster pointer, or `None` when this project has registered no instruments.

        `None` rather than an empty mapping: a project with no roster and a project whose roster
        is empty are different states, and only the first is ordinary.
        """
        import json

        if not self.roster_path.is_file():
            return None
        raw = self.roster_path.read_text(encoding="utf-8")
        try:
            pointer = json.loads(raw)
            # Shape as well as syntax. Guarding only the parse left every reader indexing
            # `pointer["tables"]` and `pointer["digest"]` on a dict that might not have them, so
            # valid-but-incomplete JSON moved the crash one layer down instead of removing it.
            # Checked here, at the one door both `list` and `run` come through.
            if not isinstance(pointer, dict):
                raise TypeError(f"expected a JSON object, found {type(pointer).__name__}")
            absent = [key for key in ("tables", "digest") if key not in pointer]
            if absent:
                raise KeyError(f"missing {', '.join(absent)}")
            if not isinstance(pointer["tables"], dict) or not pointer["tables"]:
                raise TypeError("`tables` must be a non-empty JSON object")
            return pointer
        except (json.JSONDecodeError, TypeError, KeyError) as broken:
            # A corrupt pointer is a corrupt workspace, and this file says so rather than letting
            # a raw `JSONDecodeError` reach the envelope as `stage: "unhandled"`. Reported, never
            # repaired and never treated as absent: "no roster" and "a roster whose record is
            # damaged" are different states, and only the first is ordinary.
            raise _workspace_error(
                stage=Stage.READ,
                code="roster.unreadable",
                status=Status.UNAVAILABLE,
                requirement="the registered instrument roster pointer must be readable JSON",
                observed=f"{self.roster_path.name}: {broken}",
                fix=(
                    "re-register the roster with `vqapr register <instruments>.yaml`, which "
                    "rewrites this file"
                ),
                source=FailureSource(file=str(self.roster_path)),
                retry="re-register the instrument roster, then retry",
                cause=broken,
            ) from broken

    def remove(self, kind: str, identity: str) -> bool:
        """Withdraw one registration, refusing while anything live still names it.

        Returns True when something was removed and False when the id was already absent, which
        makes a repeated removal idempotent rather than an error.

        **Refuses on live declarations only, never on past run records.** A finished run pins the
        component id and fingerprint it used inside its own frozen record, so its provenance does
        not depend on the workspace still holding that registration. Refusing here on run history
        would make the workspace un-prunable the moment it was used once, which is immutability by
        the back door -- the thing issue 009 removes. A record whose component was later withdrawn
        still reports what it ran; it simply cannot be enriched from a registration that is gone.
        """
        with self._exclusive():
            state = self._read()
            # The reference check runs HERE, against the state the lock already read, rather than
            # before the lock against a state that can be stale by the time the write lands.
            # `docs/issues/043`: it was two reads with no lock across them, and the consequence is
            # worse than a lost update -- `_decode` validates forward references, so a document
            # holding a config whose component was removed makes `Workspace.open()` raise and every
            # command in the project fail until the file is hand-repaired.
            blockers = self._references_in(state, kind, identity)
            if blockers:
                raise _workspace_error(
                    stage=Stage.REMOVE,
                    code="remove.referenced",
                    status=Status.CONFLICT,
                    requirement=f"a {kind} may be removed only when nothing live still names it",
                    observed=f"{identity!r} is referenced by " + ", ".join(blockers),
                    fix=f"remove {', '.join(blockers)} first, or keep {identity!r} registered",
                    retry="withdraw the referencing declarations, then retry",
                )
            # Looked up after the reference check, so an unsupported kind still gets the typed
            # refusal `_references_in` raises rather than a bare `KeyError` from this dict.
            section = {"dataset": "datasets", "component": "components", "run": "runs"}[kind]
            declarations = dict(state._asdict()[section])
            if identity not in declarations:
                self._replace_state(*state)
                return False
            withdrawn = declarations.pop(identity)
            merged = state._replace(**{section: declarations})
            if kind == "dataset":
                # The physical source goes with the last dataset that named it: a source
                # nothing reads is a path the document keeps pointing at for no one.
                source_id = withdrawn.source
                still_named = any(item.source == source_id for item in declarations.values())
                if not still_named:
                    merged = merged._replace(
                        sources={
                            key: spec for key, spec in state.sources.items() if key != source_id
                        }
                    )
            self._write(*merged)
            self._replace_state(*merged)
            return True

    def references_to(self, kind: str, identity: str) -> tuple[str, ...]:
        """Every live declaration that still names ``identity``, as human-readable labels.

        The workspace validates references in the FORWARD direction only, and it does so while
        decoding: a strategy config naming a component that must already exist. Withdrawing a
        registration asks the opposite question -- given this id, what still points at it -- and
        no index answers it, so this walk builds one. It is deliberately a walk rather than a
        maintained index: the workspace document is small, it is already fully in memory by the
        time this is called, and a second structure to keep in sync is how the two disagree.

        Returns labels rather than objects because the only consumer is a refusal that has to
        NAME what blocks it. A refusal that says "something still references this" sends the
        reader looking, which is the failure `docs/implementations/057` is about.

        Reads the workspace itself, for callers outside a write cycle. `remove` does NOT use this:
        it holds the lock and must evaluate against the state that lock already read, which is
        `_references_in` below (`docs/issues/043`).
        """
        return self._references_in(self._read(), kind, identity)

    def _references_in(self, state: _State, kind: str, identity: str) -> tuple[str, ...]:
        """The same question asked of a state already in hand.

        Split out so the check and the write can see ONE snapshot. When this walked its own read,
        `remove` performed two reads with no lock across them and a competing registration could
        land between them -- and because `_decode` validates forward references, the result was a
        workspace `Workspace.open()` refuses rather than merely a stale answer.
        """
        # By name: the tuple lost a member when `execution_inputs` retired (record 185),
        # and a positional read here was the one place that noticed too late.
        components = state.components
        runs: Mapping[str, RunDefinition] = state.runs
        blockers: list[str] = []
        if kind == "component":
            for run_id, definition in runs.items():
                named = {definition.exchange}
                named.update(entry.component_id for entry in definition.strategies)
                named.update(name for entry in definition.strategies for name in entry.constraints)
                named.update(entry.component_id for entry in definition.datamodels)
                if identity in named:
                    blockers.append(f"run {run_id!r}")
        elif kind == "dataset":
            # What the DOCUMENT knows names a dataset: a registered run whose sessions come from
            # it. A component's reads are declared in its code, not here, so a strategy that
            # reads a withdrawn dataset is refused by `check` and `run` at its next preflight
            # (`check.dataset.unregistered`), which is the same place it would be refused had
            # the dataset never been registered. A datamodel run that WRITES this dataset is
            # not a blocker: withdrawing the output is how that run is run again
            # (`docs/issues/060`).
            for run_id, definition in runs.items():
                if definition.sessions_from == identity:
                    blockers.append(f"run {run_id!r} (sessions_from)")
                # The venue table is a dataset too (record 185): a run that fills against
                # it holds it by name in the document.
                if definition.execution is not None and definition.execution.dataset == identity:
                    blockers.append(f"run {run_id!r} (execution)")
        elif kind == "run":
            # A run is the top of the document: nothing names a run, and a run's RECORDS are
            # not registrations -- `vqapr rm run` removes those separately.
            return ()
        else:
            raise _workspace_error(
                stage=Stage.REMOVE,
                code="remove.unsupported_kind",
                status=Status.INVALID,
                requirement="kind must be one this workspace stores",
                observed=repr(kind),
                fix="use one of: dataset, component, run",
                retry="retry with a kind this workspace stores",
            )
        if kind == "component" and identity not in components:
            return ()
        return tuple(sorted(blockers))

    def _config_lookup[T](
        self,
        key: str,
        declarations: Mapping[str, T],
        label: str,
        *,
        noun: str = "run_id",
    ) -> T:
        if not isinstance(key, str) or not key:
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="run.invalid",
                status=Status.INVALID,
                requirement=f"{label} lookup requires a valid {noun}",
                observed=repr(key),
                fix=f"pass a non-empty {noun} string to look up this configuration",
                retry=f"use a valid {noun}, then retry",
            )
        try:
            return declarations[key]
        except KeyError as error:
            what = {"component_id": "strategy", "run_id": "run"}.get(noun, "agenda")
            raise _workspace_error(
                stage=Stage.LOOKUP,
                code="run.unregistered",
                status=Status.MISSING,
                requirement=f"{label} for {what} {key!r} must be registered",
                observed=f"registered {label}s: {', '.join(sorted(declarations)) or '(none)'}",
                fix=f"register a {label} for {what} {key!r}, or use one of the ids listed above",
                retry=f"register the {label}, then retry",
                cause=error,
            ) from error

    def _reference_error(self, requirement: str, *, fix: str) -> VqaprError:
        return _workspace_error(
            stage=Stage.REGISTER,
            code="run.reference_invalid",
            status=Status.INVALID,
            requirement=requirement,
            observed="referenced declaration is absent or differs from the registered declaration",
            fix=fix,
            retry="register matching referenced declarations before retrying",
        )

    def _locked_refusal(self, lock: Path, timeout: float) -> VqaprError:
        """The refusal a waiter gets when another writer held the workspace for the whole timeout.

        Passed to `filelock.exclusive` rather than raised by it: the shared mutex knows it timed
        out, and this knows what a workspace is and what a reader should do about it.
        """
        return _workspace_error(
            stage=Stage.WRITE,
            code="workspace.locked",
            status=Status.LOCKED,
            requirement=f"workspace at {self.path} must be writable within {timeout:.0f}s",
            observed=f"another process has held {lock} for the whole timeout",
            fix=(
                f"wait for the other writer to finish, or delete {lock} if no writer "
                "is actually running"
            ),
            source=FailureSource(file=str(lock)),
            retry=f"wait for the other writer to finish; if none is running, delete {lock}",
        )

    def _exclusive(self) -> AbstractContextManager[None]:
        """Hold the workspace for one read-modify-write cycle.

        The mechanism is `_internal/filelock.exclusive`, shared with the catalog store since
        record `106`. What stays here is the part that is about workspaces rather than about
        locking: which file, and what a waiter is told when the wait runs out.
        """
        return filelock.exclusive(
            self.path.parent / WORKSPACE_LOCK_FILENAME,
            on_timeout=self._locked_refusal,
            timeout=WORKSPACE_LOCK_TIMEOUT,
            stale_after=WORKSPACE_LOCK_STALE_AFTER,
        )

    def _read(self) -> _State:
        text: str | None = None
        for attempt in range(WORKSPACE_SWAP_ATTEMPTS):
            try:
                text = self.path.read_text(encoding="utf-8")
                break
            except FileNotFoundError as error:
                raise _workspace_error(
                    stage=Stage.OPEN,
                    code="workspace.missing",
                    status=Status.MISSING,
                    requirement=f"workspace must exist at {self.path}",
                    observed="path does not exist",
                    # A CLI path, because the reader who reaches this has only ever typed
                    # commands: `register` is the door into a workspace, and it creates one where
                    # none exists. Naming `Workspace.create()` sent a user who had never written
                    # a line of Python to look for a Python call, which is the same substitution
                    # `declaration.read` avoids by naming the file rather than the dict lookup.
                    fix=(
                        "run `vqapr register <declaration>.yaml` in this directory, which "
                        "creates the workspace as it registers; or `vqapr new run` to "
                        "start from a template"
                    ),
                    source=FailureSource(file=str(self.path)),
                    retry="create the workspace, then retry",
                    cause=error,
                ) from error
            except OSError as error:
                # A concurrent atomic replace, not an unreadable workspace. Distinguished by
                # outlasting it: a swap completes, a permission problem does not.
                if attempt + 1 == WORKSPACE_SWAP_ATTEMPTS:
                    raise _workspace_error(
                        stage=Stage.OPEN,
                        code="workspace.unreadable",
                        status=Status.UNAVAILABLE,
                        requirement=f"workspace must be readable at {self.path}",
                        observed=str(error),
                        fix="fix filesystem permissions on the workspace file, then retry",
                        source=FailureSource(file=str(self.path)),
                        retry="make the workspace readable, then retry",
                        cause=error,
                    ) from error
                _time.sleep(WORKSPACE_SWAP_BACKOFF * (attempt + 1))
        assert text is not None

        try:
            return _State(*read_workspace(text))
        except (TypeError, ValueError, yaml.YAMLError) as error:
            message = str(error)
            requirement = (
                message
                if "is retired" in message
                else "workspace YAML must contain valid physical sources and dataset declarations"
            )
            raise _workspace_error(
                stage=Stage.OPEN,
                code="workspace.invalid",
                status=Status.INVALID,
                requirement=requirement,
                observed=str(error),
                fix="hand-edit or recreate the workspace YAML to match the current schema",
                source=FailureSource(file=str(self.path)),
                retry="fix or recreate the workspace, then retry",
                cause=error,
            ) from error

    def _replace_state(
        self,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
        components: Mapping[ComponentId, ComponentRef],
        runs: Mapping[str, RunDefinition] | None = None,
    ) -> None:
        self._datasets = {key: value for key, value in datasets.items()}
        self._sources = dict(sources)
        self._components = {key: value for key, value in components.items()}
        self._runs = dict(runs or {})

    def _write(
        self,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
        components: Mapping[ComponentId, ComponentRef],
        runs: Mapping[str, RunDefinition] | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = write_workspace(
            datasets,
            sources,
            components,
            runs or {},
        )
        try:
            atomic.write_atomically(
                self.path,
                payload,
                attempts=WORKSPACE_SWAP_ATTEMPTS,
                backoff=WORKSPACE_SWAP_BACKOFF,
            )
        except OSError as error:
            raise _workspace_error(
                stage=Stage.WRITE,
                code="workspace.write_failed",
                status=Status.UNAVAILABLE,
                requirement=f"workspace must be written at {self.path}",
                observed=str(error),
                fix="make the workspace directory writable, then retry",
                source=FailureSource(file=str(self.path)),
                retry="make the workspace directory writable, then retry",
                cause=error,
            ) from error


















def _roster_payload(tables: Mapping[str, Path | str], *, digest: str) -> dict[str, object]:
    if not isinstance(tables, Mapping) or not tables:
        raise ValueError("instrument registration requires at least one table")
    if not isinstance(digest, str) or not digest:
        raise ValueError("digest must be a non-empty string")
    return {
        "schema": "vqapr.instruments/v1",
        "tables": {str(kind): str(Path(path)) for kind, path in sorted(tables.items())},
        "digest": digest,
    }


class Transaction:
    """Several registrations, staged now and written once.

    `view` is a `Workspace` holding the snapshot plus everything staged so far, so `_apply` can
    resolve a config's component or an agenda's dataset declared earlier in the same document
    exactly as it would resolve one already on disk. Each `register_*` runs the same merge the
    single-item `Workspace.register_*` runs, against that staged state, so a conflict or a missing
    reference is refused where the author can still see which item it was.

    `commit()` is the only method that touches disk. It holds the lock for one read and one
    write: the merges are replayed against the state read under the lock, so a registration
    that landed from another process in the meantime is seen and, if it conflicts, refused --
    and then nothing is written. The roster sidecar, when a document declares one, is written
    after the document and inside the same lock.
    """

    def __init__(self, staging: Workspace, *, fresh: bool = False) -> None:
        self._staging = staging
        self._ops: list[Callable[[_State], tuple[_State, bool]]] = []
        self._rosters: list[Mapping[str, object]] = []
        # `fresh`: this transaction began from a ROOT on a project with no document yet, so its
        # first registration writes the document. A `Workspace` handed in was created or opened
        # against a document that existed; if that document has VANISHED since, it is damage,
        # and a registration against it refuses by name (`workspace.open.missing`) rather than
        # quietly recreating an empty one underneath the caller -- the guarantee the direct
        # doors had, kept by the one door. Decided by who started the transaction, not by
        # whether the file happens to exist at that moment.
        self._fresh = fresh

    def __enter__(self) -> Transaction:
        return self

    def __exit__(self, exc_type: object, *_exc: object) -> None:
        """Commit on a clean exit; leave the workspace untouched on an exception.

        The one door (one-shape campaign Step 5, decision D3). A single registration reads
        `with Workspace.transaction(root) as t: t.register_run(definition)`, the same merge
        the document path runs, staged and written once. A refusal raised inside the block
        propagates and nothing is written, which is the property `docs/issues/A3` (record `134`)
        made of the document path and which the direct `Workspace.register_*` doors could not
        share: each of those took its own lock and wrote its own item.
        """
        if exc_type is None:
            self.commit()

    @property
    def view(self) -> Workspace:
        """The snapshot plus what is staged: what a later declaration may look up."""
        return self._staging

    def _stage(self, merge: Callable[[_State], tuple[_State, bool]]) -> bool:
        merged, changed = merge(self._staging._state())
        self._staging._replace_state(*merged)
        self._ops.append(merge)
        return changed

    def register_dataset(self, registration: DatasetRegistration, source: SourceSpec) -> bool:
        ws = self._staging
        return self._stage(lambda state: ws._merge_dataset(state, registration, source))

    def register_component(self, ref: ComponentRef) -> bool:
        if not isinstance(ref, ComponentRef):
            raise TypeError("ref must be a ComponentRef")
        ws = self._staging
        return self._stage(lambda state: ws._merge_component(state, ref))

    def register_run(self, definition: RunDefinition) -> bool:
        if not isinstance(definition, RunDefinition):
            raise TypeError("definition must be a RunDefinition")
        ws = self._staging
        return self._stage(lambda state: ws._merge_run(state, definition))

    def register_instruments(
        self, tables: Mapping[str, Path | str], *, digest: str
    ) -> dict[str, object]:
        payload = _roster_payload(tables, digest=digest)
        self._rosters.append(payload)
        return payload

    def commit(self) -> None:
        """One lock, one read, the staged merges replayed, one write."""
        if not self._ops and not self._rosters:
            return
        ws = self._staging
        with ws._exclusive():
            state = ws._read_or_empty() if self._fresh else ws._read()
            changed = False
            for merge in self._ops:
                state, merged_changed = merge(state)
                changed = changed or merged_changed
            # A project that holds a roster is a workspace: the first thing registered in an
            # empty directory may be the roster alone, and a sidecar beside no document is
            # what `open` refuses as damage. `Workspace.create` used to write the empty
            # document as a side effect of the direct door; the one door writes it here.
            if changed or self._fresh:
                ws._write(*state)
            ws._replace_state(*state)
            for payload in self._rosters:
                ws._write_roster(payload)
        self._ops = []
        self._rosters = []


def _require_span(dataset_id: str, registration: DatasetRegistration) -> None:
    """Refuse a registration that predates span persistence, naming the command that repairs it.

    Raised at the point of USE rather than at decode. Decode admits a span-less registration so
    the workspace stays enumerable and rewritable -- otherwise the refusal would block `list` from
    reporting what needs fixing and block `register` from fixing it, which is a deadlock whose
    only exit is hand-editing YAML.
    """
    if registration.span is not None:
        return
    raise _workspace_error(
        stage=Stage.REGISTER,
        code="dataset.span_absent",
        status=Status.INVALID,
        requirement="every registration must carry a span measured while it validated",
        observed=f"{dataset_id} was registered before span persistence",
        # The real invocation. `vqapr register` takes one positional argument, the declaration
        # YAML that names the dataset and its source; there is no `data` subcommand and no
        # parquet path goes on this command line.
        fix=(
            f"re-register {dataset_id} by running: vqapr register <declaration.yaml>, where that "
            "document declares this dataset and the source it reads"
        ),
        retry=(
            f"re-register {dataset_id} by running: vqapr register <declaration.yaml>, where that "
            "document declares this dataset and the source it reads"
        ),
    )














def _workspace_error(
    *,
    stage: Stage,
    code: str,
    status: Status,
    requirement: str,
    observed: str,
    retry: str,
    fix: str,
    source: FailureSource | None = None,
    cause: BaseException | None = None,
) -> VqaprError:
    """One refusal, one failure. `cause` is the exception in hand at the site, when there is one;
    otherwise the failure records the site itself (record `171`)."""
    return VqaprError(
        stage=stage,
        failures=[
            Failure.bounded(
                code,
                requirement,
                status=status,
                observed=observed,
                fix=fix,
                source=source,
                cause=cause,
            )
        ],
        mutation=False,
        retry_precondition=retry,
    )
