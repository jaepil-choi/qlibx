"""한 project가 명령 사이에 축적하는 선언 집합.

workspace는 선언을 보관하고 조회할 뿐 검증하지 않는다. dataset의 물리 스키마와 logical key가
유효한지는 ``data.datasets.validate``가 판정한 뒤 이 경계로 들어온다.
"""

from __future__ import annotations

import time as _time
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import yaml

from vqapr._internal import atomic, filelock
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data import datasets as datasets_module
from vqapr.data import scan
from vqapr.data.datasets import DatasetRegistration
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
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import ExecutionInputRegistration
from vqapr.extension.component import ComponentRef
from vqapr.flow.run import StrategyConfig
from vqapr.runtime.agendas import OperationAgenda, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace_codec import (
    _decode_cached,
    _detach_agenda,
    _detach_component,
    _detach_execution_input,
    _detach_monitoring_policy,
    _detach_registration,
    _detach_source,
    _detach_strategy_config,
    _detach_valuation_config,
    _encode,
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
VALUATION_REGISTER_STAGE = "workspace.valuation_config.register"
MONITORING_REGISTER_STAGE = "workspace.monitoring_policy.register"
REMOVE_STAGE = "workspace.remove"
_CONSTRUCTION_TOKEN = object()


class _State(NamedTuple):
    """Everything `workspace.yaml` holds, as one value.

    A tuple, so every `*state` unpacking and `state[4]` index in this module still works; named,
    so a merge can say `state.agendas` and `state._replace(agendas=...)` instead of threading
    eight positional mappings through every signature. What it encodes is unchanged.
    """

    datasets: dict[DatasetId, DatasetRegistration]
    sources: dict[SourceId, SourceSpec]
    execution_inputs: dict[ExecutionInputId, ExecutionInputRegistration]
    components: dict[ComponentId, ComponentRef]
    agendas: dict[str, OperationAgenda]
    strategy_configs: dict[str, StrategyConfig]
    valuation_configs: dict[str, ValuationConfig]
    monitoring_policies: dict[str, MonitoringPolicy]


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
        with self._exclusive():
            merged, changed = self._merge_dataset(self._read(), registration, source)
            self._commit(merged, changed)
            return changed

    def register_execution_input(self, registration: ExecutionInputRegistration) -> bool:
        """검증을 통과한 execution table + fill declaration을 원자적으로 보관한다."""
        if not isinstance(registration, ExecutionInputRegistration):
            raise TypeError("registration must be an ExecutionInputRegistration")
        with self._exclusive():
            merged, changed = self._merge_execution_input(self._read(), registration)
            self._commit(merged, changed)
            return changed

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
            merged, changed = self._merge_component(self._read(), ref, force=force)
            self._commit(merged, changed)
            return changed

    def register_agenda(self, agenda: OperationAgenda) -> bool:
        if not isinstance(agenda, OperationAgenda):
            raise TypeError("agenda must be an OperationAgenda")
        with self._exclusive():
            merged, changed = self._merge_agenda(self._read(), agenda)
            self._commit(merged, changed)
            return changed

    def register_strategy_config(self, config: StrategyConfig) -> bool:
        if not isinstance(config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        with self._exclusive():
            merged, changed = self._merge_strategy_config(self._read(), config)
            self._commit(merged, changed)
            return changed

    def register_valuation_config(self, config: ValuationConfig) -> bool:
        if not isinstance(config, ValuationConfig):
            raise TypeError("config must be a ValuationConfig")
        with self._exclusive():
            merged, changed = self._merge_valuation_config(self._read(), config)
            self._commit(merged, changed)
            return changed

    def register_monitoring_policy(self, policy: MonitoringPolicy) -> bool:
        if not isinstance(policy, MonitoringPolicy):
            raise TypeError("policy must be a MonitoringPolicy")
        with self._exclusive():
            merged, changed = self._merge_monitoring_policy(self._read(), policy)
            self._commit(merged, changed)
            return changed

    # ------------------------------------------------------------------------------------------
    # Merges: one registration folded into one state. Pure in the sense that matters -- they read
    # the state they are given and return a new one, and they neither lock nor write -- so the
    # same function serves a single `register_*` and a whole document applied as one transaction.
    # Every refusal a registration can raise lives here, once.
    # ------------------------------------------------------------------------------------------

    def _commit(self, state: _State, changed: bool) -> None:
        """Write the merged state if anything changed, and adopt it either way."""
        if changed:
            self._write(*state)
        self._replace_state(*state)

    def _merge_dataset(
        self, state: _State, registration: DatasetRegistration, source: SourceSpec
    ) -> tuple[_State, bool]:
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

        key = registration.dataset_id
        source_key = source.source_id
        existing_source = state.sources.get(source_key)
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

        existing = state.datasets.get(key)
        if existing is not None and existing.span is None:
            # A quarantined registration is being repaired. It differs from its replacement
            # only in what has been MEASURED about it -- the span it never carried, and the
            # field types nobody had derived when it was written -- so the conflict check
            # below would read that as a changed declaration and refuse the repair it
            # advertises. Compare on the declared half, and let the measurements be the things
            # that change.
            repaired = replace(
                existing,
                span=registration.span,
                field_types=registration.field_types,
                aggregated=registration.aggregated,
            )
            if repaired != registration:
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
                return state, False
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

        return (
            state._replace(
                datasets={**state.datasets, key: _detach_registration(registration)},
                sources={**state.sources, source_key: _detach_source(source)},
            ),
            True,
        )

    def _merge_execution_input(
        self, state: _State, registration: ExecutionInputRegistration
    ) -> tuple[_State, bool]:
        key = registration.execution_input_id
        source = registration.table.source
        source_key = source.source_id
        existing_source = state.sources.get(source_key)
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
        existing = state.execution_inputs.get(key)
        if existing is not None:
            if existing == registration and existing_source == source:
                return state, False
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
        return (
            state._replace(
                sources={**state.sources, source_key: _detach_source(source)},
                execution_inputs={
                    **state.execution_inputs,
                    key: _detach_execution_input(registration),
                },
            ),
            True,
        )

    def _merge_component(
        self, state: _State, ref: ComponentRef, *, force: bool = False
    ) -> tuple[_State, bool]:
        key = ref.component_id
        existing = state.components.get(key)
        if existing is not None:
            if existing == ref:
                return state, False
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
        return state._replace(components={**state.components, key: _detach_component(ref)}), True

    def _merge_agenda(self, state: _State, agenda: OperationAgenda) -> tuple[_State, bool]:
        return self._merge_declaration(
            state, "agendas", agenda.agenda_id, agenda, _detach_agenda, AGENDA_REGISTER_STAGE
        )

    def _merge_strategy_config(self, state: _State, config: StrategyConfig) -> tuple[_State, bool]:
        self._require_agenda(
            state.agendas, config.agenda_id, config.agenda_role, STRATEGY_REGISTER_STAGE
        )
        if state.components.get(config.component.component_id) != config.component:
            raise self._reference_error(
                STRATEGY_REGISTER_STAGE,
                "strategy component must be registered",
                fix="register the strategy's component before registering the StrategyConfig",
            )
        return self._merge_declaration(
            state,
            "strategy_configs",
            config.agenda_id,
            config,
            _detach_strategy_config,
            STRATEGY_REGISTER_STAGE,
        )

    def _merge_valuation_config(
        self, state: _State, config: ValuationConfig
    ) -> tuple[_State, bool]:
        self._require_agenda(
            state.agendas, config.agenda_id, config.agenda_role, VALUATION_REGISTER_STAGE
        )
        return self._merge_declaration(
            state,
            "valuation_configs",
            config.agenda_id,
            config,
            _detach_valuation_config,
            VALUATION_REGISTER_STAGE,
        )

    def _merge_monitoring_policy(
        self, state: _State, policy: MonitoringPolicy
    ) -> tuple[_State, bool]:
        self._require_agenda(
            state.agendas, policy.agenda_id, policy.agenda_role, MONITORING_REGISTER_STAGE
        )
        return self._merge_declaration(
            state,
            "monitoring_policies",
            policy.agenda_id,
            policy,
            _detach_monitoring_policy,
            MONITORING_REGISTER_STAGE,
        )

    @staticmethod
    def _merge_declaration(
        state: _State,
        section: str,
        key: str,
        value: object,
        detach: object,
        stage: str,
    ) -> tuple[_State, bool]:
        """One agenda-keyed declaration folded into its section: idempotent, conflict, or new."""
        declarations: Mapping[str, object] = getattr(state, section)
        existing = declarations.get(key)
        if existing is not None:
            if existing == value:
                return state, False
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
        updated = {**declarations, key: detach(value)}  # type: ignore[operator]
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
                    stage=REMOVE_STAGE,
                    code=f"{REMOVE_STAGE}.referenced",
                    requirement=f"a {kind} may be removed only when nothing live still names it",
                    observed=f"{identity!r} is referenced by " + ", ".join(blockers),
                    fix=f"remove {', '.join(blockers)} first, or keep {identity!r} registered",
                    explain=ExplainTopic.WORKSPACE_STATE,
                    retry="withdraw the referencing declarations, then retry",
                )
            # Looked up after the reference check, so an unsupported kind still gets the typed
            # refusal `_references_in` raises rather than a bare `KeyError` from this dict.
            position = {
                "component": 3,
                "agenda": 4,
                "strategy_config": 5,
                "valuation_config": 6,
                "monitoring_policy": 7,
            }[kind]
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

        Reads the workspace itself, for callers outside a write cycle. `remove` does NOT use this:
        it holds the lock and must evaluate against the state that lock already read, which is
        `_references_in` below (`docs/issues/043`).
        """
        return self._references_in(self._read(), kind, identity)

    def _references_in(
        self, state: tuple[object, ...], kind: str, identity: str
    ) -> tuple[str, ...]:
        """The same question asked of a state already in hand.

        Split out so the check and the write can see ONE snapshot. When this walked its own read,
        `remove` performed two reads with no lock across them and a competing registration could
        land between them -- and because `_decode` validates forward references, the result was a
        workspace `Workspace.open()` refuses rather than merely a stale answer.
        """
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

    def _read(self) -> _State:
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
            return _State(*_decode_cached(text))
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
        try:
            atomic.write_atomically(
                self.path,
                payload,
                attempts=WORKSPACE_SWAP_ATTEMPTS,
                backoff=WORKSPACE_SWAP_BACKOFF,
            )
        except OSError as error:
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
