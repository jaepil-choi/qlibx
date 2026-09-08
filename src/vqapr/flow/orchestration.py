"""Assemble and execute one run -- every strategy it names -- from a frozen authority to results.

**This is where `vqapr.public.run` lives**, and record `111` is why it moved: a facade that
executes runs is not a facade. Record `139` made it a run of several strategies: the run layer is
frozen once, and each strategy runs in its own `StrategyEventLoop` with its own `Account` and its
own record directory (design §4.1, §7-4). Sequentially by default; with `jobs > 1`, in that many
processes, each of which freezes the registered run again and runs one strategy of it.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

from vqapr.account.account import Account
from vqapr.account.history import retained_marks
from vqapr.account.snapshot import AccountState
from vqapr.authoring import Component
from vqapr.constraints.evaluation import (
    constraint_requirements as declared_constraint_requirements,
)
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.scan import ScanSession
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore, physical_digest
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.domain.values import normalize_memory
from vqapr.evidence.artifacts import SimulationFailure
from vqapr.exchange.execution_table import validate_execution_table
from vqapr.extension.component import ComponentRef
from vqapr.extension.loading import (
    as_loaded_fingerprint,
    load_constraint,
    load_data_model,
    load_exchange,
    load_strategy_model,
)
from vqapr.flow.datamodel import DataModelEventLoop, DataModelOutput, DataModelResult
from vqapr.flow.frozen import FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.judgments import require_judged
from vqapr.flow.preflight import preflight_run as _preflight_run
from vqapr.flow.record import (
    DATAMODEL_KIND,
    RunRecordWriter,
    freeze_datamodel_record,
    freeze_run_record,
    freeze_strategy_record,
    read_datamodel_record,
    read_strategy_record,
)
from vqapr.flow.roster import RegisteredRoster, registered_roster, roster_report
from vqapr.flow.run import RunDefinition
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.simulation import SimulationResult, StrategyEventLoop
from vqapr.workspace import Workspace


def preflight_run(
    workspace_or_root: Workspace | str | Path, definition: RunDefinition
) -> FrozenRun:
    """Judge a run definition against registered declarations, then freeze it, without running it.

    The judgments come first, and here rather than in the CLI: the CLI and the Python surface are
    two spellings of one process, and a run the CLI refused must not freeze from Python (record
    `168`; before it, `vqapr run` asked the judgments and this function did not, so the sample's
    own `execute` ran what `vqapr run` refused). A refused or blocked judgment raises the
    `VqaprError` `check` renders, in `check`'s codes.

    Takes the `Workspace` a caller already holds, or a root to open one from. A CLI command
    opens the document once and hands that one snapshot to every step (`docs/issues/070`):
    opening again here made the run freeze against a document that could differ from the one
    its judgments had just read.
    """
    if not isinstance(definition, RunDefinition):
        raise TypeError("definition must be a RunDefinition")
    workspace = (
        workspace_or_root
        if isinstance(workspace_or_root, Workspace)
        else Workspace.open(workspace_or_root)
    )
    require_judged(definition, workspace)
    return _preflight_run(workspace, definition)


class _FrozenCatalog:
    """Read-only data declarations captured by preflight, never a mutable workspace."""

    def __init__(self, frozen: FrozenRun) -> None:
        self._datasets = {str(dataset.dataset_id): dataset for dataset in frozen.datasets}
        self._sources = {str(source.source_id): source for source in frozen.sources}

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        return self._datasets[raw_dataset_id]

    def source(self, raw_source_id: str) -> SourceSpec:
        return self._sources[raw_source_id]


COMPLETED = "completed"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StrategyOutcome:
    """What one strategy of a run came to: its record, or the failure that ended it.

    Strings and plain dict trees only, on purpose: this is what a `--jobs` worker returns to the
    parent, and the `SimulationFailure` it stands in for cannot cross that boundary -- its
    keyword-only constructor and the owner objects it keeps on itself both refuse to pickle
    (`docs/issues/073`). `failure` is the exception's `as_dict()`, the same payload a
    single-process run renders, so the two paths report one shape.
    """

    component_id: str
    status: str
    record: Mapping[str, object] | None = None
    failure: Mapping[str, object] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in (COMPLETED, FAILED):
            raise ValueError(f"status must be {COMPLETED!r} or {FAILED!r}; got {self.status!r}")
        if (self.status == FAILED) != (self.failure is not None):
            raise ValueError("a failed outcome carries its failure, and only a failed one does")


@dataclass(frozen=True, slots=True)
class RunResult:
    """What one call to `run` produced: an outcome per strategy it ran, and their records.

    `results` holds the in-process `SimulationResult` of every strategy this process ran to the
    end. `records` holds each strategy's `strategy.json` as written, for every strategy run under
    a store -- including those run by worker processes, whose in-process result never crosses the
    process boundary and is read back from the record instead. `outcomes` has an entry for EVERY
    strategy the run was asked to run, completed or failed (`docs/issues/073`): a refusal of one
    strategy's decision is that strategy's outcome and does not stop the others. `errors` keeps
    the `SimulationFailure` itself for a strategy that failed in this process.
    """

    run_id: str
    results: Mapping[str, SimulationResult | DataModelResult]
    records: Mapping[str, Mapping[str, object]]
    roster: RegisteredRoster | None = None
    """The instrument roster this run read at its start, or `None` when none was registered --
    or when the run was a datamodel run, which reads no roster. Carried so the caller's report
    is built from what the run used rather than from a second read (`docs/issues/070`)."""
    outcomes: Mapping[str, StrategyOutcome] = field(default_factory=dict)
    errors: Mapping[str, SimulationFailure] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Every strategy the run was asked to run completed."""
        return all(outcome.status == COMPLETED for outcome in self.outcomes.values())

    @property
    def failed(self) -> tuple[str, ...]:
        """The ids of the strategies whose flow ended in a `SimulationFailure`, in run order."""
        return tuple(
            component_id
            for component_id, outcome in self.outcomes.items()
            if outcome.status == FAILED
        )

    def result(self, component_id: str | None = None) -> SimulationResult | DataModelResult:
        """The one model's result, or the only one when the run ran exactly one.

        A strategy that failed in this process raises its own `SimulationFailure` here, so a
        Python caller that asked for one strategy's result meets the real exception rather than
        a count. One that failed in a worker has only its outcome, and the error says so.
        """
        if component_id is None:
            if len(self.results) == 1:
                return next(iter(self.results.values()))
            if not self.results and len(self.outcomes) == 1:
                (component_id,) = self.outcomes
            else:
                raise ValueError(
                    f"run {self.run_id!r} produced {len(self.results)} in-process results; "
                    "name the strategy"
                )
        if component_id in self.results:
            return self.results[component_id]
        if component_id in self.errors:
            raise self.errors[component_id]
        outcome = self.outcomes.get(component_id)
        if outcome is not None and outcome.status == FAILED:
            raise ValueError(
                f"strategy {component_id!r} of run {self.run_id!r} failed in a worker process: "
                f"{outcome.error}; read `outcomes[{component_id!r}].failure`"
            )
        return self.results[component_id]


def run(
    project_root: str | Path,
    frozen_run: FrozenRun,
    *,
    store_root: str | Path | None = None,
    strategies: Sequence[str] | None = None,
    jobs: int = 1,
    replace_record: bool = False,
    record_account_positions: bool = True,
    workspace: Workspace | None = None,
) -> RunResult:
    """Execute a frozen run: each of its strategies (or those named), each in its own flow.

    `workspace` is the document the caller already opened, when it did: the roster is read
    through it rather than by opening the document again (`docs/issues/070`), so a command
    judges, freezes and runs against one snapshot. Omitted, the roster is read from
    `project_root` -- one open, once per run, not once per strategy.

    When `store_root` is given the run writes `run.json` first and each strategy freezes its own
    record beneath `strategies/<id>@<fp8>/`, which is what makes the results readable by any later
    process -- `show strategy` from a cold one, and the other strategies' processes. Omitted, the
    results stay in memory: an in-process caller that already holds them should not be made to
    write them to disk to get them.

    `jobs > 1` runs the strategies in that many processes. Each worker opens the workspace,
    freezes the REGISTERED run under this id again and runs one strategy, so it needs a store (the
    record is how a result comes back) and a registered run (a frozen run built in-process does
    not cross a process boundary). Each worker builds its own panels (design §7-2, owner decision
    2026-09-02).
    """
    if not isinstance(frozen_run, FrozenRun):
        raise TypeError("frozen_run must be a FrozenRun returned by preflight_run")
    if not isinstance(jobs, int) or jobs < 1:
        raise ValueError("jobs must be a positive integer")
    root_path = Path(project_root)
    frozen = frozen_run
    if frozen.datamodels:
        return _run_datamodels(
            root_path,
            frozen,
            store_root=store_root,
            selected=strategies,
            jobs=jobs,
            replace_record=replace_record,
        )
    if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None:
        raise ValueError("public run requires frozen initial account authority")
    if frozen.exchange is None:
        raise ValueError("public run requires a frozen Exchange authority")
    if frozen.execution is None:
        raise ValueError("public run requires a frozen execution dataset")
    validate_execution_table(frozen.execution).raise_if_failed()

    # ONE read of the roster for the whole run, through the caller's workspace when it has one.
    # It was read once per strategy, and the CLI read it a further time for its envelope
    # (`docs/issues/070`); the record is written from this read and so is the report.
    roster = registered_roster(workspace if workspace is not None else root_path)
    selected = tuple(frozen.strategy(name) for name in (strategies or ())) or frozen.strategies
    store = None if store_root is None else Path(store_root)
    if store is not None:
        freeze_run_record(store, frozen, source_digests=_source_digests(frozen))

    results: dict[str, SimulationResult] = {}
    records: dict[str, Mapping[str, object]] = {}
    outcomes: dict[str, StrategyOutcome] = {}
    errors: dict[str, SimulationFailure] = {}
    if jobs > 1 and len(selected) > 1:
        # Every worker's outcome is collected, failed or not. A `SimulationFailure` comes
        # back INSIDE the outcome (`run_registered_strategy`); only an exception about the
        # store or the package itself still escapes `result()` here, as it did before.
        outcomes = _in_workers(
            selected,
            run_registered_strategy,
            (replace_record, record_account_positions),
            jobs=jobs,
            store=store,
            root_path=root_path,
            run_id=frozen.run_id,
        )
        records = {
            component_id: outcome.record
            for component_id, outcome in outcomes.items()
            if outcome.record is not None
        }
        return RunResult(
            frozen.run_id,
            MappingProxyType(results),
            MappingProxyType(records),
            roster=roster,
            outcomes=MappingProxyType(outcomes),
        )

    for layer in selected:
        try:
            result, record = _run_strategy(
                root_path,
                frozen,
                layer,
                store=store,
                replace_record=replace_record,
                record_account_positions=record_account_positions,
                roster=roster,
            )
        except SimulationFailure as failed:
            # One strategy's refusal is that strategy's outcome (`docs/issues/073`, `071`). It
            # has its own flow and its own account (design section 7-4); the strategies after it
            # in the run have nothing to learn from its decision being declined, and stopping
            # them left a comparison run with three records and no word about the other five.
            errors[layer.component_id] = failed
            outcomes[layer.component_id] = _failed_outcome(layer.component_id, failed)
            continue
        results[layer.component_id] = result
        if record is not None:
            records[layer.component_id] = record
        outcomes[layer.component_id] = StrategyOutcome(layer.component_id, COMPLETED, record=record)
    return RunResult(
        frozen.run_id,
        MappingProxyType(results),
        MappingProxyType(records),
        roster=roster,
        outcomes=MappingProxyType(outcomes),
        errors=MappingProxyType(errors),
    )


def _failed_outcome(component_id: str, failed: SimulationFailure) -> StrategyOutcome:
    """The picklable stand-in for a strategy's `SimulationFailure`."""
    return StrategyOutcome(
        component_id, FAILED, failure=failed.as_dict(), error=f"{type(failed).__name__}: {failed}"
    )


def _run_datamodels(
    root_path: Path,
    frozen: FrozenRun,
    *,
    store_root: str | Path | None,
    selected: Sequence[str] | None,
    jobs: int,
    replace_record: bool,
) -> RunResult:
    """Execute a datamodel run: each of its datamodels (or those named), each in its own flow.

    The same shape as the strategy branch of `run` (record `148`): `run.json` first, one record
    directory per member, workers under `--jobs` that each re-freeze the registered run. What a
    datamodel produces beyond its record is a registered dataset, which is why every one of them
    needs a store: the record is what says which dataset a run wrote.
    """
    layers = tuple(frozen.datamodel(name) for name in (selected or ())) or frozen.datamodels
    store = None if store_root is None else Path(store_root)
    if store is not None:
        freeze_run_record(store, frozen, source_digests=_source_digests(frozen))

    results: dict[str, SimulationResult | DataModelResult] = {}
    records: dict[str, Mapping[str, object]] = {}
    if jobs > 1 and len(layers) > 1:
        # A datamodel's refusal is a `VqaprError`, and unlike a `SimulationFailure` it makes the
        # trip back from the worker as itself (`VqaprError.__reduce__`), so `result()` raises
        # here exactly what the sequential loop below raises.
        records = _in_workers(
            layers,
            run_registered_datamodel,
            (replace_record,),
            jobs=jobs,
            store=store,
            root_path=root_path,
            run_id=frozen.run_id,
        )
        return RunResult(frozen.run_id, MappingProxyType(results), MappingProxyType(records))

    for layer in layers:
        result, record = _run_datamodel(
            root_path, frozen, layer, store=store, replace_record=replace_record
        )
        results[layer.component_id] = result
        if record is not None:
            records[layer.component_id] = record
    return RunResult(frozen.run_id, MappingProxyType(results), MappingProxyType(records))


def _in_workers[Returned](
    layers: Sequence[FrozenStrategy] | Sequence[FrozenDataModel],
    worker: Callable[..., Returned],
    arguments: tuple[object, ...],
    *,
    jobs: int,
    store: Path | None,
    root_path: Path,
    run_id: str,
) -> dict[str, Returned]:
    """One member per worker, in `jobs` spawned processes; what each returns, by component id.

    The one pool behind `--jobs` for both kinds of run. The strategy branch and the datamodel
    branch each carried their own copy of this, and the `docs/issues/073` fix -- a worker's
    failure has to be something `concurrent.futures` can pickle -- landed in only one of them.
    `worker` is a module-level function taking `(project_root, run_id, component_id, store_root,
    *arguments)` as strings and bools, because it crosses a `spawn` boundary.
    """
    if store is None:
        raise ValueError(
            "jobs > 1 needs a store_root: a worker's result comes back through the record store"
        )
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=min(jobs, len(layers)), mp_context=context) as pool:
        futures = {
            layer.component_id: pool.submit(
                worker, str(root_path), run_id, layer.component_id, str(store), *arguments
            )
            for layer in layers
        }
        return {component_id: future.result() for component_id, future in futures.items()}


def run_registered_datamodel(
    project_root: str,
    run_id: str,
    component_id: str,
    store_root: str,
    replace_record: bool,
) -> Mapping[str, object]:
    """Run one datamodel of a REGISTERED run, in this process; the worker under `--jobs`.

    A refusal is raised, not returned: a datamodel's `VqaprError` pickles (`__reduce__`), so the
    parent's `future.result()` re-raises it as itself, the same exception the sequential loop
    raises. The strategy worker cannot do this because its `SimulationFailure` carries the owner
    objects that were refused; that is why it returns a `StrategyOutcome` instead.
    """
    workspace = Workspace.open(project_root)
    frozen = _preflight_run(workspace, workspace.run_definition(run_id))
    _, record = _run_datamodel(
        Path(project_root),
        frozen,
        frozen.datamodel(component_id),
        store=Path(store_root),
        replace_record=replace_record,
    )
    assert record is not None
    return record


def _run_datamodel(
    root_path: Path,
    frozen: FrozenRun,
    layer: FrozenDataModel,
    *,
    store: Path | None,
    replace_record: bool,
) -> tuple[DataModelResult, Mapping[str, object] | None]:
    """Execute exactly one datamodel of a frozen run: its sessions, its dataset, its record.

    Order at the end, deliberately: the dataset registers first and the record is written last.
    The registration is the product; the record existing is what marks the member complete, and
    a record that said "wrote dataset X" beside a registration that never happened would be the
    invisibility `059` measured.
    """
    model = load_data_model(layer.component, project_root=root_path)
    as_loaded = {layer.component_id: as_loaded_fingerprint(layer.component, project_root=root_path)}
    if tuple(model.requirements()) != layer.requirements:
        raise ValueError("loaded DataModel requirements drifted from FrozenRun")
    model.memory = normalize_memory(layer.initial_model_memory)
    catalog = _FrozenCatalog(frozen)
    session = ScanSession()
    writer = None
    try:
        observation_store = DuckDbObservationStore(catalog, session=session)
        if store is not None:
            opened_writer = RunRecordWriter(
                store, frozen.run_id, layer.record_ref, member_kind=DATAMODEL_KIND
            )
            opened_writer.open(replace=replace_record)
            writer = opened_writer
        output = DataModelOutput(root_path, layer, run_id=frozen.run_id)
        flow = DataModelEventLoop(
            frozen,
            layer,
            model,
            window_for_occurrence=lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=frozen.instruments,
                store=observation_store,
                allowed_requirements=layer.requirements,
                consumer_id=layer.component_id,
            ),
            output=output,
            on_progress=writer.heartbeat if writer is not None else None,
        )
        result = flow.run()
        registration = output.register(Workspace.open(root_path))
        result = DataModelResult(
            occurrences=result.occurrences,
            rows=result.rows,
            output_path=result.output_path,
            registration=registration,
        )
        if writer is not None:
            freeze_datamodel_record(writer, result, frozen, layer, as_loaded)
    except BaseException:
        if writer is not None:
            writer.release()
        raise
    finally:
        session.close()
    record = (
        None
        if writer is None
        else read_datamodel_record(writer.root, frozen.run_id, layer.record_ref)
    )
    return result, record


def run_registered_strategy(
    project_root: str,
    run_id: str,
    component_id: str,
    store_root: str,
    replace_record: bool,
    record_account_positions: bool,
) -> StrategyOutcome:
    """One strategy of one registered run, in this process, returning its outcome.

    The worker behind `jobs > 1`. Module-level and taking only strings and bools, because it
    crosses a `spawn` boundary; it freezes the registered run again rather than receiving a
    frozen one, since a frozen run is built from workspace objects that are not meant to travel.

    A `SimulationFailure` is returned inside the outcome rather than raised, because it cannot
    make the trip back: `concurrent.futures` pickles a worker's exception to hand it to the
    parent, and this one carries the owner object that was refused -- a `Rebalance` whose weights
    are a `MappingProxyType` -- so the parent used to receive `TypeError: cannot pickle
    'mappingproxy' object`, render `stage: unhandled` with `failures: []`, and say nothing about
    the strategies that had finished (`docs/issues/073`).
    """
    workspace = Workspace.open(project_root)
    frozen = _preflight_run(workspace, workspace.run_definition(run_id))
    layer = frozen.strategy(component_id)
    try:
        _, record = _run_strategy(
            Path(project_root),
            frozen,
            layer,
            store=Path(store_root),
            replace_record=replace_record,
            record_account_positions=record_account_positions,
            roster=registered_roster(workspace),
        )
    except SimulationFailure as failed:
        return _failed_outcome(component_id, failed)
    assert record is not None
    return StrategyOutcome(component_id, COMPLETED, record=record)


def _source_digests(frozen: FrozenRun) -> dict[str, str]:
    """The physical digest of every source the run reads, keyed by source id (A7)."""
    return {str(source.source_id): physical_digest(source.path) for source in frozen.sources}


def _run_strategy(
    root_path: Path,
    frozen: FrozenRun,
    layer: FrozenStrategy,
    *,
    store: Path | None,
    replace_record: bool,
    record_account_positions: bool,
    roster: RegisteredRoster | None,
) -> tuple[SimulationResult, Mapping[str, object] | None]:
    """Execute exactly one strategy of a frozen run, with its own Account and its own record.

    `roster` is the one read `run` made at its start (`docs/issues/070`); the record is written
    from it rather than from a read of this strategy's own.
    """
    strategy = load_strategy_model(layer.config.component, project_root=root_path)
    exchange = load_exchange(frozen.exchange, project_root=root_path)
    constraints = tuple(
        load_constraint(ref, project_root=root_path) for ref in layer.constraints.constraints
    )
    # What was ACTUALLY loaded, computed beside the loads that read it.
    #
    # Since the drift refusal went (issue 009), an edited component runs instead of being
    # refused, so the registered fingerprints -- fixed at preflight -- can describe bytes this
    # run never executed. Recording only those would leave a receipt that looks authoritative
    # and is stale, which is worse than the gate it replaced.
    as_loaded = _as_loaded_fingerprints(frozen, layer, root_path)
    # The record is written from the ONE roster read `run` made, never from a second one.
    # `roster` carries the digest and the table list beside the registry, so a `vqapr register`
    # landing during the run cannot make the record state a digest the fills were never classified
    # by (`docs/issues/050`).
    registry = roster.registry if roster is not None else None
    catalog = _FrozenCatalog(frozen)
    # One physical handle for the whole strategy. duckdb caches parquet metadata for a
    # connection's lifetime, and closing per query threw that away on every observation.
    session = ScanSession()
    writer = None
    try:
        observation_store = DuckDbObservationStore(catalog, session=session)
        strategy_requirements = strategy.requirements()
        if strategy_requirements != layer.requirements:
            raise ValueError("loaded Strategy requirements drifted from FrozenRun")
        constraint_requirements = declared_constraint_requirements(constraints)
        if constraint_requirements != layer.constraint_requirements:
            raise ValueError("loaded Constraint requirements drifted from FrozenRun")
        root = AccountState(frozen.initial_account_snapshot)
        strategy.memory = normalize_memory(layer.initial_model_memory)
        strategy.load_payload(BytesIO(layer.initial_payload))
        if store is not None:
            opened_writer = RunRecordWriter(store, frozen.run_id, layer.record_ref)
            opened_writer.open(replace=replace_record)
            writer = opened_writer
        state = RunStateRepository(
            initial_account=root,
            initial_model_memory=layer.initial_model_memory,
            initial_payload=layer.initial_payload,
            # What each constraint holds as loaded -- its constructor's doing, from the config
            # the fingerprint already folds -- is the memory the run commits from (record `181`).
            initial_component_memory={
                **{constraint.constraint_id: constraint.memory for constraint in constraints},
                # The venue too, when it is a Component (record `184`); a loader double that
                # only offers `execute` carries no memory to commit.
                **(
                    {exchange.exchange_id: exchange.memory}
                    if isinstance(exchange, Component)
                    else {}
                ),
            },
            # Accepted rows enter the writer buffer; normal and exceptional exits flush it.
            # A hard kill preserves only spilled rows. Without a store, roots retain rows.
            row_sink=None if writer is None else writer.append,
        )
        if state.root.current_model_state_ref != layer.initial_model_state_ref:
            raise RuntimeError("initial Model state does not match frozen run authority")
        initial_ref = state.root.current_model_state_ref
        if initial_ref is None or state.load_payload(initial_ref) != layer.initial_payload:
            raise RuntimeError("initial Strategy payload does not match frozen run authority")
        flow = StrategyEventLoop(
            frozen,
            strategy,
            state,
            layer=layer,
            strategy_window_for_occurrence=lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=frozen.instruments,
                store=observation_store,
                allowed_requirements=layer.requirements,
                consumer_id=layer.component_id,
            ),
            constraint_window_for_occurrence=lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=frozen.instruments,
                store=observation_store,
                # No consumer: this window serves every loaded constraint, and which one is reading
                # is known only inside the loop that calls them.
                allowed_requirements=layer.constraint_requirements,
            ),
            # Monitoring reads as of the fill instant it judges (record `148`).
            constraint_window_at=lambda instant: ModelWindow(
                evaluation_time=instant,
                instruments=frozen.instruments,
                store=observation_store,
                allowed_requirements=layer.constraint_requirements,
            ),
            # Each strategy has its own Account (design §7-4): the run shares the initial
            # DECLARATION, not the book. It retains the marks this strategy declared it would
            # read; declaring nothing keeps one.
            account=Account(
                mode=frozen.initial_account_mode,
                retained_marks=retained_marks(strategy.account_history()),
            ),
            exchange=exchange,
            constraints=constraints,
            scan_session=session,
            # The strategy's liveness signal. Without it the record's lock is stamped once at `open`
            # and never touched again, so any run longer than `LOCK_STALE_AFTER` reads as dead WHILE
            # STILL EXECUTING, and a peer takes its id and deletes its tables.
            on_progress=writer.heartbeat if writer is not None else None,
            registry=registry,
            record_account_positions=record_account_positions,
        )
        result = flow.run()
        if writer is not None:
            # `roster_report` is evaluated HERE, after the run returned and outside the argument
            # list, and its failure is absorbed: the report is decoration on a record; the record
            # is the run. Losing the decoration is the cheaper failure, and it is recorded as a
            # stale marker rather than as `null`, which this record's own contract defines as
            # "no roster was ever read".
            freeze_strategy_record(
                writer, result, frozen, layer, as_loaded, _roster_report_or_stale(roster)
            )
    except BaseException:
        # A strategy that died still holds its record's lock. Releasing here turns a crash into
        # an ordinary retry instead of stranding the directory until the lock goes stale.
        if writer is not None:
            writer.release()
        raise
    finally:
        session.close()
    record = (
        None
        if writer is None
        else read_strategy_record(writer.root, frozen.run_id, layer.record_ref)
    )
    return result, record


def _roster_report_or_stale(roster: RegisteredRoster | None) -> object | None:
    """The roster block for the record, or a STALE MARKER when it cannot be built at record time.

    Narrow on purpose: it catches `VqaprError` only, so a bug in report construction still fails
    loudly. **Not `None`, and that distinction is the whole point.** `roster: null` in a record
    means *"the run never knew the categories"*; any run that reaches this line did read its
    roster, so the marker says what actually happened: the run knew its categories, and the record
    could not re-read them at the end (`docs/issues/042`, `050`).
    """
    try:
        return roster_report(roster)
    except VqaprError as unreadable:
        return {
            "known": True,
            "stale": True,
            "note": (
                "the run read its instrument roster at start, and the roster pointer could not be "
                "re-read when this record was written; the categories the run used are not "
                f"recoverable from this record ({unreadable})"
            ),
        }


def _as_loaded_fingerprints(
    frozen: FrozenRun, layer: FrozenStrategy, root_path: Path | None
) -> dict[str, str]:
    """The fingerprint of every component this strategy actually loaded, by component id.

    Per component rather than folded (design §4.2): the strategy's own fingerprint is readable on
    its own, so a change to one constraint does not disguise itself as a change to the strategy.
    Only refs that carry a real source are included -- a run assembled in-process may hold a stub
    in place of a registered component, and such a thing has no bytes on disk to fingerprint.
    """
    candidates = [layer.config.component, frozen.exchange, *layer.constraints.constraints]
    return {
        str(ref.component_id): as_loaded_fingerprint(ref, project_root=root_path)
        for ref in candidates
        if isinstance(ref, ComponentRef)
    }
