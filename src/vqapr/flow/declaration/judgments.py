"""The judgments a run must pass, owned by neither verb that asks them.

These answer one question -- is this run worth starting? -- and both `check` and `run` need the
answer. They lived in `cli/check.py` because `check` was built on top of `run`'s spec vocabulary and
so the judgments landed in the verb that needed them first. That left `run` executing what `check`
would refuse: a real look-ahead ran to completion, wrote a permanent record, and appeared beside
legitimate runs with nothing marking it (`docs/issues/archive/015`).

Moving them here is what makes a single answer possible. The module sits below the CLI and imports
nothing from it, so both verbs can reach the same judgments without either importing the other.

**Judged on a `RunDefinition` since record `139`.** A run is a registered declaration rather than
a spec file, so the judgments read the definition the workspace holds -- and each of its strategies
is judged in turn, since one run now names several.

`judgments` returns its blocked list rather than filling a caller-supplied one. The out-parameter
it replaced was easy to forget -- and forgetting it means a run whose judgment could not ANSWER
reports as clean, which is the divergence this module exists to close, reproduced one layer down.

**No helper in this module catches on behalf of a judge** (`docs/issues/archive/077`). Five of them
did, and returned an empty result, which `judgments` cannot tell from "asked the question, found
nothing wrong" -- so `check` reported `passed: [..., "judgments"]` on a run whose look-ahead
judgment never ran, with `blocked` empty. Every judge here therefore lets its exception reach the
one wrapper below that owns the decision. The defect is then named twice, once as a blocked judgment
and once as preflight's own refusal, and that is deliberate: they are two different statements, one
saying the question could not be asked and the other saying what is wrong (owner decision,
2026-09-04).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from difflib import get_close_matches
from typing import Any

from vqapr.account.account import AccountMode
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError, status_of

# Through `extension/`, not `_internal/`, matching `flow/declaration/preflight.py:27-28` and
# `flow/materialize.py:30`. Two names for one authority is how a later deletion of the
# adapters misses a caller (`docs/issues/archive/029`).
from vqapr.extension.loading import load_data_model, load_strategy_model
from vqapr.flow.declaration.preflight import RunFacts
from vqapr.flow.declaration.roster import absent_roster_failure
from vqapr.project.run import FINGERPRINT_PREFIX, RunDefinition

# `vqapr.project.store`, not `vqapr.public`. The facade is the CLI's supported surface and sits
# ABOVE this layer; a module under `flow/` importing it reaches back up through the thing it is
# supposed to sit beneath. `flow/declaration/preflight.py` takes the same class from the same
# place, and the boundary tripwire in `docs/design/agent-first-surface.md` counts modules that do
# otherwise.
from vqapr.project.store import Workspace

__all__ = [
    "JUDGMENT_BLOCKED",
    "JUDGMENT_CODES",
    "JUDGMENT_STAGE",
    "judgments",
]

JUDGMENT_STAGE = Stage.CHECK
"""The stage a refused judgment is reported under, by every door that asks them."""

# One constant per code, and each judge below raises through its constant rather than through a
# literal of its own. `cli/check.py` publishes the set of codes this verb can emit, and when that
# set was a hand-written copy of the literals here it drifted: a ninth judge was added and the copy
# still said eight. `JUDGMENT_CODES` is the only list, `check` imports it, and a test over this
# module's source holds every code literal to membership in it -- so the next judge added without
# a line here fails the suite rather than the reader. Record `171`: the codes lost their `check.`
# prefix; `status` says who must act and `stage` (CHECK) says which operation was under way.
UNIVERSE_ABSENT = "universe.absent"
ROSTER_ABSENT = "roster.absent"
PERIOD_UNCOVERED = "period.uncovered"
EXECUTION_NOT_AFTER_DECISION = "execution.not_after_decision"
FIELD_ABSENT = "field.absent"
LOOKBACK_UNCOVERED = "lookback.uncovered"
DATASET_UNREGISTERED = "dataset.unregistered"
WEIGHTS_MODE_CONFLICT = "weights.mode_conflict"
WEIGHTS_VENUE_CONFLICT = "weights.venue_conflict"
RUN_OUTPUT_REGISTERED = "run.output_registered"
RUN_OUTPUT_STALE = "run.output_stale"

JUDGMENT_CODES = (
    UNIVERSE_ABSENT,
    ROSTER_ABSENT,
    PERIOD_UNCOVERED,
    EXECUTION_NOT_AFTER_DECISION,
    FIELD_ABSENT,
    LOOKBACK_UNCOVERED,
    DATASET_UNREGISTERED,
    WEIGHTS_MODE_CONFLICT,
    WEIGHTS_VENUE_CONFLICT,
    RUN_OUTPUT_REGISTERED,
    RUN_OUTPUT_STALE,
)
"""Every code `judgments` can emit, in the order the judges run and raise them.

Each is a question a run must answer YES to before it starts, asked independently of the others
-- and of every strategy the run names -- so a declaration with four defects reports four refusals
rather than the first one four times. `check` renders these as failures; `run` refuses on them.
"""

JUDGMENT_BLOCKED = "judgment.blocked"
"""The code of a judgment that could not ANSWER, whichever door asked.

Not in `JUDGMENT_CODES`: it is not a judgment. `judgments` builds one such failure per judge that
raised, carrying the exception whole in `cause` and its status by whose frame raised; `check`
reports them AS blocked and `verify.RunVerdict.require_frozen` (`preflight_run`, hence `run`
and the sample's `execute`) refuses on them beside the refusals proper.
"""


def judgments(
    definition: RunDefinition, workspace: Workspace, facts: RunFacts | None = None
) -> tuple[list[Failure], list[Failure]]:
    """The judgments (`JUDGMENT_CODES`), each answered independently of the others, for every
    strategy: `(found, blocked)`.

    Independence is the whole design: each judge reads the definition and the workspace and
    answers on its own, so a run carrying four defects produces four refusals in a single call.
    Within the dataset judge a later code is gated behind an earlier one -- an absent dataset
    suppresses the field and lookback questions about it, because there is nothing to ask them of
    -- and each such gate carries its own reason.

    A judgment that could not ANSWER is returned as a `JUDGMENT_BLOCKED` failure in the second
    list, carrying the exception whole in `cause` and a status that says whose fault it is, so a
    framework bug reads differently from a routine decline. It is never reported as passing, and
    `ok` is false while anything is blocked.
    """
    found: list[Failure] = []
    blocked: list[Failure] = []
    at = FailureSource(key_path=f"runs.{definition.run_id}")
    registered = {str(item.dataset_id): item for item in workspace.datasets}
    # The run's facts, each read at most ONCE for every judge that reads it -- and for the
    # freeze that follows, when the caller hands the same `facts` to both (`verify.verify_run`).
    # `docs/issues/archive/069` made the agenda one derivation rather than one per judge; record
    # `241` makes every fact so. Reached through a CALL rather than handed over as a value: a
    # failure to read it has to land inside the per-judge wrapper below, where it becomes a
    # blocked entry for each judge that needed it. Flattening it to `None` here was
    # `docs/issues/archive/077` -- the judges read `None` as "nothing to report" and the run was
    # reported as judged.
    read = facts if facts is not None else RunFacts(workspace, definition)

    judges: tuple[tuple[str, Callable[[], list[Failure]]], ...] = (
        ("universe", lambda: _judge_universe(definition, at)),
        ("roster", lambda: _judge_roster(definition, workspace, at)),
        ("period", lambda: _judge_period(definition, at)),
        (
            "execution_ordering",
            lambda: _judge_execution_ordering(definition, at, read),
        ),
        # ONE judge per member, NAMED for the member it judges. Two reasons, both from
        # `docs/issues/archive/077`. A member whose component does not load blocks its own entry and
        # no other -- this verb promises every INDEPENDENT problem at once, and one member failing
        # to load says nothing about another member's datasets. And the name is where the reader
        # learns WHICH member: a blocked entry carries the exception's own text, and `VqaprError:
        # component object must load and construct` does not say whose. Default arguments rather
        # than closure capture -- a lambda reading the loop variable would hand every member the
        # last one.
        *(
            (
                f"datasets[{member[1].component_id}]",
                lambda member=member: _judge_member_datasets(
                    definition, member, workspace, registered, at, read
                ),
            )
            for member in _members(definition)
        ),
        ("weights", lambda: _judge_weights(definition, at, read)),
        ("outputs", lambda: _judge_outputs(definition, registered, at, workspace)),
    )
    for name, judge in judges:
        try:
            found.extend(judge())
        except Exception as error:
            # One judgment failing to ANSWER must not silence the others -- letting the exception
            # abort the loop would quietly restore the stop-at-first behaviour this verb exists to
            # replace. But swallowing it silently is the worse half of that trade: the judgment
            # did not find nothing, it could not look, and a run nothing was proven about would
            # then report as clean and ready. So it is recorded as BLOCKED, with the exception
            # whole in `cause`. Its status is the refusal's own when the framework declined to
            # answer (a `VqaprError` already says who must act: an unregistered dataset is the
            # submission's 404, not the framework's 500), and by whose frame raised otherwise --
            # a `KeyError` from inside this module is almost certainly this verb being wrong.
            status = error.status if isinstance(error, VqaprError) else status_of(error)
            blocked.append(
                Failure.bounded(
                    JUDGMENT_BLOCKED,
                    "every judgment answers before a run is accepted",
                    status=status,
                    observed=f"{name} could not answer: {type(error).__name__}: {error}",
                    fix=(
                        f"run `vqapr check {definition.run_id}` to see the full report, then fix "
                        "what stopped the judgment from answering; the exception is in `cause`"
                    ),
                    cause=error,
                    source=at,
                )
            )
    return found, blocked


def _key(at: FailureSource, *path: str) -> FailureSource:
    return replace(at, key_path=".".join((at.key_path or "", *path)).strip("."))


def _judge_universe(definition: RunDefinition, at: FailureSource) -> list[Failure]:
    """A run with no instruments has nothing to decide about.

    A `RunDefinition` refuses an empty universe at construction, so a registered run cannot reach
    this with none; the judgment stays because `check` publishes `JUDGMENT_CODES` as the questions
    it asks, and a reader counting them should find each one asked.
    """
    if definition.instruments:
        return []
    return [
        Failure.bounded(
            UNIVERSE_ABSENT,
            "a run must declare at least one instrument to decide about",
            observed=f"instruments: {definition.instruments!r}",
            fix="list the instrument ids the run trades under `instruments:` in the run",
            status=Status.MISSING,
            source=_key(at, "instruments"),
        )
    ]


def _judge_roster(
    definition: RunDefinition, workspace: Workspace, at: FailureSource
) -> list[Failure]:
    """A strategy run over a project that has declared no instrument cannot fill an order.

    Design §6.3, the preflight half asked here so `check` reports it beside the run's other
    defects: zero declarations means no order can succeed, so there is no reason to run. A
    datamodel run orders nothing and is not asked. Only the pointer is read; the tables are read
    once, at run start.
    """
    if definition.strategy is None or workspace.registered_instruments() is not None:
        return []
    return [absent_roster_failure(definition.run_id, source=_key(at, "exchange"))]


def _instant(value: object) -> datetime | None:
    """One declared timestamp as an aware instant. `None` ONLY when nothing was declared.

    Comparing these as STRINGS is wrong in both directions, and quietly. `2024-01-02T00:00:00+09:00`
    sorts after `2024-01-01T20:00:00+00:00` while being five hours EARLIER, so a valid period reads
    as reversed and `check` refuses what `run` accepts -- a gate contradicting the thing it gates.

    A value that IS declared but is not an aware instant raises, and the judgment that asked for it
    blocks (`docs/issues/archive/077`). Returning `None` for it read, at the call site, as "nothing
    was declared" -- so a dataset whose span could not be parsed left the lookback question silently
    unasked and the judgment reported as passed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"declared timestamp {value.isoformat()} carries no offset")
        return value
    if not isinstance(value, str):
        raise TypeError(f"declared timestamp must be a datetime or an ISO-8601 string: {value!r}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"declared timestamp {value!r} carries no offset")
    return parsed


def _judge_period(definition: RunDefinition, at: FailureSource) -> list[Failure]:
    """The declared period must be a real interval, not a point or a reversal."""
    start, end = definition.start, definition.end
    if start is None or end is None:
        return [
            Failure.bounded(
                PERIOD_UNCOVERED,
                "a run must declare both start and end so its period is bounded",
                observed=f"start={start!r}, end={end!r}",
                fix="declare both start and end as ISO-8601 timestamps with an explicit offset",
                status=Status.PRECONDITION,
                source=_key(at, "start" if start is None else "end"),
            )
        ]
    if start >= end:
        return [
            Failure.bounded(
                PERIOD_UNCOVERED,
                "a run's end must be later than its start",
                observed=f"start={start.isoformat()}, end={end.isoformat()}",
                fix=f"set end later than {start.isoformat()}, or set start earlier than "
                f"{end.isoformat()}",
                status=Status.PRECONDITION,
                source=_key(at, "end"),
            )
        ]
    return []


def _judge_execution_ordering(
    definition: RunDefinition,
    at: FailureSource,
    facts: RunFacts,
) -> list[Failure]:
    """AC-C5: every decision must have an execution instant after it that the fill rule admits.

    Caught here, before the run, rather than at the first callback. The old failure mode was a
    bare `ValueError: no exact execution target exists within the run horizon` raised only once
    the simulation was already underway and earlier callbacks had mutated account state. Since
    design §3.5 the question is asked of the table itself -- the market clock -- rather than of a
    wall time: a decision AT the last instant of the day, with `at` set to that instant, has no
    fill until the next day, and `within: 1d` may forbid that.

    An execution dataset that does not resolve, and an agenda that cannot be derived, both raise
    out of here on purpose (`docs/issues/archive/077`).

    Asked of the occurrences INSIDE `[start, end]`, the same slice preflight freezes and the run
    walks. `derived_agenda` cuts on venue-local dates and keeps a superset
    (`docs/issues/archive/069`), so an `end` between a day's fill and that day's decision -- the one
    for a decide-after-close, fill-next-close run -- leaves that day's decision in the derived
    agenda and after `end`. Handed to `select_target`, that occurrence broke its contract and
    the judgment blocked as a 500 instead of answering (`docs/issues/099`).
    """
    if definition.execution is None or definition.start is None or definition.end is None:
        return []
    # The agenda first: an execution table that cannot be read blocks this judge and the
    # dataset judge for the SAME reason (`docs/issues/archive/077`), rather than this one
    # naming the horizon scan and the other the agenda derivation.
    occurrences = facts.agenda().inclusive_slice(definition.start, definition.end)
    table = facts.execution_table()
    # Cut from the instants the agenda was derived from, not scanned again (record `238`).
    horizon = facts.horizon()
    late = [
        occurrence.occurrence_id
        for occurrence in occurrences
        if table.select_target(
            decision_time=occurrence.evaluation_time, end_time=definition.end, horizon=horizon
        )
        is None
    ]
    if not late or definition.strategy is None:
        return []
    return [
        Failure.bounded(
            EXECUTION_NOT_AFTER_DECISION,
            "every decision must have an execution instant after it that the fill rule admits",
            observed=(
                f"strategy {definition.strategy.component_id!r} fills at "
                f"{table.fill.describe()}; {len(late)} occurrence(s) with no such instant"
            ),
            examples=late,
            example_total=len(late),
            fix=(
                "move the decision earlier than the instant it should fill at, extend the run "
                "end, or loosen the fill's `at`/`after`/`within`"
            ),
            status=Status.PRECONDITION,
            source=_key(at, "strategies", definition.strategy.component_id),
        )
    ]


def _members(definition: RunDefinition) -> list[tuple[str, Any, Any]]:
    """Every component the run names: the section it was declared under, the entry, its loader."""
    return [
        *(
            ("strategies", entry, load_strategy_model)
            for entry in ((definition.strategy,) if definition.strategy is not None else ())
        ),
        *(
            ("datamodels", entry, load_data_model)
            for entry in ((definition.datamodel,) if definition.datamodel is not None else ())
        ),
    ]


def _judge_member_datasets(
    definition: RunDefinition,
    member: tuple[str, Any, Any],
    workspace: Workspace,
    registered: dict[str, Any],
    at: FailureSource,
    facts: RunFacts,
) -> list[Failure]:
    """Every dataset ONE member reads must be registered, and expose the field it names.

    Two codes rather than one, because they are two different repairs: an unregistered dataset is
    fixed by registering it, and an absent field is fixed by correcting the component or the
    source. Collapsing them would tell the reader which command failed but not which to run.

    One member per call, and `judgments` dispatches one judge per member, so a component that does
    not load blocks its own entry and leaves the other members answered. It used to `continue` past
    that member inside a single judgment covering all of them -- which reported the whole judgment
    as passed while a component nothing could be read from sat in the run
    (`docs/issues/archive/077`).
    """
    section, entry, loader = member
    found: list[Failure] = []
    source = _key(at, section, entry.component_id)
    # LOAD the component. `workspace.component()` returns a `ComponentRef` -- an identity, a path
    # and a fingerprint -- which has no `requirements` attribute at all. Only the loaded model
    # knows what it reads. A component that does not resolve or does not load raises from here;
    # loaded once, the freeze takes the same instance (record `241`).
    component = facts.component(entry.component_id, loader)

    first_read = _first_decision(definition, facts.agenda)
    # One unregistered dataset is ONE problem however many fields the component reads from
    # it (`docs/issues/archive/056`): `requirements()` fans a `DatasetInput` out to one requirement
    # per field, and reporting per requirement printed eight identical failures for one
    # missing registration. The fields ride along as examples, which is what a reader
    # deciding between "register it" and "point the component elsewhere" wants to see.
    unregistered: dict[str, list[str]] = {}
    for requirement in component.requirements() or ():
        dataset_id = str(getattr(requirement, "dataset_id", ""))
        if not dataset_id:
            continue
        registration = registered.get(dataset_id)
        if registration is None:
            field_id = str(getattr(requirement, "field_id", ""))
            fields = unregistered.setdefault(dataset_id, [])
            if field_id and field_id not in fields:
                fields.append(field_id)
            continue

        exposed = set(registration.fields)
        field_id = str(getattr(requirement, "field_id", ""))
        if field_id and field_id not in exposed:
            found.append(
                Failure.bounded(
                    FIELD_ABSENT,
                    f"dataset {dataset_id!r} must expose every field the component reads",
                    observed=(f"missing: {field_id}; exposed: {', '.join(sorted(exposed))}"),
                    examples=(field_id,),
                    example_total=1,
                    fix=(
                        f"add {field_id} to the dataset's fields mapping and register it "
                        "again, or read a field it already exposes"
                    ),
                    status=Status.MISSING,
                    source=source,
                )
            )

        lookback = getattr(requirement, "lookback", None)
        rows = getattr(lookback, "rows", None)
        span = getattr(registration, "span", None)
        # Measured against the first instant that actually READS, not against the run's
        # `start`. Nothing reads at `start`: it bounds the horizon, and the strategy reads at
        # the occurrences its agenda generates inside that horizon (issue 012).
        begins = _instant(span[0]) if span is not None else None
        if (
            rows
            and span is not None
            and begins is not None
            and first_read is not None
            and begins > first_read
        ):
            found.append(
                Failure.bounded(
                    LOOKBACK_UNCOVERED,
                    (
                        f"dataset {dataset_id!r} must carry history reaching back past the "
                        "first decision, or that decision reads a short window"
                    ),
                    observed=(
                        f"dataset begins {span[0]}, first decision "
                        f"{first_read.isoformat()}, lookback {rows} row(s)"
                    ),
                    fix=(
                        f"start the run late enough that its first decision falls at or "
                        f"after {span[0]}, or prepare the dataset with history reaching "
                        "further back"
                    ),
                    status=Status.PRECONDITION,
                    source=_key(at, "start"),
                )
            )
    for dataset_id, fields in unregistered.items():
        close = get_close_matches(dataset_id, sorted(registered), n=1)
        # The graph's answer first (design §2): if a registered run declares this name as its
        # `writes`, the dataset is not missing, it is not made yet -- and the repair is to run
        # that run, not to register anything.
        producer = workspace.producer_of(dataset_id)
        if producer is not None and producer != definition.run_id:
            fix = f"run {producer!r} writes {dataset_id!r}: vqapr run {producer}, then this run"
        elif close:
            fix = f"register {dataset_id!r}, or point the component at {close[0]!r}"
        else:
            fix = f"register {dataset_id!r} with `vqapr register <declaration>`"
        found.append(
            Failure.bounded(
                DATASET_UNREGISTERED,
                f"dataset {dataset_id!r} must be registered before a run can read it",
                observed=(
                    f"{entry.component_id!r} reads {len(fields)} field(s) from it; "
                    f"registered: {', '.join(sorted(registered)) or '(none)'}"
                    + (
                        f"; run {producer!r} declares it as its writes and has not run"
                        if producer is not None and producer != definition.run_id
                        else ""
                    )
                ),
                examples=tuple(fields),
                example_total=len(fields),
                fix=fix,
                status=Status.MISSING,
                source=source,
            )
        )
    return found


def _judge_outputs(
    definition: RunDefinition,
    registered: dict[str, Any],
    at: FailureSource,
    workspace: Workspace | None = None,
) -> list[Failure]:
    """A run writes a dataset that does not exist yet -- either kind, one rule (design §2).

    The refusal preflight raises as `run.output_registered` under `freeze`, asked here so `check`
    cannot certify a run that `run` then refuses. It was a datamodel-only question (record `148`)
    while only datamodels wrote; a strategy publishes its allocation now, so both do.

    The run's own earlier output is not a defect of the declaration (see preflight) -- unless it
    was written by a version of the component other than the one registered now
    (`docs/issues/091`). That is `run.output_stale`, a 412: the declaration is sound, the
    workspace holds a parquet the current component did not produce, and nothing but this
    judgment would say so. The testbed found five of eight pooled alphas in that state, each with
    a plausible number, by re-measuring every one by hand.
    """
    taken = registered.get(definition.writes)
    if taken is None:
        return []
    if getattr(taken, "produced_by", None) == definition.run_id:
        return _judge_output_freshness(definition, taken, at, workspace)
    return [
        Failure.bounded(
            RUN_OUTPUT_REGISTERED,
            "a run writes a dataset that does not exist yet",
            observed=f"{definition.writes!r} is already registered",
            fix=(
                f"declare a new `writes` for run {definition.run_id!r}, or withdraw the "
                f"existing {definition.writes} first: vqapr rm dataset {definition.writes}"
            ),
            status=Status.CONFLICT,
            source=_key(at, "writes"),
        )
    ]


def _judge_output_freshness(
    definition: RunDefinition, taken: Any, at: FailureSource, workspace: Workspace | None
) -> list[Failure]:
    """The run's own output was written by the component version registered now, or say which.

    Only asked when the dataset names its producing record: a document written before
    `produced_by_record` existed has nothing to compare, and the member judge already reports a
    component that does not resolve, so an unresolvable one is left to it rather than blocking
    this judgment too.
    """
    written_by = getattr(taken, "produced_by_record", None)
    if not written_by or workspace is None:
        return []
    member = definition.member
    try:
        ref = workspace.component(member.component_id)
    except VqaprError:
        return []
    current = f"{member.component_id}@{ref.fingerprint[:FINGERPRINT_PREFIX]}"
    if current == written_by:
        return []
    return [
        Failure.bounded(
            RUN_OUTPUT_STALE,
            "a run's registered output was written by the component version registered now",
            observed=(
                f"{definition.writes!r} was written by record {written_by!r}; the registered "
                f"component is {current!r}"
            ),
            fix=(
                f"vqapr run {definition.run_id} --force to rewrite it from the current component, "
                f"or re-register the component version that wrote it"
            ),
            status=Status.PRECONDITION,
            source=_key(at, "writes"),
        )
    ]


def _first_decision(definition: RunDefinition, agenda: Callable[[], object]) -> datetime | None:
    """When the run's models first read, or `None` when the run declared no horizon.

    The earliest occurrence the run's agenda generates inside the declared horizon. Every model
    of a run shares the one agenda (record `148`), so this is a fact about the run rather than
    about one member.

    `None` means the run declared no `start` or no `end` -- which the period judgment reports, and
    which leaves nothing here to measure against. An agenda that cannot be DERIVED is a different
    thing entirely and is no longer flattened into the same `None`: `agenda()` raises, and the
    judgment that asked blocks (`docs/issues/archive/077`).
    """
    start, end = definition.start, definition.end
    if start is None or end is None:
        return None
    occurrences = agenda().occurrences  # type: ignore[attr-defined]
    inside = [
        moment
        for moment in (occurrence.local_instant.instant for occurrence in occurrences)
        if start <= moment <= end
    ]
    return min(inside) if inside else None


def _judge_weights(definition: RunDefinition, at: FailureSource, facts: RunFacts) -> list[Failure]:
    """The account mode and the venue must both permit the positions the run can take.

    Two codes for two different contradictions: a long-only account that will be asked to short,
    and a venue whose listings do not permit the side the account allows. Both are declared facts
    that disagree, and both are answerable before the run.
    """
    found: list[Failure] = []
    snapshot, mode = definition.initial_account_snapshot, definition.initial_account_mode
    if snapshot is None or mode is None:
        return found

    if mode is AccountMode.LONG_ONLY:
        shorts = [name for name, quantity in snapshot.positions.items() if quantity < 0]
        if shorts:
            found.append(
                Failure.bounded(
                    WEIGHTS_MODE_CONFLICT,
                    "a long-only account must not open with a short position",
                    observed=f"short: {', '.join(shorts)}",
                    examples=shorts,
                    example_total=len(shorts),
                    fix=(
                        f"drop {', '.join(shorts)} from the initial account, or declare the "
                        "account mode as SIGNED"
                    ),
                    status=Status.PRECONDITION,
                    source=_key(at, "initial_account", "positions"),
                )
            )

    # The venue side of the same contradiction. A SIGNED account claims it may hold a negative
    # position; a listing marked LONG_ONLY or NONE says the venue will not fill one. Both are
    # declared facts, they disagree, and the disagreement is answerable now rather than at the
    # first callback that tries to short.
    if definition.exchange is None or mode is not AccountMode.SIGNED:
        return found
    # No `try`. An exchange that does not resolve or does not load is still preflight's refusal to
    # name, but it is ALSO the reason this judgment cannot be made, and swallowing it reported the
    # weights judgment as passed on a run nothing was proven about (`docs/issues/archive/077`).
    exchange = facts.exchange()

    # `listings` rather than `listing(id)`: every shipped profile exposes the collection, but only
    # `Academic` exposes the single-id lookup. KrxExchange keys its rules by instrument id;
    # Academic carries a tuple of Listing. Both are shipped profiles, so reading only one shape
    # made this judgment silently find nothing on the other -- which reads exactly like a pass.
    listings = getattr(exchange, "listings", None) or ()
    if isinstance(listings, Mapping):
        declared = {str(name): getattr(rule, "access", None) for name, rule in listings.items()}
    else:
        declared = {
            str(getattr(listing, "instrument_id", "")): getattr(listing, "access", None)
            for listing in listings
        }
    unshortable = [
        f"{name}: {declared[name]}"
        for name in definition.instruments
        # An instrument with no listing at all is `universe.unlisted_instrument`'s refusal to
        # make (preflight); reporting it here too would give one defect two names.
        if name in declared and str(declared[name]) != "signed"
    ]
    if not unshortable:
        return found

    found.append(
        Failure.bounded(
            WEIGHTS_VENUE_CONFLICT,
            (
                "a signed account must trade on listings the venue permits a short on, or it "
                "declares a freedom the venue will not fill"
            ),
            observed=f"{len(unshortable)} listing(s) not signed: {', '.join(unshortable[:5])}",
            examples=unshortable,
            example_total=len(unshortable),
            fix=(
                "declare the account mode as LONG_ONLY, or list those instruments with signed "
                "access on the exchange"
            ),
            status=Status.PRECONDITION,
            source=_key(at, "initial_account", "mode"),
        )
    )
    return found
