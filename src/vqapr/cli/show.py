"""`vqapr show run <id>` — answer questions about a finished run, from any process.

Reads the frozen record. Does not recompute, and could not: the process that ran the simulation is
gone, and re-running it to answer a question about it would be a different run with a different
answer.

That is also why AC-R5's field-set equality matters more than it first looks. If `show run` built
its reply from anything other than the record, the reply and the record could diverge -- and the
divergence would be invisible, because nobody compares a CLI's output to a file they cannot see.
Both sides build from one field set, `RECORD_FIELDS`: the writer assembles its payload by iterating
it, and this projects the same names back out. A field named there without a builder is an error at
the writer, not a drift that reaches disk and waits to be noticed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.inputs import InputError
from vqapr.domain.errors import VqaprError
from vqapr.flow.run_records import RECORD_FIELDS as _RECORD_FIELDS
from vqapr.flow.run_records import read_record, run_ids
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

KINDS = ("run", "model")


# Imported, not redefined. The record is the artifact and this is one of its readers, so the field
# set lives beside the record in `flow/run_records.py` and the CLI reads it from there.
RECORD_FIELDS = _RECORD_FIELDS


def record_view(record: dict[str, Any]) -> dict[str, Any]:
    """The record's answers, in the field set both sides read from `RECORD_FIELDS`."""
    return {field: record.get(field) for field in RECORD_FIELDS}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=KINDS, help="what to show")
    parser.add_argument("identifier", help="the run id to show")
    parser.add_argument(
        "--store-root",
        dest="store_root",
        type=Path,
        default=None,
        help="where run records live, when they were written outside the workspace directory",
    )


def _model(component_id: str, project_root: Path) -> dict[str, Any]:
    """Every declaration one authored model makes, read from the model itself.

    AC-A5. The five answers are what the component TELLS the framework -- what it reads, when it
    decides, what it forms, what weights it produces and what it records -- and an author who has
    to open the source to recall them is being asked to keep the framework's own index in their
    head. Read by loading the component rather than by parsing it, so what is reported is what the
    framework will actually act on.
    """
    from vqapr._internal.extensions.loading import load_strategy_model

    space = Workspace.open(project_root)
    try:
        ref = space.component(component_id)
    except VqaprError:
        known = sorted(str(item.component_id) for item in space.components)
        raise InputError(
            "cli.input.value_invalid",
            requirement="show model requires the id of a registered component",
            observed=f"{component_id!r}; registered: {', '.join(known) or '(none)'}",
            retry="run `vqapr list components` to see what this workspace holds",
        ) from None

    model = load_strategy_model(ref, project_root=project_root)
    # An authored model arrives wrapped in the adapter that stamps identity and provenance, so the
    # declarations live on the adapter under its own names. Reading the loaded object rather than
    # re-parsing the file means this reports what the framework will actually act on.
    aliases = dict(getattr(model, "_aliases", {}) or {})
    tables = tuple(getattr(model, "_authored_tables", ()) or ())
    history = getattr(model, "_authored_history", None)
    return {
        "component_id": component_id,
        "kind": str(getattr(ref, "kind", "")),
        "reads": {
            alias: {
                "dataset_id": str(declared.dataset_id),
                "fields": list(declared.fields),
                "lookback": str(declared.lookback),
            }
            for alias, declared in sorted(aliases.items())
        },
        "decides": [str(requirement.dataset_id) for requirement in model.requirements()],
        "forms": [str(table.table_id) for table in tables],
        # Derived by the package from the decision, never declared: that is the authoring
        # contract's whole point, and saying so beats reporting an empty field.
        "weights": "derived from the Rebalance the model returns",
        "records": [str(table.table_id) for table in tables]
        + (["vqapr.account"] if history is not None else []),
    }


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "model":
        return success("model.show", **_model(args.identifier, project_root))
    root = args.store_root or project_root / WORKSPACE_DIRECTORY
    known = run_ids(root)
    if args.identifier not in known:
        raise InputError(
            "cli.input.value_invalid",
            requirement="show run requires the id of a run this store holds a record for",
            observed=f"{args.identifier!r}; known: {', '.join(known) or '(none)'}",
            retry=(
                "run `vqapr list runs` to see what this store holds, then show one of those ids"
            ),
        )
    return success("run.show", **record_view(read_record(root, args.identifier)))
