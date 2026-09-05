"""`vqapr show run|strategy|model|dataset <id>` — answer questions from what was frozen.

Reads the record. Does not recompute, and could not: the process that ran the simulation is gone,
and re-running it to answer a question about it would be a different run with a different answer.

**Two records since record `139`** (design §4.2). `show run <run-id>` reads `run.json`: the
configuration every strategy shared -- and, for a materialization or a run recorded before `139`,
the `record.json` those still write. `show strategy <run-id>/<id>@<fp8>` reads one strategy's
`strategy.json`, and `--table` reads that strategy's rows back.

Both sides of each record are built from one field set (`record_fields`), so the reply and the
file cannot diverge: a field named there without a builder is an error at the writer.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.register import cli_kind
from vqapr.domain.errors import VqaprError
from vqapr.flow.run_records import (
    DATAMODEL_KIND,
    RECORD_FIELDS_BY_KIND,
    RUN_JSON_FIELDS,
    RUN_KIND,
    STRATEGY_KIND,
    datamodel_refs,
    read_datamodel_record,
    read_run_record,
    read_strategy_record,
    read_table,
    record_fields,
    run_ids,
    strategy_refs,
    table_ids,
)
from vqapr.inputs import InputError
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

KINDS = ("run", "strategy", "datamodel", "model", "dataset")


# Imported, not redefined. The record is the artifact and this is one of its readers, so the field
# sets live beside the record in `flow/run_records.py` and the CLI reads them from there.
RECORD_FIELDS = record_fields(RUN_KIND)
STRATEGY_FIELDS = record_fields(STRATEGY_KIND)
DATAMODEL_FIELDS = record_fields(DATAMODEL_KIND)


def record_view(record: dict[str, Any]) -> dict[str, Any]:
    """The record's answers, in the field set for the kind of record this is.

    `kind` is surfaced rather than treated as metadata the way `schema` is. `schema` says how to
    parse the file, which is this reader's problem and not its caller's; `kind` says what the file
    is about, which the caller has to know to read the rest. A `run.json` is kind `run` with the
    `RUN_JSON_FIELDS`; a `record.json` of kind `run` is the field set written before `139`.
    """
    kind = record.get("kind", RUN_KIND)
    if kind == RUN_KIND and "strategies" in record:
        fields: tuple[str, ...] = RUN_JSON_FIELDS
    else:
        fields = record_fields(kind) if kind in RECORD_FIELDS_BY_KIND else RECORD_FIELDS
    return {"kind": kind, **{field: record.get(field) for field in fields}}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=KINDS, help="what to show")
    parser.add_argument(
        "identifier",
        help=(
            "run: the run id; strategy: `<run-id>/<strategy-id>@<fp8>` (or "
            "`<run-id>/<strategy-id>` when one record of it exists); model: a component id; "
            "dataset: a dataset id"
        ),
    )
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
            "read one of the strategy's recorded tables back instead of its record "
            "(vqapr.account, vqapr.fill, vqapr.monitoring, vqapr.weight, or a table the model "
            "formed)"
        ),
    )
    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=100,
        help="rows to return when --table is given; 0 returns every row",
    )
    parser.add_argument(
        "--instrument",
        dest="instrument",
        default=None,
        help=(
            "with --table: return only rows whose `instrument` is this id "
            "(`_ACCOUNT` is the cash-and-NAV row of vqapr.account)"
        ),
    )


def _model(component_id: str, project_root: Path) -> dict[str, Any]:
    """Every declaration one authored model makes, read from the model itself.

    AC-A5. The five answers are what the component TELLS the framework -- what it reads, when it
    decides, what it forms, what weights it produces and what it records -- and an author who has
    to open the source to recall them is being asked to keep the framework's own index in their
    head. Read by loading the component rather than by parsing it, so what is reported is what the
    framework will actually act on.
    """
    from vqapr.authoring import StrategyModel
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

    kind = getattr(ref, "kind", None)
    if kind is ComponentKind.CONSTRAINT:
        # A constraint declares what it reads and answers to an id, so it is describable in the
        # same terms -- it simply forms nothing and produces no weights.
        from vqapr.extension.loading import load_constraint

        rule = load_constraint(ref, project_root=project_root)
        return {
            "component_id": component_id,
            "kind": cli_kind(kind),
            "constraint_id": str(rule.constraint_id),
            "reads": {
                f"{requirement.dataset_id}.{requirement.field_id}": str(requirement.lookback)
                for requirement in rule.requirements()
            },
            "decides": "the feasible set every instrument's weight must lie in",
            "forms": [],
            "weights": "bounds only; a constraint narrows weights and never proposes them",
            "records": [],
        }
    if kind is ComponentKind.DATA_MODEL:
        model = load_data_model(ref, project_root=project_root)
    elif kind is ComponentKind.STRATEGY_MODEL:
        model = load_strategy_model(ref, project_root=project_root)
    else:
        # A registered id of a kind this verb does not describe. It used to fall through to the
        # strategy loader, whose `TypeError: ref must identify a strategy_model component` then
        # left as `stage: unhandled` -- a sentence that is false (this verb reads three kinds,
        # and had just shown a datamodel) and unstructured (`docs/issues/083`). The mistake is
        # the same one as an unregistered id, one line up, and gets the same answer.
        shown = ", ".join(
            cli_kind(item)
            for item in (
                ComponentKind.STRATEGY_MODEL, ComponentKind.DATA_MODEL, ComponentKind.CONSTRAINT
            )
        )
        raise InputError(
            "cli.input.value_invalid",
            requirement=f"show model describes a component of kind {shown}",
            observed=f"{component_id!r} is registered as {cli_kind(kind)}",
            retry=(
                "run `vqapr list components --kind <kind>` to pick a component this verb "
                "describes"
            ),
        )
    # From the model's own declarations -- `inputs()`, `tables()`, `account_history()` -- which
    # are what the framework acts on. This read three private attributes nothing in the tree
    # assigned (`_aliases`, `_authored_tables`, `_authored_history`, relics of the shape records
    # `126`-`133` removed) behind `getattr` defaults, so `reads` was always empty and `records`
    # never listed a declared table (`docs/issues/055`). No defaults now: a model without
    # `inputs` is not a model, and the loader would already have refused it.
    aliases = dict(model.inputs())
    tables = tuple(model.tables()) if isinstance(model, StrategyModel) else ()
    history = model.account_history() if isinstance(model, StrategyModel) else None
    return {
        "component_id": component_id,
        "kind": cli_kind(getattr(ref, "kind", None)),
        "reads": {
            alias: {
                "dataset_id": str(declared.dataset_id),
                "fields": list(declared.fields),
                "lookback": str(declared.lookback),
            }
            for alias, declared in sorted(aliases.items())
        },
        # The DISTINCT datasets, in declaration order: `requirements()` fans one read out to one
        # requirement per field, and reporting per requirement printed a dataset id seven times.
        "decides": list(
            dict.fromkeys(str(requirement.dataset_id) for requirement in model.requirements())
        ),
        "forms": [str(table.table_id) for table in tables],
        "weights": "derived from the Rebalance the model returns",
        "records": [str(table.table_id) for table in tables]
        + (["vqapr.account"] if history is not None else []),
    }


def _dataset(dataset_id: str, project_root: Path, limit: int) -> dict[str, Any]:
    """What a registered dataset actually holds, not merely that it exists."""
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
        "field_types": (
            None
            if item.field_types is None
            else {name: str(column_type) for name, column_type in item.field_types.items()}
        ),
        "aggregated": item.aggregated,
        "grain": None if item.grain is None else item.grain.value,
        "instrument_field": item.instrument_field,
        "available_at": item.available_at,
        "span": [str(value) for value in (item.span or ())] or None,
        "rows_total": scan.row_count(source),
        "returned": len(rows),
        "items": rows,
    }


def resolve_strategy(root: Path, identifier: str) -> tuple[str, str]:
    """`<run-id>/<strategy-id>@<fp8>` -> (run_id, strategy_ref); the short form when unique."""
    return resolve_member(root, identifier, kind="strategy")


def resolve_member(root: Path, identifier: str, *, kind: str) -> tuple[str, str]:
    """`<run-id>/<id>@<fp8>` -> (run_id, ref) for a strategy or a datamodel record.

    The short form is a convenience for the ordinary case of one record per model; with several
    fingerprints of one model the reader is shown them and asked to pick, because guessing the
    newest would answer a question about a tweak the reader did not name.
    """
    plural = "strategies" if kind == "strategy" else "datamodels"
    run_id, slash, rest = identifier.partition("/")
    if not slash or not rest:
        raise InputError(
            "cli.input.value_invalid",
            requirement=f"show {kind} takes `<run-id>/<{kind}-id>@<fp8>`",
            observed=repr(identifier),
            retry=f"run `vqapr list {plural} --run <run-id>` to see the records, then show one",
        )
    known = strategy_refs(root, run_id) if kind == "strategy" else datamodel_refs(root, run_id)
    if rest in known:
        return run_id, rest
    matching = [ref for ref in known if ref.rsplit("@", 1)[0] == rest]
    if len(matching) == 1:
        return run_id, matching[0]
    raise InputError(
        "cli.input.value_invalid",
        requirement=f"show {kind} requires a {kind} record this store holds",
        observed=(
            f"{identifier!r}; "
            + (
                f"{rest!r} has {len(matching)} records: {', '.join(matching)}"
                if matching
                else f"run {run_id!r} holds: {', '.join(known) or '(none)'}"
            )
        ),
        retry=f"run `vqapr list {plural} --run <run-id>` to see the records, then show one",
    )


def _rows(
    root: Path, run_id: str, strategy_ref: str | None, args: argparse.Namespace, label: str
) -> dict[str, Any]:
    """The rows a strategy wrote, which its record only counts."""
    table = args.table
    known_tables = table_ids(root, run_id, strategy_ref)
    if table not in known_tables:
        raise InputError(
            "cli.input.value_invalid",
            requirement="--table names one of the tables this record holds",
            observed=f"{table!r}; recorded: {', '.join(known_tables) or '(none)'}",
            retry=(
                f"choose one of the tables above, or drop --table to see the record; "
                f"`vqapr show {label}` reports each table's row count"
            ),
        )
    limit = max(int(getattr(args, "limit", 100) or 0), 0)
    instrument = getattr(args, "instrument", None)
    rows: list[dict[str, Any]] = []
    total = 0
    matched = 0
    try:
        for row in read_table(root, run_id, table, strategy_ref):
            total += 1
            # Filtered here, row by row, rather than after loading the table: a 2.6M-row
            # `vqapr.account` is why the testbed bypassed this command (A6).
            if instrument is not None and row.get("instrument") != instrument:
                continue
            matched += 1
            if limit == 0 or len(rows) < limit:
                rows.append(row)
    except ValueError as damaged:
        raise InputError(
            "cli.input.value_invalid",
            requirement=f"every line of {table!r} must be one JSON row",
            observed=str(damaged),
            retry=f"restore the file, or run again to write a fresh record; `vqapr show {label}` "
            "still reports what the record itself holds",
        ) from damaged
    return {
        "run_id": run_id,
        "strategy_ref": strategy_ref,
        "table": table,
        # Three numbers: what the table holds, what the filter admitted, what this page returned.
        "rows_total": total,
        "matched": matched,
        "returned": len(rows),
        "tables": list(known_tables),
        "items": rows,
    }


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "model":
        return success("model.show", **_model(args.identifier, project_root))
    if args.kind == "dataset":
        limit = max(int(getattr(args, "limit", 100) or 0), 0)
        return success("dataset.show", **_dataset(args.identifier, project_root, limit))
    root = args.store_root or project_root / WORKSPACE_DIRECTORY
    if args.kind == "strategy":
        run_id, strategy_ref = resolve_strategy(root, args.identifier)
        if getattr(args, "table", None) is not None:
            return success(
                "strategy.table",
                **_rows(root, run_id, strategy_ref, args, f"strategy {run_id}/{strategy_ref}"),
            )
        record = read_strategy_record(root, run_id, strategy_ref)
        return success(
            "strategy.show",
            kind=STRATEGY_KIND,
            **{field: record.get(field) for field in STRATEGY_FIELDS},
        )
    if args.kind == "datamodel":
        run_id, datamodel_ref = resolve_member(root, args.identifier, kind="datamodel")
        record = read_datamodel_record(root, run_id, datamodel_ref)
        if getattr(args, "table", None) is not None:
            raise InputError(
                "cli.input.value_invalid",
                requirement="a datamodel's rows are the dataset it registered, not a table",
                observed=f"{args.identifier!r} wrote dataset {record.get('dataset_id')!r}",
                retry=f"vqapr show dataset {record.get('dataset_id')}",
            )
        return success(
            "datamodel.show",
            kind=DATAMODEL_KIND,
            **{field: record.get(field) for field in DATAMODEL_FIELDS},
        )
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
    record = read_run_record(root, args.identifier)
    if getattr(args, "table", None) is not None:
        # Only a record written before `139` keeps tables in the run directory; a run's tables
        # live with its strategies now.
        if "strategies" in record:
            raise InputError(
                "cli.input.value_invalid",
                requirement="a run's tables belong to its strategies",
                observed=(
                    f"run {args.identifier!r} recorded "
                    f"{', '.join(strategy_refs(root, args.identifier)) or '(none)'}"
                ),
                retry=(
                    f"vqapr show strategy {args.identifier}/<strategy-id>@<fp8> "
                    f"--table {args.table}"
                ),
            )
        return success(
            "run.table", **_rows(root, args.identifier, None, args, f"run {args.identifier}")
        )
    view = record_view(record)
    if "strategies" in record:
        view["recorded"] = [
            *strategy_refs(root, args.identifier),
            *datamodel_refs(root, args.identifier),
        ]
    return success("run.show", **view)
