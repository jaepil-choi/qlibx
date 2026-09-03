"""`vqapr run <run-id>` — freeze a registered run, preflight it, and execute its strategies.

A run is a registered declaration since record `139` (`runs:` in a declaration document, design
§4.1): the reusable unit is a name in the workspace, not a file. This verb looks the run up,
makes the same judgments `vqapr check` makes, freezes it once, and runs each strategy it names --
or those named with `--strategy` -- each in its own flow with its own account and its own record.

The one file this verb still takes is a MATERIALIZATION spec (`datamodel:`), because a
materialization registers a dataset rather than writing a run record and has no run to register.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from vqapr.analysis.execution import fill_summary
from vqapr.cli.envelope import success

# `register` owns the CLI spelling of a component kind and imports nothing from this module, so
# naming it here adds no cycle. The judgments take it as a callable rather than importing it
# themselves, which is what keeps `flow/` free of `cli`.
from vqapr.cli.register import cli_kind
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    VqaprError,
)
from vqapr.flow.judgments import judgments, materialization_judgments
from vqapr.flow.reporting import FILL_TABLE
from vqapr.flow.run_records import (
    RunRecordConflict,
    RunRecordExists,
    RunRecordLive,
    read_typed_table,
)
from vqapr.flow.run_spec import MATERIALIZATION
from vqapr.inputs import INCOMPLETE, VALUE_INVALID, InputError, read_yaml_mapping
from vqapr.public import RunDefinition, Workspace, preflight_run
from vqapr.public import run as execute_run
from vqapr.workspace import WORKSPACE_DIRECTORY

SPEC_SUFFIXES = (".yaml", ".yml")


def is_spec_path(target: str) -> bool:
    """Whether a `run`/`check` argument names a file rather than a registered run.

    A registered run id is a bare identifier; a materialization spec is a YAML path. Decided by
    the suffix so that a run id which happens to match a file in the working directory is still
    a run id.
    """
    return Path(target).suffix.lower() in SPEC_SUFFIXES


def _timestamp(value: object, *, name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif not isinstance(value, str):
        raise InputError(
            VALUE_INVALID,
            requirement=f"{name} must be an ISO-8601 timezone-aware datetime",
            observed=f"{type(value).__name__}: {value!r}",
            retry=f"write {name} with an explicit UTC offset, then retry",
            examples=["2024-01-02T00:00:00+09:00"],
        )
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise InputError(
                VALUE_INVALID,
                requirement=f"{name} must be an ISO-8601 timezone-aware datetime",
                observed=f"{name}={value!r}",
                retry=f"write {name} with an explicit UTC offset, then retry",
                examples=["2024-01-02T00:00:00+09:00"],
            ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(
            VALUE_INVALID,
            requirement=(
                f"{name} must include a UTC offset; a date or naive datetime does not identify "
                "one instant"
            ),
            observed=f"{name}={parsed.isoformat()!r}",
            retry=f"write {name} with an explicit UTC offset, then retry",
            examples=["2024-01-02T00:00:00+09:00"],
        )
    return parsed


def require_materialization_spec(document: dict[str, Any], path: Path) -> None:
    """A YAML file handed to `run` or `check` must be a materialization spec, and complete.

    A file declaring `strategy:` is the run spec of before record `139`. It is refused by name,
    pointing at the declaration section that replaced it, rather than parsed as if the schema had
    not moved.
    """
    if "strategy" in document and MATERIALIZATION in document:
        raise InputError(
            VALUE_INVALID,
            requirement=(
                f"a materialization spec declares `{MATERIALIZATION}:` alone; a simulation is a "
                "registered run"
            ),
            observed=f"{path} declares both `{MATERIALIZATION}:` and `strategy:`",
            retry=(
                f"keep `{MATERIALIZATION}:` and drop `strategy:`; a run is declared under `runs:`"
            ),
            source=FailureSource(file=str(path), key_path="strategy"),
        )
    if "strategy" in document and MATERIALIZATION not in document:
        raise InputError(
            VALUE_INVALID,
            requirement=(
                "a simulation is a registered run: declare it under `runs:` in a declaration "
                "document, register it, and run it by id"
            ),
            observed=f"{path} declares `strategy:`, the run-spec shape retired by record 139",
            retry=(
                "write the run as a `runs:` section (`vqapr new run --out runs.yaml`), "
                "`vqapr register runs.yaml`, then `vqapr run <run-id>`"
            ),
            source=FailureSource(file=str(path), key_path="strategy"),
        )
    if MATERIALIZATION not in document:
        raise InputError(
            INCOMPLETE,
            requirement=f"a materialization spec declares `{MATERIALIZATION}:`",
            observed=f"{path} declares: {', '.join(sorted(document)) or '(nothing)'}",
            retry=f"add `{MATERIALIZATION}: <component id>` to the spec, then retry",
            source=FailureSource(file=str(path), key_path=MATERIALIZATION),
        )
    required = ("instruments", "output", "evaluate_at")
    missing = [key for key in required if key not in document]
    if missing:
        raise InputError(
            INCOMPLETE,
            requirement=f"a materialization spec must declare: {MATERIALIZATION}, "
            + ", ".join(required),
            observed=f"missing {len(missing)}: {', '.join(missing)}",
            retry="add the missing keys, then retry",
            examples=missing,
            source=FailureSource(file=str(path), key_path=missing[0]),
        )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        help=(
            "the id of a registered run (`vqapr list runs`), or the path of a materialization "
            "spec YAML declaring `datamodel:`"
        ),
    )
    parser.add_argument(
        "--strategy",
        dest="strategies",
        action="append",
        default=None,
        help="run only this strategy of the run (repeatable); default: every strategy it names",
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
        help="where run records are written (default: the workspace directory)",
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


def _materialize(
    args: argparse.Namespace, document: dict[str, Any], spec_path: Path, project_root: Path
) -> dict[str, Any]:
    """Run a registered DataModel, through the verb that already exists.

    A DataModel could be scaffolded, registered and described, and nothing would ever run it:
    `flow/materialize.py` held a real entry point no CLI command called. It is reached here rather
    than through a `materialize` verb of its own, because registration is already symmetric.

    `--strategy`, `--jobs` and `--force` are refused rather than ignored. All are defined in terms
    of a run record, and a materialization writes none: it registers a dataset.
    """
    from vqapr.public import MaterializationSpec, materialize

    for flag, value in (
        ("--strategy", getattr(args, "strategies", None)),
        ("--force", getattr(args, "force", False)),
        ("--jobs", (getattr(args, "jobs", 1) or 1) > 1),
    ):
        if value:
            raise InputError(
                VALUE_INVALID,
                requirement=f"{flag} applies to a registered run, which writes run records",
                observed=f"this spec declares `{MATERIALIZATION}:`, so it registers a dataset",
                retry=f"drop {flag}; to replace the output, remove its dataset registration first",
            )

    output = document["output"]
    if not isinstance(output, dict):
        raise InputError(
            VALUE_INVALID,
            requirement="`output:` must be a mapping declaring dataset_id and value_fields",
            observed=f"found {type(output).__name__}",
            retry="write `output:` with `dataset_id:` and `value_fields:` beneath it",
            source=FailureSource(file=str(spec_path), key_path="output"),
        )
    missing = [key for key in ("dataset_id", "value_fields") if key not in output]
    if missing:
        raise InputError(
            INCOMPLETE,
            requirement="`output:` must declare dataset_id and value_fields",
            observed=f"missing {', '.join(missing)}",
            retry="add the missing keys under `output:`, then retry",
            examples=missing,
            source=FailureSource(file=str(spec_path), key_path=f"output.{missing[0]}"),
        )
    judged = materialization_judgments(
        document, Workspace.open(project_root), project_root, kind_spelling=cli_kind
    )
    if judged:
        raise VqaprError(stage=JUDGMENT_STAGE, family=FailureFamily.INTENT, failures=judged)

    try:
        spec = MaterializationSpec.of(
            str(output["dataset_id"]),
            value_fields=[str(field) for field in output["value_fields"]],
        )
    except (TypeError, ValueError) as invalid:
        raise InputError(
            VALUE_INVALID,
            requirement="`output:` must describe a materialization this package can write",
            observed=str(invalid),
            retry="correct `output:`, then retry",
            source=FailureSource(file=str(spec_path), key_path="output"),
        ) from invalid

    times = tuple(
        _timestamp(value, name=f"evaluate_at[{index}]")
        for index, value in enumerate(document["evaluate_at"] or ())
    )
    result = materialize(
        project_root,
        str(document[MATERIALIZATION]),
        spec,
        evaluation_times=[moment for moment in times if moment is not None],
        instruments=[str(name) for name in document["instruments"]],
    )
    return success(
        "materialize.complete",
        dataset_id=str(spec.dataset_id),
        output_path=str(result.output_path),
        lineage_path=str(result.lineage_path),
        evaluations=len(result.invocations),
        rows_total=sum(invocation.row_count for invocation in result.invocations),
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    target = str(args.target)
    if is_spec_path(target):
        spec_path = Path(target)
        document = read_yaml_mapping(spec_path, what="a materialization spec")
        require_materialization_spec(document, spec_path)
        return _materialize(args, document, spec_path, project_root)

    workspace = Workspace.open(project_root)
    definition: RunDefinition = workspace.run_definition(target)
    # Before the freeze, and in the order `check` asks them: a run that cannot pass these has
    # nothing to gain from being frozen first.
    _refuse_if_judged(*judgments(definition, workspace), definition.run_id)
    selected = tuple(getattr(args, "strategies", None) or ())
    for name in selected:
        definition.member(name)  # KeyError names the models the run does hold
    frozen = preflight_run(project_root, definition)
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
        roster=_roster_envelope(project_root),
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


def _roster_envelope(project_root: Path) -> dict[str, object]:
    """The roster clause of the success envelope, present whether or not one is registered.

    A mapping in every case, including failure, because a reader testing `payload["roster"]` for
    absence should not have to distinguish "no roster" from "this version does not report one".
    `known` is the field that answers the question.

    **This runs after the run completed and its records are on disk.** `registered_roster` refuses
    a registered-but-unreadable roster, which is right at run START; here it would be wrong: the
    workspace and the tables can become unreadable in the minutes a real run takes, and letting
    that refusal escape would report exit 1 for a run whose records exist.
    """
    from vqapr.domain.errors import VqaprError
    from vqapr.public import roster_report

    try:
        report = roster_report(_registered_roster_for_report(project_root))
    except VqaprError as vanished:
        # `known: True`, because the run DID know: `registered_roster` refuses an unreadable
        # roster at run start, so any run reaching this envelope read its roster successfully.
        # `stale` is the fact that actually differs: the counts could not be re-read.
        return {
            "known": True,
            "stale": True,
            "note": (
                "this run read a registered roster, and the roster -- or the workspace recording "
                "it -- became unreadable before the envelope was written, so the per-category "
                "counts could not be re-read; the "
                f"frozen record states what the run actually used. {vanished}"
            ),
        }
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


def _registered_roster_for_report(project_root: Path) -> object | None:
    from vqapr.flow.roster import registered_roster

    return registered_roster(project_root)
