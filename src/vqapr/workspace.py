"""한 project가 명령 사이에 축적하는 선언 집합.

workspace는 선언을 보관하고 조회할 뿐 검증하지 않는다. dataset의 물리 스키마와 logical key가
유효한지는 ``data.datasets.validate``가 판정한 뒤 이 경계로 들어온다.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time as _time
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

import yaml

from vqapr._internal import filelock
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data import datasets as datasets_module
from vqapr.data import scan
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, FailureSource, VqaprError
from vqapr.domain.identifiers import (
    ComponentId,
    DatasetId,
    ExecutionInputId,
    SourceId,
    component_id,
    dataset_id,
    execution_input_id,
    source_id,
)
from vqapr.domain.timestamps import LocalInstantDeclaration, require_tz_aware
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import StrategyConfig
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig

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
COMPONENT_REGISTER_STAGE = "workspace.component.register"
COMPONENT_LOOKUP_STAGE = "workspace.component.lookup"
AGENDA_REGISTER_STAGE = "workspace.agenda.register"
AGENDA_LOOKUP_STAGE = "workspace.agenda.lookup"
STRATEGY_REGISTER_STAGE = "workspace.strategy_config.register"
VALUATION_REGISTER_STAGE = "workspace.valuation_config.register"
MONITORING_REGISTER_STAGE = "workspace.monitoring_policy.register"
REMOVE_STAGE = "workspace.remove"
_CONSTRUCTION_TOKEN = object()


class Workspace:
    """명시적으로 선택한 project root의 등록 선언 모음.

    현재 작업 디렉터리나 process-global provider를 보지 않는다. 호출자가 project root를 전달하고,
    이후 run은 이 mutable workspace를 다시 읽지 않는 frozen input을 별도로 만들어야 한다.
    """

    __slots__ = (
        "_agendas",
        "_components",
        "_datasets",
        "_execution_inputs",
        "_monitoring_policies",
        "_sources",
        "_strategy_configs",
        "_valuation_configs",
        "project_root",
    )

    def __init__(
        self,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration] | None = None,
        sources: Mapping[SourceId, SourceSpec] | None = None,
        execution_inputs: Mapping[ExecutionInputId, ExecutionInputRegistration] | None = None,
        components: Mapping[ComponentId, ComponentRef] | None = None,
        agendas: Mapping[str, OperationAgenda] | None = None,
        strategy_configs: Mapping[str, StrategyConfig] | None = None,
        valuation_configs: Mapping[str, ValuationConfig] | None = None,
        monitoring_policies: Mapping[str, MonitoringPolicy] | None = None,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError("construct a workspace with Workspace.create() or Workspace.open()")
        self.project_root = Path(project_root)
        self._datasets = {
            key: _detach_registration(value) for key, value in (datasets or {}).items()
        }
        self._sources = {key: _detach_source(value) for key, value in (sources or {}).items()}
        self._execution_inputs = {
            key: _detach_execution_input(value) for key, value in (execution_inputs or {}).items()
        }
        self._components = {
            key: _detach_component(value) for key, value in (components or {}).items()
        }
        self._agendas = {key: _detach_agenda(value) for key, value in (agendas or {}).items()}
        self._strategy_configs = {
            key: _detach_strategy_config(value) for key, value in (strategy_configs or {}).items()
        }
        self._valuation_configs = {
            key: _detach_valuation_config(value) for key, value in (valuation_configs or {}).items()
        }
        self._monitoring_policies = {
            key: _detach_monitoring_policy(value)
            for key, value in (monitoring_policies or {}).items()
        }

    @classmethod
    def _from_state(
        cls,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
        execution_inputs: Mapping[ExecutionInputId, ExecutionInputRegistration],
        components: Mapping[ComponentId, ComponentRef],
        agendas: Mapping[str, OperationAgenda],
        strategy_configs: Mapping[str, StrategyConfig],
        valuation_configs: Mapping[str, ValuationConfig],
        monitoring_policies: Mapping[str, MonitoringPolicy],
    ) -> Workspace:
        return cls(
            project_root,
            datasets,
            sources,
            execution_inputs,
            components,
            agendas,
            strategy_configs,
            valuation_configs,
            monitoring_policies,
            _token=_CONSTRUCTION_TOKEN,
        )

    @property
    def path(self) -> Path:
        return self.project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME

    @classmethod
    def create(cls, project_root: str | Path) -> Workspace:
        """새 project workspace를 만들거나 이미 있으면 그대로 연다."""
        candidate = cls._from_state(project_root, {}, {}, {}, {}, {}, {}, {}, {})
        if candidate.path.exists():
            return cls.open(project_root)
        candidate._write({}, {}, {}, {}, {}, {}, {}, {})
        return candidate

    @classmethod
    def open(cls, project_root: str | Path) -> Workspace:
        """기존 workspace 전체를 읽는다. 없거나 손상됐으면 일부 상태를 반환하지 않는다."""
        candidate = cls._from_state(project_root, {}, {}, {}, {}, {}, {}, {}, {})
        return cls._from_state(project_root, *candidate._read())

    @property
    def datasets(self) -> tuple[DatasetRegistration, ...]:
        """dataset_id 순으로 정렬된 detached 선언들."""
        return tuple(_detach_registration(self._datasets[key]) for key in sorted(self._datasets))

    @property
    def sources(self) -> tuple[SourceSpec, ...]:
        """source_id 순으로 정렬된 detached 물리 선언들."""
        return tuple(_detach_source(self._sources[key]) for key in sorted(self._sources))

    @property
    def execution_inputs(self) -> tuple[ExecutionInputRegistration, ...]:
        """execution_input_id 순으로 정렬된 detached Exchange 입력 선언들."""
        return tuple(
            _detach_execution_input(self._execution_inputs[key])
            for key in sorted(self._execution_inputs)
        )

    @property
    def components(self) -> tuple[ComponentRef, ...]:
        """component_id 순으로 정렬된 detached project-local component references."""
        return tuple(_detach_component(self._components[key]) for key in sorted(self._components))

    @property
    def agendas(self) -> tuple[OperationAgenda, ...]:
        return tuple(_detach_agenda(self._agendas[key]) for key in sorted(self._agendas))

    @property
    def strategy_configs(self) -> tuple[StrategyConfig, ...]:
        return tuple(
            _detach_strategy_config(self._strategy_configs[key])
            for key in sorted(self._strategy_configs)
        )

    @property
    def valuation_configs(self) -> tuple[ValuationConfig, ...]:
        return tuple(
            _detach_valuation_config(self._valuation_configs[key])
            for key in sorted(self._valuation_configs)
        )

    @property
    def monitoring_policies(self) -> tuple[MonitoringPolicy, ...]:
        return tuple(
            _detach_monitoring_policy(self._monitoring_policies[key])
            for key in sorted(self._monitoring_policies)
        )

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        """등록된 선언 하나를 조회한다."""
        try:
            key = dataset_id(raw_dataset_id)
        except ValueError as error:
            raise _workspace_error(
                stage=LOOKUP_STAGE,
                code=f"{LOOKUP_STAGE}.invalid",
                requirement="dataset lookup requires a valid dataset_id",
                observed=str(error),
                fix="pass a valid dataset_id string to Workspace.dataset()",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="use a valid dataset_id, then retry",
            ) from error
        try:
            registration = self._datasets[key]
        except KeyError as error:
            raise _workspace_error(
                stage=LOOKUP_STAGE,
                code=f"{LOOKUP_STAGE}.missing",
                requirement=f"dataset {key!r} must be registered in this workspace",
                observed=f"registered datasets: {', '.join(sorted(self._datasets)) or '(none)'}",
                fix=(
                    f"register dataset {key!r}, or look up one of the registered datasets "
                    "listed above"
                ),
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="register the dataset, then retry",
            ) from error
        # Point of use, which is where a quarantined registration is refused. Decode admits it so
        # the workspace stays enumerable and repairable; USING it is what must not happen, since
        # every consumer downstream of here treats a registration as complete.
        _require_span(str(key), registration)
        return _detach_registration(registration)

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
        """
        registration = self.dataset(raw_dataset_id)
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
                    stage=LOOKUP_STAGE,
                    code=f"{LOOKUP_STAGE}.invalid",
                    requirement=f"dataset {raw_dataset_id!r} available_at must be a timestamp",
                    observed=type(value).__name__,
                    fix="re-register the dataset with a timestamp-typed available_at column",
                    explain=ExplainTopic.DATASET_PREPARATION,
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
                stage=SOURCE_LOOKUP_STAGE,
                code=f"{SOURCE_LOOKUP_STAGE}.invalid",
                requirement="source lookup requires a valid source_id",
                observed=str(error),
                fix="pass a valid source_id string to Workspace.source()",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="use a valid source_id, then retry",
            ) from error
        try:
            return _detach_source(self._sources[key])
        except KeyError as error:
            raise _workspace_error(
                stage=SOURCE_LOOKUP_STAGE,
                code=f"{SOURCE_LOOKUP_STAGE}.missing",
                requirement=f"source {key!r} must be registered in this workspace",
                observed=f"registered sources: {', '.join(sorted(self._sources)) or '(none)'}",
                fix=f"register a dataset or execution input against source_id {key!r} first",
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="register a dataset or execution input with that source, then retry",
            ) from error

    def execution_input(self, raw_execution_input_id: str) -> ExecutionInputRegistration:
        """등록된 execution input 하나를 조회한다."""
        try:
            key = execution_input_id(raw_execution_input_id)
        except ValueError as error:
            raise _workspace_error(
                stage=EXECUTION_LOOKUP_STAGE,
                code=f"{EXECUTION_LOOKUP_STAGE}.invalid",
                requirement="execution input lookup requires a valid execution_input_id",
                observed=str(error),
                fix="pass a valid execution_input_id string to Workspace.execution_input()",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="use a valid execution_input_id, then retry",
                family=FailureFamily.EXCHANGE,
            ) from error
        try:
            return _detach_execution_input(self._execution_inputs[key])
        except KeyError as error:
            raise _workspace_error(
                stage=EXECUTION_LOOKUP_STAGE,
                code=f"{EXECUTION_LOOKUP_STAGE}.missing",
                requirement=f"execution input {key!r} must be registered in this workspace",
                observed=(
                    "registered execution inputs: "
                    f"{', '.join(sorted(self._execution_inputs)) or '(none)'}"
                ),
                fix=f"register execution input {key!r}, or use one of the ids listed above",
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="register the execution input, then retry",
                family=FailureFamily.EXCHANGE,
            ) from error

    def component(self, raw_component_id: str) -> ComponentRef:
        """등록된 project-local component reference 하나를 조회한다."""
        try:
            key = component_id(raw_component_id)
        except ValueError as error:
            raise _workspace_error(
                stage=COMPONENT_LOOKUP_STAGE,
                code=f"{COMPONENT_LOOKUP_STAGE}.invalid",
                requirement="component lookup requires a valid component_id",
                observed=str(error),
                fix="pass a valid component_id string to Workspace.component()",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="use a valid component_id, then retry",
            ) from error
        try:
            return _detach_component(self._components[key])
        except KeyError as error:
            raise _workspace_error(
                stage=COMPONENT_LOOKUP_STAGE,
                code=f"{COMPONENT_LOOKUP_STAGE}.missing",
                requirement=f"component {key!r} must be registered in this workspace",
                observed=(
                    f"registered components: {', '.join(sorted(self._components)) or '(none)'}"
                ),
                fix=f"register component {key!r}, or use one of the ids listed above",
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="register the component, then retry",
            ) from error

    def agenda(self, raw_agenda_id: str) -> OperationAgenda:
        if not isinstance(raw_agenda_id, str) or not raw_agenda_id:
            raise _workspace_error(
                stage=AGENDA_LOOKUP_STAGE,
                code=f"{AGENDA_LOOKUP_STAGE}.invalid",
                requirement="agenda lookup requires a valid agenda_id",
                observed=repr(raw_agenda_id),
                fix="pass a non-empty agenda_id string to Workspace.agenda()",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="use a valid agenda_id, then retry",
            )
        try:
            return _detach_agenda(self._agendas[raw_agenda_id])
        except KeyError as error:
            raise _workspace_error(
                stage=AGENDA_LOOKUP_STAGE,
                code=f"{AGENDA_LOOKUP_STAGE}.missing",
                requirement=f"agenda {raw_agenda_id!r} must be registered in this workspace",
                observed=f"registered agendas: {', '.join(sorted(self._agendas)) or '(none)'}",
                fix=f"register agenda {raw_agenda_id!r}, or use one of the ids listed above",
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="register the agenda, then retry",
            ) from error

    def strategy_config(self, raw_agenda_id: str) -> StrategyConfig:
        return self._config_lookup(
            raw_agenda_id,
            self._strategy_configs,
            _detach_strategy_config,
            STRATEGY_REGISTER_STAGE,
            "strategy config",
        )

    def valuation_config(self, raw_agenda_id: str) -> ValuationConfig:
        return self._config_lookup(
            raw_agenda_id,
            self._valuation_configs,
            _detach_valuation_config,
            VALUATION_REGISTER_STAGE,
            "valuation config",
        )

    def monitoring_policy(self, raw_agenda_id: str) -> MonitoringPolicy:
        return self._config_lookup(
            raw_agenda_id,
            self._monitoring_policies,
            _detach_monitoring_policy,
            MONITORING_REGISTER_STAGE,
            "monitoring policy",
        )

    def register_dataset(self, registration: DatasetRegistration, source: SourceSpec) -> bool:
        """물리·의미 선언을 보관한다. 새 dataset이면 True, 동일하면 False다.

        같은 ``dataset_id``가 다른 선언을 뜻하도록 조용히 바꾸지 않는다. replace는 이 slice의
        지원 범위가 아니다.
        """
        if registration.source != source.source_id:
            raise _workspace_error(
                stage=REGISTER_STAGE,
                code=f"{REGISTER_STAGE}.source_mismatch",
                requirement="DatasetRegistration.source must match SourceSpec.source_id",
                observed=(
                    f"registration source={registration.source!r}, source spec={source.source_id!r}"
                ),
                fix="pass a DatasetRegistration and SourceSpec that name the same source_id",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="bind the dataset and physical source to the same source_id, then retry",
            )

        if registration.span is None:
            # Refused, not measured here. This method is a metadata write and opens no source; the
            # span comes from the full read `validate` already performs, so measuring again would
            # be a second scan of the same file and would turn persistence into an I/O operation.
            raise _workspace_error(
                stage=REGISTER_STAGE,
                code="dataset.register.span.absent",
                requirement="every registration must carry a span measured while it validated",
                observed=f"dataset {str(registration.dataset_id)!r} carries no measured span",
                fix=(
                    "call vqapr.public.register_dataset instead of "
                    "Workspace.register_dataset directly"
                ),
                # WORKSPACE_STATE, not RUN_PRECONDITION: this fires on a direct
                # `Workspace.register_dataset` before any run exists, so it is a fact about what
                # the workspace already holds rather than about a declared run. The sibling
                # refusal for the same code decides the same way, and one code carrying two
                # topics would break the closed-set classification the enum exists to provide.
                explain=ExplainTopic.WORKSPACE_STATE,
                retry=(
                    "register through vqapr.public.register_dataset, which validates the source "
                    "which measures the span while it validates"
                ),
            )

        with self._exclusive():
            (
                datasets,
                sources,
                execution_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            ) = self._read()
            key = registration.dataset_id
            source_key = source.source_id
            existing_source = sources.get(source_key)
            if existing_source is not None and existing_source != source:
                raise _workspace_error(
                    stage=REGISTER_STAGE,
                    code=f"{REGISTER_STAGE}.source_conflict",
                    requirement=(
                        f"source_id {source_key!r} must keep its existing "
                        "physical declaration"
                    ),
                    observed="a different SourceSpec is already registered",
                    fix=(
                        f"reuse the registered SourceSpec for {source_key!r}, or register "
                        "under a new source_id"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                    retry="use the existing source declaration or choose a new source_id",
                )

            existing = datasets.get(key)
            if existing is not None and existing.span is None:
                # A quarantined registration is being repaired. It differs from its replacement in
                # exactly one way -- it has no span -- so the conflict check below would read that
                # as a changed declaration and refuse the repair it advertises. Compare on the
                # declared half, and let the measurement be the thing that changes.
                if replace(existing, span=registration.span) != registration:
                    raise _workspace_error(
                        stage=REGISTER_STAGE,
                        code=f"{REGISTER_STAGE}.conflict",
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
                        explain=ExplainTopic.WORKSPACE_STATE,
                        retry="use the existing declaration or choose a new dataset_id",
                    )
                existing = None

            if existing is not None:
                if existing == registration and existing_source == source:
                    self._replace_state(
                        datasets,
                        sources,
                        execution_inputs,
                        components,
                        agendas,
                        strategy_configs,
                        valuation_configs,
                        monitoring_policies,
                    )
                    return False
                raise _workspace_error(
                    stage=REGISTER_STAGE,
                    code=f"{REGISTER_STAGE}.conflict",
                    requirement=(
                        f"dataset_id {key!r} must keep its existing declaration "
                        "or use a new identity"
                    ),
                    observed="a different declaration is already registered",
                    fix=(
                        f"keep the registered declaration for {key!r} unchanged, or "
                        "choose a new dataset_id"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                    retry="use the existing declaration or choose a new dataset_id",
                )

            merged_datasets = dict(datasets)
            merged_sources = dict(sources)
            merged_datasets[key] = _detach_registration(registration)
            merged_sources[source_key] = _detach_source(source)
            self._write(
                merged_datasets,
                merged_sources,
                execution_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            )
            self._replace_state(
                merged_datasets,
                merged_sources,
                execution_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            )
            return True

    def register_execution_input(self, registration: ExecutionInputRegistration) -> bool:
        """검증을 통과한 execution table + fill declaration을 원자적으로 보관한다."""
        if not isinstance(registration, ExecutionInputRegistration):
            raise TypeError("registration must be an ExecutionInputRegistration")

        with self._exclusive():
            (
                datasets,
                sources,
                execution_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            ) = self._read()
            key = registration.execution_input_id
            source = registration.table.source
            source_key = source.source_id
            existing_source = sources.get(source_key)
            if existing_source is not None and existing_source != source:
                raise _workspace_error(
                    stage=EXECUTION_REGISTER_STAGE,
                    code=f"{EXECUTION_REGISTER_STAGE}.source_conflict",
                    requirement=(
                        f"source_id {source_key!r} must keep its existing "
                        "physical declaration"
                    ),
                    observed="a different SourceSpec is already registered",
                    fix=(
                        f"reuse the registered SourceSpec for {source_key!r}, or register "
                        "under a new source_id"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                    retry="use the existing source declaration or choose a new source_id",
                    family=FailureFamily.EXCHANGE,
                )

            existing = execution_inputs.get(key)
            if existing is not None:
                if existing == registration and existing_source == source:
                    self._replace_state(
                        datasets,
                        sources,
                        execution_inputs,
                        components,
                        agendas,
                        strategy_configs,
                        valuation_configs,
                        monitoring_policies,
                    )
                    return False
                raise _workspace_error(
                    stage=EXECUTION_REGISTER_STAGE,
                    code=f"{EXECUTION_REGISTER_STAGE}.conflict",
                    requirement=(
                        f"execution_input_id {key!r} must keep its existing "
                        "declaration or use a new identity"
                    ),
                    observed="a different execution input declaration is already registered",
                    fix=(
                        f"keep the registered declaration for {key!r} unchanged, or "
                        "choose a new execution_input_id"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                    retry="use the existing declaration or choose a new execution_input_id",
                    family=FailureFamily.EXCHANGE,
                )

            merged_sources = dict(sources)
            merged_inputs = dict(execution_inputs)
            merged_sources[source_key] = _detach_source(source)
            merged_inputs[key] = _detach_execution_input(registration)
            self._write(
                datasets,
                merged_sources,
                merged_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            )
            self._replace_state(
                datasets,
                merged_sources,
                merged_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            )
            return True

    def register_component(self, ref: ComponentRef, *, force: bool = False) -> bool:
        """검증과 fingerprinting을 통과한 component reference를 원자적으로 보관한다.

        ``force=True`` replaces an existing registration whose source has changed, in place and
        under the same ``component_id``.

        Without it, editing a registered component and re-registering is refused, and the refusal
        names a new identity as the repair. That instruction contradicts the one `loading.py`
        prints when the same edit is loaded rather than registered -- it says *re-register the
        component*, which this method then declined. A reader following either message arrives at
        the other, which `docs/implementations/057` names as worse than a generic error.

        Replacing does not lose provenance: a finished run pins the fingerprint it ran under in
        its own record, so what a past run used is testified to by that run and not by whichever
        registration currently holds the id.
        """
        if not isinstance(ref, ComponentRef):
            raise TypeError("ref must be a ComponentRef")
        if not isinstance(force, bool):
            raise TypeError("force must be a bool")
        with self._exclusive():
            (
                datasets,
                sources,
                execution_inputs,
                components,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            ) = self._read()
            key = ref.component_id
            existing = components.get(key)
            if existing is not None:
                if existing == ref:
                    self._replace_state(
                        datasets,
                        sources,
                        execution_inputs,
                        components,
                        agendas,
                        strategy_configs,
                        valuation_configs,
                        monitoring_policies,
                    )
                    return False
                # An edited source replaces its registration in place, under the same id.
                #
                # This used to refuse and name a NEW component_id as the repair, while
                # `loading.py` -- meeting the same edit -- said "re-register the component", which
                # is what this refused. The two pointed at each other, and
                # `docs/implementations/057` names that shape as worse than a generic error.
                #
                # The real cost was never one command: a new id needed a new strategy_configs
                # binding and a spec edit, four steps for a one-line change, and the workspace
                # accumulated `mom`, `mom-eb04...`, `mom-91c7...` for one strategy. Keeping the id
                # also makes "this strategy ran 47 times across 12 fingerprints" countable, which
                # a new id per edit scatters across twelve ids where nothing counts it.
                #
                # Provenance is not weakened. A finished run pins the fingerprint it ran under in
                # its own frozen record, so what a past run used is testified to by that run, not
                # by whichever registration currently holds the id.
                #
                # `force` is retained as an explicit spelling for callers that want to say they
                # meant it, but it no longer gates anything: replacement is the default.
                _ = force
            merged = dict(components)
            merged[key] = _detach_component(ref)
            self._write(
                datasets,
                sources,
                execution_inputs,
                merged,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            )
            self._replace_state(
                datasets,
                sources,
                execution_inputs,
                merged,
                agendas,
                strategy_configs,
                valuation_configs,
                monitoring_policies,
            )
            return True

    def register_agenda(self, agenda: OperationAgenda) -> bool:
        if not isinstance(agenda, OperationAgenda):
            raise TypeError("agenda must be an OperationAgenda")
        with self._exclusive():
            state = self._read()
            agendas = state[4]
            return self._register_declaration(
                agenda.agenda_id, agenda, agendas, _detach_agenda, AGENDA_REGISTER_STAGE, state, 4
            )

    def register_strategy_config(self, config: StrategyConfig) -> bool:
        if not isinstance(config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        with self._exclusive():
            state = self._read()
            self._require_agenda(
                state[4], config.agenda_id, config.agenda_role, STRATEGY_REGISTER_STAGE
            )
            if state[3].get(config.component.component_id) != config.component:
                raise self._reference_error(
                    STRATEGY_REGISTER_STAGE,
                    "strategy component must be registered",
                    fix="register the strategy's component before registering the StrategyConfig",
                )
            return self._register_declaration(
                config.agenda_id,
                config,
                state[5],
                _detach_strategy_config,
                STRATEGY_REGISTER_STAGE,
                state,
                5,
            )

    def register_valuation_config(self, config: ValuationConfig) -> bool:
        if not isinstance(config, ValuationConfig):
            raise TypeError("config must be a ValuationConfig")
        with self._exclusive():
            state = self._read()
            self._require_agenda(
                state[4], config.agenda_id, config.agenda_role, VALUATION_REGISTER_STAGE
            )
            return self._register_declaration(
                config.agenda_id,
                config,
                state[6],
                _detach_valuation_config,
                VALUATION_REGISTER_STAGE,
                state,
                6,
            )

    def register_monitoring_policy(self, policy: MonitoringPolicy) -> bool:
        if not isinstance(policy, MonitoringPolicy):
            raise TypeError("policy must be a MonitoringPolicy")
        with self._exclusive():
            state = self._read()
            self._require_agenda(
                state[4], policy.agenda_id, policy.agenda_role, MONITORING_REGISTER_STAGE
            )
            return self._register_declaration(
                policy.agenda_id,
                policy,
                state[7],
                _detach_monitoring_policy,
                MONITORING_REGISTER_STAGE,
                state,
                7,
            )

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

    def register_instruments(
        self, tables: Mapping[str, Path | str], *, digest: str
    ) -> dict[str, object]:
        """Record which files declare this project's instruments, and what they hashed to.

        Stores a POINTER plus a digest, never a frozen copy. Issue 009 settles why: a roster grows
        as a matter of course -- a daily batch lists new tickers, issuers delist, a name is
        reclassified -- so a run is never refused for reading a roster that differs from the one
        recorded. The digest is STATED in the run record and compared against nothing.

        Re-registration is ordinary, unlike a dataset's. A dataset registration is immutable
        because changing it would rewrite provenance; a roster correction is a statement about the
        world ("069500 is an ETF"), and what a past run treated an instrument as is testified to
        by that run's own fills.
        """
        import json

        if not isinstance(tables, Mapping) or not tables:
            raise ValueError("instrument registration requires at least one table")
        if not isinstance(digest, str) or not digest:
            raise ValueError("digest must be a non-empty string")
        payload = {
            "schema": "vqapr.instruments/v1",
            "tables": {str(kind): str(Path(path)) for kind, path in sorted(tables.items())},
            "digest": digest,
        }
        with self._exclusive():
            self.roster_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return payload

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
                stage="workspace.instruments",
                code="workspace.instruments.unreadable",
                requirement="the registered instrument roster pointer must be readable JSON",
                observed=f"{self.roster_path.name}: {broken}",
                fix=(
                    "re-register the roster with `vqapr register <instruments>.yaml`, which "
                    "rewrites this file"
                ),
                explain=ExplainTopic.WORKSPACE_STATE,
                source=FailureSource(file=str(self.roster_path)),
                retry="re-register the instrument roster, then retry",
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
        blockers = self.references_to(kind, identity)
        if blockers:
            raise _workspace_error(
                stage=REMOVE_STAGE,
                code=f"{REMOVE_STAGE}.referenced",
                requirement=f"a {kind} may be removed only when nothing live still names it",
                observed=f"{identity!r} is referenced by " + ", ".join(blockers),
                fix=(
                    f"remove {', '.join(blockers)} first, or keep {identity!r} registered"
                ),
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="withdraw the referencing declarations, then retry",
            )
        position = {
            "component": 3,
            "agenda": 4,
            "strategy_config": 5,
            "valuation_config": 6,
            "monitoring_policy": 7,
        }[kind]
        with self._exclusive():
            state = self._read()
            declarations = dict(state[position])
            if identity not in declarations:
                self._replace_state(*state)
                return False
            del declarations[identity]
            merged = list(state)
            merged[position] = declarations
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
        """
        state = self._read()
        components, agendas, strategy_configs, valuation_configs, monitoring_policies = (
            state[3],
            state[4],
            state[5],
            state[6],
            state[7],
        )
        blockers: list[str] = []
        if kind == "component":
            for config_id, config in strategy_configs.items():
                if str(config.component.component_id) == identity:
                    blockers.append(f"strategy config {config_id!r}")
        elif kind == "agenda":
            for config_id, config in strategy_configs.items():
                if config.agenda_id == identity:
                    blockers.append(f"strategy config {config_id!r}")
            for config_id in valuation_configs:
                if config_id == identity:
                    blockers.append(f"valuation config {config_id!r}")
            for policy_id in monitoring_policies:
                if policy_id == identity:
                    blockers.append(f"monitoring policy {policy_id!r}")
        elif kind == "dataset":
            # A dataset is named by a component's declared requirements rather than by the
            # workspace document, so nothing here can claim to know every reader of one. Said
            # plainly instead of returning an empty tuple that would read as "safe to remove".
            raise _workspace_error(
                stage=REMOVE_STAGE,
                code=f"{REMOVE_STAGE}.unsupported_kind",
                requirement="removable kinds are component, agenda, and their configs",
                observed=repr(kind),
                fix=(
                    "a dataset's readers are declared inside component requirements, which this "
                    "workspace does not index; rebuild the workspace instead of removing one"
                ),
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="remove a component, agenda, or config instead",
            )
        elif kind in ("strategy_config", "valuation_config", "monitoring_policy"):
            # Leaf declarations: a run definition names them, and a run definition is not a
            # workspace registration. Nothing inside the workspace points at these.
            return ()
        else:
            raise _workspace_error(
                stage=REMOVE_STAGE,
                code=f"{REMOVE_STAGE}.unsupported_kind",
                requirement="kind must be one this workspace stores",
                observed=repr(kind),
                fix="use one of: component, agenda, strategy_config, valuation_config, "
                "monitoring_policy",
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="retry with a kind this workspace stores",
            )
        if kind == "component" and identity not in components:
            return ()
        if kind == "agenda" and identity not in agendas:
            return ()
        return tuple(sorted(blockers))

    def _config_lookup(
        self, key: str, declarations: Mapping[str, object], detach: object, stage: str, label: str
    ) -> object:
        if not isinstance(key, str) or not key:
            raise _workspace_error(
                stage=stage,
                code=f"{stage}.invalid",
                requirement=f"{label} lookup requires a valid agenda_id",
                observed=repr(key),
                fix="pass a non-empty agenda_id string to look up this configuration",
                explain=ExplainTopic.DECLARATION_SHAPE,
                retry="use a valid agenda_id, then retry",
            )
        try:
            return detach(declarations[key])  # type: ignore[operator]
        except KeyError as error:
            raise _workspace_error(
                stage=stage,
                code=f"{stage}.missing",
                requirement=f"{label} for agenda {key!r} must be registered",
                observed=f"registered {label}s: {', '.join(sorted(declarations)) or '(none)'}",
                fix=f"register a {label} for agenda {key!r}, or use one of the ids listed above",
                explain=ExplainTopic.WORKSPACE_STATE,
                retry=f"register the {label}, then retry",
            ) from error

    def _require_agenda(
        self,
        agendas: Mapping[str, OperationAgenda],
        agenda_id: str,
        role: OperationRole,
        stage: str,
    ) -> None:
        agenda = agendas.get(agenda_id)
        if agenda is None or agenda.role is not role:
            # Two different repairs hide behind one condition: the agenda may be absent, or it
            # may exist under a role this configuration cannot use. Saying which one it is costs
            # nothing here -- both values are parameters -- and saves the reader from checking.
            missing = agenda is None
            wanted = role.value.lower()
            raise self._reference_error(
                stage,
                "declared agenda must be registered with the matching role",
                fix=(
                    f"register agenda {agenda_id!r} with role {wanted} before registering this "
                    "configuration"
                    if missing
                    else (
                        f"agenda {agenda_id!r} is registered as "
                        f"{agenda.role.value.lower()}; register it as {wanted}, or point this "
                        "configuration at an agenda that already has that role"
                    )
                ),
            )

    def _reference_error(self, stage: str, requirement: str, *, fix: str) -> VqaprError:
        return _workspace_error(
            stage=stage,
            code=f"{stage}.reference",
            requirement=requirement,
            observed="referenced declaration is absent or differs from the registered declaration",
            fix=fix,
            explain=ExplainTopic.WORKSPACE_STATE,
            retry="register matching referenced declarations before retrying",
        )

    def _locked_refusal(self, lock: Path, timeout: float) -> VqaprError:
        """The refusal a waiter gets when another writer held the workspace for the whole timeout.

        Passed to `filelock.exclusive` rather than raised by it: the shared mutex knows it timed
        out, and this knows what a workspace is, what a reader should do about it, and which
        `explain` topic answers the follow-up question.
        """
        return _workspace_error(
            stage=WRITE_STAGE,
            code=f"{WRITE_STAGE}.locked",
            requirement=f"workspace at {self.path} must be writable within {timeout:.0f}s",
            observed=f"another process has held {lock} for the whole timeout",
            fix=(
                f"wait for the other writer to finish, or delete {lock} if no writer "
                "is actually running"
            ),
            explain=ExplainTopic.WORKSPACE_STATE,
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

    def _register_declaration(
        self,
        key: str,
        value: object,
        declarations: Mapping[str, object],
        detach: object,
        stage: str,
        state: tuple[object, ...],
        position: int,
    ) -> bool:
        existing = declarations.get(key)
        if existing is not None:
            if existing == value:
                self._replace_state(*state)  # type: ignore[arg-type]
                return False
            raise _workspace_error(
                stage=stage,
                code=f"{stage}.conflict",
                requirement=(
                    f"agenda_id {key!r} must keep its existing declaration or use a new identity"
                ),
                observed="a different declaration is already registered",
                fix=(
                    f"keep the registered declaration for {key!r} unchanged, or choose "
                    "a new agenda_id"
                ),
                explain=ExplainTopic.WORKSPACE_STATE,
                retry="use the existing declaration or choose a new agenda_id",
            )
        merged = list(state)
        updated = dict(declarations)
        updated[key] = detach(value)  # type: ignore[operator]
        merged[position] = updated
        self._write(*merged)  # type: ignore[arg-type]
        self._replace_state(*merged)  # type: ignore[arg-type]
        return True

    def _read(
        self,
    ) -> tuple[
        dict[DatasetId, DatasetRegistration],
        dict[SourceId, SourceSpec],
        dict[ExecutionInputId, ExecutionInputRegistration],
        dict[ComponentId, ComponentRef],
        dict[str, OperationAgenda],
        dict[str, StrategyConfig],
        dict[str, ValuationConfig],
        dict[str, MonitoringPolicy],
    ]:
        text: str | None = None
        for attempt in range(WORKSPACE_SWAP_ATTEMPTS):
            try:
                text = self.path.read_text(encoding="utf-8")
                break
            except FileNotFoundError as error:
                raise _workspace_error(
                    stage=OPEN_STAGE,
                    code=f"{OPEN_STAGE}.missing",
                    requirement=f"workspace must exist at {self.path}",
                    observed="path does not exist",
                    # A CLI path, because the reader who reaches this has only ever typed
                    # commands: `register` is the door into a workspace, and it creates one where
                    # none exists. Naming `Workspace.create()` sent a user who had never written
                    # a line of Python to look for a Python call, which is the same substitution
                    # `declaration.read` avoids by naming the file rather than the dict lookup.
                    fix=(
                        "run `vqapr register <declaration>.yaml` in this directory, which "
                        "creates the workspace as it registers; or `vqapr new run-spec` to "
                        "start from a template"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                    source=FailureSource(file=str(self.path)),
                    retry="create the workspace, then retry",
                ) from error
            except OSError as error:
                # A concurrent atomic replace, not an unreadable workspace. Distinguished by
                # outlasting it: a swap completes, a permission problem does not.
                if attempt + 1 == WORKSPACE_SWAP_ATTEMPTS:
                    raise _workspace_error(
                        stage=OPEN_STAGE,
                        code=f"{OPEN_STAGE}.unreadable",
                        requirement=f"workspace must be readable at {self.path}",
                        observed=str(error),
                        fix="fix filesystem permissions on the workspace file, then retry",
                        explain=ExplainTopic.WORKSPACE_STATE,
                        source=FailureSource(file=str(self.path)),
                        retry="make the workspace readable, then retry",
                    ) from error
                _time.sleep(WORKSPACE_SWAP_BACKOFF * (attempt + 1))
        assert text is not None

        try:
            return _decode_cached(text)  # type: ignore[return-value]
        except (TypeError, ValueError, yaml.YAMLError) as error:
            message = str(error)
            requirement = (
                message
                if (
                    "offset_sessions is no longer supported" in message
                    or "old fill schema" in message
                )
                else "workspace YAML must contain valid physical sources and dataset declarations"
            )
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.invalid",
                requirement=requirement,
                observed=str(error),
                fix="hand-edit or recreate the workspace YAML to match the current schema",
                explain=ExplainTopic.WORKSPACE_STATE,
                source=FailureSource(file=str(self.path)),
                retry="fix or recreate the workspace, then retry",
            ) from error

    def _replace_state(
        self,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
        execution_inputs: Mapping[ExecutionInputId, ExecutionInputRegistration],
        components: Mapping[ComponentId, ComponentRef],
        agendas: Mapping[str, OperationAgenda],
        strategy_configs: Mapping[str, StrategyConfig],
        valuation_configs: Mapping[str, ValuationConfig],
        monitoring_policies: Mapping[str, MonitoringPolicy],
    ) -> None:
        self._datasets = {key: _detach_registration(value) for key, value in datasets.items()}
        self._sources = {key: _detach_source(value) for key, value in sources.items()}
        self._execution_inputs = {
            key: _detach_execution_input(value) for key, value in execution_inputs.items()
        }
        self._components = {key: _detach_component(value) for key, value in components.items()}
        self._agendas = {key: _detach_agenda(value) for key, value in agendas.items()}
        self._strategy_configs = {
            key: _detach_strategy_config(value) for key, value in strategy_configs.items()
        }
        self._valuation_configs = {
            key: _detach_valuation_config(value) for key, value in valuation_configs.items()
        }
        self._monitoring_policies = {
            key: _detach_monitoring_policy(value) for key, value in monitoring_policies.items()
        }

    def _write(
        self,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
        execution_inputs: Mapping[ExecutionInputId, ExecutionInputRegistration],
        components: Mapping[ComponentId, ComponentRef],
        agendas: Mapping[str, OperationAgenda],
        strategy_configs: Mapping[str, StrategyConfig],
        valuation_configs: Mapping[str, ValuationConfig],
        monitoring_policies: Mapping[str, MonitoringPolicy],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _encode(
            datasets,
            sources,
            execution_inputs,
            components,
            agendas,
            strategy_configs,
            valuation_configs,
            monitoring_policies,
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{WORKSPACE_FILENAME}.",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(WORKSPACE_SWAP_ATTEMPTS):
                try:
                    os.replace(temporary, self.path)
                    break
                except OSError:
                    # A reader has the target open. Windows refuses the swap rather than letting
                    # the reader keep the old file, and the reader is gone microseconds later.
                    if attempt + 1 == WORKSPACE_SWAP_ATTEMPTS:
                        raise
                    _time.sleep(WORKSPACE_SWAP_BACKOFF * (attempt + 1))
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise _workspace_error(
                stage=WRITE_STAGE,
                code=f"{WRITE_STAGE}.failed",
                requirement=f"workspace must be written at {self.path}",
                observed=str(error),
                fix="make the workspace directory writable, then retry",
                explain=ExplainTopic.PUBLICATION,
                source=FailureSource(file=str(self.path)),
                retry="make the workspace directory writable, then retry",
            ) from error


def _stale_lock_age(lock: Path) -> float | None:
    """Seconds since the lock was created, or None if it just disappeared."""
    try:
        return max(0.0, _time.time() - lock.stat().st_mtime)
    except OSError:
        return None


def _detach_registration(registration: DatasetRegistration) -> DatasetRegistration:
    detached = DatasetRegistration.of(
        str(registration.dataset_id),
        str(registration.source),
        instrument_field=registration.instrument_field,
        available_at=registration.available_at,
        key_fields=registration.key_fields,
        fields=dict(registration.fields),
    )
    # `of` does not take a span, because a span is measured rather than declared. Detaching must
    # still carry the measurement across, or every read would hand back a registration that had
    # silently forgotten it.
    return detached if registration.span is None else detached.with_span(*registration.span)


def _detach_source(source: SourceSpec) -> SourceSpec:
    return SourceSpec.of(
        str(source.source_id),
        source.path,
        hive_partitioned=source.hive_partitioned,
    )


def _detach_execution_input(
    registration: ExecutionInputRegistration,
) -> ExecutionInputRegistration:
    table = registration.table
    fill = registration.fill
    return ExecutionInputRegistration.of(
        str(registration.execution_input_id),
        ExecutionTableSpec(
            source=_detach_source(table.source),
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


def _detach_valuation_config(config: ValuationConfig) -> ValuationConfig:
    return ValuationConfig(config.agenda_id, config.agenda_role)


def _detach_monitoring_policy(policy: MonitoringPolicy) -> MonitoringPolicy:
    return MonitoringPolicy(policy.agenda_id, policy.agenda_role)


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
        stage=SPAN_STAGE,
        code=f"{SPAN_STAGE}.absent",
        requirement="every registration must carry a span measured while it validated",
        observed=f"{dataset_id} was registered before span persistence",
        # The real invocation. `vqapr register` takes one positional argument, the declaration
        # YAML that names the dataset and its source; there is no `data` subcommand and no
        # parquet path goes on this command line.
        fix=(
            f"re-register {dataset_id} by running: vqapr register <declaration.yaml>, where that "
            "document declares this dataset and the source it reads"
        ),
        explain=ExplainTopic.WORKSPACE_STATE,
        retry=(
            f"re-register {dataset_id} by running: vqapr register <declaration.yaml>, where that "
            "document declares this dataset and the source it reads"
        ),
    )


def _encoded_dataset(registration: DatasetRegistration) -> dict[str, object]:
    """One registration as it is written back.

    A quarantined registration -- one decoded from a document written before spans existed -- is
    written back in the SAME legacy shape it was read in, without a span. This is what makes the
    repair incremental: `register_dataset` rewrites the whole document, so inventing a span for
    the other stale entries would either fabricate a measurement nobody took or refuse the write
    and block the repair of the one dataset the caller actually fixed.

    A span-less registration that never came from disk cannot reach here: `register_dataset`
    refuses it before the document is assembled.
    """
    body: dict[str, object] = {
        "source": str(registration.source),
        "instrument_field": registration.instrument_field,
        "available_at": registration.available_at,
        "key_fields": list(registration.key_fields),
        "fields": dict(registration.fields),
    }
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
    valuation_configs: Mapping[str, ValuationConfig],
    monitoring_policies: Mapping[str, MonitoringPolicy],
) -> str:
    document = {
        "sources": {
            str(key): {
                "path": str(source.path),
                "hive_partitioned": source.hive_partitioned,
            }
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
        "strategy_configs": {
            key: {
                "component": str(config.component.component_id),
                "agenda_role": str(config.agenda_role),
            }
            for key, config in sorted(strategy_configs.items())
        },
        "valuation_configs": {
            key: {
                "agenda_role": str(config.agenda_role),
            }
            for key, config in sorted(valuation_configs.items())
        },
        "monitoring_policies": {
            key: {"agenda_role": str(policy.agenda_role)}
            for key, policy in sorted(monitoring_policies.items())
        },
    }
    for section in ("agendas", "strategy_configs", "valuation_configs", "monitoring_policies"):
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
    dict[str, ValuationConfig],
    dict[str, MonitoringPolicy],
]:
    document = yaml.load(text, Loader=_YAML_LOADER)
    required_roots = {"sources", "datasets"}
    optional_roots = {
        "execution_inputs",
        "components",
        "agendas",
        "strategy_configs",
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
            "components, agendas, strategy_configs, valuation_configs, and monitoring_policies"
        )

    raw_sources = document["sources"]
    if not isinstance(raw_sources, dict):
        raise TypeError("sources must be a mapping")

    decoded_sources: dict[SourceId, SourceSpec] = {}
    expected_source = {"path", "hive_partitioned"}
    for raw_id, raw_source in raw_sources.items():
        if not isinstance(raw_id, str):
            raise TypeError("every source_id must be a string")
        if not isinstance(raw_source, dict) or set(raw_source) != expected_source:
            raise ValueError(f"source {raw_id!r} must contain exactly {sorted(expected_source)}")
        path = raw_source["path"]
        hive_partitioned = raw_source["hive_partitioned"]
        if not isinstance(path, str):
            raise TypeError(f"source {raw_id!r} path must be a string")
        if not isinstance(hive_partitioned, bool):
            raise TypeError(f"source {raw_id!r} hive_partitioned must be a boolean")
        source = SourceSpec.of(raw_id, path, hive_partitioned=hive_partitioned)
        decoded_sources[source.source_id] = source

    raw_datasets = document["datasets"]
    if not isinstance(raw_datasets, dict):
        raise TypeError("datasets must be a mapping")

    decoded: dict[DatasetId, DatasetRegistration] = {}
    expected = {"source", "instrument_field", "available_at", "key_fields", "fields", "span"}
    legacy = expected - {"span"}

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
        present = set(raw_registration)
        if present == legacy:
            quarantined.add(raw_id)
        elif present != expected:
            raise ValueError(f"dataset {raw_id!r} must contain exactly {sorted(expected)}")

        source = raw_registration["source"]
        instrument_field = raw_registration["instrument_field"]
        available_at = raw_registration["available_at"]
        key_fields = raw_registration["key_fields"]
        fields = raw_registration["fields"]
        if not all(isinstance(value, str) for value in (source, instrument_field, available_at)):
            raise TypeError(f"dataset {raw_id!r} scalar declarations must be strings")
        if not isinstance(key_fields, list) or not all(
            isinstance(value, str) for value in key_fields
        ):
            raise TypeError(f"dataset {raw_id!r} key_fields must be a list of strings")
        if not isinstance(fields, dict) or not all(
            isinstance(name, str) and isinstance(column, str) for name, column in fields.items()
        ):
            raise TypeError(f"dataset {raw_id!r} fields must map strings to strings")
        registration = DatasetRegistration.of(
            raw_id,
            source,
            instrument_field=instrument_field,
            available_at=available_at,
            key_fields=key_fields,
            fields=fields,
        )
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
    raw_valuation_configs = document.get("valuation_configs", {})
    raw_monitoring_policies = document.get("monitoring_policies", {})
    if not all(
        isinstance(value, dict)
        for value in (raw_strategy_configs, raw_valuation_configs, raw_monitoring_policies)
    ):
        raise TypeError("configuration sections must be mappings")
    decoded_strategy_configs: dict[str, StrategyConfig] = {}
    for raw_id, raw_config in raw_strategy_configs.items():
        if (
            not isinstance(raw_id, str)
            or not isinstance(raw_config, dict)
            or set(raw_config) != {"component", "agenda_role"}
        ):
            raise ValueError(
                "strategy config must contain an agenda_id and exactly component and agenda_role"
            )
        component = raw_config["component"]
        role = raw_config["agenda_role"]
        if not isinstance(component, str) or not isinstance(role, str):
            raise TypeError("strategy config fields must be strings")
        try:
            registered_component = decoded_components[component_id(component)]
        except KeyError as error:
            raise ValueError(
                f"strategy config {raw_id!r} references an unregistered component"
            ) from error
        config = StrategyConfig(registered_component, raw_id, OperationRole(role))
        if (
            decoded_agendas.get(raw_id) is None
            or decoded_agendas[raw_id].role is not config.agenda_role
        ):
            raise ValueError(
                f"strategy config {raw_id!r} references an absent or mismatched agenda"
            )
        decoded_strategy_configs[raw_id] = config
    decoded_valuation_configs: dict[str, ValuationConfig] = {}
    for raw_id, raw_config in raw_valuation_configs.items():
        if not isinstance(raw_id, str) or not isinstance(raw_config, dict):
            raise ValueError("valuation config must contain an agenda_id and agenda_role")
        if "mark_requirement" in raw_config:
            # Refuse rather than ignore. A workspace written before valuation moved to the
            # execution table declares a price subscription this run would silently not use, and
            # its NAV would differ from what that declaration says it should be.
            raise ValueError(
                f"valuation config {raw_id!r} declares mark_requirement, which no longer exists: "
                "valuation reads the execution table, so re-register the valuation config "
                "without it"
            )
        if set(raw_config) != {"agenda_role"}:
            raise ValueError("valuation config must contain exactly agenda_role")
        role = raw_config["agenda_role"]
        if not isinstance(role, str):
            raise TypeError("valuation config agenda_role must be a string")
        config = ValuationConfig(raw_id, OperationRole(role))
        if (
            decoded_agendas.get(raw_id) is None
            or decoded_agendas[raw_id].role is not config.agenda_role
        ):
            raise ValueError(f"valuation config {raw_id!r} references an absent declaration")
        decoded_valuation_configs[raw_id] = config
    decoded_monitoring_policies: dict[str, MonitoringPolicy] = {}
    for raw_id, raw_policy in raw_monitoring_policies.items():
        if (
            not isinstance(raw_id, str)
            or not isinstance(raw_policy, dict)
            or set(raw_policy) != {"agenda_role"}
            or not isinstance(raw_policy["agenda_role"], str)
        ):
            raise ValueError("monitoring policy must contain an agenda_id and exactly agenda_role")
        policy = MonitoringPolicy(raw_id, OperationRole(raw_policy["agenda_role"]))
        if (
            decoded_agendas.get(raw_id) is None
            or decoded_agendas[raw_id].role is not policy.agenda_role
        ):
            raise ValueError(
                f"monitoring policy {raw_id!r} references an absent or mismatched agenda"
            )
        decoded_monitoring_policies[raw_id] = policy
    return (
        decoded,
        decoded_sources,
        decoded_execution_inputs,
        decoded_components,
        decoded_agendas,
        decoded_strategy_configs,
        decoded_valuation_configs,
        decoded_monitoring_policies,
    )


def _encode_requirement(requirement: DataRequirement) -> dict[str, object]:
    lookback = requirement.lookback
    if isinstance(lookback, RowsLookback):
        encoded_lookback: dict[str, object] = {"kind": "rows", "rows": lookback.rows}
    else:
        encoded_lookback = {
            "kind": "calendar",
            "years": lookback.years,
            "months": lookback.months,
            "days": lookback.days,
            "timezone": lookback.timezone,
        }
    return {
        "consumer_id": requirement.consumer_id,
        "dataset_id": str(requirement.dataset_id),
        "fields": list(requirement.fields),
        "lookback": encoded_lookback,
    }


def _decode_requirement(raw: object) -> DataRequirement:
    if not isinstance(raw, dict) or set(raw) != {"consumer_id", "dataset_id", "fields", "lookback"}:
        raise ValueError(
            "mark_requirement must contain exactly consumer_id, dataset_id, fields, and lookback"
        )
    consumer_id, raw_dataset_id, fields, raw_lookback = (
        raw["consumer_id"],
        raw["dataset_id"],
        raw["fields"],
        raw["lookback"],
    )
    if (
        not isinstance(consumer_id, str)
        or not isinstance(raw_dataset_id, str)
        or not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
    ):
        raise TypeError("mark_requirement declarations must use strings")
    if not isinstance(raw_lookback, dict) or not isinstance(raw_lookback.get("kind"), str):
        raise TypeError("mark_requirement lookback must be a mapping with a kind")
    if raw_lookback["kind"] == "rows" and set(raw_lookback) == {"kind", "rows"}:
        lookback = RowsLookback(raw_lookback["rows"])
    elif raw_lookback["kind"] == "calendar" and set(raw_lookback) == {
        "kind",
        "years",
        "months",
        "days",
        "timezone",
    }:
        lookback = CalendarLookback(
            raw_lookback["years"],
            raw_lookback["months"],
            raw_lookback["days"],
            raw_lookback["timezone"],
        )
    else:
        raise ValueError("mark_requirement lookback has an invalid shape")
    return DataRequirement.of(consumer_id, raw_dataset_id, fields=fields, lookback=lookback)


def _workspace_error(
    *,
    stage: str,
    code: str,
    requirement: str,
    observed: str,
    retry: str,
    fix: str,
    explain: ExplainTopic,
    family: FailureFamily = FailureFamily.DATA,
    source: FailureSource | None = None,
) -> VqaprError:
    return VqaprError(
        stage=stage,
        family=family,
        failures=[
            Failure.bounded(
                code, requirement, observed=observed, fix=fix, explain=explain, source=source
            )
        ],
        mutation=False,
        retry_precondition=retry,
    )
