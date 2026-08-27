"""`vqapr run <spec.yaml>` — freeze a declaration and execute it.

The spec is a projection of `RunDefinition`, not a second declaration language. Anything the
framework can derive — requirements, datasets, sources — is deliberately absent: restating it
here would let the file drift from the registered components, and preflight rejects that drift.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.inputs import INCOMPLETE, VALUE_INVALID, InputError, read_yaml_mapping
from vqapr.flow.run_records import RunRecordExists, RunRecordLive
from vqapr.flow.store_spec import StoreSpec
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ConstraintSet,
    MonitoringPolicy,
    OperationRole,
    RunDefinition,
    StrategyConfig,
    ValuationConfig,
    Workspace,
    preflight_run,
)
from vqapr.public import run as execute_run
from vqapr.workspace import WORKSPACE_DIRECTORY

_REQUIRED = (
    "strategy",
    "valuation",
    "instruments",
    "start",
    "end",
    "exchange",
    "execution_input",
    "initial_account",
)
"""Every key this command cannot execute without.

`RunDefinition` permits `start`, `end`, `exchange`, `execution_input` and the initial account to be
absent, because a definition is also built in-process by callers who supply them another way. This
command always continues into `preflight_run` and then `run`, and both refuse without them. Listing
only three keys here meant the other five surfaced from deep inside the framework as
`stage: "unhandled"` — which tells an agent the framework broke, when the truth is its spec was
incomplete. Checking them here names all of the missing keys at once instead.
"""


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


def _strategy(document: dict[str, Any], workspace: Workspace) -> StrategyConfig:
    declared = document["strategy"]
    if not isinstance(declared, dict):
        raise TypeError("strategy must be a mapping")
    component = workspace.component(str(declared["component"]))
    return StrategyConfig(
        component=component,
        agenda_id=str(declared["agenda_id"]),
        agenda_role=OperationRole.STRATEGY_CALLBACK,
    )


def _valuation(document: dict[str, Any]) -> ValuationConfig:
    """Build the valuation declaration.

    Valuation declares no mark source. The book is valued from the prices the venue published as
    executable at the execution instant, which the run already reads to fill against.
    """
    declared = document["valuation"]
    if not isinstance(declared, dict):
        raise TypeError("valuation must be a mapping")
    if "mark" in declared:
        raise ValueError(
            "valuation.mark no longer exists: the book is valued from the execution table, "
            "so remove the mark declaration"
        )
    return ValuationConfig(
        agenda_id=str(declared["agenda_id"]),
        agenda_role=OperationRole.VALUATION,
    )


def _constraints(document: dict[str, Any], workspace: Workspace) -> ConstraintSet:
    declared = document.get("constraints") or ()
    return ConstraintSet(tuple(workspace.component(str(name)) for name in declared))


def _account(document: dict[str, Any]) -> tuple[AccountSnapshot | None, AccountMode | None]:
    declared = document.get("initial_account")
    if declared is None:
        return None, None
    if not isinstance(declared, dict):
        raise TypeError("initial_account must be a mapping")
    positions = {
        str(name): Decimal(str(quantity))
        for name, quantity in (declared.get("positions") or {}).items()
    }
    snapshot = AccountSnapshot(
        version=int(declared.get("version", 0)),
        cash=Decimal(str(declared["cash"])),
        positions=positions,
    )
    return snapshot, AccountMode[str(declared["mode"]).upper()]


def require_declared_keys(document: dict[str, Any]) -> None:
    """Reject an incomplete spec before anything is opened.

    This reads only the user's own file, so it runs first. Checking it after `Workspace.open`
    meant an incomplete spec in an uninitialised directory reported the missing workspace and
    said nothing about the spec, sending the user to fix the wrong file.
    """
    missing = [key for key in _REQUIRED if key not in document]
    if missing:
        raise InputError(
            INCOMPLETE,
            requirement=f"a run spec must declare: {', '.join(_REQUIRED)}",
            observed=f"missing {len(missing)} of {len(_REQUIRED)}: {', '.join(missing)}",
            retry="add the missing keys, then retry",
            examples=missing,
        )


def definition_from_document(document: dict[str, Any], workspace: Workspace) -> RunDefinition:
    """Build a `RunDefinition` without re-implementing its invariants.

    Pairing rules (exchange with execution input, start with end, snapshot with mode) are
    enforced by `RunDefinition.__post_init__`, so this function only shapes values.
    """
    require_declared_keys(document)
    exchange = document.get("exchange")
    snapshot, mode = _account(document)
    return RunDefinition(
        strategy=_strategy(document, workspace),
        valuation=_valuation(document),
        constraints=_constraints(document, workspace),
        monitoring=(
            MonitoringPolicy(
                agenda_id=str(document["monitoring"]["agenda_id"]),
                agenda_role=OperationRole.MONITORING,
            )
            if document.get("monitoring")
            else None
        ),
        exchange=workspace.component(str(exchange)) if exchange else None,
        execution_input_id=(
            str(document["execution_input"]) if document.get("execution_input") else None
        ),
        start=_timestamp(document.get("start"), name="start"),
        end=_timestamp(document.get("end"), name="end"),
        initial_account_snapshot=snapshot,
        initial_account_mode=mode,
        initial_model_memory=document.get("initial_model_memory"),
        instruments=tuple(str(name) for name in document["instruments"]),
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        # Says what the flag DOES, which is not what it said. It replaces this run's frozen
        # record under the same --run-id; it does not touch a published dataset or a registration.
        # The two dataset-exists refusals were corrected to stop naming this flag, and leaving the
        # claim alive in --help would send an agent here to read the version that was disproved.
        help=(
            "replace this run id's existing run record instead of refusing. Refusing is the "
            "default because a repeated run under the same --run-id is far more often a retry "
            "than an intended overwrite. This does not remove a published dataset"
        ),
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="identity for this run's frozen record (defaults to the spec's filename)",
    )
    parser.add_argument(
        "spec",
        type=Path,
        help="path to the run spec YAML (write one with `vqapr new run-spec --out`)",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    spec_path = Path(args.spec)
    document = read_yaml_mapping(spec_path, what="a run spec")
    require_declared_keys(document)
    workspace = Workspace.open(project_root)
    # One parser owns the `store` keys, and this is its only reader in the CLI. A second place
    # reading `document["store"]` directly is how `root` becomes optional in one path and required
    # in another, with neither wrong on its own.
    store = StoreSpec.of(document.get("store"), base=spec_path.parent)
    frozen = preflight_run(project_root, definition_from_document(document, workspace))
    run_id = getattr(args, "run_id", None) or spec_path.stem
    try:
        result = execute_run(
            project_root,
            frozen,
            store_root=store.resolve(project_root, WORKSPACE_DIRECTORY),
            run_id=run_id,
            replace_record=bool(getattr(args, "force", False)),
        )
    except RunRecordLive as running:
        # A different remedy from RunRecordExists, and naming the wrong one here would be
        # destructive: `--force` against a live run destroys the rows it is still writing.
        raise InputError(
            VALUE_INVALID,
            requirement="a run id must not already be executing",
            observed=f"{run_id!r} is running now at {running.directory} (pid {running.holder})",
            retry=(
                "wait for that run to finish, or run with --run-id <new-id>. Do NOT use --force: "
                "it would destroy the rows that run is still writing"
            ),
        ) from running
    except RunRecordExists as existing:
        # Choosing a run id twice is a mistake the reader can fix in one flag. Letting the bare
        # FileExistsError escape renders it as `stage: "unhandled"`, which says the framework
        # broke rather than naming the id and the remedy.
        raise InputError(
            VALUE_INVALID,
            requirement="each run must have a run id no record has already been written under",
            observed=f"{run_id!r} already has a record at {existing.directory}",
            retry=(
                f"run with --run-id <new-id>, or replace the existing record deliberately: "
                f"vqapr run {spec_path} --force"
            ),
        ) from existing
    return success(
        "run.complete",
        occurrences=len(result.occurrences),
        # Two counters, reported as two fields. The run state advances on every publication,
        # including a valuation that records a mark without trading; the Account advances only
        # when a fill commits. Reporting the former under the latter's name made an independent
        # valuation clock look like it was moving the books.
        run_state_version=result.final_state.version,
        account_version=result.final_state.account.snapshot.version,
        store_root=str(store.resolve(project_root, WORKSPACE_DIRECTORY)),
        # No `publishes`-shaped field is reported here, and that is deliberate.
        #
        # `store.tables` parses, validates and resolves correctly, but nothing yet turns a
        # declared table into a registered dataset -- `publish_run_record` is the only function
        # that does, and this path does not call it. Echoing a `publishes` claim would be a
        # machine-readable claim that a dataset exists when `list datasets` shows none, and the
        # first reader of this envelope is an agent that would believe it.
        #
        # The batch's own precedent is `_contract_report`, which declines to report
        # weights/forms/records because inventing entries would report a promise nobody made. The
        # same rule applies to a promise the code has not yet kept: AC-P3's parsing half is
        # delivered and tested, its publication half is not, and the envelope says only what is
        # true today.
        tables_declared=list(store.tables),
    )
