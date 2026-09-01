"""Assemble and execute one simulation, from a frozen authority to a result.

**This is where `vqapr.public.run` lives**, and record `111` is why it moved. `public.py` was the
package's documented surface and also its orchestrator: 775 lines, of which 450 were function
bodies. A facade that executes runs is not a facade, and every module below it that needed one of
these functions had to import the top-level surface to get it -- the fan-in `docs/issues/028`
records.

`vqapr.public` re-exports `run` and `preflight_run` unchanged, so no caller and no emitted scaffold
moved. What changed is where the code lives: beside `flow/preflight.py`, which freezes the
declarations this consumes, and `flow/run.py`, which defines the `FrozenRun` it takes.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from vqapr.account.account import Account
from vqapr.account.history import retained_marks
from vqapr.account.snapshot import AccountState
from vqapr.constraints.evaluation import (
    constraint_requirements as declared_constraint_requirements,
)
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.scan import ScanSession
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
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
from vqapr.flow.records import freeze_record
from vqapr.flow.roster import RegisteredRoster, registered_roster, roster_report
from vqapr.flow.run import FrozenRun, RunDefinition
from vqapr.flow.run_records import RunRecordWriter
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


def run(
    project_root: str | Path,
    frozen_run: FrozenRun,
    *,
    store_root: str | Path | None = None,
    run_id: str | None = None,
    replace_record: bool = False,
) -> SimulationResult:
    """Execute exactly one simulation from a preflight-produced frozen authority.

    When `store_root` is given the run freezes its own record beneath it, which is what makes the
    result readable by any later process -- including `show run` from a cold one, and including the
    other four of five concurrent runs. Omitted, the run keeps its results in memory exactly as
    before: an in-process caller that already holds the result should not be made to write it to
    disk to get it.
    """
    if not isinstance(frozen_run, FrozenRun):
        raise TypeError("frozen_run must be a FrozenRun returned by preflight_run")
    root_path = Path(project_root)
    frozen = frozen_run
    if frozen.initial_account_snapshot is None or frozen.initial_account_mode is None:
        raise ValueError("public run requires frozen initial account authority")
    if frozen.exchange is None:
        raise ValueError("public run requires a frozen Exchange authority")
    if frozen.execution_input is None:
        raise ValueError("public run requires a frozen execution input")
    validate_execution_input(frozen.execution_input).raise_if_failed()

    strategy = load_strategy_model(frozen.strategy.component, project_root=root_path)
    exchange = load_exchange(frozen.exchange, project_root=root_path)
    constraints = tuple(
        load_constraint(ref, project_root=root_path) for ref in frozen.constraints.constraints
    )
    # What was ACTUALLY loaded, computed beside the loads that read it.
    #
    # Since the drift refusal went (issue 009), an edited component runs instead of being
    # refused, so `frozen.identity` -- fixed at preflight from the REGISTERED fingerprints -- can
    # describe bytes this run never executed. Recording only that would leave a receipt that
    # looks authoritative and is stale, which is worse than the gate it replaced.
    #
    # Derived here rather than inside `_load` because the loaders' return types are what their
    # callers expect, and here is where the consumer that records it lives.
    as_loaded = _as_loaded_identity(frozen, root_path)
    # ONE read of the roster, and the record is written from it rather than from a second one.
    # `roster` carries the digest and the table list beside the registry, so a `vqapr register`
    # landing during the run cannot make the record state a digest the fills were never classified
    # by (`docs/issues/050`).
    roster = registered_roster(root_path)
    registry = roster.registry if roster is not None else None
    catalog = _FrozenCatalog(frozen)
    # One physical handle for the whole run. duckdb caches parquet metadata for a connection's
    # lifetime, and closing per query threw that away on every observation.
    session = ScanSession()
    store = DuckDbObservationStore(catalog, session=session)
    strategy_requirements = strategy.requirements()
    if strategy_requirements != frozen.strategy_requirements:
        raise ValueError("loaded Strategy requirements drifted from FrozenRun")
    constraint_requirements = declared_constraint_requirements(constraints)
    if constraint_requirements != frozen.constraint_requirements:
        raise ValueError("loaded Constraint requirements drifted from FrozenRun")
    root = AccountState(frozen.initial_account_snapshot)
    strategy.memory = normalize_memory(frozen.initial_model_memory)
    strategy.load_payload(BytesIO(frozen.initial_payload))
    state = RunStateRepository(
        initial_account=root,
        initial_model_memory=frozen.initial_model_memory,
        initial_payload=frozen.initial_payload,
    )
    if state.root.current_model_state_ref != frozen.initial_model_state_ref:
        raise RuntimeError("initial Model state does not match frozen run authority")
    initial_ref = state.root.current_model_state_ref
    if initial_ref is None or state.load_payload(initial_ref) != frozen.initial_payload:
        raise RuntimeError("initial Strategy payload does not match frozen run authority")
    writer = None
    if store_root is not None:
        writer = RunRecordWriter(Path(store_root), run_id or str(frozen.identity))
        writer.open(replace=replace_record)
    flow = SimulationFlow(
        frozen,
        strategy,
        state,
        strategy_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=frozen.instruments,
            store=store,
            allowed_requirements=frozen.strategy_requirements,
            consumer_id=str(frozen.strategy.component.component_id),
        ),
        constraint_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=frozen.instruments,
            store=store,
            # No consumer: this window serves every loaded constraint, and which one is reading
            # is known only inside the loop that calls them. `project_constraints` and
            # `evaluate_constraints` take a view per constraint.
            allowed_requirements=frozen.constraint_requirements,
        ),
        # A run retains exactly the marks somebody declared they would read. Declaring nothing
        # keeps one, so a Strategy that never looks at its own path costs nothing to carry it.
        account=Account(
            mode=frozen.initial_account_mode,
            retained_marks=retained_marks(
                tuple(getattr(strategy, "account_requirements", tuple)())
            ),
        ),
        exchange=exchange,
        constraints=constraints,
        scan_session=session,
        # The run's liveness signal. Without it the record's lock is stamped once at `open` and
        # never touched again until the run ends -- so any run longer than `LOCK_STALE_AFTER`
        # reads as dead WHILE STILL EXECUTING, and a peer takes its id and deletes its tables. A
        # factor run here takes three to six minutes against a two-minute window, so that is every
        # real run, not an edge case.
        on_progress=writer.heartbeat if writer is not None else None,
        registry=registry,
    )
    try:
        result = flow.run()
        if writer is not None:
            # `roster_report` is evaluated HERE, after the run returned and outside the argument
            # list, and its failure is absorbed. It no longer reads anything -- `docs/issues/050`
            # moved the digest and the table list onto the read taken before `flow.run()` -- but
            # the shape stays, because the defect it fixes was structural: the report is built
            # after the run, outside the argument list, and whatever it raises stops at the
            # absorber rather than at the writer.
            #
            # Evaluated as an argument inside the `try`, that refusal skipped `freeze_record`
            # entirely: no rows, no `record.json`, the id released for a peer to take, exit 1 --
            # **a completed multi-hour run discarded because one small JSON file went bad after it
            # finished**. `cli/run.py` already wrote the defence for exactly this case ("the tables
            # can become unreadable in the minutes a real run takes, and letting that refusal
            # escape would report exit 1 for a run that completed"), but that guard runs after
            # `run()` returns and so never covered this line.
            #
            # The report is decoration on a record; the record is the run. Losing the decoration is
            # the cheaper failure, and it is recorded as a stale marker rather than as `null`,
            # which this record's own contract defines as "no roster was ever read".
            freeze_record(
                writer,
                result,
                frozen,
                as_loaded,
                _roster_report_or_stale(roster),
            )
    except BaseException:
        # A run that died still holds its id. Releasing here turns a crash into an ordinary
        # retry instead of stranding the id until the lock goes stale. `freeze_record` is inside
        # the guard for the same reason: a failure while writing the record is still a failure
        # that must not keep the id.
        if writer is not None:
            writer.release()
        raise
    finally:
        session.close()
    return result


def _roster_report_or_stale(roster: RegisteredRoster | None) -> object | None:
    """The roster block for the record, or a STALE MARKER when it cannot be built at record time.

    Narrow on purpose: it catches `VqaprError` only, so a bug in report construction still fails
    loudly. What it absorbed was the one thing that legitimately changes underneath a long run --
    the roster pointer on disk -- and the alternative was discarding a finished run over it.
    Since `docs/issues/050` the report is built from the read taken before `flow.run()` and touches
    no file, so that refusal can no longer originate here; the absorber stays as the standing
    guarantee that nothing computed AFTER a run completed can cost the record.

    **Not `None`, and that distinction is the whole point.** `flow/records.py` and
    `flow/run_records.py` both define `roster: null` in a record as *"the run never knew the
    categories"*. But `run` calls `registered_roster` before `flow.run()` and that refuses an
    unreadable pointer outright, so **any run that reaches this line did read its roster**.
    Returning `None` here would write a falsehood into the frozen artifact a later cold process
    reads -- the exact collapse `flow/roster.py` calls "the opposite of the truth" and that
    `docs/issues/042` exists to stop.

    So the marker says what actually happened: the run knew its categories, and the record could
    not re-read them at the end. `cli/run.py`'s `_roster_envelope` reaches the same shape for the
    same reason on the envelope side; this is the record side of it.
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


def _as_loaded_identity(frozen: FrozenRun, root_path: Path | None) -> str:
    """One digest over every component this run actually loaded, in a fixed order.

    Folded the same way `frozen.identity` folds the registered fingerprints, so the two are
    comparable: equal when nothing was edited between registration and the run, different exactly
    when something was.
    """
    # Only refs that carry a real source are folded. A FrozenRun assembled in-process may hold a
    # stub in place of a registered component -- `tests/boundaries` does exactly that -- and such
    # a thing has no bytes on disk to fingerprint. Skipping it keeps the digest a statement about
    # what was loaded from source, rather than raising on a run that is otherwise valid.
    candidates = [frozen.strategy.component, frozen.exchange]
    candidates.extend(frozen.constraints.constraints)
    parts = [
        (
            str(ref.component_id),
            as_loaded_fingerprint(ref, project_root=root_path),
        )
        for ref in candidates
        if isinstance(ref, ComponentRef)
    ]
    payload = "|".join(f"{name}={digest}" for name, digest in sorted(parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
