"""`vqapr new <kind> [<id>]` — emit a component that runs, or a template spec.

Two modes:

- `vqapr new datamodel|strategy <id> --dataset <d>` emits a component `.py` and its registrable
  declaration `.yaml`. Both files are complete: `vqapr new` then `vqapr register` is the whole
  path from nothing to a registered component.

- `vqapr new dataset|run --out <path>` emits a YAML template with
  every required key, inline comments explaining each one, and placeholder values that need
  replacing. An agent that reads this file knows exactly what `vqapr register` or `vqapr run`
  expects, without opening documentation or guessing field names.

## Every declaration kind a run needs has a template

`register` understands four sections, and a run needs three of them: a dataset (the venue table a
run fills against is a dataset with an `execution:` role), an exchange and the run itself. There
is no agenda to declare (record `148`): the run
says which sessions it fires on and at what wall time, every strategy is called on every
session and decides for itself, the book is valued at the instant the venue fills, and the
declared constraints judge it right after each commit.
"""

from __future__ import annotations

import argparse
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import yaml

from vqapr.account.account import AccountMode
from vqapr.agent.sample.materialize import RUN_ID as SAMPLE_RUN_ID
from vqapr.agent.sample.materialize import materialize as materialize_sample
from vqapr.cli.envelope import success
from vqapr.domain.inputs import INCOMPLETE, VALUE_INVALID, InputError, refuse_existing
from vqapr.extension.component import ComponentKind
from vqapr.extension.lookback import lookback_declaration
from vqapr.extension.scaffold import _class_name, render
from vqapr.project.store import WORKSPACE_DIRECTORY, WORKSPACE_FILENAME, Workspace

_KINDS = {
    "datamodel": ComponentKind.DATA_MODEL,
    "strategy": ComponentKind.STRATEGY_MODEL,
    "constraint": ComponentKind.CONSTRAINT,
}

_LOOKBACK_DEFAULT = 6
"""Rows of history the scaffolds declare when no lookback flag is given.

Named rather than repeated, because `authoring_lookback.lookback_declaration` compares against it
to tell "the user
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
    # GRAIN: what one row of this table IS. Required; registration refuses without it.
    #   instrument_instant  one value per (available_at, instrument) -- a date x ticker table.
    #                       A panel can be built from it, and this is the shape to prefer.
    #   instant             one value per available_at, no instrument axis (index level, rate).
    #   rows                the vendor's grain (long / EAV); unique on key_fields; no panel.
    #   On a panel grain, RowsLookback(n) is the last n rows of the pivoted table -- the same
    #   instants for every name. Per-name counting is InstantsLookback on grain: rows.
    grain: instrument_instant
    key_fields:                       # columns that together uniquely identify each row
      - timestamp
      - instrument
    fields:                           # every column the dataset exposes, mapping name -> column
      close: close
      volume: volume
    field_types:                      # what each field IS, one of: TIMESTAMP_TZ, DATE, INTEGER,
      close: DOUBLE                   #   DOUBLE, VARCHAR, BOOLEAN. Registration reads the file
      volume: INTEGER                 #   once and refuses a field whose column disagrees. A
                                      #   DECIMAL column is refused: cast it to DOUBLE while
                                      #   preparing the source, so a model reads one numeric type.
    # hive_partitioned: false         # uncomment if the source is a hive-partitioned directory
    # execution:                      # uncomment to make this the venue table a run fills against:
    #   is_tradable: is_tradable      #   a BOOLEAN field saying a name was executable at that row.
    #                                 #   Its numeric fields are the prices a run may choose
    #                                 #   from; the run names one as `execution.fill.trade_price`.
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

_RUN_TEMPLATE = f"""\
# Run declaration -- register with `vqapr register <this-file.yaml>`, then `vqapr run RUN_ID`
#
# A run is configuration (record 139): the universe, the period, the strategy clock it decides
# on (`agenda`), the venue, the execution dataset, the initial account, and the one strategy it
# runs. The clock is expanded over the trading days the execution dataset has rows for -- a
# denser table adds fill instants, never decision days -- and the strategy is called at every
# instant of it, deciding for itself whether to act. The book is valued at the instant the venue
# fills and the declared constraints judge it right after each commit; there is no separate
# valuation or monitoring time to declare. The run's record lives under .vqapr/runs/RUN_ID/.
# Ids below name registered declarations; nothing here registers them.

runs:
  RUN_ID:                            # your chosen identity: `vqapr run RUN_ID`
    instruments:                     # the universe every strategy trades
      - INSTRUMENT_A
      - INSTRUMENT_B
    start: "2024-01-02T00:00:00+09:00"  # timezone-aware ISO-8601 datetime, inclusive
    end: "2024-12-31T15:30:00+09:00"    # include the final callback's later execution target
    timezone: Asia/Seoul             # the zone every wall time below is expressed in
    agenda:                          # the strategy clock: a day filter and a within-day rule
      every: 1d                      # 1d | 2d | 1w | 1M select trading days and pair with `at`;
      at: "15:29"                    #   1m | 5m | 1h select instants and pair with `from`/`to`
      # from: "09:00"                # the trading days are the days the execution dataset
      # to: "15:20"                  #   below has rows for -- nothing to declare here
    exchange: my-venue               # component_id of a registered Exchange
    execution:                       # the registered venue table, and THIS run's fill on it
      dataset: my-venue-daily        # a dataset registered with `execution: {{is_tradable: ...}}`
      trade_price: close             # which numeric field of the dataset this run fills at;
                                     #   another run may fill the same table at `open`
      fill:                          # optional. Without it a decision fills at the FIRST
        at: "15:30"                  #   execution instant after it; `at` keeps only instants at
        # after: "10m"               #   this wall time (run timezone) -- STRICTLY LATER than the
        # within: "1d"               #   decision. `after`: minimum gap. `within`: maximum gap,
                                     #   else the run is refused before it starts
    initial_account:
      cash: "1000000"                # quoted to preserve precision (parsed as Decimal)
      # The venue must permit the direction too: `--profile krx` is long-only and cannot hold a
      # SIGNED book. A costed long/short book needs a venue whose listings set access=SIGNED.
      mode: LONG_ONLY                # {_ACCOUNT_MODES}
      positions: {{}}                  # mapping of instrument -> quantity, or empty
    writes: my-alpha-weights         # the dataset this run puts in the warehouse: its allocation,
                                     #   one row per instrument per decision. Other runs read it
    strategy:                        # the ONE registered StrategyModel this run executes
      component: my-alpha
      # constraints: [constraint-component-id]
      # initial_model_memory: {{}}
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


def _declaration(
    component_id: str,
    kind: ComponentKind,
    source: Path,
    object_name: str,
    *,
    dataset_id: str | None = None,
) -> str:
    """The registrable declaration for what was just scaffolded.

    The component is declared. A datamodel also gets the run that computes it (record `148`):
    its sessions are the dataset it reads, its output is named after it, and the universe and
    period are placeholders to fill -- registrable as emitted, refused by `check` until the
    instruments are real. A strategy's run needs a venue, an execution dataset and an account,
    which are facts about the user's project rather than about this file, so it gets none.
    """
    document: dict[str, Any] = {
        "components": {
            component_id: {
                "kind": _DECLARATION_KIND[kind],
                "path": source.name,
                "object_name": object_name,
            }
        }
    }
    if kind is ComponentKind.DATA_MODEL and dataset_id:
        document["runs"] = {
            f"{component_id}-run": {
                "instruments": ["INSTRUMENT_A", "INSTRUMENT_B"],
                "start": "2024-01-02T00:00:00+09:00",
                "end": "2024-12-31T23:00:00+09:00",
                "timezone": "Asia/Seoul",
                # A datamodel run has no execution table, so it names the dataset whose days
                # are its trading days (design §3.3).
                "agenda": {"every": "1d", "at": "16:00", "days_from": dataset_id},
                "writes": f"{component_id}-values",
                "datamodel": {
                    "component": component_id,
                    "value_fields": ["value"],
                },
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
            "exchange",
            "run",
            "sample",
        ),
        help=(
            "scaffold a component (datamodel/strategy/constraint) or emit a template "
            "(instruments/dataset/exchange/run). Component and "
            "exchange kinds write TWO files: the .py named by --out, and the .yaml beside it "
            "that registers it. Every kind reports the file to hand `vqapr register` as "
            "`declaration`; `run` emits the `runs:` declaration `vqapr run <run-id>` executes. "
            "`sample` writes a complete, runnable journey into the directory named by --out: "
            "a strategy, a venue, a synthetic panel and the one declaration registering them"
        ),
    )
    parser.add_argument(
        "component_id",
        nargs="?",
        default=None,
        help="identity of the new component (required for datamodel/strategy, unused for run)",
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
        # refuse. Found by the structural audit,
        # `docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md`, C3.
        default=None,
        help=(
            "rows of the table the model reads back -- the same N instants for every name, on "
            "a panel-grain dataset. Use --calendar-lookback for a window of N days, or "
            "--instants-lookback for each name's own last N reported instants on a rows-grain "
            "(vendor, long) dataset"
        ),
    )
    parser.add_argument(
        "--instants-lookback",
        dest="instants_lookback",
        type=int,
        default=None,
        help=(
            "scaffold a model that reads each name's own last N reported instants, per field, "
            "which is the window a rows-grain (vendor, long) dataset takes; on an unbalanced "
            "table the batch then spans whatever the sparsest name reaches back to"
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


def _run_template(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    target = args.out or project_root / "runs.yaml"
    refuse_existing(target, what="run declaration template")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_RUN_TEMPLATE, encoding="utf-8")
    # Registrable, since record `139`: a run is a `runs:` section of a declaration document, so
    # the file this emits is handed to `vqapr register` like every other template, and the run it
    # declares is then executed by id.
    return success("template.new", kind="run", path=str(target), declaration=str(target))


def _component(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    if not args.component_id:
        raise InputError(
            INCOMPLETE,
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
                INCOMPLETE,
                requirement="datamodel and strategy require --dataset",
                observed="--dataset not given",
            )
        _require_registered_dataset(args.dataset, project_root)
        # The surface reads the flags; the rule about which window a kind may declare
        # lives in `vqapr/authoring_lookback.py`. Record `114`.
        window = lookback_declaration(
            kind,
            rows=getattr(args, "lookback", None),
            calendar=getattr(args, "calendar_lookback", None),
            instants=getattr(args, "instants_lookback", None),
        )
        lookback, lookback_kind = window["lookback"], window["lookback_kind"]
        if not isinstance(lookback, int) or not isinstance(lookback_kind, str):
            raise RuntimeError("lookback_declaration answered with a window that is not (n, kind)")
        source = render(
            kind,
            args.component_id,
            dataset_id=args.dataset,
            field=args.field,
            lookback=lookback,
            lookback_kind=lookback_kind,
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
        _declaration(
            args.component_id,
            kind,
            target,
            object_name,
            dataset_id=getattr(args, "dataset", None),
        ),
        encoding="utf-8",
    )
    return success(
        "component.new",
        kind=str(kind),
        id=args.component_id,
        path=str(target),
        declaration=str(declaration),
        object_name=object_name,
    )




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
        VALUE_INVALID,
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
    # instead of branching on which of them happen to write two files (`docs/issues/archive/026`).
    return success(
        "template.new", kind="dataset", path=str(target), declaration=str(target)
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
        # it REQUIRES your execution dataset to carry that price. Preflight refuses the run by name
        # if it does not -- it will not quietly produce limit-unaware numbers. The venue-table
        # dataset a run fills against carries a trade price only by default, so this scaffold
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
    run template names `exchange:` as required. The author had to discover from refusals that
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
# id the dataset, the execution dataset and the fill table use. `kind` is one of `stock`, `etf`,
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


def _sample(args: argparse.Namespace, project_root: Path) -> dict[str, Any]:
    """Materialize the sample journey: the filled-in form beside the blank ones this verb emits.

    Every other kind gives a template the user completes with their own data; this one gives a
    strategy, a venue, a synthetic panel and the declaration that registers them, so a first
    `vqapr register` / `check` / `run` can happen before anything is authored (PRD §11.4,
    record `172`). The same function the package's own tests install the sample through.
    """
    target = args.out or project_root / "sample"
    if target.exists() and any(target.iterdir()):
        refuse_existing(target, what="sample directory")
    materialized = materialize_sample(target)
    declaration = materialized.declaration
    return success(
        "template.new",
        kind="sample",
        path=str(target),
        declaration=str(declaration),
        run_id=SAMPLE_RUN_ID,
        next=[
            f"vqapr register {declaration}",
            f"vqapr check {SAMPLE_RUN_ID}",
            f"vqapr run {SAMPLE_RUN_ID}",
        ],
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    if args.kind == "sample":
        return _sample(args, project_root)
    if args.kind == "instruments":
        return _instruments_template(args, project_root)
    if args.kind == "dataset":
        return _dataset_template(args, project_root)
    if args.kind == "exchange":
        return _exchange_template(args, project_root)
    if args.kind == "run":
        return _run_template(args, project_root)
    return _component(args, project_root)
