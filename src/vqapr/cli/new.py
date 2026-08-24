"""`vqapr new <kind> [<id>]` — emit a component that runs, or a template spec.

Two modes:

- `vqapr new datamodel|strategy <id> --dataset <d>` emits a component `.py` and its registrable
  declaration `.yaml`. Both files are complete: `vqapr new` then `vqapr register` is the whole
  path from nothing to a registered component.

- `vqapr new dataset|execution-input|agendas|run-spec --out <path>` emits a YAML template with
  every required key, inline comments explaining each one, and placeholder values that need
  replacing. An agent that reads this file knows exactly what `vqapr register` or `vqapr run`
  expects, without opening documentation or guessing field names.

## Every declaration kind a run needs has a template

`register` understands seven sections, and a run needs five of them. Before `agendas` was added
here, three of those five had a template and the rest had to be known to exist: a reader who
scaffolded all four available kinds, filled them in, and ran got
`workspace.strategy_config.register.missing` -- a section no template had ever named. The gap was
not documentation, it was that `vqapr new`'s own choice list was the de-facto index of what a
declaration could contain, and it was incomplete.

`agendas` therefore emits `agendas` + `strategy_configs` + `valuation_configs` in one file rather
than three: a config binds a role to an agenda, so neither half is usable without the other, and
splitting them would recreate the same "which other file was I supposed to write" question one
level down.
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
    # ^ This is the critical field, and it has two separate requirements.
    #
    #   MEANING: it is NOT when the event happened — it is when the observation was
    #   available. A daily close is available at the session close; an accounting fact is
    #   available at publication, weeks after the period it covers. Getting this wrong is a
    #   look-ahead the framework cannot detect for you.
    #
    #   TYPE: the column must already be a TIMEZONE-AWARE timestamp in the parquet. A naive
    #   timestamp is refused, because '2024-01-02 15:30' does not say which market close it
    #   is. Localize it while preparing the data; registration does not convert it for you.
    #
    #   PROOF: before converting the full file, round-trip one known local wall time through
    #   your exact preparation code and assert its date, time, UTC offset, and UTC instant.
    #   Merely casting a naive pyarrow timestamp to timestamp(..., tz=...) preserves the
    #   underlying epoch value; it does not localize the wall clock. Use an explicit localization
    #   operation such as pyarrow.compute.assume_timezone, then prove the round-trip.
    key_fields:                       # columns that together uniquely identify each row
      - timestamp
      - instrument
    fields:                           # every column the dataset exposes, mapping name -> column
      close: close
      volume: volume
    # hive_partitioned: false         # uncomment if the source is a hive-partitioned directory
"""

_EXECUTION_INPUT_TEMPLATE = """\
# Execution input declaration - register with `vqapr register <this-file.yaml>`
#
# This declares the venue table a run fills against: where executable prices live,
# and the rule that picks which snapshot an order is filled at.
#
# Like a dataset, the source file is declared inline (source_id + path). There is no
# separate `sources:` section.

execution_inputs:
  EXECUTION_INPUT_ID:               # your chosen identity, named by a run spec's execution_input
    table:
      source_id: EXECUTION_INPUT_ID-source  # identifies the physical file
      path: relative/path/to/venue.parquet  # resolved relative to this YAML file
      trade_at_field: trade_at      # column holding the instant an execution is available at
      instrument_field: instrument  # column identifying each instrument
      is_tradable_field: is_tradable  # boolean column: was this name executable at that instant
      price_fields:                 # executable prices, mapping name -> column
        close: close
    fill:
      selector: same_day            # SCHEDULING rule, not a price choice. One of:
      #   same_day       fill at the instant selected within the same session
      #   next_eligible  fill at the next session where the name is tradable
      at: "15:30"                   # local time of the execution instant
      timezone: Asia/Seoul          # venue timezone that `at` is expressed in
      trade_price: close            # which key from price_fields above the fill uses
"""

_AGENDAS_TEMPLATE = """\
# Agendas and the configs that bind roles to them - register with `vqapr register <this-file>`
#
# An agenda is a cadence: the days a thing happens on, and the local time of day. A config binds
# a role to one agenda. Both live here because neither is usable alone -- an agenda nothing is
# bound to never fires, and a config naming an unregistered agenda is refused.
#
# A run spec names these by id (`strategy.agenda_id`, `valuation.agenda_id`). Naming an agenda
# there does NOT bind it; the binding is the `strategy_configs`/`valuation_configs` entry below.
# A run whose components are registered but unbound fails preflight with
# `workspace.strategy_config.register.missing`.

agendas:
  daily-rebalance:                  # your chosen identity, named by a run spec's agenda_id
    role: strategy_callback         # one of: strategy_callback, valuation, monitoring
    from_dataset: DATASET_ID        # follow this registered dataset's own days
    # sessions:                     # ...or list the days literally. Declare exactly ONE of
    #   - "2024-01-02"              #    from_dataset or sessions, never both.
    #   - "2024-01-03"
    at: "15:30"                     # local time of day the occurrence fires at
    timezone: Asia/Seoul            # zone `at` is expressed in; DST is derived from it

  daily-valuation:                  # valuation usually runs on the same days as the strategy
    role: valuation
    from_dataset: DATASET_ID
    at: "15:30"
    timezone: Asia/Seoul

strategy_configs:
  COMPONENT_ID:                     # component_id of a registered StrategyModel
    agenda_id: daily-rebalance      # the agenda above whose occurrences drive it

valuation_configs:
  daily-valuation:                  # any identity; the agenda it names is what matters
    agenda_id: daily-valuation

# monitoring_policies:              # optional; only if the run spec declares `monitoring`
#   default:
#     agenda_id: daily-monitoring
"""

_RUN_SPEC_TEMPLATE = """\
# Run spec — every required key of THIS file is shown. Replace the placeholder values.
# Write this file, then execute: vqapr run <this-file.yaml>
#
# This file names components and agendas; it does not register or bind them. Before `run`
# succeeds, the ids below must already exist in the workspace, and the strategy and valuation
# must each be BOUND to their agenda by a registered config -- see `vqapr new agendas`, which
# emits the agendas and both configs together. Naming an agenda_id here is not a binding.

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
        choices=(*_KINDS, "dataset", "execution-input", "agendas", "run-spec"),
        help=(
            "scaffold a component (datamodel/strategy) or emit a template "
            "(dataset/execution-input/agendas/run-spec)"
        ),
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
    if target.suffix != ".py":
        # A component is imported by `register`, so it must be a loadable module. Writing an
        # extensionless file here reports success and then fails one command later, where the
        # refusal names the module loader rather than the flag that caused it. The default path
        # already appends `.py`; an explicit --out is held to the same rule instead of being
        # taken verbatim.
        target = target.with_suffix(".py")
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


def _execution_input_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "execution-input.yaml"
    refuse_existing(target, what="execution input template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_EXECUTION_INPUT_TEMPLATE, encoding="utf-8")
    return success("template.new", kind="execution-input", path=str(target))


def _agendas_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "agendas.yaml"
    refuse_existing(target, what="agendas template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_AGENDAS_TEMPLATE, encoding="utf-8")
    return success("template.new", kind="agendas", path=str(target))


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "dataset":
        return _dataset_template(args, project_root)
    if args.kind == "execution-input":
        return _execution_input_template(args, project_root)
    if args.kind == "agendas":
        return _agendas_template(args, project_root)
    if args.kind == "run-spec":
        return _run_spec(args, project_root)
    return _component(args, project_root)
