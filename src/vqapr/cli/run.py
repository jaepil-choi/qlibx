"""`vqapr run <run-id>` — freeze a registered run, preflight it, and execute the model it names.

A run is a registered declaration since record `139` (`runs:` in a declaration document, design
§4.1): the reusable unit is a name in the workspace, not a file. This verb looks the run up,
makes the same judgments `vqapr check` makes, freezes it, and runs its one model in its own flow
with its own account and its own record. A datamodel run (record `148`) is the same verb: its
model writes a dataset instead of tables.

**One model per run** (2026-09-09, `docs/design/two-clocks-and-the-wiring-table.md` §2.3), so
there is no member to select and `--strategy` is gone. Several models means several runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.analysis.execution import fill_summary
from vqapr.cli.envelope import failure, success

# `register` owns the CLI spelling of a component kind and imports nothing from this module, so
# naming it here adds no cycle. The judgments take it as a callable rather than importing it
# themselves, which is what keeps `flow/` free of `cli`.
from vqapr.domain.errors import (
    VALUE_INVALID,
    Failure,
    FailureSource,
    InputError,
    Stage,
    Status,
    VqaprError,
    status_of,
)
from vqapr.flow.declaration.verify import verify_run
from vqapr.flow.engine.run_state import FILL_TABLE
from vqapr.flow.orchestration import (
    COMPLETED,
    FAILED,
    batch_cubes,
    batch_reads,
    in_workers,
    require_independent_batch,
    run_registered_datamodel,
    run_registered_strategy,
)
from vqapr.project.store import WORKSPACE_DIRECTORY
from vqapr.public import RunDefinition, Workspace
from vqapr.public import run as execute_run
from vqapr.record import (
    RunRecordConflict,
    RunRecordExists,
    RunRecordLive,
    read_typed_table,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        nargs="+",
        help="the id of a registered run (`vqapr list runs`); several ids run several runs",
    )
    parser.add_argument(
        "--jobs",
        dest="jobs",
        type=int,
        default=1,
        help=(
            "run the given runs in this many processes, one run per process, strategy and "
            "datamodel runs alike; each builds its own panels. A batch whose runs depend on one "
            "another is refused: run the producer first"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "replace this run's record (its strategy's or its datamodel's) that already exists "
            "under this run and fingerprint, and the dataset it published, instead of refusing. "
            "Refusing is the default because a repeated run is far more often a retry than an "
            "intended overwrite. A live record is never replaced"
        ),
    )
    parser.add_argument(
        "--store-root",
        dest="store_root",
        type=Path,
        default=None,
        help=(
            "where run records are written: the `store_root` the result prints, which "
            "`read_strategy_table(store_root, ...)` takes back (default: `<project>/.vqapr`)"
        ),
    )
    parser.add_argument(
        "--no-account-positions",
        dest="no_account_positions",
        action="store_true",
        help=(
            "record only the `_ACCOUNT` row (cash and NAV) at each valuation instead of one row "
            "per held instrument; fills are recorded either way"
        ),
    )


_MAX_CAUSE_LINKS = 4
"""How many `__cause__` hops `observed` carries before it stops at `...`.

The chain is evidence, not a traceback. Two hops reach the original in every chain this package
raises today (`preflight` wraps one level), and the bound is what keeps `observed` from growing
with a user's OWN nesting -- a strategy is free to re-raise `from` as deep as it likes."""


def _chain(error: BaseException) -> str:
    """The refusal's own sentence followed by what raised it, innermost last.

    `raise ValueError(...) from error` is how this package names the step that failed while
    keeping the evidence, and dropping `__cause__` threw away the half that says WHY -- a reader
    was told "the initial payload cannot be staged" and never told that `load_payload` hit
    `EOFError: Ran out of input` (`docs/issues/archive/076`). Only `__cause__` is followed, never
    `__context__`: an explicit `from` is an author saying these two are one story, whereas an
    incidental exception caught during handling is not.
    """
    links = [f"{type(error).__name__}: {error}"]
    cause = error.__cause__
    while cause is not None and len(links) <= _MAX_CAUSE_LINKS:
        links.append(f"{type(cause).__name__}: {cause}")
        cause = cause.__cause__
    if cause is not None:
        links.append("...")
    return " <- ".join(links)


def preflight_refusal(phase: str, error: Exception, target: str) -> Failure:
    """A bare TypeError or ValueError from a framework invariant, given an envelope.

    ONE renderer for both verbs (`docs/issues/archive/076`). `check` caught these per phase and
    `run` called `preflight_run` outside its own `try`, so the same `ValueError` was a bounded
    refusal from one verb and `stage: "unhandled"` -- the framework broke -- from the other.

    The two codes are written literally rather than selected into a variable so the refusal-code
    inventory's constant folding can see them. Both carry the exception whole as `cause`; the
    `run`/`spec` phases are the declaration's fault (400), and a preflight invariant is classified
    by whose frame raised it (`status_of`: 500 framework, 502 user code), because a bare
    `ValueError` here may be either and the traceback is what says which (record `171`).
    """
    detail = _chain(error)
    fix = f"correct the run {target!r} so the {phase} phase completes, then check again"
    source = FailureSource(key_path=f"runs.{target}")
    if phase in ("run", "spec"):
        return Failure.bounded(
            "run.declaration_invalid",
            "the run must resolve against what the workspace has registered",
            status=Status.INVALID,
            observed=detail,
            fix=fix,
            source=source,
            cause=error,
        )
    return Failure.bounded(
        "preflight.refused",
        "every run precondition must hold before the run starts",
        status=status_of(error),
        observed=detail,
        fix=fix,
        source=source,
        cause=error,
    )


def refuse_a_path(target: str, *, verb: str) -> None:
    """A run is named by id. A YAML path here is the spec file record `148` retired.

    Refused by name rather than parsed: the spec (`datamodel:`, `evaluate_at`) is now a `runs:`
    entry with `datamodels:`, registered like every other run and executed by id.
    """
    if Path(target).suffix.lower() not in (".yaml", ".yml"):
        return
    raise InputError(
        VALUE_INVALID,
        requirement=f"`vqapr {verb}` takes the id of a registered run",
        observed=f"{target} is a file; a datamodel is run as a registered run since record 148",
        retry=(
            f"declare the datamodel under `runs:` with `datamodels:` (`vqapr new datamodel` emits "
            f"the block), `vqapr register {target}`, then `vqapr {verb} <run-id>`"
        ),
        source=FailureSource(file=target),
    )


def _run_one(target: str, args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    refuse_a_path(target, verb="run")

    workspace = Workspace.open(project_root)
    definition: RunDefinition = workspace.run_definition(target)
    # The ONE workspace this command opened goes to preflight and to the run
    # (`docs/issues/archive/070`): the judgments, the freeze and the roster read all see the same
    # document. The judgments are asked inside `preflight_run`, in the order `check` asks them, so
    # this verb and a Python caller refuse the same run for the same reasons (record `168`); a
    # refusal arrives as the `VqaprError` below deliberately lets through.
    try:
        frozen, resources = verify_run(workspace, definition).require_ready()
    except (TypeError, ValueError) as refused:
        # `check` renders exactly this as a bounded refusal; letting it escape here rendered the
        # SAME judgment as `stage: "unhandled"` (`docs/issues/archive/076`).
        #
        # These two types are the WHOLE escape set, not a guessed subset: every `raise` in
        # `flow/declaration/preflight.py` is a `TypeError`, a `ValueError`, or a `VqaprError`, and
        # user code reached through `load_strategy_model` comes back already bounded as
        # `component.load`.
        # `VqaprError` and `InputError` are therefore deliberately not caught -- both already
        # carry their own bounded body and their own truer stage.
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[preflight_refusal("preflight", refused, target)],
        ) from refused
    store_root = getattr(args, "store_root", None) or project_root / WORKSPACE_DIRECTORY
    replace = bool(getattr(args, "force", False))
    try:
        outcome = execute_run(
            project_root,
            frozen,
            store_root=store_root,
            replace_record=replace,
            record_account_positions=not getattr(args, "no_account_positions", False),
            workspace=workspace,
            resources=resources,
        )
    except (RunRecordLive, RunRecordExists, RunRecordConflict) as refused:
        raise _record_refusal(refused, frozen, target) from refused
    if frozen.datamodel is not None:
        return success(
            "run.complete",
            run_id=frozen.run_id,
            writes=frozen.writes,
            store_root=str(store_root),
            datamodels={
                component_id: _datamodel_envelope(record)
                for component_id, record in outcome.records.items()
            },
        )
    # One line per strategy the run was asked to run, completed or failed
    # (`docs/issues/archive/073`). A failed strategy's line is the same `simulation.*` payload a
    # refusal used to be the whole envelope of, so a reader who handled that shape handles this one,
    # per strategy.
    strategies: dict[str, dict[str, Any]] = {}
    for component_id, result in outcome.outcomes.items():
        if result.status == COMPLETED:
            strategies[component_id] = {
                "status": COMPLETED,
                **_strategy_envelope(store_root, frozen.run_id, result.record),
            }
        else:
            strategies[component_id] = {"status": FAILED, **dict(result.failure or {})}
    roster = _roster_envelope(outcome.roster)
    if not outcome.ok:
        return _strategy_failed(frozen, store_root, strategies, roster)
    return success(
        "run.complete",
        run_id=frozen.run_id,
        writes=frozen.writes,
        store_root=str(store_root),
        strategies=strategies,
        # What this run knew each instrument to be, or that it knew nothing. Reported on the
        # SUCCESS path on purpose: the run is legitimate, and the thing worth saying is what it
        # was computed against.
        roster=roster,
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    """One registered run, or several.

    A run holds one model since 2026-09-09 (`docs/design/two-clocks-and-the-wiring-table.md`
    §2.3), so `--jobs` spreads RUNS rather than the members of one. Several targets each get
    their own envelope under `runs`, keyed by run id, and one target keeps the envelope it has
    always had -- a caller that names one run sees no change.

    Each run is independent: one refusal is reported in that run's entry rather than ending the
    others, which is the same rule a run's members used to get (`docs/issues/archive/073`) at the
    level the unit moved to. The envelope says how many processes actually ran the batch
    (`jobs`), because a caller cannot see a pool that is not there
    (`docs/issues/report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs.md`).
    """
    targets = [str(name) for name in args.target]
    if len(targets) == 1:
        return _run_one(targets[0], args, project_root=project_root)
    jobs = int(getattr(args, "jobs", 1) or 1)
    store_root = getattr(args, "store_root", None) or project_root / WORKSPACE_DIRECTORY
    if jobs > 1:
        return _run_each_in_workers(targets, args, project_root=project_root, jobs=jobs)
    runs: dict[str, Any] = {}
    for target in targets:
        try:
            runs[target] = _run_one(target, args, project_root=project_root)
        except (VqaprError, InputError) as refused:
            runs[target] = _refusal_envelope(refused)
    return _runs_envelope(runs, store_root, jobs=1)


def _run_each_in_workers(
    targets: list[str], args: argparse.Namespace, *, project_root: Path, jobs: int
) -> dict[str, Any]:
    """The runs in `jobs` spawned processes, each freezing its own run (design §2.3).

    Both kinds of run go through the pool. Datamodel runs ran here sequentially from record
    `201` until the testbed measured `--jobs 16` at exactly one run at a time
    (`docs/issues/report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs.md`): the
    datamodel worker raises its refusal, and `in_workers` then ended the whole batch on the
    first one. `in_workers` now returns what each worker raised as that run's entry, so the
    reason is gone.

    Before anything is spawned the batch is judged as a batch: a run that reads what another
    run in it writes is refused whole (owner decision 2026-09-10), because a pool promises no
    order and the reader would see the dataset as it stood before, or race the writer. Datamodel
    runs are spawned first and strategy runs after, so a batch that passes that judgment still
    sees every dataset it could.
    """
    store_root = getattr(args, "store_root", None) or project_root / WORKSPACE_DIRECTORY
    for target in targets:
        refuse_a_path(target, verb="run")
    workspace = Workspace.open(project_root)
    # What each run reads, asked of its components once and handed to both doors below
    # (record `238`): the independence judgment and the bake each loaded every component again.
    reads = batch_reads(workspace, targets)
    require_independent_batch(workspace, targets, reads)
    definitions = {target: workspace.run_definition(target) for target in targets}
    replace = bool(getattr(args, "force", False))
    positions = not getattr(args, "no_account_positions", False)
    datamodel_runs = [t for t in targets if definitions[t].datamodel is not None]
    strategy_runs = [t for t in targets if definitions[t].datamodel is None]
    outcomes: dict[str, Any] = {}
    # The batch bakes each panel-grain dataset it reads once, every worker maps it, and the
    # files are gone when the batch returns (record `236`, `docs/issues/098`).
    with batch_cubes(workspace, targets, reads) as cubes:
        baked = "" if cubes is None else str(cubes)
        if datamodel_runs:
            outcomes.update(
                in_workers(
                    datamodel_runs,
                    run_registered_datamodel,
                    (replace, baked),
                    jobs=jobs,
                    store=Path(store_root),
                    root_path=project_root,
                )
            )
        if strategy_runs:
            outcomes.update(
                in_workers(
                    strategy_runs,
                    run_registered_strategy,
                    (replace, positions, baked),
                    jobs=jobs,
                    store=Path(store_root),
                    root_path=project_root,
                )
            )
    runs = {
        target: _worker_entry(target, definitions[target], outcomes[target], store_root)
        for target in targets
    }
    return _runs_envelope(runs, store_root, jobs=min(jobs, len(targets)))


def _worker_entry(
    run_id: str, definition: RunDefinition, outcome: Any, store_root: Path
) -> dict[str, Any]:
    """One run's entry of the batch envelope, from what its worker returned or raised.

    A datamodel worker returns its record and raises its refusal; a strategy worker returns an
    outcome that carries either (`docs/issues/archive/073`). A raised record exception -- a
    standing record, a live lock, a changed configuration -- is rendered through the same door
    `_run_one` uses, so a run refused in a worker reads exactly as one refused in this process.
    """
    if isinstance(outcome, Exception):
        return _refusal_envelope(_record_refusal(outcome, definition, run_id))
    if definition.datamodel is not None:
        return success(
            "run.complete",
            run_id=run_id,
            writes=definition.writes,
            store_root=str(store_root),
            datamodels={definition.datamodel.component_id: _datamodel_envelope(outcome)},
        )
    if outcome.status == COMPLETED:
        return {
            "ok": True,
            "run_id": run_id,
            "strategies": {
                outcome.component_id: {
                    "status": COMPLETED,
                    **_strategy_envelope(store_root, run_id, outcome.record),
                }
            },
        }
    return {
        "ok": False,
        "run_id": run_id,
        "strategies": {outcome.component_id: {"status": FAILED, **dict(outcome.failure or {})}},
    }


def _record_refusal(refused: Exception, frozen: object, target: str) -> Exception:
    """The bounded refusal for an exception the record store raised, or the exception itself.

    One door for the sequential path and the pool: `_run_one` raises what this returns, and a
    worker's raised exception is passed through it before rendering. `frozen` is anything that
    says `.datamodel` -- the frozen run in-process, the registered definition for a worker.
    """
    if isinstance(refused, RunRecordLive):
        return _held_record(refused)
    if isinstance(refused, RunRecordExists):
        return _standing_record(refused, frozen, target)
    if isinstance(refused, RunRecordConflict):
        return InputError(
            VALUE_INVALID,
            requirement="a run id's records all belong to one configuration",
            observed=str(refused),
            retry=(
                f"vqapr rm run {refused.run_id} to clear the old records, or register the "
                "changed run under a new id"
            ),
        )
    return refused


def _refusal_envelope(refused: Exception) -> dict[str, Any]:
    """One run's refusal as its entry, so the other runs in the batch still report.

    The same rendering `main` gives a refusal that ends a single run: the bounded body when the
    exception has one, `unhandled` with the whole traceback when it does not. It looked for an
    `as_envelope` method nothing defines and so rendered every entry as a bare `error` string
    until the batch path was exercised for real.
    """
    return failure(refused, stage=Stage.RUN)


def _runs_envelope(runs: dict[str, Any], store_root: Path, *, jobs: int) -> dict[str, Any]:
    """The batch envelope: every run's entry, and the number of processes that ran them."""
    ok = all(entry.get("ok", True) for entry in runs.values())
    envelope = success("run.complete", store_root=str(store_root), jobs=jobs, runs=runs)
    envelope["ok"] = ok
    return envelope


def _strategy_failed(
    frozen: Any, store_root: Path, strategies: dict[str, dict[str, Any]], roster: dict[str, Any]
) -> dict[str, Any]:
    """The envelope of a run in which at least one strategy's flow ended in a refusal.

    `ok: false` because not everything that was asked for was done, and the SAME `strategies`
    map as the success path, so the strategies that completed are named beside the one that did
    not -- the payload that filed `073` had `failures: []` and no word about seven finished
    records. `failures` is every failed strategy's entries, each stamped with its `strategy`, so
    a reader following the skill's rule (read `fix` first) still can; the per-strategy block
    holds the full replay coordinates (`at`, `retry_precondition`) for each.
    """
    failed = {name: block for name, block in strategies.items() if block["status"] == FAILED}
    return {
        "ok": False,
        "stage": "run.strategy_failed",
        "mutation": any(bool(block.get("mutation")) for block in failed.values()),
        "retry_precondition": None,
        "correlation_id": frozen.identity,
        "failures": [
            {**entry, "strategy": name}
            for name, block in failed.items()
            for entry in block.get("failures") or ()
        ],
        "error": (
            f"{len(failed)} of {len(strategies)} strategies failed: {', '.join(failed)}; "
            f"the other {len(strategies) - len(failed)} completed and their records stand"
        ),
        "run_id": frozen.run_id,
        "store_root": str(store_root),
        "strategies": strategies,
        "roster": roster,
    }


def _datamodel_envelope(record: Any) -> dict[str, Any]:
    """One datamodel's line of the success envelope, read from its record (record `148`)."""
    period = record.get("period") or {}
    return {
        "record": str(record.get("datamodel_ref")),
        "fingerprint": record.get("fingerprint"),
        "dataset_id": record.get("dataset_id"),
        "rows": record.get("rows"),
        "sessions": period.get("occurrences"),
    }


def _strategy_envelope(store_root: Path, run_id: str, record: Any) -> dict[str, Any]:
    """One strategy's line of the success envelope, read from its record.

    From the record rather than the in-process result, so a strategy run in a worker process
    (`--jobs`) reports exactly as one run here: the record is the one thing both have.
    """
    account = record.get("account") or {}
    period = record.get("period") or {}
    strategy_ref = str(record.get("strategy_ref"))
    return {
        "record": strategy_ref,
        "fingerprint": record.get("fingerprint"),
        "occurrences": period.get("occurrences"),
        "account_version": account.get("version"),
        "tables": sorted(record.get("tables") or {}),
        # What the orders did, not only that they were placed. `ok: true` means the simulation
        # executed; it does not mean the book that was declared is the book that was held, and
        # those differed by nine percent of NAV in the run that filed `docs/issues/archive/039`.
        # Streamed, a batch at a time (record `254`): the whole table as dicts was the peak.
        "fills": fill_summary(read_typed_table(store_root, run_id, FILL_TABLE, strategy_ref)),
        "contract": record.get("contract"),
        # Seconds by phase (`docs/issues/archive/068`), so "my strategy is 5% of the wall clock and
        # the snapshot is half of it" is read off the result rather than off a profiler.
        "timing": record.get("timing"),
    }


def _standing_record(existing: RunRecordExists, frozen: object, target: str) -> VqaprError:
    """The refusal for a record that already stands under this run and fingerprint.

    Running the same model again under the same fingerprint is a retry or an overwrite, and the
    reader says which in one flag (`--force`). Letting the bare `FileExistsError` escape rendered
    it as `stage: "unhandled"`, which says the framework broke; rendering it as a 400 said the
    ARGUMENT was wrong, and its `fix` said "edit the strategy" to a run that declared a datamodel
    (`docs/issues/090`). It is a 409 at stage `record`, beside `record.live`: what the store
    already holds disagrees with a write, and the model's kind is the run's own to say. No
    `cause`: the OS-level `FileExistsError` is how the record was found standing, not something
    a reader needs a traceback of.
    """
    kind = "datamodel" if getattr(frozen, "datamodel", None) is not None else "strategy"
    return VqaprError(
        stage=Stage.RECORD,
        failures=[
            Failure.bounded(
                "record.exists",
                f"a {kind} record is written once per run and fingerprint",
                status=Status.CONFLICT,
                observed=f"{existing.run_id!r} already has a record at {existing.directory}",
                fix=(
                    f"edit the {kind} (a new fingerprint records beside the old one), or replace "
                    f"this record and the dataset it published deliberately: "
                    f"vqapr run {target} --force"
                ),
            )
        ],
        mutation=False,
        retry_precondition=(
            f"change the {kind} so its fingerprint differs, or pass --force to replace the "
            "standing record, then retry"
        ),
    )


def _held_record(running: RunRecordLive) -> VqaprError:
    """The refusal for a record whose lock is still inside its heartbeat window.

    Status 423 at stage `record` (record `171`): another process holds it, and the submission is
    not what must change. It was an `InputError`, which told the reader their argument was wrong.

    **What this refusal may not say is that the holder is alive.** The lock proves only that it was
    touched within `LOCK_STALE_AFTER`, and the pid is copied out of the file rather than
    interrogated -- so a run killed seconds ago presents exactly like one that is executing
    (`docs/issues/archive/037`). `fix` names the self-healing wait FIRST, because it is the remedy
    that is correct under both readings and costs nothing.
    """
    claim = running.claim
    fix = (
        f"wait about {claim.releases_in:.0f}s: a live run refreshes that lock continuously, "
        f"and if its process is gone the lock is released automatically, after which "
        f"re-running this exact command reclaims the record. Do not use --force while the "
        f"holder may be live: against a run that is still writing it destroys that run's rows"
    )
    return VqaprError(
        stage=Stage.RECORD,
        failures=[
            Failure.bounded(
                "record.live",
                "a record must not already be held by a lock inside its heartbeat window",
                status=Status.LOCKED,
                observed=(
                    f"{running.run_id!r} holds a lock last refreshed {claim.age:.0f}s ago at "
                    f"{running.directory} (pid {claim.pid}, not interrogated)"
                ),
                fix=fix,
                source=FailureSource(file=str(running.directory)),
                cause=running,
            )
        ],
        retry_precondition=fix,
    )


def _roster_envelope(roster: object | None) -> dict[str, object]:
    """The roster clause of the success envelope, present whether or not one is registered.

    A mapping in every case because a reader testing `payload["roster"]` for absence should not
    have to distinguish "no roster" from "this version does not report one". `known` is the
    field that answers the question.

    Built from the roster the run READ (`RunResult.roster`), never from a second read after the
    run (`docs/issues/archive/070`): what this reports is what the fills were classified by, and the
    `stale` branch that described a re-read failing after a long run describes a state that can
    no longer occur.
    """
    from vqapr.public import roster_report

    report = roster_report(roster)  # type: ignore[arg-type]
    if report is None:
        return {
            "known": False,
            "note": (
                "no instrument roster is registered, so every fill records kind: None and "
                "the report's cost by kind shows one 'unknown' bucket; register one with "
                "`vqapr register <instruments>.yaml`"
            ),
        }
    return {"known": True, **report}
