"""`vqapr rm run|strategy|<declaration kind> <id>` — remove a record, or withdraw a registration.

The deleting machinery existed before the verb: `RunRecordWriter` protects a live record with a
lock it refreshes as it writes, and only a claim that has aged out is ever cleared; the workspace
refuses to withdraw a registration that something live still names. Architecture §17.5 and the
testbed's C4/E1 measured the same gap from both sides -- *"there is no command that deletes a
run"*, and `Workspace.remove()` had no caller. Record `139` is the verb.

**A record and a registration are different things.** `rm run <id>` and `rm strategy
<run>/<id>@<fp8>` remove what a run WROTE; `rm run-definition <id>` withdraws the registered run;
the other declaration kinds withdraw theirs. Neither reaches across: withdrawing a registration
leaves its records readable (a finished run pins what it used inside its own record), and removing
records leaves the run registered to run again.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.show import resolve_strategy
from vqapr.flow.run_records import (
    RunRecordLive,
    remove_run_record,
    remove_strategy_record,
    run_ids,
)
from vqapr.inputs import VALUE_INVALID, InputError
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

RECORD_KINDS = ("run", "strategy")
DECLARATION_KINDS = {
    "component": "component",
    "agenda": "agenda",
    "strategy-config": "strategy_config",
    "valuation-config": "valuation_config",
    "monitoring-policy": "monitoring_policy",
    "run-definition": "run",
}
KINDS = (*RECORD_KINDS, *DECLARATION_KINDS)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=KINDS, help="what to remove")
    parser.add_argument(
        "identifier",
        help=(
            "run: a run id (its records); strategy: `<run-id>/<strategy-id>@<fp8>`; "
            "run-definition and the other declaration kinds: the registered id"
        ),
    )
    parser.add_argument(
        "--keep-latest",
        dest="keep_latest",
        action="store_true",
        help="`run` only: keep the newest record of each strategy; remove older fingerprints",
    )
    parser.add_argument(
        "--store-root",
        dest="store_root",
        type=Path,
        default=None,
        help="where run records live, when they were written outside the workspace directory",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    root = getattr(args, "store_root", None) or project_root / WORKSPACE_DIRECTORY
    kind = str(args.kind)
    identifier = str(args.identifier)
    try:
        if kind == "run":
            if identifier not in run_ids(root):
                raise InputError(
                    VALUE_INVALID,
                    requirement="rm run requires the id of a run this store holds records for",
                    observed=f"{identifier!r}; known: {', '.join(run_ids(root)) or '(none)'}",
                    retry="run `vqapr list runs` to see what this store holds",
                )
            removed = remove_run_record(
                root, identifier, keep_latest=bool(getattr(args, "keep_latest", False))
            )
            return success("record.removed", kind=kind, run_id=identifier, removed=list(removed))
        if kind == "strategy":
            run_id, strategy_ref = resolve_strategy(root, identifier)
            remove_strategy_record(root, run_id, strategy_ref)
            return success("record.removed", kind=kind, run_id=run_id, removed=[strategy_ref])
    except RunRecordLive as live:
        # A lock inside its heartbeat window may belong to a run that is writing this very
        # record. Waiting costs at most the window; deleting under a live writer destroys rows.
        raise InputError(
            VALUE_INVALID,
            requirement="a record is removed only once no writer may still hold it",
            observed=(
                f"{live.run_id!r} holds a lock last refreshed {live.claim.age:.0f}s ago "
                f"(pid {live.claim.pid}, not interrogated)"
            ),
            retry=(
                f"wait about {live.claim.releases_in:.0f}s for the lock to age out if its "
                "writer is gone, then retry"
            ),
        ) from live
    workspace_kind = DECLARATION_KINDS[kind]
    removed = Workspace.open(project_root).remove(workspace_kind, identifier)
    return success("workspace.removed", kind=kind, identifier=identifier, removed=bool(removed))
