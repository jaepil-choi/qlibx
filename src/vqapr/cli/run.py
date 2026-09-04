"""`vqapr run <run-id>` — freeze a registered run, preflight it, and execute its strategies.

A run is a registered declaration since record `139` (`runs:` in a declaration document, design
§4.1): the reusable unit is a name in the workspace, not a file. This verb looks the run up,
makes the same judgments `vqapr check` makes, freezes it once, and runs each strategy it names --
or those named with `--strategy` -- each in its own flow with its own account and its own record.
A datamodel run (record `148`) is the same verb: its members write datasets instead of tables.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.analysis.execution import fill_summary
from vqapr.cli.envelope import success

# `register` owns the CLI spelling of a component kind and imports nothing from this module, so
# naming it here adds no cycle. The judgments take it as a callable rather than importing it
# themselves, which is what keeps `flow/` free of `cli`.
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    VqaprError,
)
from vqapr.flow.judgments import judgments
from vqapr.flow.reporting import FILL_TABLE
from vqapr.flow.run_records import (
    RunRecordConflict,
    RunRecordExists,
    RunRecordLive,
    read_typed_table,
)
from vqapr.inputs import VALUE_INVALID, InputError
from vqapr.public import RunDefinition, Workspace, preflight_run
from vqapr.public import run as execute_run
from vqapr.workspace import WORKSPACE_DIRECTORY


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        help="the id of a registered run (`vqapr list runs`)",
    )
    parser.add_argument(
        "--strategy",
        dest="strategies",
        action="append",
        default=None,
        help="run only this model of the run (repeatable); default: every model it names",
    )
    parser.add_argument(
        "--jobs",
        dest="jobs",
        type=int,
        default=1,
        help="run the strategies in this many processes; each builds its own panels",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "replace a strategy record that already exists under this run and fingerprint "
            "instead of refusing. Refusing is the default because a repeated run is far more "
            "often a retry than an intended overwrite. A live record is never replaced"
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


JUDGMENT_STAGE = "run.judgments"


def _refuse_if_judged(failures: list[Failure], blocked: list[dict[str, str]], run_id: str) -> None:
    """Refuse the run when a judgment refused, or when one could not answer.

    `check` asked these questions and `run` did not, so a run with a real look-ahead -- a fill at
    15:30 with decisions at or after it -- was refused by one verb and executed by the other, and
    wrote a permanent record nothing marked (`docs/issues/015`). Refusing outright, with no flag
    to bypass, is the decision recorded in `docs/implementations/087`.

    **Blocked counts as refused.** A judgment that could not answer is not a judgment that passed;
    letting it through would let a run nothing was proven about run to completion.

    The refusals keep the codes `check` publishes: a green `run` means what a green `check` means.
    """
    if not failures and not blocked:
        return
    reported = list(failures)
    for entry in blocked:
        reported.append(
            Failure.bounded(
                "run.check.judgment_blocked",
                "every judgment must be answerable before the run starts",
                observed=(
                    f"the {entry.get('check')} judgment could not answer: {entry.get('blocked_by')}"
                ),
                fix=(
                    f"run `vqapr check {run_id}` to see the full report, then fix what stopped "
                    "the judgment from answering"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
                source=FailureSource(key_path=f"runs.{run_id}"),
            )
        )
    raise VqaprError(
        stage=JUDGMENT_STAGE,
        family=FailureFamily.INTENT,
        failures=reported,
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


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    target = str(args.target)
    refuse_a_path(target, verb="run")

    workspace = Workspace.open(project_root)
    definition: RunDefinition = workspace.run_definition(target)
    # Before the freeze, and in the order `check` asks them: a run that cannot pass these has
    # nothing to gain from being frozen first.
    _refuse_if_judged(*judgments(definition, workspace), definition.run_id)
    selected = tuple(getattr(args, "strategies", None) or ())
    for name in selected:
        definition.member(name)  # KeyError names the models the run does hold
    # The ONE workspace this command opened goes to preflight and to the run (`docs/issues/070`):
    # the judgments above, the freeze and the roster read all see the same document.
    frozen = preflight_run(workspace, definition)
    store_root = getattr(args, "store_root", None) or project_root / WORKSPACE_DIRECTORY
    replace = bool(getattr(args, "force", False))
    try:
        outcome = execute_run(
            project_root,
            frozen,
            store_root=store_root,
            strategies=selected or None,
            jobs=int(getattr(args, "jobs", 1) or 1),
            replace_record=replace,
            record_account_positions=not getattr(args, "no_account_positions", False),
            workspace=workspace,
        )
    except RunRecordLive as running:
        raise _held_record(running) from running
    except RunRecordExists as existing:
        # Running a strategy again under the same fingerprint is a retry or an overwrite, and
        # the reader says which in one flag. Letting the bare FileExistsError escape renders it
        # as `stage: "unhandled"`, which says the framework broke.
        raise InputError(
            VALUE_INVALID,
            requirement="a strategy record is written once per run and fingerprint",
            observed=f"{existing.run_id!r} already has a record at {existing.directory}",
            retry=(
                f"edit the strategy (a new fingerprint records beside the old one), or replace "
                f"this record deliberately: vqapr run {target} --force"
            ),
        ) from existing
    except RunRecordConflict as changed:
        raise InputError(
            VALUE_INVALID,
            requirement="a run id's records all belong to one configuration",
            observed=str(changed),
            retry=(
                f"vqapr rm run {changed.run_id} to clear the old records, or register the "
                "changed run under a new id"
            ),
        ) from changed
    if frozen.datamodels:
        return success(
            "run.complete",
            run_id=frozen.run_id,
            store_root=str(store_root),
            datamodels={
                component_id: _datamodel_envelope(record)
                for component_id, record in outcome.records.items()
            },
        )
    strategies = {
        component_id: _strategy_envelope(store_root, frozen.run_id, record)
        for component_id, record in outcome.records.items()
    }
    return success(
        "run.complete",
        run_id=frozen.run_id,
        store_root=str(store_root),
        strategies=strategies,
        # What this run knew each instrument to be, or that it knew nothing. Reported on the
        # SUCCESS path on purpose: the run is legitimate, and the thing worth saying is what it
        # was computed against.
        roster=_roster_envelope(outcome.roster),
    )


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
        # those differed by nine percent of NAV in the run that filed `docs/issues/039`.
        "fills": fill_summary(
            tuple(read_typed_table(store_root, run_id, FILL_TABLE, strategy_ref))
        ),
        "contract": record.get("contract"),
        # Seconds by phase (`docs/issues/068`), so "my strategy is 5% of the wall clock and
        # the snapshot is half of it" is read off the result rather than off a profiler.
        "timing": record.get("timing"),
    }


def _held_record(running: RunRecordLive) -> InputError:
    """The refusal for a record whose lock is still inside its heartbeat window.

    **What this refusal may not say is that the holder is alive.** The lock proves only that it
    was touched within `LOCK_STALE_AFTER`, and the pid is copied out of the file rather than
    interrogated -- so a run killed seconds ago presents exactly like one that is executing
    (`docs/issues/037`). `fix` names the self-healing wait FIRST, because it is the remedy that is
    correct under both readings and costs nothing.
    """
    claim = running.claim
    return InputError(
        VALUE_INVALID,
        requirement="a record must not already be held by a lock inside its heartbeat window",
        observed=(
            f"{running.run_id!r} holds a lock last refreshed {claim.age:.0f}s ago at "
            f"{running.directory} (pid {claim.pid}, not interrogated)"
        ),
        retry=(
            f"wait about {claim.releases_in:.0f}s: a live run refreshes that lock continuously, "
            f"and if its process is gone the lock is released automatically, after which "
            f"re-running this exact command reclaims the record. Do not use --force while the "
            f"holder may be live: against a run that is still writing it destroys that run's rows"
        ),
    )


def _roster_envelope(roster: object | None) -> dict[str, object]:
    """The roster clause of the success envelope, present whether or not one is registered.

    A mapping in every case because a reader testing `payload["roster"]` for absence should not
    have to distinguish "no roster" from "this version does not report one". `known` is the
    field that answers the question.

    Built from the roster the run READ (`RunResult.roster`), never from a second read after the
    run (`docs/issues/070`): what this reports is what the fills were classified by, and the
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
                "cost_by_kind() collapses to one unlabelled bucket; register one with "
                "`vqapr register <instruments>.yaml`"
            ),
        }
    return {"known": True, **report}
