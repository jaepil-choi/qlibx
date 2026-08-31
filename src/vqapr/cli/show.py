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
from vqapr.cli.register import cli_kind
from vqapr.domain.errors import VqaprError
from vqapr.flow.run_records import (
    RECORD_FIELDS_BY_KIND,
    RUN_KIND,
    read_record,
    read_table,
    record_fields,
    run_ids,
    table_ids,
)
from vqapr.inputs import InputError
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

KINDS = ("run", "model", "dataset")


# Imported, not redefined. The record is the artifact and this is one of its readers, so the field
# set lives beside the record in `flow/run_records.py` and the CLI reads it from there.
RECORD_FIELDS = record_fields(RUN_KIND)


def record_view(record: dict[str, Any]) -> dict[str, Any]:
    """The record's answers, in the field set for the kind of record this is.

    **Reads `kind` and branches on it since record `115`.** A flat field set could describe one kind
    of record; with two, projecting a materialization through a run's field list would render six
    nulls and drop everything it actually answers.

    `kind` is surfaced rather than treated as metadata the way `schema` is. `schema` says how to
    parse the file, which is this reader's problem and not its caller's; `kind` says what the file
    is about, which the caller has to know to read the rest. One `show run` covers both kinds only
    if it says which one it just showed.
    """
    kind = record.get("kind", RUN_KIND)
    fields = record_fields(kind) if kind in RECORD_FIELDS_BY_KIND else RECORD_FIELDS
    return {"kind": kind, **{field: record.get(field) for field in fields}}


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
    parser.add_argument(
        "--table",
        dest="table",
        default=None,
        help=(
            "read one of the run's recorded tables back instead of its record "
            "(vqapr.account, vqapr.fill, vqapr.weight, or a table the model formed)"
        ),
    )
    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=100,
        help="rows to return when --table is given; 0 returns every row",
    )


def _model(component_id: str, project_root: Path) -> dict[str, Any]:
    """Every declaration one authored model makes, read from the model itself.

    AC-A5. The five answers are what the component TELLS the framework -- what it reads, when it
    decides, what it forms, what weights it produces and what it records -- and an author who has
    to open the source to recall them is being asked to keep the framework's own index in their
    head. Read by loading the component rather than by parsing it, so what is reported is what the
    framework will actually act on.
    """
    from vqapr.extension.component import ComponentKind
    from vqapr.extension.loading import load_data_model, load_strategy_model

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

    # Both authored kinds, because both declare the same things. `show model` loaded only a
    # StrategyModel and refused a DataModel with a message about the wrong kind -- so the one
    # component whose whole job is to DERIVE a column could be scaffolded and registered and never
    # described. A first-time-user journey reported that as a blocker while trying to find out
    # what a DataModel is for.
    kind = getattr(ref, "kind", None)
    if kind is ComponentKind.CONSTRAINT:
        # A constraint declares what it reads and answers to an id, so it is describable in the
        # same terms -- it simply forms nothing and produces no weights. Falling through to the
        # StrategyModel loader raised a bare `TypeError` as `stage: "unhandled"`, so the one
        # component a reader most needs to inspect before trusting it could not be inspected at
        # all. Found by a first-time-user journey after a cap refused its run.
        from vqapr.extension.loading import load_constraint

        rule = load_constraint(ref, project_root=project_root)
        return {
            "component_id": component_id,
            "kind": cli_kind(kind),
            "constraint_id": str(rule.constraint_id),
            "reads": {
                str(requirement.dataset_id): {
                    "fields": list(requirement.fields),
                    "lookback": str(requirement.lookback),
                }
                for requirement in rule.requirements()
            },
            # Named rather than left absent, because "reads nothing" is the ordinary answer for a
            # rule about weights and an empty mapping alone does not say so.
            "decides": "the feasible set every instrument's weight must lie in",
            "forms": [],
            "weights": "bounds only; a constraint narrows weights and never proposes them",
            "records": [],
        }
    if kind is ComponentKind.DATA_MODEL:
        model = load_data_model(ref, project_root=project_root)
    else:
        model = load_strategy_model(ref, project_root=project_root)
    # An authored model arrives wrapped in the adapter that stamps identity and provenance, so the
    # declarations live on the adapter under its own names. Reading the loaded object rather than
    # re-parsing the file means this reports what the framework will actually act on.
    aliases = dict(getattr(model, "_aliases", {}) or {})
    tables = tuple(getattr(model, "_authored_tables", ()) or ())
    history = getattr(model, "_authored_history", None)
    return {
        "component_id": component_id,
        # Spelled the way `new` and `register` accept it, not as the domain enum's value: a
        # reader cannot type `data_model` anywhere.
        "kind": cli_kind(getattr(ref, "kind", None)),
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


def _dataset(dataset_id: str, project_root: Path, limit: int) -> dict[str, Any]:
    """What a registered dataset actually holds, not merely that it exists.

    `list datasets` proves a registration. Nothing could read a row back, so a reader who
    materialized a DataModel and wanted to see what it computed had to build a second complete
    run -- execution input, exchange, strategy, agendas, spec -- purely to observe the values, or
    open the parquet by hand. A first-time-user journey did both.

    Exactly the gap `show run --table` closed one artifact over: the record reported per-table row
    counts and nothing could read a row. The same rule applies here, so the same answer does.
    """
    from vqapr.data import scan

    space = Workspace.open(project_root)
    registered = {str(item.dataset_id): item for item in space.datasets}
    item = registered.get(dataset_id)
    if item is None:
        raise InputError(
            "cli.input.value_invalid",
            requirement="show dataset requires the id of a registered dataset",
            observed=f"{dataset_id!r}; registered: {', '.join(sorted(registered)) or '(none)'}",
            retry="run `vqapr list datasets` to see what this workspace holds",
        )

    source = space.source(str(item.source))
    rows = scan.head(source, limit=limit)
    return {
        "dataset_id": dataset_id,
        "source_id": str(source.source_id),
        "path": str(source.path),
        "fields": dict(item.fields),
        "instrument_field": item.instrument_field,
        "available_at": item.available_at,
        "span": [str(value) for value in (item.span or ())] or None,
        # Two numbers for the same reason `show run --table` reports two: a page that reported
        # only what it returned would let a reader conclude a dataset holds ten rows.
        "rows_total": scan.row_count(source),
        "returned": len(rows),
        "items": rows,
    }


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "model":
        return success("model.show", **_model(args.identifier, project_root))
    if args.kind == "dataset":
        limit = max(int(getattr(args, "limit", 100) or 0), 0)
        return success("dataset.show", **_dataset(args.identifier, project_root, limit))
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
    table = getattr(args, "table", None)
    if table is None:
        return success("run.show", **record_view(read_record(root, args.identifier)))

    # The rows a run wrote, which the record only counts. `record["tables"]` reports how many rows
    # and how many instants each table holds, and nothing could read one back -- so the evidence
    # tables `RunRecorder` writes on every run were reachable only by knowing the on-disk layout
    # and opening the .jsonl by hand. That is the file this surface should not require a reader to
    # know about, the same rule `list instruments` answers for the roster sidecar.
    known_tables = table_ids(root, args.identifier)
    if table not in known_tables:
        raise InputError(
            "cli.input.value_invalid",
            requirement="--table names one of the tables this run recorded",
            observed=f"{table!r}; this run recorded: {', '.join(known_tables) or '(none)'}",
            retry=(
                f"choose one of the tables above, or drop --table to see the record; "
                f"`vqapr show run {args.identifier}` reports each table's row count"
            ),
        )
    limit = max(int(getattr(args, "limit", 100) or 0), 0)
    rows: list[dict[str, Any]] = []
    total = 0
    try:
        for row in read_table(root, args.identifier, table):
            total += 1
            if limit == 0 or len(rows) < limit:
                rows.append(row)
    except ValueError as damaged:
        # A damaged row is reported here rather than skipped in the reader. Skipping would return
        # a short table that looks complete, and a reader comparing it against the record's own
        # count would find two numbers disagreeing with no reason given. An empty table file stays
        # legal and returns zero rows: a run may record a table and write nothing to it.
        raise InputError(
            "cli.input.value_invalid",
            requirement=f"every line of {table!r} must be one JSON row",
            observed=str(damaged),
            retry=(
                f"restore the file, or re-run to write a fresh record; "
                f"`vqapr show run {args.identifier}` still reports what the record itself holds"
            ),
        ) from damaged
    return success(
        "run.table",
        run_id=args.identifier,
        table=table,
        # Two numbers, because a truncated read that reported only `len(rows)` would let a reader
        # conclude the run wrote 100 rows when it wrote 40,000. `rows_total` is what the table
        # holds; `rows` is what this call returned.
        rows_total=total,
        returned=len(rows),
        tables=list(known_tables),
        items=rows,
    )
