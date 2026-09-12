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

**`rm run <id> --cascade` is the one gesture that says *remove all of it*** (owner ruling,
2026-09-05, `docs/issues/archive/081`: deletion must be easy). Records first -- the only step that
can refuse, on a live lock, and it refuses before anything is touched -- then the run definition,
then the materialized outputs its datamodels wrote, then the components it named. A dataset or a
component that another registered run still names is kept and reported as kept, with the run that
holds it. Nothing is rolled back on a failure part-way: deleted evidence cannot be restored, so the
payload names what went and what remains instead.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.show import resolve_member
from vqapr.domain.errors import VALUE_INVALID, InputError
from vqapr.record import (
    DATAMODEL_KIND,
    RunRecordLive,
    datamodel_refs,
    recorded_run_ids,
    remove_run_record,
    remove_strategy_record,
    strategy_refs,
    unfinished_datamodel_refs,
    unfinished_strategy_refs,
)
from vqapr.run.engine.output import MATERIALIZED_DIRECTORY
from vqapr.workspace.registry import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME, Workspace

RECORD_KINDS = ("run", "strategy", "datamodel")
DECLARATION_KINDS = {
    "component": "component",
    "run-definition": "run",
    # `docs/issues/archive/060`: the skill told the user to withdraw a dataset registration and the
    # CLI had no kind for it, so three throw-away materializations (1.3 GB) stayed registered and a
    # half-finished one could only be retried under a new id.
    "dataset": "dataset",
}
KINDS = (*RECORD_KINDS, *DECLARATION_KINDS)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=KINDS, help="what to remove")
    parser.add_argument(
        "identifier",
        help=(
            "run: a run id (its records); strategy: `<run-id>/<strategy-id>@<fp8>`; "
            "datamodel: `<run-id>/<datamodel-id>@<fp8>`; "
            "dataset: the registered dataset id (a datamodel's output under "
            ".vqapr/materialized/ is deleted with it; a dataset at your own path is left there); "
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
        "--cascade",
        dest="cascade",
        action="store_true",
        help=(
            "`run` only: remove everything of this run -- its records, its registered "
            "definition, the materialized datasets its datamodels wrote, and the components it "
            "named that no other run still names"
        ),
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
    cascade = bool(getattr(args, "cascade", False))
    if cascade and kind != "run":
        raise InputError(
            VALUE_INVALID,
            requirement="`--cascade` belongs to `rm run`",
            observed=f"--cascade given with `rm {kind}`",
            retry="run `vqapr rm run <run-id> --cascade`",
        )
    try:
        if kind == "run":
            if cascade:
                return _cascade(project_root, root, identifier)
            if identifier not in recorded_run_ids(root):
                raise InputError(
                    VALUE_INVALID,
                    requirement="rm run requires the id of a run this store holds records for",
                    observed=(
                        f"{identifier!r}; known: {', '.join(recorded_run_ids(root)) or '(none)'}"
                    ),
                    retry="run `vqapr list runs` to see what this store holds",
                )
            removed = remove_run_record(
                root, identifier, keep_latest=bool(getattr(args, "keep_latest", False))
            )
            return success("record.removed", kind=kind, run_id=identifier, removed=list(removed))
        if kind == "strategy":
            run_id, strategy_ref = resolve_member(
                root, identifier, kind="strategy", unfinished=True
            )
            remove_strategy_record(root, run_id, strategy_ref)
            return success("record.removed", kind=kind, run_id=run_id, removed=[strategy_ref])
        if kind == "datamodel":
            # The record only. The dataset it registered stays registered: a record is what a run
            # wrote about itself, and a dataset is what other runs may already read. A directory
            # WITHOUT a record -- what a crashed datamodel run leaves -- is precisely the one a
            # reader wants to remove, and this could not name it (`docs/issues/archive/080`).
            run_id, datamodel_ref = resolve_member(
                root, identifier, kind="datamodel", unfinished=True
            )
            remove_strategy_record(root, run_id, datamodel_ref, kind=DATAMODEL_KIND)
            return success("record.removed", kind=kind, run_id=run_id, removed=[datamodel_ref])
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
    workspace = Workspace.open(project_root)
    materialized: Path | None = None
    if kind == "dataset":
        # Where the rows live, read BEFORE the registration goes: a dataset a datamodel run
        # wrote sits under `.vqapr/materialized/<id>/`, and withdrawing its registration while
        # leaving the chunks would keep the 1.3 GB `060` measured with nothing pointing at it.
        # A dataset registered from the user's own path is theirs; only the package's own
        # directory is deleted.
        registered = {str(item.dataset_id): item for item in workspace.datasets}
        item = registered.get(identifier)
        if item is not None:
            path = workspace.source(str(item.source)).path.resolve()
            own = (project_root / WORKSPACE_DIRECTORY / MATERIALIZED_DIRECTORY).resolve()
            if own in path.parents:
                materialized = path
    removed = workspace.remove(workspace_kind, identifier)
    payload = success("workspace.removed", kind=kind, identifier=identifier, removed=bool(removed))
    if removed and materialized is not None:
        shutil.rmtree(materialized, ignore_errors=True)
        payload["deleted"] = str(materialized)
    if kind == "run-definition":
        # What the withdrawal left behind, and the verb that removes it. The refusals on the
        # way here name the next step; this names the last one, which otherwise had to be
        # performed from memory once `list runs` stopped showing the id (`docs/issues/archive/081`).
        remaining = _records_of(root, identifier)
        payload["records_remaining"] = remaining
        if remaining:
            payload["remove_records_with"] = f"vqapr rm run {identifier}"
    return payload


def _records_of(root: Path, run_id: str) -> list[str]:
    """Every member directory this run holds, finished or not, as `<id>@<fp8>`."""
    return [
        *strategy_refs(root, run_id),
        *datamodel_refs(root, run_id),
        *unfinished_strategy_refs(root, run_id),
        *unfinished_datamodel_refs(root, run_id),
    ]


def _materialized_path(project_root: Path, workspace: Workspace, dataset_id: str) -> Path | None:
    """Where a registered dataset's rows live, if they live under the package's own directory."""
    registered = {str(item.dataset_id): item for item in workspace.datasets}
    item = registered.get(dataset_id)
    if item is None:
        return None
    path = workspace.source(str(item.source)).path.resolve()
    own = (project_root / WORKSPACE_DIRECTORY / MATERIALIZED_DIRECTORY).resolve()
    return path if own in path.parents else None


def _cascade(project_root: Path, root: Path, run_id: str) -> dict[str, Any]:
    """Everything of one run, in the order that lets a refusal happen before any deletion.

    1. Records. `remove_run_record` checks every live lock before it removes anything, so a
       `RunRecordLive` here leaves the run exactly as it was.
    2. The registered definition, read first so its members are known after it is gone.
    3. The materialized datasets its datamodels wrote. Kept when another registered run takes
       its sessions from one, which is what `Workspace.remove` refuses.
    4. The components it named. Kept when another registered run still names one.

    A step that fails after records are gone is reported, not rolled back: the payload says what
    went and what remains, and the reader finishes with the single-kind verbs.
    """
    workspace = (
        Workspace.open(project_root)
        if (project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).exists()
        else None
    )
    definition = None
    if workspace is not None:
        definition = next(
            (item for item in workspace.run_definitions if item.run_id == run_id), None
        )
    if definition is None and run_id not in recorded_run_ids(root):
        raise InputError(
            VALUE_INVALID,
            requirement="rm run --cascade requires a run this workspace registers or holds "
            "records for",
            observed=f"{run_id!r}; recorded: {', '.join(recorded_run_ids(root)) or '(none)'}",
            retry="run `vqapr list runs` to see what this workspace holds",
        )
    removed: dict[str, Any] = {
        "records": list(remove_run_record(root, run_id)),
        "run_definition": False,
        "datasets": [],
        "components": [],
    }
    kept: list[dict[str, str]] = []
    if definition is None or workspace is None:
        return success("workspace.removed", kind="run", identifier=run_id, cascade=True,
                       removed=removed, kept=kept)
    removed["run_definition"] = bool(workspace.remove("run", run_id))
    outputs = [str(definition.writes)]
    for dataset_id in outputs:
        blockers = workspace.references_to("dataset", dataset_id)
        if blockers:
            kept.append(
                {"kind": "dataset", "id": dataset_id, "held_by": ", ".join(blockers)}
            )
            continue
        materialized = _materialized_path(project_root, workspace, dataset_id)
        if workspace.remove("dataset", dataset_id):
            removed["datasets"].append(dataset_id)
            if materialized is not None:
                shutil.rmtree(materialized, ignore_errors=True)
    named: list[str] = [definition.member.component_id, *definition.compliance]
    if definition.exchange is not None:
        named.append(definition.exchange)
    for component_id in dict.fromkeys(named):
        blockers = workspace.references_to("component", component_id)
        if blockers:
            kept.append(
                {"kind": "component", "id": component_id, "held_by": ", ".join(blockers)}
            )
            continue
        if workspace.remove("component", component_id):
            removed["components"].append(component_id)
    return success(
        "workspace.removed",
        kind="run",
        identifier=run_id,
        cascade=True,
        removed=removed,
        kept=kept,
    )
