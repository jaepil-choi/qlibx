"""Templates emitted by `vqapr new`.

A template must **run as written**. A skeleton that raises on the first callback teaches nothing
and cannot be executed to see the shape of a result, so the emitted file is a complete working
Strategy with exactly one marked place to change.

The template deliberately knows nothing about listings, halts, or delistings. Tradability is an
execution-time fact the callback cannot observe (architecture §10, `docs/implementations/
013-halted-names-do-not-stop-a-rebalance.md`); eligibility falls out of whether the declared
lookback is present, and the venue publishes typed zero-dealt evidence for the rest.
"""

from __future__ import annotations

from vqapr.extension.component import ComponentKind

_STRATEGY_TEMPLATE = '''"""A long-only cross-sectional Strategy. Edit the marked signal line."""

from decimal import Decimal

from vqapr import authoring as va

LOOKBACK = {lookback}  # rows per name: a five-day return needs six observations, not five


class {class_name}(va.StrategyModel):
    """`{dataset_id}`.`{field}` over LOOKBACK rows; the momentum signal below is a placeholder."""

    def inputs(self):
        read = va.DatasetInput(
            dataset_id="{dataset_id}", fields=("{field}",), lookback=va.RowsLookback(rows=LOOKBACK)
        )
        return {{"{alias}": read}}  # the alias is YOUR name for this read; `call.read` takes it

    def decide(self, call):
        # One field as a window: instants x instruments, the same LOOKBACK instants for every name.
        window = call.read("{alias}", "{field}")
        history: dict[str, list[Decimal]] = {{}}
        for name in window.instruments:
            # `Decimal(str(v))`, never `Decimal(v)`: a float64 0.1 is not one tenth.
            history[name] = [Decimal(str(v)) for v in window.values[name] if v is not None]

        scores = {{}}
        for instrument, values in history.items():
            if len(values) >= LOOKBACK and values[0] > 0:
                # THE SIGNAL. Momentum: recent gain wins. Flip the sign for reversal.
                scores[instrument] = values[-1] / values[0] - 1

        chosen = {{name: score for name, score in scores.items() if score > 0}}
        if not chosen:
            return va.Hold(reason="no name scored above zero")  # prose; spaces are fine
        # Relative conviction: the package normalises, rounds and balances against cash.
        return va.Rebalance.of(long=chosen, invested="{invested}")

    # State across callbacks lives in `self.memory` (strict JSON, restored before every call).
    # A table of your own is DECLARED in `tables()` as a `va.TableSpec` before decide() writes it.
'''

_DATA_MODEL_TEMPLATE = '''"""A DataModel that derives one column from declared observations."""

from __future__ import annotations

from decimal import Decimal

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
{history_block}

        # ---- the one line to change -------------------------------------------------------
        # Trailing return over the declared lookback.
        derived = {{
            name: values[-1] / values[0] - Decimal(1)
            for name, values in history.items()
            if {completeness_guard}
        }}
        # -----------------------------------------------------------------------------------

        # One dict per instrument. The fields are the ones the materialization spec declares;
        # `available_at` is the package's to stamp and a row that carries one is refused.
        return [
            {{"instrument": name, "{output_field}": value}}
            for name, value in sorted(derived.items())
        ]
'''

_PANEL_HISTORY_BLOCK = """\
        # One field of the alias as a window: `instants` x `instruments`, the same instants for
        # every name. `window.values[name]` is that name's values over them, `None` where it had
        # none; `window.current()` is the cross-section at the last instant (a name with no row
        # there is absent), `window.latest()` the newest value per name anywhere in the window.
        window = context.read("{alias}", FIELD)
        history: dict[str, list[Decimal]] = {{}}
        for name in window.instruments:
            # `Decimal(str(v))` rather than `Decimal(v)`: a value keeps its parquet column's type,
            # so a DOUBLE column arrives as `float` and a DECIMAL one as `Decimal`, and arithmetic
            # mixing the two raises. Going through `str` also avoids inheriting the binary float's
            # expansion, so 0.1 stays 0.1.
            history[name] = [Decimal(str(v)) for v in window.values[name] if v is not None]"""

_ROWS_HISTORY_BLOCK = """\
        # A rows-grain (vendor, long) dataset streams observations: one per (instant, instrument),
        # ordered by `available_at`, each carrying its own `available_at` and `instrument_id`
        # alongside the fields declared above. Instruments INTERLEAVE within an instant.
        history: dict[str, list[Decimal]] = {{}}
        for row in context.rows("{alias}"):
            value = row.values[FIELD]
            if value is not None:
                # `Decimal(str(v))` rather than `Decimal(v)`: a value keeps its parquet column's
                # type, so a DOUBLE column arrives as `float` and a DECIMAL one as `Decimal`, and
                # arithmetic mixing the two raises. Going through `str` also avoids inheriting the
                # binary float's expansion, so 0.1 stays 0.1.
                history.setdefault(row.instrument_id, []).append(Decimal(str(value)))"""

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
        "history_block": _PANEL_HISTORY_BLOCK,
        "lookback_class": "RowsLookback",
        "lookback_declaration": (
            "LOOKBACK = {lookback}  # rows of the table: the same instants for every name"
        ),
        "lookback_expression": "va.RowsLookback(rows=LOOKBACK)",
        "completeness_guard": "len(values) == LOOKBACK",
        "lookback_note": _ROWS_LOOKBACK_NOTE,
    },
    "instants": {
        "history_block": _ROWS_HISTORY_BLOCK,
        "lookback_class": "InstantsLookback",
        "lookback_declaration": (
            "LOOKBACK = {lookback}  # instants per name, per field (grain: rows only)"
        ),
        "lookback_expression": "va.InstantsLookback(instants=LOOKBACK)",
        "completeness_guard": "len(values) == LOOKBACK",
        "lookback_note": _INSTANTS_LOOKBACK_NOTE,
    },
    "calendar": {
        "history_block": _PANEL_HISTORY_BLOCK,
        "lookback_class": "CalendarLookback",
        "lookback_declaration": (
            'LOOKBACK_DAYS = {lookback}  # calendar days, not sessions: a week is 7, not 5\n'
            'TIMEZONE = "Asia/Seoul"  # where the day boundary falls; use the venue\'s zone'
        ),
        "lookback_expression": "va.CalendarLookback(days=LOOKBACK_DAYS, timezone=TIMEZONE)",
        "completeness_guard": "len(values) >= 2",
        "lookback_note": _CALENDAR_LOOKBACK_NOTE,
    },
}
"""The three lookback members, and the four places in the template that differ between them.

One template rather than two files, because everything else about the two scaffolds is identical
and a second copy would drift. What differs is exactly what an author has to understand: which
class, what the number means, and which completeness guard follows from it (`docs/issues/033`).
"""

_CONSTRAINT_TEMPLATE = '''"""A Constraint capping how much of the book any one name may be.

The run spec offers a `constraints:` list and nothing said what went in it. Guessing `project`
wrong produces a backtest that looks correct and is not, so it is written out below rather than
left as a signature.

Edit `CAP`. Everything else runs as written.
"""

from decimal import Decimal

from vqapr import authoring as va

CAP = Decimal("{cap}")  # THE RULE. No single name may exceed this share of the book.
FLOOR = Decimal("0")

# A cap on SIZE, measured on absolute weight, so a -0.30 short is as much a violation as a +0.30
# long. It says nothing about sign: shorting within the cap is permitted here, and forbidding it
# is a separate rule. Constraints intersect -- lower bounds take the max, upper bounds the min --
# so declaring the shipped `no-short` alongside this gives long-only-with-a-cap without either
# rule knowing about the other.


class {class_name}(va.Constraint):
    """No single instrument may exceed `CAP` of the book, long or short.

    Two members, and they do different jobs. `project` says what is permitted, and construction
    does its best inside that. `monitor` says whether what you actually hold went over. A decision
    that goes over does not stop the run -- it is a breach, and this is where breaches are seen.
    """

    @property
    def constraint_id(self) -> str:
        """The id this constraint answers to.

        It must equal the id you register it under, character for character. Registration refuses
        a mismatch, so this is fixed to the id `vqapr new` was given rather than left as a string
        to keep in step by hand.
        """
        return "{component_id}"

    def inputs(self):
        """What this constraint reads. Nothing: the rule is a property of the weight.

        A constraint comparing against a benchmark would return a `va.DatasetInput` here, and
        `call.read("<your alias>", "<field>")` inside `project` would hand back its window --
        `current()` is the benchmark's weight per name at the window's last instant.
        """
        return {{}}

    def project(self, call) -> va.ConstraintBounds:
        """**The feasible set.** Return the lower and upper bound for EVERY instrument in
        `call.instruments`.

        Not the offenders, not a correction -- the box the optimiser must stay inside. Both bounds
        are mandatory for every name: a projection that misses one is refused, because a missing
        bound would silently widen the feasible set rather than fail.
        """
        return va.ConstraintBounds(
            lower_weights={{instrument: -CAP for instrument in call.instruments}},
            upper_weights={{instrument: CAP for instrument in call.instruments}},
        )

    def monitor(self, call, account: va.EconomicAccountView, bounds) -> va.ConstraintFinding:
        """Judge the book that was actually committed, after it was marked.

        This is the only member that judges. It sees what `project` could not: execution does not
        always fill what was intended, and rounding a weight into whole shares can push a position
        over a limit that the decision itself respected.
        """
        # `account.weights()` is each name's marked value over NAV. It refuses rather than
        # returning zeros when the account has not been marked, so an unmarked book cannot look
        # like a compliant one.
        weights = account.weights() if account.nav else {{}}
        offenders = tuple(sorted(name for name, w in weights.items() if abs(w) > CAP))
        worst = max((abs(w) for w in weights.values()), default=FLOOR)
        return va.ConstraintFinding(
            passed=not offenders,
            measured=worst,
            bound=CAP,
            excess=max(worst - CAP, FLOOR),
            details={{}},
            offenders=offenders,
        )
'''

_TEMPLATES = {
    ComponentKind.STRATEGY_MODEL: _STRATEGY_TEMPLATE,
    ComponentKind.DATA_MODEL: _DATA_MODEL_TEMPLATE,
    ComponentKind.CONSTRAINT: _CONSTRAINT_TEMPLATE,
}


def _class_name(component_id: str) -> str:
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
    kind: ComponentKind,
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
    StrategyModel are defined by what they read; a Constraint is a rule about weights, and the
    shipped `NoShort` returns an empty `requirements()` for exactly that reason. Requiring a
    dataset here would make the caller invent one to scaffold a rule that never opens it.

    `lookback_kind` selects which member of the lookback pair a DataModel declares. `rows` is the
    default because it is what this scaffold always emitted; `calendar` exists because the default
    is the wrong member for every cross-sectional model and there was no way to ask for the other
    one (`docs/issues/033`). The StrategyModel template takes `rows` only: its body counts
    observations per name, so a calendar window would leave the emitted guard meaningless.
    """
    if kind not in _TEMPLATES:
        raise ValueError(
            f"no template for {kind}; user authoring covers datamodel, strategy and constraint"
        )
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if lookback_kind not in _LOOKBACK_FLAVOURS:
        raise ValueError(f"lookback_kind must be one of: {', '.join(_LOOKBACK_FLAVOURS)}")
    if kind is ComponentKind.CONSTRAINT:
        return _TEMPLATES[kind].format(
            component_id=component_id,
            class_name=_class_name(component_id),
            cap=cap,
        )
    if dataset_id is None:
        raise ValueError(f"{kind.value} reads a dataset, so dataset_id is required")
    if kind is ComponentKind.STRATEGY_MODEL:
        if lookback_kind != "rows":
            raise ValueError(
                "the strategy scaffold declares a rows lookback: its signal counts observations "
                "per name. Scaffold it with the default and edit the requirement if you want a "
                "calendar window"
            )
        return _TEMPLATES[kind].format(
            component_id=component_id,
            class_name=_class_name(component_id),
            dataset_id=dataset_id,
            # The alias is the dataset id (`docs/issues/063`): a fixed `prices` read as a
            # required name to a first-time user, and described a read the flags did not ask for.
            alias=dataset_id,
            field=field,
            lookback=lookback,
            invested=invested,
            output_field=output_field,
        )
    flavour = _LOOKBACK_FLAVOURS[lookback_kind]
    return _TEMPLATES[kind].format(
        history_block=flavour["history_block"].format(alias=dataset_id),
        component_id=component_id,
        class_name=_class_name(component_id),
        dataset_id=dataset_id,
        alias=dataset_id,
        field=field,
        invested=invested,
        output_field=output_field,
        lookback_class=flavour["lookback_class"],
        lookback_declaration=flavour["lookback_declaration"].format(lookback=lookback),
        lookback_expression=flavour["lookback_expression"],
        completeness_guard=flavour["completeness_guard"],
        lookback_note=flavour["lookback_note"],
    )
