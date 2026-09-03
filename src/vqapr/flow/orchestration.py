"""Assemble and execute one run -- every strategy it names -- from a frozen authority to results.

**This is where `vqapr.public.run` lives**, and record `111` is why it moved: a facade that
executes runs is not a facade. Record `139` made it a run of several strategies: the run layer is
frozen once, and each strategy runs in its own `SimulationFlow` with its own `Account` and its own
record directory (design §4.1, §7-4). Sequentially by default; with `jobs > 1`, in that many
processes, each of which freezes the registered run again and runs one strategy of it.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

from vqapr.account.account import Account
from vqapr.account.history import retained_marks
from vqapr.account.snapshot import AccountState
from vqapr.constraints.evaluation import (
    constraint_requirements as declared_constraint_requirements,
)
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.scan import ScanSession
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore, physical_digest
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.exchange.execution_table import validate_execution_input
from vqapr.extension.component import ComponentRef
from vqapr.extension.loading import (
    as_loaded_fingerprint,
    load_constraint,
    load_exchange,
    load_strategy_model,
)
from vqapr.flow.preflight import preflight_run as _preflight_run
from vqapr.flow.records import freeze_run_record, freeze_strategy_record
from vqapr.flow.roster import RegisteredRoster, registered_roster, roster_report
from vqapr.flow.run import FrozenRun, FrozenStrategy, RunDefinition
from vqapr.flow.run_records import RunRecordWriter, read_strategy_record
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.simulation import SimulationFlow, SimulationResult
from vqapr.models.memory import normalize_memory
from vqapr.workspace import Workspace


def preflight_run(project_root: str | Path, definition: RunDefinition) -> FrozenRun:
    """Resolve a run definition against registered declarations without running it."""
    if not isinstance(definition, RunDefinition):
        raise TypeError("definition must be a RunDefinition")
    return _preflight_run(Workspace.open(project_root), definition)


class _FrozenCatalog:
    """Read-only data declarations captured by preflight, never a mutable workspace."""

    def __init__(self, frozen: FrozenRun) -> None:
        self._datasets = {str(dataset.dataset_id): dataset for dataset in frozen.datasets}
        self._sources = {str(source.source_id): source for source in frozen.sources}

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        return self._datasets[raw_dataset_id]

    def source(self, raw_source_id: str) -> SourceSpec:
        return self._sources[raw_source_id]


@dataclass(frozen=True, slots=True)
class RunResult:
    """What one call to `run` produced: a result per strategy it ran, and their records.

    `results` holds the in-process `SimulationResult` of every strategy this process ran.
    `records` holds each strategy's `strategy.json` as written, for every strategy run under a
    store -- including those run by worker processes, whose in-process result never crosses the
    process boundary and is read back from the record instead.
    """

    run_id: str
    results: Mapping[str, SimulationResult]
    records: Mapping[str, Mapping[str, object]]

    def result(self, component_id: str | None = None) -> SimulationResult:
        """The one strategy's result, or the only one when the run ran exactly one."""
        if component_id is None:
            if len(self.results) != 1:
                raise ValueError(
                    f"run {self.run_id!r} produced {len(self.results)} in-process results; "
                    "name the strategy"
                )
            return next(iter(self.results.values()))
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
) -> RunResult:
    """Execute a frozen run: each of its strategies (or those named), each in its own flow.

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
    if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None:
        raise ValueError("public run requires frozen initial account authority")
    if frozen.exchange is None:
        raise ValueError("public run requires a frozen Exchange authority")
    if frozen.execution_input is None:
        raise ValueError("public run requires a frozen execution input")
    validate_execution_input(frozen.execution_input).raise_if_failed()

    selected = tuple(frozen.strategy(name) for name in (strategies or ())) or frozen.strategies
    store = None if store_root is None else Path(store_root)
    if store is not None:
        freeze_run_record(store, frozen, source_digests=_source_digests(frozen))

    results: dict[str, SimulationResult] = {}
    records: dict[str, Mapping[str, object]] = {}
    if jobs > 1 and len(selected) > 1:
        if store is None:
            raise ValueError(
                "jobs > 1 needs a store_root: a worker's result comes back as its record"
            )
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=min(jobs, len(selected)), mp_context=context) as pool:
            futures = {
                layer.component_id: pool.submit(
                    run_registered_strategy,
                    str(root_path),
                    frozen.run_id,
                    layer.component_id,
                    str(store),
                    replace_record,
                    record_account_positions,
                )
                for layer in selected
            }
            for component_id, future in futures.items():
                records[component_id] = future.result()
        return RunResult(frozen.run_id, MappingProxyType(results), MappingProxyType(records))

    for layer in selected:
        result, record = _run_strategy(
            root_path,
            frozen,
            layer,
            store=store,
            replace_record=replace_record,
            record_account_positions=record_account_positions,
        )
        results[layer.component_id] = result
        if record is not None:
            records[layer.component_id] = record
    return RunResult(frozen.run_id, MappingProxyType(results), MappingProxyType(records))


def run_registered_strategy(
    project_root: str,
    run_id: str,
    component_id: str,
    store_root: str,
    replace_record: bool,
    record_account_positions: bool,
) -> Mapping[str, object]:
    """One strategy of one registered run, in this process, returning its record.

    The worker behind `jobs > 1`. Module-level and taking only strings and bools, because it
    crosses a `spawn` boundary; it freezes the registered run again rather than receiving a
    frozen one, since a frozen run is built from workspace objects that are not meant to travel.
    """
    workspace = Workspace.open(project_root)
    frozen = _preflight_run(workspace, workspace.run_definition(run_id))
    layer = frozen.strategy(component_id)
    _, record = _run_strategy(
        Path(project_root),
        frozen,
        layer,
        store=Path(store_root),
        replace_record=replace_record,
        record_account_positions=record_account_positions,
    )
    assert record is not None
    return record


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
) -> tuple[SimulationResult, Mapping[str, object] | None]:
    """Execute exactly one strategy of a frozen run, with its own Account and its own record."""
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
    # ONE read of the roster, and the record is written from it rather than from a second one.
    # `roster` carries the digest and the table list beside the registry, so a `vqapr register`
    # landing during the run cannot make the record state a digest the fills were never classified
    # by (`docs/issues/050`).
    roster = registered_roster(root_path)
    registry = roster.registry if roster is not None else None
    catalog = _FrozenCatalog(frozen)
    # One physical handle for the whole strategy. duckdb caches parquet metadata for a
    # connection's lifetime, and closing per query threw that away on every observation.
    session = ScanSession()
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
    writer = None
    if store is not None:
        writer = RunRecordWriter(store, frozen.run_id, layer.record_ref)
        writer.open(replace=replace_record)
    state = RunStateRepository(
        initial_account=root,
        initial_model_memory=layer.initial_model_memory,
        initial_payload=layer.initial_payload,
        # Rows leave the run as each occurrence is accepted, into this strategy's own directory;
        # a killed run keeps everything up to its last accepted occurrence, and the heap holds
        # one occurrence's rows rather than the run's. Without a store, roots keep rows as before.
        row_sink=None if writer is None else writer.append,
    )
    if state.root.current_model_state_ref != layer.initial_model_state_ref:
        raise RuntimeError("initial Model state does not match frozen run authority")
    initial_ref = state.root.current_model_state_ref
    if initial_ref is None or state.load_payload(initial_ref) != layer.initial_payload:
        raise RuntimeError("initial Strategy payload does not match frozen run authority")
    flow = SimulationFlow(
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
        # DECLARATION, not the book. It retains exactly the marks this strategy declared it would
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
    try:
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
