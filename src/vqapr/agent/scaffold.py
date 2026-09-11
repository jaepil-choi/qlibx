"""Templates emitted by `vqapr new`.

A template must **run as written**. A skeleton that raises on the first callback teaches nothing
and cannot be executed to see the shape of a result, so the emitted file is a complete working
Strategy with exactly one marked place to change.

The template deliberately knows nothing about listings, halts, or delistings. Tradability is an
execution-time fact the callback cannot observe (architecture §10, `docs/implementations/
013-halted-names-do-not-stop-a-rebalance.md`); eligibility falls out of whether the declared
lookback is present, and the venue publishes typed zero-dealt evidence for the rest.

Which lookback a kind's template may emit, and how much of it, is decided here too
(`lookback_declaration`): a template's guard has to mean something for the window it declares.
"""

from __future__ import annotations

from vqapr.domain.errors import VALUE_INVALID, InputError
from vqapr.domain.wiring import Role

__all__ = [
    "DECLARATION_KIND",
    "LOOKBACK_DEFAULT",
    "lookback_declaration",
    "render",
]


LOOKBACK_DEFAULT = 6
"""Rows of history the scaffold declares when the author does not say."""


DECLARATION_KIND = {
    Role.DATA_MODEL: "datamodel",
    Role.STRATEGY_MODEL: "strategy",
}
"""How each scaffoldable kind is spelled on the command line and in a declaration."""


def lookback_declaration(
    kind: Role, *, rows: int | None, calendar: int | None, instants: int | None = None
) -> dict[str, object]:
    """Which lookback the scaffold declares, and how much of it.

    Two flags rather than one with a unit suffix, because the two are different questions -- N rows
    per name, or N calendar days for everyone -- and a single `--lookback 313` cannot say which was
    meant. Giving both is refused rather than resolved by precedence: a reader should not have to
    know which flag wins to predict what their own command emits.

    Both kinds take rows or a calendar window; the scaffold emits the guard each window implies,
    so no guard counts observations against a number of days (`docs/issues/archive/033`). The
    strategy took rows only until record `251` -- while `vqapr new --help` and the strategy
    skill both pointed a day window at `--calendar-lookback`. `--instants-lookback` stays the
    datamodel's: a strategy reads a panel window.
    """
    given = {
        name: value
        for name, value in (
            ("--lookback", rows),
            ("--calendar-lookback", calendar),
            ("--instants-lookback", instants),
        )
        if value is not None
    }
    if len(given) > 1:
        raise InputError(
            VALUE_INVALID,
            requirement=(
                f"{' and '.join(given)} declare {'two' if len(given) == 2 else 'three'} "
                "different windows"
            ),
            observed=" and ".join(f"{name} {value}" for name, value in given.items()),
            retry=(
                "keep --lookback for the table's last N rows (a panel grain), --calendar-lookback "
                "for a window of N days every name shares, or --instants-lookback for each name's "
                "own last N reported instants (a rows grain); drop the others"
            ),
        )
    if instants is not None:
        if instants <= 0:
            raise InputError(
                VALUE_INVALID,
                requirement="--instants-lookback must be a positive number of instants",
                observed=f"--instants-lookback {instants}",
                retry="pass a positive number of instants per name, then retry",
            )
        if kind is not Role.DATA_MODEL:
            # The template refused this with a bare `ValueError`, which reached the envelope as
            # `unhandled` (record `251`).
            raise InputError(
                VALUE_INVALID,
                requirement="--instants-lookback applies to the datamodel scaffold",
                observed=f"--instants-lookback given for kind {DECLARATION_KIND[kind]}",
                retry=(
                    "scaffold the strategy with --lookback N (the table's last N rows) or "
                    "--calendar-lookback DAYS (a window of N days); each name's own last N "
                    "reported instants are a rows-grain read, which a datamodel makes"
                ),
            )
        return {"lookback": instants, "lookback_kind": "instants"}
    if calendar is None:
        return {
            "lookback": LOOKBACK_DEFAULT if rows is None else rows,
            "lookback_kind": "rows",
        }
    if calendar <= 0:
        raise InputError(
            VALUE_INVALID,
            requirement="--calendar-lookback must be a positive number of days",
            observed=f"--calendar-lookback {calendar}",
            retry="pass a positive number of calendar days, then retry",
        )
    return {"lookback": calendar, "lookback_kind": "calendar"}


_STRATEGY_TEMPLATE = '''"""A long-only cross-sectional Strategy. Edit the marked signal line.

Every other piece a strategy reaches for is shown where it goes: a second dataset (in `inputs`),
state across callbacks (`self.memory`), and a table of your own (`tables` and `self.recorder`).
"""

import numpy as np

from vqapr import authoring as va

{lookback_declaration}
DECISIONS = "decisions"  # a table of your own; `vqapr export` writes it as tables/decisions.csv


class {class_name}(va.StrategyModel):
    """`{dataset_id}`.`{field}` over {window_words}; the momentum signal below is a placeholder."""

    def inputs(self):
        read = va.DatasetInput(
            dataset_id="{dataset_id}", fields=("{field}",), lookback={lookback_expression}
        )
        # A second dataset is a second entry under an alias of its own, read the same way. For one
        # value per name at the decision -- an index weight, a bool flag -- use
        # `call.read(alias, field).current()` (name -> value); `matrix()` is for numeric windows.
        #   "bench": va.DatasetInput(dataset_id="<id>", fields=("weight",), lookback=<as above>),
        return {{"{alias}": read}}  # the alias is YOUR name for this read; `call.read` takes it

    def tables(self):
        # Every table decide() writes, with its exact fields; each row's time is stamped for you.
        return (va.TableSpec(DECISIONS, ("instrument", "action", "score")),)

    def decide(self, call):
        # One field as a window: instants x instruments, {window_comment}.
        window = call.read("{alias}", "{field}")
        # The window as one float array (rows: instants, newest last; columns: `window.instruments`;
        # NaN where a name had no value), so the signal is one expression over every name at once.
        closes = window.matrix()
{signal_block}
        names = window.instruments
        chosen = {{name: scores[j] for j, name in enumerate(names) if full[j] and scores[j] > 0}}
        if not chosen:
            return va.Hold(reason="no name scored above zero")  # prose; spaces are fine
        # State across callbacks: `self.memory` is strict JSON, restored before every call and kept
        # after it. One instance serves the whole run, so never keep state anywhere else.
        held = set(self.memory.get("held", []))
        self.memory["held"] = sorted(chosen)
        # Log what was DECIDED. What a fill did -- its price, quantity and cost -- is in
        # `vqapr.fill` (`vqapr export` writes fills.csv): a fill comes after its callback, and no
        # callback follows the run's last fill, so a fill logged from here is lost at the end.
        for name in sorted(held ^ set(chosen)):
            action = "enter" if name in chosen else "exit"
            self.recorder.append(
                DECISIONS, {{"instrument": name, "action": action, "score": chosen.get(name)}}
            )
        # Relative conviction: the package normalises, rounds and balances against cash. A name
        # left out of `long` is sold.
        return va.Rebalance.of(long=chosen, invested="{invested}")
'''


_STRATEGY_ROWS_SIGNAL = """\
        if closes.shape[0] < LOOKBACK:
            return va.Hold(reason="fewer than LOOKBACK sessions in the window")
        full = np.isfinite(closes).all(axis=0) & (closes[0] > 0)  # a complete window, per name
        with np.errstate(divide="ignore", invalid="ignore"):
            # THE SIGNAL. Momentum: recent gain wins. Flip the sign for reversal.
            scores = closes[-1] / closes[0] - 1.0"""


_STRATEGY_CALENDAR_SIGNAL = """\
        if closes.shape[0] < 2:
            return va.Hold(reason="fewer than two sessions in the window")
        # A calendar window promises a date range, not a row count: a name that did not trade on
        # every session has fewer values inside it. So the return runs from each name's first
        # observed value in the window to its newest, and a name needs two of them.
        finite = np.isfinite(closes)
        columns = np.arange(closes.shape[1])
        first = closes[finite.argmax(axis=0), columns]
        newest = closes[closes.shape[0] - 1 - finite[::-1].argmax(axis=0), columns]
        full = (finite.sum(axis=0) >= 2) & (first > 0)  # two observed values, per name
        with np.errstate(divide="ignore", invalid="ignore"):
            # THE SIGNAL. Momentum: recent gain wins. Flip the sign for reversal.
            scores = newest / first - 1.0"""


_STRATEGY_FLAVOURS = {
    "rows": {
        "lookback_declaration": (
            "LOOKBACK = {lookback}  # rows of the window: a five-day return needs six "
            "observations, not five"
        ),
        "window_words": "LOOKBACK rows",
        "lookback_expression": "va.RowsLookback(rows=LOOKBACK)",
        "window_comment": "the same LOOKBACK instants for every name",
        "signal_block": _STRATEGY_ROWS_SIGNAL,
    },
    "calendar": {
        "lookback_declaration": (
            "LOOKBACK_DAYS = {lookback}  # calendar days, not sessions: a year is 365, not 252\n"
            'TIMEZONE = "Asia/Seoul"  # where the day boundary falls; use the venue\'s zone'
        ),
        "window_words": "the last LOOKBACK_DAYS calendar days",
        "lookback_expression": "va.CalendarLookback(days=LOOKBACK_DAYS, timezone=TIMEZONE)",
        "window_comment": "every instant of the last LOOKBACK_DAYS days",
        "signal_block": _STRATEGY_CALENDAR_SIGNAL,
    },
}
"""The two windows the strategy scaffold declares (record `251`), and what differs between them.

A rows window is the table's last N instants for every name, so a complete window is N finite
values and the return runs from the first row to the last. A calendar window is a date range, so
the guard asks for two observed values and the return runs from each name's first to its newest
(`docs/issues/archive/033` is why the guard must follow the window). The rows text is what the
scaffold always emitted, byte for byte.
"""


_DATA_MODEL_TEMPLATE = '''"""A DataModel that derives one column from declared observations."""

from __future__ import annotations

{imports}

from vqapr import authoring as va

DATASET_ID = "{dataset_id}"
FIELD = "{field}"
{lookback_declaration}


class {class_name}(va.DataModel):
    """Derives one value per instrument from `{field}` of `{dataset_id}`, each session.

    The example below is a trailing return and is a placeholder: replace the marked block, and
    this docstring, with what this model actually computes.
    """

    def inputs(self):
        read = va.DatasetInput(
            dataset_id=DATASET_ID, fields=(FIELD,), lookback={lookback_expression}
        )
        return {{"{alias}": read}}  # the alias is YOUR name for this read; `context.read` takes it

    def compute(self, context):
{lookback_note}
{body_block}

        # One dict per instrument. The fields are the ones the materialization spec declares;
        # `available_at` is the package's to stamp and a row that carries one is refused.
        # The value crosses back to `float`: a dataset field is DOUBLE, never DECIMAL (record
        # 173), and the first session's row types the output for every later one.
        return [
            {{"instrument": name, "{output_field}": float(value)}}
            for name, value in sorted(derived.items())
        ]
'''


_PANEL_BODY_BLOCK = """\
        # One field of the alias as a window: `instants` x `instruments`, the same instants for
        # every name. `window.matrix()` is that window as one float array -- rows are instants
        # (the last row is the newest), columns are `window.instruments`, NaN where a name had no
        # value -- so the computation below is one expression over every name at once.
        # `window.current()` is the cross-section at the last instant (a name with no row there
        # is absent), `window.latest()` the newest value per name anywhere in the window.
        window = context.read("{alias}", FIELD)
        values = window.matrix()
        if values.shape[0] == 0:
            return []  # nothing observed yet: this session contributes no row
        finite = np.isfinite(values)
        columns = np.arange(values.shape[1])
        # Each name's first and newest observed value inside the window.
        first = values[finite.argmax(axis=0), columns]
        newest = values[values.shape[0] - 1 - finite[::-1].argmax(axis=0), columns]
        # A name is eligible only where the window is complete: {completeness_guard}.
        eligible = ({eligibility}) & (first > 0)

        # ---- the one line to change -------------------------------------------------------
        # Trailing return over the declared lookback, for every name at once.
        with np.errstate(divide="ignore", invalid="ignore"):
            signal = newest / first - 1.0
        # -----------------------------------------------------------------------------------

        derived = {{
            name: float(signal[column])
            for column, name in enumerate(window.instruments)
            if eligible[column]
        }}"""


_ROWS_BODY_BLOCK = """\
        # A rows-grain (vendor, long) dataset streams observations: one per (instant, instrument),
        # ordered by `available_at`, each carrying its own `available_at` and `instrument_id`
        # alongside the fields declared above. Instruments INTERLEAVE within an instant, and
        # there is no shared instant axis, so the reduction is per name.
        history: dict[str, list[Decimal]] = {{}}
        for row in context.rows("{alias}"):
            value = row.values[FIELD]
            if value is not None:
                # A DOUBLE field arrives as `float`, as the dataset declared it. The intent
                # below is stated in Decimal, so cross once here and through `str`:
                # `Decimal(0.1)` inherits the binary float's expansion, `Decimal("0.1")` is one
                # tenth.
                history.setdefault(row.instrument_id, []).append(Decimal(str(value)))

        # ---- the one line to change -------------------------------------------------------
        # Trailing return over the declared lookback.
        derived = {{
            name: values[-1] / values[0] - Decimal(1)
            for name, values in history.items()
            if {completeness_guard}
        }}
        # -----------------------------------------------------------------------------------"""


_ROWS_LOOKBACK_NOTE = """\
        #
        # This model declares a ROWS lookback on a panel-grain dataset, so the window is the
        # table's last N rows -- the same N instants for every name. A name that stopped
        # publishing contributes fewer values inside it rather than reaching further back, which
        # is what makes a cross-section built from this window safe. The reduction below is still
        # per instrument because a trailing return is a per-name question; the guard asks for a
        # full window. A calendar period instead of a row count is `--calendar-lookback DAYS`;
        # per-name counting (each name's own last N reported instants) is `InstantsLookback`
        # and belongs to a `grain: rows` dataset: `--instants-lookback N`."""


_INSTANTS_LOOKBACK_NOTE = """\
        #
        # This model declares an INSTANTS lookback on a rows-grain (vendor, long) dataset, so
        # the window is each name's own last N reported instants: on an unbalanced table a
        # sparse name reaches further back than a liquid one, and the batch's calendar span is
        # set by the sparsest of them. That is why the reduction below is per instrument. A
        # CROSS-SECTIONAL model -- anything comparing names on the same dates -- must not be
        # written on this grain: register the table as `grain: instrument_instant` (or derive
        # one from it) and read it with `RowsLookback` or `CalendarLookback` instead."""


_CALENDAR_LOOKBACK_NOTE = """\
        #
        # This model declares a CALENDAR lookback, so every name is read over the same date range
        # and a sparse name simply contributes fewer rows inside it. That is what makes a
        # cross-section safe to build: group rows by `available_at` to get one date's observations
        # across the universe. The reduction below is still per instrument, because a trailing
        # return is a per-name question; the guard is on having two observations rather than on a
        # row count, since a calendar window does not promise one."""


_LOOKBACK_FLAVOURS = {
    "rows": {
        "body_block": _PANEL_BODY_BLOCK,
        "imports": "import numpy as np",
        "lookback_class": "RowsLookback",
        "lookback_declaration": (
            "LOOKBACK = {lookback}  # rows of the table: the same instants for every name"
        ),
        "lookback_expression": "va.RowsLookback(rows=LOOKBACK)",
        "completeness_guard": "LOOKBACK rows, every one a number",
        "eligibility": "finite.all(axis=0) & (values.shape[0] == LOOKBACK)",
        "lookback_note": _ROWS_LOOKBACK_NOTE,
    },
    "instants": {
        "body_block": _ROWS_BODY_BLOCK,
        "imports": "from decimal import Decimal",
        "lookback_class": "InstantsLookback",
        "lookback_declaration": (
            "LOOKBACK = {lookback}  # instants per name, per field (grain: rows only)"
        ),
        "lookback_expression": "va.InstantsLookback(instants=LOOKBACK)",
        "completeness_guard": "len(values) == LOOKBACK",
        "eligibility": "",
        "lookback_note": _INSTANTS_LOOKBACK_NOTE,
    },
    "calendar": {
        "body_block": _PANEL_BODY_BLOCK,
        "imports": "import numpy as np",
        "lookback_class": "CalendarLookback",
        "lookback_declaration": (
            "LOOKBACK_DAYS = {lookback}  # calendar days, not sessions: a week is 7, not 5\n"
            'TIMEZONE = "Asia/Seoul"  # where the day boundary falls; use the venue\'s zone'
        ),
        "lookback_expression": "va.CalendarLookback(days=LOOKBACK_DAYS, timezone=TIMEZONE)",
        "completeness_guard": "at least two observed values",
        "eligibility": "finite.sum(axis=0) >= 2",
        "lookback_note": _CALENDAR_LOOKBACK_NOTE,
    },
}
"""The three lookback members, and the places in the template that differ between them.

A panel grain reads its window as a matrix (record `233`) and the two panel flavours differ only
in what makes a name eligible; the rows grain has no shared instant axis and keeps the per-name
reduction over `Decimal`s.

One template rather than two files, because everything else about the two scaffolds is identical and
a second copy would drift. What differs is exactly what an author has to understand: which class,
what the number means, and which completeness guard follows from it (`docs/issues/archive/033`).
"""


_COMPLIANCE_TEMPLATE = '''"""A Compliance rule reporting any name above `CAP` of the book.

A rule observes. It does not shape the portfolio -- the strategy does that itself, calling the
box kit (`no_short`, `single_name_cap`, `intersect`) before `Rebalance`. What a rule
does is look at the book the venue actually left, at every instant of the market clock, right
after it is marked, and say whether it is inside the limit this rule watches. A breach never
stops the run; it is recorded, named, in `vqapr.monitoring`.

Edit `CAP`. Everything else runs as written.
"""

from decimal import Decimal

from vqapr import authoring as va

CAP = Decimal("{cap}")  # THE RULE. No single name may exceed this share of the book.
FLOOR = Decimal("0")

# A cap on SIZE, measured on absolute weight, so a -0.30 short is as much a finding as a +0.30
# long. It says nothing about sign: reporting a short is the shipped `no-short` rule's job, and a
# run may declare both under `compliance:`.


class {class_name}(va.Compliance):
    """No single instrument may exceed `CAP` of the marked book, long or short.

    The rule's parameters are its own. It does not inherit the cap the strategy built inside --
    a watcher that inherits the target of the thing it watches is grading itself -- so the two
    numbers may differ, and their differing is what the report shows.
    """

    @property
    def compliance_id(self) -> str:
        """The id this rule answers to.

        It must equal the id you register it under, character for character. Registration refuses
        a mismatch, so this is fixed to the id `vqapr new` was given rather than left as a string
        to keep in step by hand.
        """
        return "{component_id}"

    def inputs(self):
        """What this rule reads. Nothing: the limit is a property of the weight itself.

        A rule comparing against a benchmark would return a `va.DatasetInput` here, and
        `call.read("<your alias>", "<field>")` inside `observe` would hand back its window as of
        the instant observed -- `latest()` is the benchmark's newest weight per name.
        """
        return {{}}

    def observe(self, call: va.ComplianceCall) -> va.ComplianceFinding:
        """Judge the book that was actually committed, after it was marked.

        Execution does not always fill what was intended, and rounding a weight into whole shares
        can push a position over a limit that the decision itself respected. Compare strictly:
        the framework judges the excess against its tolerance, once, for every rule.
        """
        # `call.account.weights()` is each name's marked value over NAV. It refuses rather than
        # returning zeros when the call.account has not been marked, so an unmarked book cannot look
        # like a compliant one.
        weights = call.account.weights() if call.account.nav else {{}}
        offenders = tuple(sorted(name for name, w in weights.items() if abs(w) > CAP))
        worst = max((abs(w) for w in weights.values()), default=FLOOR)
        return va.ComplianceFinding(
            passed=not offenders,
            measured=worst,
            bound=CAP,
            excess=max(worst - CAP, FLOOR),
            details={{}},
            offenders=offenders,
        )
'''


_TEMPLATES = {
    Role.STRATEGY_MODEL: _STRATEGY_TEMPLATE,
    Role.DATA_MODEL: _DATA_MODEL_TEMPLATE,
    Role.COMPLIANCE: _COMPLIANCE_TEMPLATE,
}


def class_name_for(component_id: str) -> str:
    """The class a scaffold declares, or a refusal naming what an id may contain.

    Title-casing the hyphen-separated parts is not enough on its own: it accepted ids that cannot
    be Python identifiers -- a leading digit, punctuation -- and emitted them verbatim into the
    source, where the file failed to parse and surfaced as `stage: "unhandled"` with a raw
    `SyntaxError`. The id is checked here, before anything is written, because this is the one
    place that knows what it has to become.
    """
    parts = [part for part in component_id.replace("_", "-").split("-") if part]
    if not parts:
        raise ValueError("component_id must contain at least one alphanumeric part")
    import keyword

    candidate = "".join(part[:1].upper() + part[1:] for part in parts)
    # `isidentifier()` is lexical shape only and returns True for keywords. `None`, `True` and
    # `False` are already title-case, so the transformation leaves them untouched and they reach
    # the emitted source as a class name that will not parse. Lowercase keywords are safe only by
    # accident -- `class` becomes `Class` -- which is not a property to rely on.
    if not candidate.isidentifier() or keyword.iskeyword(candidate):
        raise ValueError(
            f"component_id {component_id!r} cannot name a Python class: it becomes "
            f"{candidate!r}, which is not a usable identifier. Use letters, digits, hyphens and "
            f"underscores, starting with a letter, and avoid Python keywords -- for example "
            f"'position-cap'"
        )
    return candidate


def render(
    kind: Role,
    component_id: str,
    *,
    dataset_id: str | None = None,
    field: str = "close",
    lookback: int = 6,
    lookback_kind: str = "rows",
    invested: str = "0.9",
    output_field: str = "value",
    cap: str = "0.2",
) -> str:
    """Return a runnable component source for `kind`.

    `dataset_id` is optional because not every authored kind reads one. A DataModel and a
    StrategyModel are defined by what they read; a Compliance rule is a rule about the book, and
    the shipped `NoShort` returns an empty `requirements()` for exactly that reason. Requiring a
    dataset here would make the caller invent one to scaffold a rule that never opens it.

    `lookback_kind` selects which member of the lookback pair a DataModel declares. `rows` is the
    default because it is what this scaffold always emitted; `calendar` exists because the default
    is the wrong member for every cross-sectional model and there was no way to ask for the other
    one (`docs/issues/archive/033`). The StrategyModel template takes `rows` or `calendar`, each
    with the guard its window implies (record `251`): it took `rows` only, while the strategy
    skill told authors to scaffold a day window with `--calendar-lookback`, and three of three
    agents building a 12-month momentum were refused
    (`docs/issues/report-2026-09-11-new-help-points-a-strategy-at-calendar-lookback-...`).

    A panel-grain body computes on `window.matrix()` -- one float array over every name -- and a
    rows-grain body reduces per name (record `233`, `docs/issues/096`).
    """
    if kind not in _TEMPLATES:
        raise ValueError(
            f"no template for {kind}; user authoring covers datamodel, strategy and compliance"
        )
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if lookback_kind not in _LOOKBACK_FLAVOURS:
        raise ValueError(f"lookback_kind must be one of: {', '.join(_LOOKBACK_FLAVOURS)}")
    if kind is Role.COMPLIANCE:
        return _TEMPLATES[kind].format(
            component_id=component_id,
            class_name=class_name_for(component_id),
            cap=cap,
        )
    if dataset_id is None:
        raise ValueError(f"{kind.value} reads a dataset, so dataset_id is required")
    if kind is Role.STRATEGY_MODEL:
        if lookback_kind not in _STRATEGY_FLAVOURS:
            raise ValueError(
                "the strategy scaffold declares a rows or a calendar lookback; each name's own "
                "last N reported instants are a rows-grain read, which a datamodel scaffolds"
            )
        window = _STRATEGY_FLAVOURS[lookback_kind]
        return _TEMPLATES[kind].format(
            component_id=component_id,
            class_name=class_name_for(component_id),
            dataset_id=dataset_id,
            # The alias is the dataset id (`docs/issues/archive/063`): a fixed `prices` read as a
            # required name to a first-time user, and described a read the flags did not ask for.
            alias=dataset_id,
            field=field,
            invested=invested,
            output_field=output_field,
            lookback_declaration=window["lookback_declaration"].format(lookback=lookback),
            window_words=window["window_words"],
            lookback_expression=window["lookback_expression"],
            window_comment=window["window_comment"],
            signal_block=window["signal_block"],
        )
    flavour = _LOOKBACK_FLAVOURS[lookback_kind]
    return _TEMPLATES[kind].format(
        body_block=flavour["body_block"].format(
            alias=dataset_id,
            completeness_guard=flavour["completeness_guard"],
            eligibility=flavour["eligibility"],
        ),
        imports=flavour["imports"],
        component_id=component_id,
        class_name=class_name_for(component_id),
        dataset_id=dataset_id,
        alias=dataset_id,
        field=field,
        invested=invested,
        output_field=output_field,
        lookback_class=flavour["lookback_class"],
        lookback_declaration=flavour["lookback_declaration"].format(lookback=lookback),
        lookback_expression=flavour["lookback_expression"],
        lookback_note=flavour["lookback_note"],
    )
