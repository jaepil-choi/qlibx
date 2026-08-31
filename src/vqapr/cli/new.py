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
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import yaml

from vqapr.account.account import AccountMode
from vqapr.cli.envelope import success
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import _class_name, render
from vqapr.inputs import VALUE_INVALID, InputError, refuse_existing
from vqapr.workspace import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME, Workspace

_KINDS = {
    "datamodel": ComponentKind.DATA_MODEL,
    "strategy": ComponentKind.STRATEGY_MODEL,
    "constraint": ComponentKind.CONSTRAINT,
}

_LOOKBACK_DEFAULT = 6
"""Rows of history the scaffolds declare when no lookback flag is given.

Named rather than repeated, because `_lookback_arguments` compares against it to tell "the user
asked for rows" from "the user left the default alone and asked for calendar days".
"""

_DECLARATION_KIND = {
    ComponentKind.DATA_MODEL: "datamodel",
    ComponentKind.STRATEGY_MODEL: "strategy",
    ComponentKind.CONSTRAINT: "constraint",
}
"""The declaration spelling for each authored kind.

Keyed by `ComponentKind` and read while emitting the companion `.yaml`, so a kind added to
`_KINDS` and forgotten here surfaces as a bare `KeyError` -- `stage: "unhandled"` -- which is the
failure shape this slice exists to remove. The three tables are the same three kinds.
"""

_DATASET_TEMPLATE = """\
# Dataset declaration — register with `vqapr register <this-file.yaml>`
#
# A dataset and its source file register together. There is no separate `sources:`
# section; source_id and path are declared here, inline under the dataset.
#
# Registrations are immutable. During disposable first-run setup, correct this YAML and rebuild
# the project-local workspace; after a run matters, preserve provenance by registering a new id.

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
#
# Registrations are immutable. During disposable first-run setup, correct this YAML and rebuild
# the project-local workspace; after a run matters, preserve provenance by registering a new id.

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
      at: "15:30"                   # execution must be STRICTLY LATER than the strategy callback
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
#
# Registrations are immutable. During disposable first-run setup, correct this YAML and rebuild
# the project-local workspace; after a run matters, preserve provenance by registering new ids.

agendas:
  daily-rebalance:                  # your chosen identity, named by a run spec's agenda_id
    role: strategy_callback         # one of: strategy_callback, valuation, monitoring
    from_dataset: DATASET_ID        # follow this registered dataset's own days
    # sessions:                     # ...or list the days literally. Declare exactly ONE of
    #   - "2024-01-02"              #    from_dataset or sessions, never both.
    #   - "2024-01-03"
    at: "15:29"                     # strictly before the execution template's 15:30 target
    timezone: Asia/Seoul            # zone `at` is expressed in; DST is derived from it

  # A callback at 15:29 sees only data whose `available_at` is strictly before 15:29. For a
  # dataset published at the 15:30 close, that means a strategy firing at 15:29 on session N
  # decides on session N-1's data -- which is correct, and is the point: it cannot see the close
  # it is about to trade into.
  #
  # Applied to VALUATION the same instant is usually wrong. A mark taken at 15:29 values the book
  # at the previous session's close, so the daily NAV series lags by one session for no stated
  # reason. Put valuation AFTER the execution instant instead -- 15:31 below -- so the first NAV
  # equals the initial cash exactly and each later one marks the close the run just filled at.

  daily-valuation:                  # valuation usually runs on the same days as the strategy
    role: valuation
    from_dataset: DATASET_ID
    at: "15:31"                     # after the 15:30 execution instant, not before it
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

_ACCOUNT_MODES = " or ".join(mode.name for mode in AccountMode)
"""The account modes spelled the way the spec parser accepts them, derived rather than restated.

The template used to say `LONG_ONLY or LONG_SHORT` in a hand-written comment. `LONG_SHORT` does not
exist and never did -- the members are `LONG_ONLY` and `SIGNED` -- so the template handed a
first-time author a value that cannot work, and the refusal it produced named a `KeyError` rather
than the permitted set. Deriving the list from the enum means the comment cannot drift from it
again: adding or renaming a member updates the template in the same edit.

`.name` rather than `.value`, because the spec is parsed by member NAME (`LONG_ONLY`), while
`.value` is the lowercase `long_only` a reader must not type here.
"""

_RUN_SPEC_TEMPLATE = f"""\
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

start: "2024-01-02T00:00:00+09:00"  # timezone-aware ISO-8601 datetime, inclusive
end: "2024-12-31T15:30:00+09:00"    # include the final callback's later execution target

exchange: my-venue             # component_id of a registered Exchange

execution_input: my-exec       # execution_input_id of a registered execution input

initial_account:
  cash: "1000000"              # quoted to preserve precision (parsed as Decimal)
  # The venue must permit the direction too: `--profile krx` is long-only and cannot hold a
  # SIGNED book. A costed long/short book needs a venue whose listings set access=SIGNED.
  mode: LONG_ONLY              # {_ACCOUNT_MODES}
  positions: {{}}                # mapping of instrument -> quantity, or empty

# Optional sections (uncomment to use):
# constraints:
#   - constraint-component-id
# monitoring:
#   agenda_id: monitoring-agenda
"""


def _emitted_class_name(source: str) -> str:
    """The class a template emitted, found by parsing rather than by splitting on `"class "`.

    The string split this replaces took the first occurrence of `"class "` anywhere in the file,
    including inside a docstring: a template whose prose contained "subclass and" yielded an
    `object_name` of half a paragraph, which registered and then failed at import with an
    `AttributeError` naming that paragraph. `register.py` already parses its equivalent with `ast`
    for exactly this reason, and this is the same fact about the same file.
    """
    import ast

    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            return node.name
    raise ValueError("the emitted template declares no class")


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
        choices=(
            *_KINDS,
            "instruments",
            "dataset",
            "execution-input",
            "agendas",
            "exchange",
            "run-spec",
        ),
        help=(
            "scaffold a component (datamodel/strategy/constraint) or emit a template "
            "(instruments/dataset/execution-input/agendas/exchange/run-spec). Component and "
            "exchange kinds write TWO files: the .py named by --out, and the .yaml beside it "
            "that registers it. Every registrable kind reports the file to hand "
            "`vqapr register` as `declaration`; `run-spec` reports `registrable: false` "
            "instead, because a run spec is handed to `vqapr run` rather than registered"
        ),
    )
    parser.add_argument(
        "component_id",
        nargs="?",
        default=None,
        help="identity of the new component (required for datamodel/strategy, unused for run-spec)",
    )
    parser.add_argument(
        "--instruments",
        nargs="*",
        default=None,
        help="instrument ids to list on a new exchange (defaults to two placeholders)",
    )
    parser.add_argument(
        "--profile",
        choices=("academic", "krx"),
        default="academic",
        help=(
            "which execution profile a new exchange is: academic fills free, "
            "krx charges KRX commission and sale tax including the ETF exemption"
        ),
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="dataset_id the component reads (required for datamodel/strategy)",
    )
    parser.add_argument("--field", default="close", help="price field the scaffold references")
    parser.add_argument(
        "--lookback",
        type=int,
        # `None`, not `_LOOKBACK_DEFAULT`, so "was this flag given" is answered by presence rather
        # than by value. Defaulting to 6 made `--lookback 6 --calendar-lookback 30` -- both flags,
        # one of them at the default -- indistinguishable from "only --calendar-lookback", so the
        # conflict refusal below silently ignored `--lookback` in exactly the case it exists to
        # refuse. Found by the structural audit in `docs/refactoring/`, C3.
        default=None,
        help=(
            "rows of history each name needs, counted per instrument and per field. On an "
            "unbalanced panel the batch then spans whatever the sparsest name reaches back to; "
            "use --calendar-lookback for a window every name shares"
        ),
    )
    parser.add_argument(
        "--calendar-lookback",
        dest="calendar_lookback",
        type=int,
        default=None,
        help=(
            "scaffold a datamodel that reads a CALENDAR window of this many days instead of "
            "--lookback rows per name. Use it for anything cross-sectional: a rows lookback "
            "gives each name its own last N observations, so on an unbalanced panel the batch "
            "spans whatever the sparsest name reaches back to"
        ),
    )
    parser.add_argument(
        "--cap",
        default="0.2",
        help="largest share of the book any one name may be (constraint scaffold)",
    )
    parser.add_argument("--out", type=Path, default=None, help="output path for the emitted file")


def _run_spec(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "run-spec.yaml"
    refuse_existing(target, what="run spec template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_RUN_SPEC_TEMPLATE, encoding="utf-8")
    # No `declaration` here, and this is the one kind where its absence is the honest answer: a
    # run spec is not registrable. `vqapr register` refuses it with
    # `declaration.read.unknown_section`, because a spec names components rather than declaring
    # any. `vqapr run` is what takes this file.
    #
    # `new --help` promised the key for EVERY kind, which was wrong in both directions -- four
    # kinds did not emit it, and one of those four could not honestly emit it. The help now says
    # what is true, and `registrable` says it in the envelope so a caller can branch on a field
    # rather than on a list of kind names it has to keep in sync (`docs/issues/026`).
    return success("template.new", kind="run-spec", path=str(target), registrable=False)


def _component(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    if not args.component_id:
        raise InputError(
            "cli.input.keys_missing",
            requirement="datamodel and strategy require a positional component_id",
            observed="no component_id given",
        )
    kind = _KINDS[args.kind]
    # `render` refuses an id that cannot become a Python class name. Caught here rather than left
    # to escape, because a bare `ValueError` reaches the envelope as `stage: "unhandled"` -- and
    # it did: `vqapr new constraint '123-bad!'` emitted an unparseable file and then failed on
    # re-reading it, reporting a SyntaxError about the framework's own output.
    try:
        _class_name(args.component_id)
    except ValueError as unusable:
        raise InputError(
            VALUE_INVALID,
            requirement="a component id must be able to name the class the scaffold declares",
            observed=str(unusable),
            retry="choose an id like `position-cap`, then retry",
        ) from unusable
    # Per kind, not per command. A DataModel and a StrategyModel are defined by what they read; a
    # Constraint is a rule about weights and reads nothing -- the shipped `NoShort` returns an
    # empty `requirements()`. Demanding `--dataset` from all three would make an author invent a
    # dataset to scaffold a rule that never opens one.
    if kind is ComponentKind.CONSTRAINT:
        source = render(kind, args.component_id, cap=str(getattr(args, "cap", "0.2")))
    else:
        if not args.dataset:
            raise InputError(
                "cli.input.keys_missing",
                requirement="datamodel and strategy require --dataset",
                observed="--dataset not given",
            )
        _require_registered_dataset(args.dataset, project_root)
        source = render(
            kind,
            args.component_id,
            dataset_id=args.dataset,
            field=args.field,
            **_lookback_arguments(args, kind),
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

    object_name = _emitted_class_name(source)
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


def _lookback_arguments(args: argparse.Namespace, kind: ComponentKind) -> dict[str, Any]:
    """Which lookback the scaffold declares, and how much of it.

    Two flags rather than one with a unit suffix, because the two are different questions -- N rows
    per name, or N calendar days for everyone -- and a single `--lookback 313` cannot say which was
    meant. Giving both is refused rather than resolved by precedence: a reader should not have to
    know which flag wins to predict what their own command emits.

    The strategy scaffold takes rows only, and says so here rather than emitting a file whose
    `len(values) >= LOOKBACK` guard counts observations against a number of days
    (`docs/issues/033`).
    """
    rows = getattr(args, "lookback", None)
    calendar = getattr(args, "calendar_lookback", None)
    if calendar is None:
        return {
            "lookback": _LOOKBACK_DEFAULT if rows is None else rows,
            "lookback_kind": "rows",
        }
    if rows is not None:
        raise InputError(
            VALUE_INVALID,
            requirement="--lookback and --calendar-lookback declare two different windows",
            observed=f"--lookback {rows} and --calendar-lookback {calendar}",
            retry=(
                "keep --lookback for N observations per name, or --calendar-lookback for a window "
                "of N days every name shares; drop the other"
            ),
        )
    if calendar <= 0:
        raise InputError(
            VALUE_INVALID,
            requirement="--calendar-lookback must be a positive number of days",
            observed=f"--calendar-lookback {calendar}",
            retry="pass a positive number of calendar days, then retry",
        )
    if kind is not ComponentKind.DATA_MODEL:
        raise InputError(
            VALUE_INVALID,
            requirement="--calendar-lookback applies to the datamodel scaffold",
            observed=f"--calendar-lookback given for kind {_DECLARATION_KIND[kind]}",
            retry=(
                "scaffold the strategy with --lookback, whose signal counts observations per "
                "name, and edit its DatasetInput if you want a calendar window"
            ),
        )
    return {"lookback": calendar, "lookback_kind": "calendar"}


def _require_registered_dataset(dataset_id: str, project_root: Path) -> None:
    """Refuse to scaffold against a dataset that is not registered, BEFORE writing anything.

    The scaffold's whole promise is that it runs as written. A component naming a dataset nobody
    registered does not: it emits successfully, and then fails at `register` or `check` with a
    refusal that names the component's requirement rather than the flag that caused it. The reader
    is left holding two files they now have to delete.

    An ABSENT workspace is not a refusal: `new` is the command typed in an empty directory, and
    demanding a workspace before the first scaffold would make the first command fail. A CORRUPT
    or unreadable one is a different thing entirely, and catching both together turned the loudest
    case into the quietest -- the scaffold would be written against an unchecked dataset in exactly
    the state that most needs a loud failure, and the user would meet a later refusal from
    `register` naming the component's requirement rather than the flag that caused it.

    `list_.py` faces the same choice and decides it the same way, for the reason recorded there: a
    corrupt workspace must keep failing loudly. Existence is tested rather than inferred from an
    exception, so the two cases stay distinguishable.
    """
    if not (project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME).exists():
        return
    registered = {str(item.dataset_id) for item in Workspace.open(project_root).datasets}

    if dataset_id in registered:
        return

    known = ", ".join(sorted(registered)) or "(none registered)"
    close = get_close_matches(dataset_id, sorted(registered), n=1)
    raise InputError(
        "cli.input.value_invalid",
        requirement="--dataset must name a dataset this workspace has registered",
        observed=f"{dataset_id!r}; registered: {known}",
        retry=(
            f"scaffold against {close[0]!r} instead"
            if close
            else "register the dataset first, then scaffold against it"
        ),
    )


def _dataset_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "dataset.yaml"
    refuse_existing(target, what="dataset declaration template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_DATASET_TEMPLATE, encoding="utf-8")
    # `declaration` is the file to hand `vqapr register`, which `new --help` promises for
    # EVERY kind. For a single-file kind the template IS the declaration, so it equals
    # `path`. Reporting it anyway is what lets a caller read one key across all nine kinds
    # instead of branching on which of them happen to write two files (`docs/issues/026`).
    return success(
        "template.new", kind="dataset", path=str(target), declaration=str(target)
    )


def _execution_input_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "execution-input.yaml"
    refuse_existing(target, what="execution input template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_EXECUTION_INPUT_TEMPLATE, encoding="utf-8")
    # `declaration` is the file to hand `vqapr register`, which `new --help` promises for
    # EVERY kind. For a single-file kind the template IS the declaration, so it equals
    # `path`. Reporting it anyway is what lets a caller read one key across all nine kinds
    # instead of branching on which of them happen to write two files (`docs/issues/026`).
    return success(
        "template.new",
        kind="execution-input",
        path=str(target),
        declaration=str(target),
    )


def _agendas_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "agendas.yaml"
    refuse_existing(target, what="agendas template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_AGENDAS_TEMPLATE, encoding="utf-8")
    # `declaration` is the file to hand `vqapr register`, which `new --help` promises for
    # EVERY kind. For a single-file kind the template IS the declaration, so it equals
    # `path`. Reporting it anyway is what lets a caller read one key across all nine kinds
    # instead of branching on which of them happen to write two files (`docs/issues/026`).
    return success(
        "template.new", kind="agendas", path=str(target), declaration=str(target)
    )


_EXCHANGE_TEMPLATE = '''"""A zero-friction Exchange listing the instruments this run may trade.

Every instrument in a run's universe needs a listing here, or preflight refuses it by name. Edit
the listing set below; the trade rule itself is usually the same for every name.
"""

from decimal import Decimal

from vqapr.public import AcademicExchange, TradeRule


def _rule(instrument_id: str) -> TradeRule:
    """One instrument's trading regime.

    `quantity_step` is the smallest tradable increment and `minimum_quantity` the smallest order.
    Whole shares on most venues; set `fractional_allowed=True` and a fractional step if yours
    permits fractions.

    **This venue charges nothing.** `buy` and `sell` default to `FREE`, which is what makes it
    academic. They are the channel for cost, and they are the two fields left out below -- so if
    you copy this shape onto a costed venue you get a venue that fills for free and refuses
    nothing. To charge here, uncomment them:

        from vqapr.public import SideCost

        buy=SideCost(commission_rate=Decimal("0.0003")),
        sell=SideCost(commission_rate=Decimal("0.0003"), tax_rate=Decimal("0.002")),

    For real KRX terms -- including the ETF sale-tax exemption, which depends on what each
    instrument IS -- do not hand-write the rates. Run `vqapr new exchange <id> --profile krx`,
    which builds them from `krx_rules`.
    """
    return TradeRule(
        instrument_id=instrument_id,
        quantity_step=Decimal(1),
        minimum_quantity=Decimal(1),
        fractional_allowed=False,
    )


class Venue(AcademicExchange):
    """Fills every order completely at the venue price, with no cost or slippage.

    `AcademicExchange` and `KrxExchange` are the only two profiles a registered Exchange may be.
    This one is for research where execution friction is deliberately not being modelled.
    """

    def __init__(self) -> None:
        super().__init__(listings={{
{listings}
        }})
'''

_KRX_EXCHANGE_TEMPLATE = '''"""A KRX Exchange that charges what KRX charges.

Commission and sale tax are resolved per fill from the project's registered instrument roster: a
stock pays the sale tax, an ETF does not, and **this file names no categories at all**.

That is deliberate. What an instrument IS belongs to the project, not to a venue -- a stock does
not become an ETF, and it is a stock on every venue. Declare it once with `vqapr new instruments`
and register it. A venue that kept its own copy could disagree with the roster, and a fill would
then say one category and be charged as another.

A run with no registered roster is refused here rather than charged one flat rate, because there
is no honest answer for an instrument nobody described.
"""

from vqapr.public import KrxExchange, krx_listings

# The ids this venue trades. What each one IS comes from the roster.
INSTRUMENTS = (
{universe}
)


class Venue(KrxExchange):
    """Whole-share KRX execution: declared commission and sale tax, long positions only.

    `AcademicExchange` and `KrxExchange` are the only two profiles a registered Exchange may be.
    This one charges; the academic one does not.
    """

    def __init__(self) -> None:
        # Costs are on. The limit-up/limit-down band is not, and that is the one thing here you
        # may want to change.
        #
        # `price_limits=True` models KRX's daily band, computed from the session base price, and
        # it REQUIRES your execution input to carry that price. Preflight refuses the run by name
        # if it does not -- it will not quietly produce limit-unaware numbers. The execution-input
        # template `vqapr new execution-input` emits carries a trade price only, so this scaffold
        # ships with the band off in order to run as emitted rather than refusing on first use.
        #
        # To switch it on: add the session base price to your execution table's `price_fields`,
        # then set this to True. The setting lives in THIS FILE, which the run record fingerprints
        # as `source_digest` -- so which of the two a past run measured is recoverable by reading
        # the venue at that digest. It is not a field in the record; do not expect to see it in
        # `vqapr show run`.
        super().__init__(krx_listings(INSTRUMENTS, price_limits=False))
'''

_EXCHANGE_DECLARATION = """\
# Registers the Exchange scaffolded beside this file:
#   vqapr register <this file>
components:
  {component_id}:
    kind: exchange
    path: {path}
    object_name: Venue
"""


def _exchange_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    """Emit a runnable Exchange plus the declaration that registers it.

    This template exists because a first-time-user journey stalled here and could not finish.
    Five of the six things a run needs had a scaffold; the Exchange did not, even though the
    run-spec template names `exchange:` as required. The author had to discover from refusals that
    only two profiles are permitted, then guess the shape of `listings` -- a mapping keyed by
    instrument id whose values are `TradeRule`, a type no template, help text or skill section
    ever named. Six consecutive guesses returned the identical error.

    A Python file rather than YAML alone, because a `TradeRule` is a typed value with a Decimal
    quantity step: expressing it in YAML would mean inventing a second spelling for something the
    package already has one spelling for.
    """
    target = args.out or project_root / "exchange.py"
    refuse_existing(target, what="exchange scaffold")
    target.parent.mkdir(parents=True, exist_ok=True)
    instruments = getattr(args, "instruments", None) or ["A005930", "A000660"]
    if getattr(args, "profile", "academic") == "krx":
        # Ids only. The CLI knows the ids and not what they are -- and neither does the venue,
        # which is the point: the categories come from the registered roster at fill time, so
        # there is no category here to default wrongly.
        universe = "\n".join(f'    "{name}",' for name in instruments)
        body = _KRX_EXCHANGE_TEMPLATE.format(universe=universe)
    else:
        listed = "\n".join(f'        "{name}": _rule("{name}"),' for name in instruments)
        body = _EXCHANGE_TEMPLATE.format(listings=listed)
    target.write_text(body, encoding="utf-8")

    declaration = target.with_suffix(".yaml")
    refuse_existing(declaration, what="exchange declaration")
    declaration.write_text(
        _EXCHANGE_DECLARATION.format(
            component_id=args.component_id or "venue", path=target.name
        ),
        encoding="utf-8",
    )
    return success(
        "template.new", kind="exchange", path=str(target), declaration=str(declaration)
    )


_INSTRUMENTS_TEMPLATE = '''\
"""Declare what each instrument in your universe IS, then export the tables.

Run this yourself, once, whenever the universe changes:

    uv run python {script_name}
    vqapr register {declaration_name}

**This file is your tool, not a registered component.** vqapr never reads it, never imports it and
never fingerprints it -- it only ever sees the parquet files you export. That is the same boundary
`available_at` already states: preparing a clean file is yours, refusing a dirty one is the
package's. Registration re-validates everything below, so a hand-written table is equally welcome.

Why a script rather than a mapping in the YAML: a real universe is generated rather than typed, and
an instrument's category is often not a column at all. A name like "2603 expiry Samsung call"
carries its right and expiry inside a string, and no declaration syntax parses that -- a few lines
of your own Python do.

The four categories vqapr ships. It is a closed set, and nothing else is accepted:

    stock   a common share
    etf     an exchange-traded fund, exempt from the sale tax a share pays on some venues
    index   an index level, referenced rather than held
    factor  a factor held against a synthetic unit price

WHY THIS MATTERS, in one line: on a KRX-shaped venue a share pays a sale tax an ETF does not, and
the category is consumed when the venue is built. Declare an ETF as a share and the wrong rate is
frozen in with nothing downstream able to notice.
"""

from pathlib import Path

from vqapr.public import export_roster

HERE = Path(__file__).parent

# Replace this with your own universe. Read your data however you like -- pandas, duckdb, a csv --
# and end with one mapping of instrument_id to category.
#
# If your source carries a classification column, map it here rather than by hand:
#
#     import duckdb
#     rows = duckdb.sql("SELECT ticker, sec_type FROM 'raw.parquet'").fetchall()
#     LOOKUP = {{"common": "stock", "preferred": "stock", "ETF": "etf"}}
#     UNIVERSE = {{ticker: LOOKUP[sec_type] for ticker, sec_type in rows}}
#
# Declaring every name a share is a legitimate answer. What is not legitimate is arriving at it
# without looking: registration prints a count per category, so a universe that is uniform will
# say so on the success path.
UNIVERSE = {universe!r}


if __name__ == "__main__":
    # `stem` is this file's own name, so the tables land where the emitted .yaml says they will.
    # Left at its default the exporter always writes `instruments_*.parquet`, which silently
    # disagreed with a declaration emitted under any other `--out` name.
    written = export_roster(UNIVERSE, HERE, stem=Path(__file__).stem)
    for kind, path in sorted(written.items()):
        print(f"{{kind:>8}}  {{path.name}}")
    print()
    print("now register them:")
    print(f"    vqapr register {declaration_name}")
'''


_INSTRUMENTS_DECLARATION = """\
# Instrument roster declaration - register with `vqapr register <this-file.yaml>`
#
# Points at the parquet tables that `{script_name}` exports. One file per category: a parquet
# carries exactly one schema, so a single table would need a nullable column for every attribute
# any category might have, and a null would then mean both "not applicable" and "omitted".
#
# Each table needs exactly two columns: `instrument_id` and `kind`. `instrument_id` is the same
# id the dataset, the execution input and the fill table use. `kind` is one of `stock`, `etf`,
# `index`, `factor` -- the closed set the package knows, because a category a venue has no terms
# for cannot be charged or sized. Registration refuses anything else and names the offending
# instrument and file, so a hand-written table is a legitimate input rather than a trap.
#
# The `kind` column inside each file repeats the key below on purpose. Registration checks the two
# against each other, which catches a table pointed at the wrong key before it charges the wrong
# rate for the life of the project.
#
# Unlike a dataset, re-registering this is ORDINARY. A roster grows as a matter of course -- a
# daily batch lists new tickers, issuers delist, a name is reclassified -- so correcting it is a
# statement about the world, not a rewrite of provenance. What a past run treated an instrument as
# is testified to by that run's own fills.
#
# A project has ONE roster. There is no name to give it: registering again replaces the whole
# slot, and `vqapr run` states the digest of whichever roster it read. The declaration used to
# carry an id here, which invited naming a second roster the workspace had nowhere to put -- it
# was echoed back and discarded.

instruments:
  tables:
{tables}
"""


def _instruments_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    """Emit the roster script and the declaration that registers what it writes.

    Two files, following `new exchange`: the runnable thing and the declaration that points at its
    output. Emitting only the YAML would leave the author to discover the four category names from
    a refusal, which is exactly the stall `new exchange` was built to remove -- an author guessed
    six times at a type no template, help text or skill section ever named.
    """
    target = args.out or project_root / "instruments.py"
    refuse_existing(target, what="instrument roster script")
    target.parent.mkdir(parents=True, exist_ok=True)

    declaration = target.with_suffix(".yaml")
    refuse_existing(declaration, what="instrument declaration")
    instruments = getattr(args, "instruments", None) or ["A005930", "A000660"]
    universe = {name: "stock" for name in instruments}

    target.write_text(
        _INSTRUMENTS_TEMPLATE.format(
            script_name=target.name,
            declaration_name=declaration.name,
            universe=universe,
        ),
        encoding="utf-8",
    )
    # Every shipped category gets a line, commented except the ones this universe uses, so the
    # author sees the whole vocabulary without having to look it up.
    used = sorted({kind for kind in universe.values()})
    lines = []
    # From the enum, not a literal tuple. `InstrumentKind` is the closed vocabulary registration
    # judges against, so a category added there and forgotten here would be registrable, would
    # appear in the refusal text derived from the enum, and would be silently missing from the
    # emitted declaration -- landing an author in exactly the undeclared-table case this same
    # command's receipt reports after the fact.
    from vqapr.domain.instruments import InstrumentKind

    for member in InstrumentKind:
        kind = str(member)
        prefix = "    " if kind in used else "    # "
        lines.append(f"{prefix}{kind}: {target.stem}_{kind}.parquet")
    declaration.write_text(
        _INSTRUMENTS_DECLARATION.format(
            script_name=target.name,
            tables="\n".join(lines),
        ),
        encoding="utf-8",
    )
    return success(
        "template.new", kind="instruments", path=str(target), declaration=str(declaration)
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "instruments":
        return _instruments_template(args, project_root)
    if args.kind == "dataset":
        return _dataset_template(args, project_root)
    if args.kind == "execution-input":
        return _execution_input_template(args, project_root)
    if args.kind == "agendas":
        return _agendas_template(args, project_root)
    if args.kind == "exchange":
        return _exchange_template(args, project_root)
    if args.kind == "run-spec":
        return _run_spec(args, project_root)
    return _component(args, project_root)
