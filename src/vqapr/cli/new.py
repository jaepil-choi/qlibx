"""`vqapr new <kind> [<id>]` — emit a component that runs, or a template spec.

Two modes:

- `vqapr new datamodel|strategy <id> --dataset <d>` emits a component `.py` and its registrable
  declaration `.yaml`. Both files are complete: `vqapr new` then `vqapr register` is the whole
  path from nothing to a registered component.

- `vqapr new run-spec --out <path>` emits a YAML template with every required key, inline
  comments explaining each one, and placeholder values that need replacing. An agent that reads
  this file knows exactly what `vqapr run` expects, without opening documentation or guessing
  field names.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from vqapr.cli.envelope import success
from vqapr.cli.inputs import InputError, refuse_existing
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import render

_KINDS = {"datamodel": ComponentKind.DATA_MODEL, "strategy": ComponentKind.STRATEGY_MODEL}

_DECLARATION_KIND = {
    ComponentKind.DATA_MODEL: "datamodel",
    ComponentKind.STRATEGY_MODEL: "strategy",
}

_DATASET_TEMPLATE = """\
# Dataset declaration — register with `vqapr register <this-file.yaml>`
#
# A dataset and its source file register together. There is no separate `sources:`
# section; source_id and path are declared here, inline under the dataset.

datasets:
  DATASET_ID:                         # your chosen identity for this dataset
    source_id: DATASET_ID-source      # identifies the physical file; convention: <id>-source
    path: relative/path/to/data.parquet  # resolved relative to this YAML file
    instrument_field: instrument      # column that identifies each instrument / name / ticker
    available_at: timestamp           # column that says WHEN this row could first have been known
    # ^ This is the critical field. It is NOT when the event happened — it is when the
    #   observation was available. A daily close is available at the session close; an
    #   accounting fact is available at publication, weeks after the period it covers.
    #   Getting this wrong is a look-ahead the framework cannot detect for you.
    key_fields:                       # columns that together uniquely identify each row
      - timestamp
      - instrument
    fields:                           # every column the dataset exposes, mapping name -> column
      close: close
      volume: volume
    # hive_partitioned: false         # uncomment if the source is a hive-partitioned directory
"""

_RUN_SPEC_TEMPLATE = """\
# Run spec — every required key is shown. Replace the placeholder values.
# Write this file, then execute: vqapr run <this-file.yaml>

strategy:
  component: my-alpha          # component_id of a registered StrategyModel
  agenda_id: daily-rebalance   # agenda_id of the operation agenda to drive the strategy

valuation:
  agenda_id: daily-valuation   # agenda_id for end-of-day valuation

instruments:                   # the universe this run trades
  - INSTRUMENT_A
  - INSTRUMENT_B

start: "2024-01-02"            # ISO-8601 date or datetime, inclusive
end: "2024-12-31"              # ISO-8601 date or datetime, inclusive

exchange: my-venue             # component_id of a registered Exchange

execution_input: my-exec       # execution_input_id of a registered execution input

initial_account:
  cash: "1000000"              # quoted to preserve precision (parsed as Decimal)
  mode: LONG_ONLY              # LONG_ONLY or LONG_SHORT
  positions: {}                # mapping of instrument -> quantity, or empty

# Optional sections (uncomment to use):
# constraints:
#   - constraint-component-id
# monitoring:
#   agenda_id: monitoring-agenda
"""


def _declaration(component_id: str, kind: ComponentKind, source: Path, object_name: str) -> str:
    """The registrable declaration for what was just scaffolded.

    Only the component is declared. The dataset it reads, and the agenda it runs on, are facts
    about the user's project rather than about this file, and inventing plausible values for them
    would produce a document that registers something the user did not mean.
    """
    document = {
        "components": {
            component_id: {
                "kind": _DECLARATION_KIND[kind],
                "path": source.name,
                "object_name": object_name,
            }
        }
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "kind",
        choices=(*_KINDS, "dataset", "run-spec"),
        help="scaffold a component (datamodel/strategy) or emit a template (dataset/run-spec)",
    )
    parser.add_argument(
        "component_id",
        nargs="?",
        default=None,
        help="identity of the new component (required for datamodel/strategy, unused for run-spec)",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="dataset_id the component reads (required for datamodel/strategy)",
    )
    parser.add_argument("--field", default="close", help="price field the scaffold references")
    parser.add_argument(
        "--lookback", type=int, default=6, help="rows of history each name needs"
    )
    parser.add_argument("--out", type=Path, default=None, help="output path for the emitted file")


def _run_spec(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "run-spec.yaml"
    refuse_existing(target, what="run spec template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_RUN_SPEC_TEMPLATE, encoding="utf-8")
    return success("template.new", kind="run-spec", path=str(target))


def _component(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    if not args.component_id:
        raise InputError(
            "cli.input.keys_missing",
            requirement="datamodel and strategy require a positional component_id",
            observed="no component_id given",
        )
    if not args.dataset:
        raise InputError(
            "cli.input.keys_missing",
            requirement="datamodel and strategy require --dataset",
            observed="--dataset not given",
        )
    kind = _KINDS[args.kind]
    source = render(
        kind,
        args.component_id,
        dataset_id=args.dataset,
        field=args.field,
        lookback=args.lookback,
    )
    target = args.out or project_root / f"{args.component_id.replace('-', '_')}.py"
    declaration = target.with_suffix(".yaml")
    refuse_existing(target, what="component file")
    refuse_existing(declaration, what="declaration file")

    object_name = source.split("class ", 1)[1].split("(", 1)[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    declaration.write_text(
        _declaration(args.component_id, kind, target, object_name), encoding="utf-8"
    )
    return success(
        "component.new",
        kind=str(kind),
        id=args.component_id,
        path=str(target),
        declaration=str(declaration),
        object_name=object_name,
    )


def _dataset_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "dataset.yaml"
    refuse_existing(target, what="dataset declaration template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_DATASET_TEMPLATE, encoding="utf-8")
    return success("template.new", kind="dataset", path=str(target))


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "dataset":
        return _dataset_template(args, project_root)
    if args.kind == "run-spec":
        return _run_spec(args, project_root)
    return _component(args, project_root)
