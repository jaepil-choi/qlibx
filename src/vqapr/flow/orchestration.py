"""Assemble and execute one run -- the one model it names -- from a frozen authority to results.

**This is where `vqapr.public.run` lives**, and record `111` is why it moved: a facade that
executes runs is not a facade. The run layer is frozen, and its model runs in its own
`strategy_loop` with its own `Account` and its own record directory (design §4.1, §7-4).

**One model per run** (2026-09-09, `docs/design/two-clocks-and-the-wiring-table.md` §2.3).
Record `139` had made it several so that a comparison would share one frozen layer; determinism
already gives that, so the sharing bought an optimisation and cost the ability to compare runs
made on different days. Parallelism moved with it: it used to be members inside a run and is now
independent runs, which is both more general and the unit the graph will schedule.
"""

from __future__ import annotations

import multiprocessing
import os
import secrets
import shutil
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from itertools import batched
from pathlib import Path
from types import MappingProxyType

from vqapr.component.base import Component
from vqapr.component.loading import (
    as_loaded_fingerprint,
    load_compliance,
    load_data_model,
    load_exchange,
    load_strategy_model,
)
from vqapr.component.reference import ComponentRef
from vqapr.component.strategy.history import retained_marks
from vqapr.data import cube as cube_module
from vqapr.data.dataset import DatasetRegistration, Grain
from vqapr.data.requirement import DataRequirement
from vqapr.data.scan import ScanSession
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore, physical_digest
from vqapr.data.window import ModelWindow
from vqapr.domain.account import Account, AccountState
from vqapr.domain.errors import Failure, FailureSource, InputError, Stage, Status, VqaprError
from vqapr.domain.memory import normalize_memory
from vqapr.flow.declaration.frozen import FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.declaration.verify import RunResources, verify_run
from vqapr.flow.engine.artifacts import SimulationFailure
from vqapr.flow.engine.run_state import RunStateRepository
from vqapr.flow.freeze import (
    freeze_datamodel_record,
    freeze_run_record,
    freeze_strategy_record,
)
from vqapr.flow.roster import (
    RegisteredRoster,
    absent_workspace,
    registered_roster,
    roster_report,
)
from vqapr.flow.run.compliance import compliance_requirements as declared_compliance_requirements
from vqapr.flow.run.loop import (
    DataModelResult,
    SimulationResult,
    datamodel_loop,
    strategy_loop,
)
from vqapr.flow.run.output import RunOutput
from vqapr.record import (
    DATAMODEL_KIND,
    STRATEGY_KIND,
    RunRecordWriter,
    read_datamodel_record,
    read_strategy_record,
    read_table,
)
from vqapr.record.schema import WEIGHT_TABLE
from vqapr.workspace.registry import WORKSPACE_DIRECTORY, Workspace
from vqapr.workspace.run_definition import RunDefinition


def preflight_run(
    workspace_or_root: Workspace | str | Path, definition: RunDefinition
) -> FrozenRun:
    """Judge a run definition against registered declarations, then freeze it, without running it.

    One door (`flow/declaration/verify.py`, record `240`): the CLI, the Python surface and the
    `--jobs` worker are spellings of one process, and a run one refused must not freeze from
    another (record `168`; before it, `vqapr run` asked the judgments and this function did not,
    so the sample's own `execute` ran what `vqapr run` refused). A refused or blocked judgment
    raises the `VqaprError` `check` renders, in `check`'s codes; a run the judgments passed is
    refused by the freeze's own error.

    Takes the `Workspace` a caller already holds, or a root to open one from. A CLI command
    opens the document once and hands that one snapshot to every step (`docs/issues/archive/070`):
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
    return verify_run(workspace, definition).require_frozen()


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
    (`docs/issues/archive/073`). `failure` is the exception's `as_dict()`, the same payload a
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

    `results` holds the in-process `SimulationResult` of every strategy this process ran to the end.
    `records` holds each strategy's `strategy.json` as written, for every strategy run under a store
    -- including those run by worker processes, whose in-process result never crosses the process
    boundary and is read back from the record instead. `outcomes` has an entry for EVERY strategy
    the run was asked to run, completed or failed (`docs/issues/archive/073`): a refusal of one
    strategy's decision is that strategy's outcome and does not stop the others. `errors` keeps the
    `SimulationFailure` itself for a strategy that failed in this process.
    """

    run_id: str
    results: Mapping[str, SimulationResult | DataModelResult]
    records: Mapping[str, Mapping[str, object]]
    roster: RegisteredRoster | None = None
    """The instrument roster this run read at its start, or `None` when none was registered --
    or when the run was a datamodel run, which reads no roster. Carried so the caller's report
    is built from what the run used rather than from a second read (`docs/issues/archive/070`)."""
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
    replace_record: bool = False,
    record_account_positions: bool = True,
    workspace: Workspace | None = None,
    resources: RunResources | None = None,
) -> RunResult:
    """Execute a frozen run: each of its strategies (or those named), each in its own flow.

    `resources` is what the verification loaded and read for this frozen run
    (`verify.RunVerdict.resources`, record `242`): the strategy, the venue, the rules and the
    execution horizon. Handed in, the run imports and scans none of them again; omitted (a
    caller holding only a `FrozenRun`), it loads them itself as it always did.

    `workspace` is the document the caller already opened, when it did: the roster is read
    through it rather than by opening the document again (`docs/issues/archive/070`), so a command
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
    root_path = Path(project_root)
    frozen = frozen_run
    if resources is not None and resources.run_identity != frozen.identity:
        raise ValueError("resources were loaded for another frozen run")
    _own_output_or_refuse(
        workspace if workspace is not None else root_path, frozen, replace_record=replace_record
    )
    if frozen.datamodel is not None:
        return _run_datamodels(
            root_path,
            frozen,
            store_root=store_root,
            replace_record=replace_record,
            resources=resources,
        )
    if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None:
        raise ValueError("public run requires frozen initial account authority")
    if frozen.exchange is None:
        raise ValueError("public run requires a frozen Exchange authority")
    if frozen.execution is None:
        raise ValueError("public run requires a frozen execution dataset")

    # ONE read of the roster, through the caller's workspace when it has one
    # (`docs/issues/archive/070`); the record is written from this read and so is the report.
    roster = registered_roster(workspace if workspace is not None else root_path)
    layer = frozen.strategy
    if layer is None:  # pragma: no cover -- `FrozenRun` refuses this
        raise ValueError("a strategy run froze no strategy")
    store = None if store_root is None else Path(store_root)

    results: dict[str, SimulationResult] = {}
    records: dict[str, Mapping[str, object]] = {}
    outcomes: dict[str, StrategyOutcome] = {}
    errors: dict[str, SimulationFailure] = {}
    if True:
        try:
            result, record = _run_strategy(
                root_path,
                frozen,
                layer,
                store=store,
                replace_record=replace_record,
                record_account_positions=record_account_positions,
                roster=roster,
                workspace=workspace,
                resources=resources,
            )
        except SimulationFailure as failed:
            # The run's refusal is its outcome, reported rather than raised
            # (`docs/issues/archive/073`, `071`): a caller running several runs learns which one
            # declined without losing the others, and that is now the caller's loop rather than
            # this function's.
            errors[layer.component_id] = failed
            outcomes[layer.component_id] = _failed_outcome(layer.component_id, failed)
        else:
            results[layer.component_id] = result
            if record is not None:
                records[layer.component_id] = record
            outcomes[layer.component_id] = StrategyOutcome(
                layer.component_id, COMPLETED, record=record
            )
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
    replace_record: bool,
    resources: RunResources | None = None,
) -> RunResult:
    """Execute a datamodel run: its one datamodel, in its own flow.

    The same shape as the strategy branch of `run` (record `148`): `run.json` first, then the
    record directory. What a datamodel produces beyond its record is a registered dataset, which
    is why it needs a store: the record is what says which dataset a run wrote.
    """
    one = frozen.datamodel
    if one is None:  # pragma: no cover -- `FrozenRun` refuses this
        raise ValueError("a datamodel run froze no datamodel")
    layers = (one,)
    store = None if store_root is None else Path(store_root)

    results: dict[str, SimulationResult | DataModelResult] = {}
    records: dict[str, Mapping[str, object]] = {}
    for layer in layers:
        result, record = _run_datamodel(
            root_path,
            frozen,
            layer,
            store=store,
            replace_record=replace_record,
            resources=resources,
        )
        results[layer.component_id] = result
        if record is not None:
            records[layer.component_id] = record
    return RunResult(frozen.run_id, MappingProxyType(results), MappingProxyType(records))


def in_workers[Returned](
    run_ids: Sequence[str],
    worker: Callable[..., Returned],
    arguments: tuple[object, ...],
    *,
    jobs: int,
    store: Path | None,
    root_path: Path,
) -> dict[str, Returned | Exception]:
    """One RUN per worker, in `jobs` spawned processes; what each returned OR raised, by run id.

    The one pool behind `--jobs`. It spread the members of a single run until 2026-09-09; a run
    holds one model now, so the unit is the run (`docs/design/two-clocks-and-the-wiring-table.md`
    §2.3). That is the more general unit as well -- two runs need share nothing, where two members
    shared a frozen layer -- and it is what a graph scheduler will hand this function later.

    `worker` is a module-level function taking `(project_root, run_id, store_root, *arguments)` as
    strings and bools, because it crosses a `spawn` boundary. The
    `docs/issues/archive/073` rule still holds: a worker's failure has to be something
    `concurrent.futures` can pickle, which is why the strategy worker returns its outcome.

    **A worker's exception is that run's entry, not the batch's end.** Until
    `docs/issues/report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs.md` this
    re-raised the first worker's exception out of the comprehension, which dropped every other
    worker's result on the floor -- and was the reason the CLI kept datamodel runs OUT of the pool
    (their worker raises its refusal, which is right: a `VqaprError` pickles and is the same
    exception the sequential path raises). Now each run comes back as what its worker returned
    or what it raised, and the caller renders each. Only a broken pool still propagates: it is
    not any one run's news.
    """
    if store is None:
        raise ValueError(
            "jobs > 1 needs a store_root: a worker's result comes back through the record store"
        )
    context = multiprocessing.get_context("spawn")
    with (
        one_blas_thread_for_workers(),
        ProcessPoolExecutor(max_workers=min(jobs, len(run_ids)), mp_context=context) as pool,
    ):
        futures = {
            run_id: pool.submit(worker, str(root_path), run_id, str(store), *arguments)
            for run_id in run_ids
        }
        outcomes: dict[str, Returned | Exception] = {}
        for run_id, future in futures.items():
            try:
                outcomes[run_id] = future.result()
            except BrokenExecutor:
                raise
            except Exception as raised:
                outcomes[run_id] = raised
        return outcomes


BLAS_THREAD_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
"""The thread counts numpy's BLAS builds read when they load (record `257`)."""


@contextmanager
def one_blas_thread_for_workers() -> Iterator[None]:
    """Start a batch's workers with one BLAS thread each, unless the user set a count.

    Record `257` (owner decision 2026-09-11). numpy's OpenBLAS commits a working buffer for every
    core it may use when it loads -- about 0.8 GB of private memory on the 32-core machine the
    2026-09-11 memory report was measured on, 27 MB of it ever touched -- and every `--jobs`
    worker is its own process loading its own. N workers already use the cores; N x 32 BLAS
    threads only fight over them. A spawned worker copies the environment when it starts, so the
    variables are set around the pool and put back after it: the parent -- a Python caller's own
    process -- is left as it was, and a count the user set is theirs and is not touched. A single
    run is not a batch and keeps whatever its process has.
    """
    set_here = [name for name in BLAS_THREAD_VARIABLES if name not in os.environ]
    for name in set_here:
        os.environ[name] = "1"
    try:
        yield
    finally:
        for name in set_here:
            os.environ.pop(name, None)


RUN_BATCH_DEPENDENT = "run.batch_dependent"
RUN_BATCH_WRITES_COLLIDE = "run.batch_writes_collide"


def batch_reads(workspace: Workspace, run_ids: Sequence[str]) -> dict[str, dict[str, set[str]]]:
    """What each run of a batch reads, by run id: asked of each run's components once.

    Both doors of a `--jobs` batch need it -- the independence judgment and the bake -- and
    each used to load every component again to ask (record `238`); the CLI asks here once and
    hands the answer to both.
    """
    return {run_id: _reads(workspace, workspace.run_definition(run_id)) for run_id in run_ids}


def require_independent_batch(
    workspace: Workspace,
    run_ids: Sequence[str],
    reads: Mapping[str, Mapping[str, set[str]]] | None = None,
) -> None:
    """Refuse a batch that one pool cannot hold: a run reading what another in it writes.

    The pool starts every run at once and promises nothing about order, so a strategy whose
    dataset a datamodel in the same batch writes would read the dataset as it stood before --
    stale under `--force`, absent otherwise -- or race the writer. Owner decision (2026-09-10):
    such a batch is refused whole before anything is spawned, rather than ordered; the graph's
    order is `vqapr run <producer>` first, then the batch without it, which is what the fix says.
    Two runs naming one `writes` are the other thing a pool cannot hold, and are refused by the
    same door with their own code.

    What a run reads is what preflight would freeze as its `requirements` (the model's and its
    Compliance rules'), plus the two datasets the run layer itself names -- `agenda.days_from`
    and `execution.dataset`. A component that does not load contributes nothing here: its own
    worker refuses it by name, and a run that cannot start cannot race anything. `reads` is
    `batch_reads` already asked; absent, it is asked here.
    """
    definitions = {run_id: workspace.run_definition(run_id) for run_id in run_ids}
    if reads is None:
        reads = batch_reads(workspace, run_ids)
    writers: dict[str, list[str]] = {}
    for run_id, definition in definitions.items():
        writers.setdefault(definition.writes, []).append(run_id)
    failures: list[Failure] = []
    for dataset_id, writing in sorted(writers.items()):
        if len(writing) < 2:
            continue
        named = ", ".join(writing)
        failures.append(
            Failure.bounded(
                RUN_BATCH_WRITES_COLLIDE,
                "runs in one --jobs batch write different datasets",
                observed=f"{dataset_id!r} is the `writes` of {len(writing)} runs: {named}",
                fix=(
                    f"register a different `writes` for all but one of {named}, or run them "
                    "one at a time"
                ),
                status=Status.INVALID,
                source=FailureSource(key_path=f"runs.{writing[0]}.writes"),
            )
        )
    for run_id in definitions:
        for dataset_id in sorted(reads[run_id]):
            producers = [other for other in writers.get(dataset_id, ()) if other != run_id]
            if not producers:
                continue
            producer = producers[0]
            failures.append(
                Failure.bounded(
                    RUN_BATCH_DEPENDENT,
                    "a run in a --jobs batch does not read what another run in it writes",
                    observed=(
                        f"{run_id!r} reads {dataset_id!r}, which {producer!r} writes; a pool "
                        "starts both at once and promises no order between them"
                    ),
                    fix=(
                        f"vqapr run {producer} first, then this batch without it -- or run "
                        f"{run_id} after the batch"
                    ),
                    status=Status.INVALID,
                    source=FailureSource(key_path=f"runs.{run_id}"),
                )
            )
    if failures:
        raise VqaprError(stage=Stage.CHECK, failures=failures)


def _reads(workspace: Workspace, definition: RunDefinition) -> dict[str, set[str]]:
    """What a run would read: each dataset id with the field ids its components declare on it.

    The two datasets the run layer itself names -- `agenda.days_from`, `execution.dataset` --
    are read whole by the framework and carry no field set here.
    """
    read: dict[str, set[str]] = {}
    if definition.agenda.days_from is not None:
        read.setdefault(definition.agenda.days_from, set())
    if definition.execution is not None:
        read.setdefault(definition.execution.dataset, set())
    loaders: list[tuple[str, Callable[..., Component]]] = []
    if definition.strategy is not None:
        loaders.append((definition.strategy.component_id, load_strategy_model))
    if definition.datamodel is not None:
        loaders.append((definition.datamodel.component_id, load_data_model))
    loaders.extend((rule_id, load_compliance) for rule_id in definition.compliance)
    for component_id, loader in loaders:
        try:
            component = loader(
                workspace.component(component_id), project_root=workspace.project_root
            )
        except Exception:
            # Its own worker refuses it by name; a component that cannot load reads nothing.
            continue
        for requirement in component.requirements() or ():
            dataset_id = str(getattr(requirement, "dataset_id", ""))
            if dataset_id:
                field_id = str(getattr(requirement, "field_id", ""))
                fields = read.setdefault(dataset_id, set())
                if field_id:
                    fields.add(field_id)
    return read


CUBES_DIRECTORY = "cubes"
CUBE_LOCK = "batch.lock"
CUBE_STALE_AFTER = 600.0
CUBE_HEARTBEAT = 30.0


@contextmanager
def batch_cubes(
    workspace: Workspace,
    run_ids: Sequence[str],
    reads: Mapping[str, Mapping[str, set[str]]] | None = None,
) -> Iterator[Path | None]:
    """Bake what a `--jobs` batch reads once, hand the directory to its workers, remove it after.

    Record `236` (`docs/issues/098`). Every panel-grain dataset any run in the batch reads is
    scanned once here, in the driver, into `<project>/.vqapr/cubes/<batch>/<dataset_id>/` --
    one memory-mappable matrix per numeric field over every instrument -- and each worker takes
    its panel as a slice of those files (`data/cube.py`). The OS page cache holds the bytes once
    per machine; the 671 scans a 671-run sweep used to make are one.

    **Nothing accumulates** (owner decision 2026-09-10). The directory goes when the batch
    returns, on success, refusal or interrupt; a directory a hard-killed driver left behind is
    swept by the next batch once its lock is stale. A heartbeat thread keeps this batch's lock
    fresh for as long as the batch runs, so a batch of long runs is never mistaken for a dead
    one. What cannot be baked -- an unverified registration, a non-numeric field, a `rows`
    grain, a source that will not scan -- is simply not there, and the worker scans and refuses
    exactly as it does outside a batch. `reads` is `batch_reads` already asked (record `238`).
    """
    root = workspace.project_root / WORKSPACE_DIRECTORY / CUBES_DIRECTORY
    root.mkdir(parents=True, exist_ok=True)
    _sweep_stale_cubes(root)
    directory = root / f"{os.getpid()}-{secrets.token_hex(4)}"
    directory.mkdir()
    lock = directory / CUBE_LOCK
    lock.write_text(str(os.getpid()), encoding="ascii")
    stop = threading.Event()
    beat = threading.Thread(target=_keep_alive, args=(lock, stop), daemon=True)
    beat.start()
    try:
        _bake_for_batch(
            workspace, reads if reads is not None else batch_reads(workspace, run_ids), directory
        )
        yield directory
    finally:
        stop.set()
        beat.join(timeout=CUBE_HEARTBEAT)
        shutil.rmtree(directory, ignore_errors=True)


def _keep_alive(lock: Path, stop: threading.Event) -> None:
    while not stop.wait(CUBE_HEARTBEAT):
        with suppress(OSError):
            os.utime(lock, None)


def _sweep_stale_cubes(root: Path) -> None:
    """Remove batch directories whose lock nobody has refreshed inside the stale window."""
    now = time.time()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            age = now - (child / CUBE_LOCK).stat().st_mtime
        except OSError:
            age = CUBE_STALE_AFTER + 1.0
        if age > CUBE_STALE_AFTER:
            shutil.rmtree(child, ignore_errors=True)


def _bake_for_batch(
    workspace: Workspace, reads: Mapping[str, Mapping[str, set[str]]], directory: Path
) -> None:
    """One cube per panel-grain dataset the batch reads, over the union of the fields it names."""
    wanted: dict[str, set[str]] = {}
    for run_reads in reads.values():
        for dataset_id, fields in run_reads.items():
            wanted.setdefault(dataset_id, set()).update(fields)
    with ScanSession() as session:
        for dataset_id, fields in sorted(wanted.items()):
            if not fields:
                continue
            try:
                registration = workspace.dataset(dataset_id)
                if registration.grain is None or registration.grain is Grain.ROWS:
                    continue
                source = workspace.source(str(registration.source))
                cube_module.bake(
                    directory,
                    registration=registration,
                    source=source,
                    source_digest=workspace.source_digest(source),
                    fields=sorted(fields),
                    session=session,
                )
            except (VqaprError, InputError, KeyError, OSError):
                # Its worker scans and refuses it by name; a cube is a shortcut, not a door.
                continue


def run_registered_datamodel(
    project_root: str,
    run_id: str,
    store_root: str,
    replace_record: bool,
    cubes: str = "",
) -> Mapping[str, object]:
    """Run one REGISTERED datamodel run, in this process; the worker under `--jobs`.

    `cubes` is the directory the batch baked its cubes into (record `236`), or empty: a string,
    because it crosses the `spawn` boundary with the other arguments.

    A refusal is raised, not returned: a datamodel's `VqaprError` pickles (`__reduce__`), so the
    parent's `future.result()` re-raises it as itself, the same exception the sequential path
    raises. The strategy worker cannot do this because its `SimulationFailure` carries the owner
    objects that were refused; that is why it returns a `StrategyOutcome` instead.
    """
    workspace = Workspace.open(project_root)
    # The same door the sequential path passes: the judgments too, not the freeze alone. A
    # batch worker used to freeze without asking them, so `run a b --jobs 2` ran what `check`
    # and `run a` refused (the `docs/issues/archive/015` gap, again, one door over).
    frozen, resources = verify_run(workspace, workspace.run_definition(run_id)).require_ready()
    layer = frozen.datamodel
    if layer is None:
        raise ValueError(f"run {run_id!r} is not a datamodel run")
    _, record = _run_datamodel(
        Path(project_root),
        frozen,
        layer,
        store=Path(store_root),
        replace_record=replace_record,
        cubes=Path(cubes) if cubes else None,
        resources=resources,
    )
    assert record is not None
    return record


def _window_factory(
    frozen: FrozenRun,
    observation_store: DuckDbObservationStore,
    *,
    allowed_requirements: Sequence[DataRequirement],
    consumer_id: str | None,
) -> Callable[[datetime], ModelWindow]:
    """A window over the run's declared instruments at one instant, for one consumer.

    Three loops built this lambda by hand (record `228`); the part's window and the rules'
    window differ only in what they may read and on whose behalf.
    """

    def at(instant: datetime) -> ModelWindow:
        return ModelWindow(
            evaluation_time=instant,
            instruments=frozen.instruments,
            store=observation_store,
            allowed_requirements=allowed_requirements,
            consumer_id=consumer_id,
        )

    return at


def _run_member[ResultT](
    frozen: FrozenRun,
    *,
    record_ref: Callable[[], str],
    member_kind: str,
    store: Path | None,
    replace_record: bool,
    body: Callable[[DuckDbObservationStore, ScanSession, RunRecordWriter | None], ResultT],
    read_record: Callable[[Path, str, str], Mapping[str, object]],
    cubes: Path | None = None,
) -> tuple[ResultT, Mapping[str, object] | None]:
    """Run one member of a run inside the resources every member needs, and read its record back.

    What a strategy and a datamodel share (record `228`): one scan session for the whole member
    (duckdb caches parquet metadata per connection, and closing per query threw that away), one
    observation store over the frozen catalog, a record writer opened before the loop and
    released if the member dies -- a member that died still held its record's lock, which
    stranded the directory until the lock went stale -- and the record read back from disk once
    the member is complete. What the member does between those is `body`'s: the loads and the
    drift checks come before, so a component that drifted claims no record directory.

    `record_ref` is asked for only when there is a store: a member run in memory (an in-process
    caller, a test with a stand-in component) names no record and needs no fingerprint.

    **`run.json` is written here, not by the callers** (record `249`). `run` and
    `_run_datamodels` each wrote it before calling in, and the `--jobs` workers
    (`run_registered_strategy`, `run_registered_datamodel`) call the member functions directly --
    so every run of a batch finished with its strategy record and no run record, `list runs`
    listed it and `show run` refused it (`docs/issues/report-2026-09-11-a-jobs-batch-writes-no-
    run-record-...`). Every path that runs a member with a store comes through this function,
    so this is the one place that cannot be skipped.
    """
    catalog = _FrozenCatalog(frozen)
    session = ScanSession()
    writer = None
    try:
        observation_store = DuckDbObservationStore(
            catalog,
            session=session,
            # The run's horizon bounds every panel scan (record `235`): a run holds its period
            # plus its lookbacks, not the registered span. A stand-in frozen run (a boundary
            # test's) may carry neither, and then the store scans the registered span.
            horizon=_horizon(frozen),
            requirements=tuple(getattr(frozen, "requirements", ())),
            # The batch's cubes, when this member runs under `--jobs` (record `236`).
            cubes=cubes,
        )
        if store is not None:
            # Before the member's writer claims its directory, so a run killed midway still says
            # what it attempted; a changed configuration under this id is refused here, by name.
            freeze_run_record(store, frozen, source_digests=_source_digests(frozen))
            opened_writer = RunRecordWriter(
                store, frozen.run_id, record_ref(), member_kind=member_kind
            )
            opened_writer.open(replace=replace_record)
            writer = opened_writer
        result = body(observation_store, session, writer)
    except BaseException:
        if writer is not None:
            writer.release()
        raise
    finally:
        session.close()
    record = None if writer is None else read_record(writer.root, frozen.run_id, record_ref())
    return result, record


def _horizon(frozen: FrozenRun) -> tuple[datetime, datetime] | None:
    """The run's period as the store's scan horizon, or `None` when the run has none frozen."""
    start = getattr(frozen, "start", None)
    end = getattr(frozen, "end", None)
    if isinstance(start, datetime) and isinstance(end, datetime):
        return (start, end)
    return None


def _run_datamodel(
    root_path: Path,
    frozen: FrozenRun,
    layer: FrozenDataModel,
    *,
    store: Path | None,
    replace_record: bool,
    cubes: Path | None = None,
    resources: RunResources | None = None,
) -> tuple[DataModelResult, Mapping[str, object] | None]:
    """Execute exactly one datamodel of a frozen run: its sessions, its dataset, its record.

    Order at the end, deliberately: the dataset registers first and the record is written last.
    The registration is the product; the record existing is what marks the member complete, and
    a record that said "wrote dataset X" beside a registration that never happened would be the
    invisibility `059` measured.
    """
    # The instance the verification loaded, when the caller handed it over (record `242`).
    model = (
        resources.datamodel
        if resources is not None and resources.datamodel is not None
        else load_data_model(layer.component, project_root=root_path)
    )
    as_loaded = {layer.component_id: as_loaded_fingerprint(layer.component, project_root=root_path)}
    if tuple(model.requirements()) != layer.requirements:
        raise ValueError("loaded DataModel requirements drifted from FrozenRun")
    model.memory = normalize_memory(layer.initial_model_memory)

    def body(
        observation_store: DuckDbObservationStore,
        session: ScanSession,
        writer: RunRecordWriter | None,
    ) -> DataModelResult:
        output = RunOutput(
            root_path,
            writes=frozen.writes,
            value_fields=layer.value_fields,
            run_id=frozen.run_id,
            record_ref=layer.record_ref,
        )
        window_at = _window_factory(
            frozen,
            observation_store,
            allowed_requirements=layer.requirements,
            consumer_id=layer.component_id,
        )
        flow = datamodel_loop(
            frozen,
            layer,
            model,
            window_for_occurrence=lambda occurrence: window_at(occurrence.evaluation_time),
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
        return result

    return _run_member(
        frozen,
        record_ref=lambda: layer.record_ref,
        member_kind=DATAMODEL_KIND,
        store=store,
        replace_record=replace_record,
        body=body,
        read_record=read_datamodel_record,
        cubes=cubes,
    )


def run_registered_strategy(
    project_root: str,
    run_id: str,
    store_root: str,
    replace_record: bool,
    record_account_positions: bool,
    cubes: str = "",
) -> StrategyOutcome:
    """One registered strategy run, in this process, returning its outcome.

    The worker behind `jobs > 1`, which parallelises RUNS since 2026-09-09 -- a run holds one
    model, so the unit that can be spread across processes is the run itself. Module-level and
    taking only strings and bools, because it
    crosses a `spawn` boundary; it freezes the registered run again rather than receiving a
    frozen one, since a frozen run is built from workspace objects that are not meant to travel.

    A `SimulationFailure` is returned inside the outcome rather than raised, because it cannot
    make the trip back: `concurrent.futures` pickles a worker's exception to hand it to the
    parent, and this one carries the owner object that was refused -- a `Rebalance` whose weights
    are a `MappingProxyType` -- so the parent used to receive `TypeError: cannot pickle
    'mappingproxy' object`, render `stage: unhandled` with `failures: []`, and say nothing about
    the strategies that had finished (`docs/issues/archive/073`).
    """
    workspace = Workspace.open(project_root)
    frozen, resources = verify_run(workspace, workspace.run_definition(run_id)).require_ready()
    layer = frozen.strategy
    if layer is None:
        raise ValueError(f"run {run_id!r} is not a strategy run")
    try:
        _, record = _run_strategy(
            Path(project_root),
            frozen,
            layer,
            store=Path(store_root),
            replace_record=replace_record,
            record_account_positions=record_account_positions,
            roster=registered_roster(workspace),
            cubes=Path(cubes) if cubes else None,
            resources=resources,
        )
    except SimulationFailure as failed:
        return _failed_outcome(layer.component_id, failed)
    assert record is not None
    return StrategyOutcome(layer.component_id, COMPLETED, record=record)


def _source_digests(frozen: FrozenRun) -> dict[str, str]:
    """The physical digest of every source the run reads, keyed by source id (A7).

    Preflight verified each source against the digest registration measured and carried it on
    the frozen run (record `234`); a run frozen in memory without them hashes here.
    """
    return {
        str(source.source_id): frozen.source_digests.get(str(source.source_id))
        or physical_digest(source.path)
        for source in frozen.sources
    }


def _run_strategy(
    root_path: Path,
    frozen: FrozenRun,
    layer: FrozenStrategy,
    *,
    store: Path | None,
    replace_record: bool,
    record_account_positions: bool,
    roster: RegisteredRoster | None,
    workspace: Workspace | None = None,
    cubes: Path | None = None,
    resources: RunResources | None = None,
) -> tuple[SimulationResult, Mapping[str, object] | None]:
    """Execute exactly one strategy of a frozen run, with its own Account and its own record.

    `roster` is the one read `run` made at its start (`docs/issues/archive/070`); the record is
    written from it rather than from a read of this strategy's own. `workspace` is the document
    the command opened, when it did, so publishing the allocation registers through that one
    open rather than a second.
    """
    # The instances the verification loaded, when the caller handed them over (record `242`);
    # otherwise loaded here, once, as before. Either way the run's own `as_loaded` receipt
    # below fingerprints the bytes on disk now.
    strategy = (
        resources.strategy
        if resources is not None and resources.strategy is not None
        else load_strategy_model(layer.config.component, project_root=root_path)
    )
    # `run` refused a strategy run frozen without a venue or an initial account before
    # dispatching here; a worker process rebuilds the frozen run and re-states that.
    if frozen.exchange is None:
        raise RuntimeError("a frozen strategy run reached execution without an Exchange")
    initial_snapshot = frozen.initial_account_snapshot
    initial_mode = frozen.initial_account_mode
    if initial_snapshot is None or initial_mode is None:
        raise RuntimeError("a frozen strategy run reached execution without an initial account")
    exchange = (
        resources.exchange
        if resources is not None and resources.exchange is not None
        else load_exchange(frozen.exchange, project_root=root_path)
    )
    rules = (
        resources.rules
        if resources is not None and len(resources.rules) == len(layer.compliance.rules)
        else tuple(load_compliance(ref, project_root=root_path) for ref in layer.compliance.rules)
    )
    horizon = resources.horizon if resources is not None else None
    # What was ACTUALLY loaded, computed beside the loads that read it.
    #
    # Since the drift refusal went (issue 009), an edited component runs instead of being
    # refused, so the registered fingerprints -- fixed at preflight -- can describe bytes this
    # run never executed. Recording only those would leave a receipt that looks authoritative
    # and is stale, which is worse than the gate it replaced.
    as_loaded = _as_loaded_fingerprints(frozen, layer, root_path)
    if strategy.requirements() != layer.requirements:
        raise ValueError("loaded Strategy requirements drifted from FrozenRun")
    if declared_compliance_requirements(rules) != layer.compliance_requirements:
        raise ValueError("loaded Compliance requirements drifted from FrozenRun")
    # The record is written from the ONE roster read `run` made, never from a second one.
    # `roster` carries the digest and the table list beside the registry, so a `vqapr register`
    # landing during the run cannot make the record state a digest the fills were never classified
    # by (`docs/issues/archive/050`).
    registry = roster.registry if roster is not None else None
    frozen_exchange = frozen.exchange

    def body(
        observation_store: DuckDbObservationStore,
        session: ScanSession,
        writer: RunRecordWriter | None,
    ) -> SimulationResult:
        root = AccountState(initial_snapshot)
        strategy.memory = normalize_memory(layer.initial_model_memory)
        strategy.load_payload(BytesIO(layer.initial_payload))
        state = RunStateRepository(
            initial_account=root,
            initial_model_memory=layer.initial_model_memory,
            initial_payload=layer.initial_payload,
            # What each rule holds as loaded -- its constructor's doing, from the config the
            # fingerprint already folds -- is the memory the run commits from (record `181`).
            initial_component_memory={
                **{rule.compliance_id: rule.memory for rule in rules},
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
            sink=None if writer is None else writer.append_chunk,
        )
        if state.root.current_model_state_ref != layer.initial_model_state_ref:
            raise RuntimeError("initial Model state does not match frozen run authority")
        initial_ref = state.root.current_model_state_ref
        if initial_ref is None or state.load_payload(initial_ref) != layer.initial_payload:
            raise RuntimeError("initial Strategy payload does not match frozen run authority")
        strategy_window_at = _window_factory(
            frozen,
            observation_store,
            allowed_requirements=layer.requirements,
            consumer_id=layer.component_id,
        )
        # The rules read as of the market-clock instant they observe at (design §7.2). No
        # consumer: this window serves every loaded rule, and which one is reading is known
        # only inside the evaluation that calls them.
        compliance_window_at = _window_factory(
            frozen,
            observation_store,
            allowed_requirements=layer.compliance_requirements,
            consumer_id=None,
        )
        flow = strategy_loop(
            frozen,
            strategy,
            state,
            layer=layer,
            strategy_window_for_occurrence=lambda occurrence: strategy_window_at(
                occurrence.evaluation_time
            ),
            compliance_window_at=compliance_window_at,
            # Each strategy has its own Account (design §7-4): the run shares the initial
            # DECLARATION, not the book. It retains the marks this strategy declared it would
            # read; declaring nothing keeps one.
            account=Account(
                mode=initial_mode,
                retained_marks=retained_marks(strategy.account_history()),
            ),
            exchange=exchange,
            compliance=rules,
            horizon=horizon,
            scan_session=session,
            # The strategy's liveness signal. Without it the record's lock is stamped once at
            # `open` and never touched again, so any run longer than `LOCK_STALE_AFTER` reads as
            # dead WHILE STILL EXECUTING, and a peer takes its id and deletes its tables.
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
                writer,
                result,
                frozen,
                layer,
                as_loaded,
                _roster_report_or_stale(roster),
                # The venue as this run had it: which one, which bytes, and what it declared it
                # models (design §6.1). Recorded so a reader can tell a tax-free KRX from a
                # taxed one without opening the source at its digest.
                exchange={
                    "component_id": str(frozen_exchange.component_id),
                    "fingerprint": frozen_exchange.fingerprint,
                    "settings": normalize_memory(dict(exchange.settings)),
                },
            )
        # The record first -- it is the run -- and then the warehouse: what the run promised
        # under `writes` (design §2), through the same door a datamodel's rows take. A stored
        # run streamed its rows to the record and keeps none on its roots, so the allocation is
        # read back from the record it just wrote; a run without a store still holds them.
        _publish_allocation(
            root_path,
            frozen,
            result.final_state.recorder_rows.get(WEIGHT_TABLE, ())
            if writer is None
            else read_table(writer.root, frozen.run_id, WEIGHT_TABLE, layer.record_ref),
            workspace=workspace,
        )
        return result

    return _run_member(
        frozen,
        record_ref=lambda: layer.record_ref,
        member_kind=STRATEGY_KIND,
        store=store,
        replace_record=replace_record,
        body=body,
        read_record=read_strategy_record,
        cubes=cubes,
    )


def _own_output_or_refuse(
    workspace_or_root: Workspace | Path, frozen: FrozenRun, *, replace_record: bool
) -> None:
    """A run whose published output stands is run again the way its record is: deliberately.

    Preflight lets the run's own `writes` through (it is this run's product, not a taken name);
    the decision to replace it is made here, beside the record's, under the same flag. Without
    `replace_record` the run is refused with the two ways forward; with it the earlier output is
    withdrawn and the run publishes afresh. An authored dataset, or another run's, never reaches
    this branch -- preflight refused it by name.

    Read through the caller's `Workspace` when it holds one (`docs/issues/archive/070`: one
    command, one open). A frozen run executed outside any workspace has nothing published to
    stand in its way, so an ABSENT document is not a refusal here -- the same narrow tolerance
    `registered_roster` keeps, and for the same reason: a damaged document still raises.
    """
    if isinstance(workspace_or_root, Workspace):
        workspace = workspace_or_root
    else:
        try:
            workspace = Workspace.open(workspace_or_root)
        except VqaprError as unopened:
            if not absent_workspace(unopened):
                raise
            return
    existing = next(
        (item for item in workspace.datasets if str(item.dataset_id) == frozen.writes), None
    )
    if existing is None or existing.produced_by != frozen.run_id:
        return
    if not replace_record:
        raise VqaprError(
            stage=Stage.RUN,
            failures=[
                Failure.bounded(
                    code="run.output_registered",
                    status=Status.CONFLICT,
                    requirement="a run publishes its output once unless told to replace it",
                    observed=(
                        f"{frozen.writes!r} was published by an earlier run of {frozen.run_id!r}"
                    ),
                    fix=(
                        f"vqapr run {frozen.run_id} --force to replace it, or "
                        f"vqapr rm dataset {frozen.writes} to withdraw it first"
                    ),
                )
            ],
            mutation=False,
            retry_precondition="pass --force, or withdraw the dataset, then retry",
        )
    workspace.remove("dataset", frozen.writes)



def _publish_allocation(
    root_path: Path,
    frozen: FrozenRun,
    recorded: Iterable[Mapping[str, object]],
    *,
    workspace: Workspace | None = None,
) -> str | None:
    """Put the strategy's allocation in the warehouse under the run's `writes` (design §2).

    The rows are the `vqapr.weight` table the callback recorded -- one per instrument per
    decision, the weight as the exact string the intent carried -- stamped `available_at` at the
    decision's own `event_time`, which is when that weight was knowable and not a second earlier.
    Published as DOUBLE: the data plane carries one numeric type per kind
    (`docs/issues/archive/088`), and the exact value stays in the record. This is what makes a
    published allocation and a registered benchmark the same kind of input
    (`portfolio/allocation.py`): a later strategy reads either through a `DataRequirement`.

    A strategy that held on every session has nothing to publish and publishes nothing: an empty
    dataset cannot be typed, and a typed nothing would be a lie. The run still completes; `writes`
    then names a dataset that does not appear, and `vqapr list runs` beside `list datasets` shows
    exactly that.

    `recorded` is the `vqapr.weight` table -- off the roots for a run without a store, read back
    from the record for a stored run. Until record `210` this read the roots only, and a stored
    run streams every row to its record and keeps none there, so `vqapr run` published nothing
    while an in-process `run()` did (the showcases registered their allocations by hand from the
    record, which is why nothing noticed).

    **A batch at a time** (record `254`). The whole table became one list of dicts before a row was
    typed -- every weight of the run in Python at once, after the run had ended and beside
    everything it still held -- and a daily 309-name run peaked there. The record reader already
    streams, and `RunOutput` holds what it is handed as Arrow.
    """
    batches = batched(
        (
            {
                "available_at": row["event_time"],
                "instrument": row["instrument"],
                "weight": float(Decimal(str(row["weight"]))),
            }
            for row in recorded
        ),
        ALLOCATION_BATCH_ROWS,
    )
    first = next(batches, None)
    if first is None:
        return None
    output = RunOutput(
        root_path,
        writes=frozen.writes,
        value_fields=("weight",),
        run_id=frozen.run_id,
        record_ref=None if frozen.strategy is None else frozen.strategy.record_ref,
    )
    output.open()
    output.append(first)
    for batch in batches:
        output.append(batch)
    output.register(workspace if workspace is not None else Workspace.open(root_path))
    return frozen.writes


ALLOCATION_BATCH_ROWS = 50_000
"""How many weight rows `_publish_allocation` types at once: small next to a run, large next to
the per-batch cost of `pa.Table.from_pylist`."""


def _roster_report_or_stale(roster: RegisteredRoster | None) -> dict[str, object] | None:
    """The roster block for the record, or a STALE MARKER when it cannot be built at record time.

    Narrow on purpose: it catches `VqaprError` only, so a bug in report construction still fails
    loudly. **Not `None`, and that distinction is the whole point.** `roster: null` in a record
    means *"the run never knew the categories"*; any run that reaches this line did read its
    roster, so the marker says what actually happened: the run knew its categories, and the record
    could not re-read them at the end (`docs/issues/archive/042`, `050`).
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
    its own, so a change to one rule does not disguise itself as a change to the strategy.
    Only refs that carry a real source are included -- a run assembled in-process may hold a stub
    in place of a registered component, and such a thing has no bytes on disk to fingerprint.
    """
    candidates = [layer.config.component, frozen.exchange, *layer.compliance.rules]
    return {
        str(ref.component_id): as_loaded_fingerprint(ref, project_root=root_path)
        for ref in candidates
        if isinstance(ref, ComponentRef)
    }
