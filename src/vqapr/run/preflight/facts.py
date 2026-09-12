"""The facts a run declaration resolves to, read once per command.

`RunFacts` is what every judgment and the freeze read instead of reading again: the derived schedule
(`derived_schedule`), the execution table bound to the run's window (`bound_execution_table`) and
the horizon that table gives (`bound_execution_horizon`). What those facts leave unresolved -- a
decision whose execution target no instant can answer -- is said here too (`unresolved_targets`,
`unresolved_target_failures`): both the check and the freeze ask it, and a shared answer lives in
the lower module.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from vqapr.component.exchange.base import Exchange
from vqapr.component.loading import (
    load_exchange,
)
from vqapr.data.dataset import execution_price_fields, require_declared
from vqapr.data.execution_table import ExecutionTable, ExecutionTableSpec
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.domain.fill import ExecutionHorizon, FillRule
from vqapr.domain.identifiers import schedule_id
from vqapr.domain.schedule import Schedule, ScheduledEvent
from vqapr.workspace.registry import Workspace
from vqapr.workspace.run_definition import (
    RunDefinition,
)

__all__ = [
    "RunFacts",
]


def _session_bounds(definition: RunDefinition) -> tuple[datetime, datetime] | None:
    """The instants a run's schedule and horizon can need: its period, widened by a day each side.

    The schedule keeps a session by its venue-local DATE inside `[start, end]` and the horizon by
    the instant inside `(start, end]`, so both are cut from the same read (record `238`) -- and
    that read used to be the table's whole column, ten years of instants to keep one (record
    `247`). A day's width on either side covers every zone the local date can fall in, and the
    two cuts below stay exactly what they were. `None` when the run declares no period: the
    schedule then spans the table, as before.
    """
    if definition.start is None or definition.end is None:
        return None
    # An `on: last` schedule reads on past `end` (record `253`): whether `end`'s month is over is
    # the next session's to say, and one can be a month and a holiday away.
    past = LAST_DAY_LOOKAHEAD if definition.schedule.rule.on == "last" else timedelta(0)
    return (definition.start - timedelta(days=1), definition.end + timedelta(days=1) + past)


LAST_DAY_LOOKAHEAD = timedelta(days=45)
"""How far past `end` an `on: last` schedule reads its trading days: the rest of `end`'s month, the
holidays that can open the next one, and margin. The horizon is cut from the same read, to
`(start, end]`, so nothing past `end` reaches a run."""


def derived_schedule(workspace: Workspace, definition: RunDefinition) -> Schedule:
    """The run's one schedule: its `schedule:` rule expanded over its trading days (design §3.4).

    The DAYS come from data and the INSTANTS from the rule (§3.3): a strategy run's trading days
    are the days its execution table has rows for -- a denser table adds instants to the market
    clock and not one day to the schedule clock, which is `UC-TIME-002`'s guarantee -- and a
    datamodel run, having no venue, names the dataset whose days count with `days_from`.
    `Schedule.expand` owns the event ids, fold and offset, so a DST wall time is
    refused rather than guessed. The book is valued at the instant the venue fills and monitored
    right after each commit, so there is no second schedule to build.
    """
    source = (
        definition.execution.dataset
        if definition.execution is not None
        else definition.schedule.days_from
    )
    if source is None:  # pragma: no cover -- `RunDefinition` refuses both shapes
        raise ValueError("a run's trading days come from its execution table or schedule.days_from")
    sessions: Iterable[datetime | date] = workspace.evaluation_times(
        source, between=_session_bounds(definition)
    )
    rule = definition.schedule.rule
    through: date | None = None
    if definition.start is not None and definition.end is not None:
        # Cut on DATES before an event is built, not on events after
        # (`docs/issues/archive/069`: a run of 15 sessions built 735 events, with their fold
        # and offset proofs and the schedule's identity over them, three times per command). An
        # event on venue-local day `d` at `at` lies inside `[start, end]` only if `d` lies
        # between the bounds' local dates, so this keeps a superset of what `inclusive_slice` keeps
        # and changes nothing it would have answered. `daily` still owns the date conversion and the
        # DST refusal.
        zone = ZoneInfo(definition.timezone)
        first = definition.start.astimezone(zone).date()
        last = definition.end.astimezone(zone).date()

        def _local_date(session: datetime | date) -> date:
            if isinstance(session, datetime):
                return (session.astimezone(zone) if session.tzinfo is not None else session).date()
            return session

        if rule.on == "last":
            # The sessions past `end` stay: they are how the last month inside the run is known
            # to be over, and `expand` fires on none of them (record `253`).
            sessions = tuple(session for session in sessions if first <= _local_date(session))
            through = last
        else:
            sessions = tuple(
                session for session in sessions if first <= _local_date(session) <= last
            )
    return Schedule.expand(
        schedule_id=schedule_id(definition.schedule_id),
        days=sessions,
        rule=rule,
        timezone=definition.timezone,
        through=through,
    )


def bound_execution_table(workspace: Workspace, definition: RunDefinition) -> ExecutionTable:
    """The execution dataset the run names, bound to the run's own fill (record `185`).

    The dataset supplies the physical columns -- its `available_at` is the instant a row is a
    fact about, its execution role names the tradable flag, its numeric fields are
    the prices a run may choose from -- and the run supplies the choice: which of those fields
    is `trade_price`, on which session instant. A run naming a dataset with no execution role,
    or a price the dataset does not expose, is refused here by name.
    """
    binding = definition.execution
    assert binding is not None
    registration = workspace.require_verified(binding.dataset)
    require_declared(registration)
    role = registration.execution
    if role is None:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[
                Failure.bounded(
                    code="execution.dataset_has_no_role",
                    status=Status.INVALID,
                    requirement=(
                        "the dataset a run fills against must declare an execution role "
                        "(`execution: {is_tradable: <field>}`)"
                    ),
                    observed=f"dataset {binding.dataset!r} declares none",
                    fix=(
                        f"register {binding.dataset!r} again with an execution role, or fill "
                        "against a dataset that has one"
                    ),
                )
            ],
            mutation=False,
            retry_precondition="declare the execution role on the dataset, then retry",
        )
    if registration.instrument_field is None:
        raise ValueError(f"execution dataset {binding.dataset!r} must declare an instrument_field")
    prices = execution_price_fields(registration)
    fill = binding.rule(definition.timezone)
    if fill.trade_price not in prices:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[
                Failure.bounded(
                    code="execution.price_not_a_field",
                    status=Status.INVALID,
                    requirement=(
                        "the run's trade_price must be a numeric field of the execution dataset"
                    ),
                    observed=(
                        f"trade_price {fill.trade_price!r}; {binding.dataset!r} exposes "
                        f"{', '.join(sorted(prices)) or '(no numeric field)'}"
                    ),
                    fix=(
                        f"declare trade_price as one of "
                        f"{', '.join(sorted(prices)) or 'the numeric'} fields of "
                        f"{binding.dataset!r}"
                    ),
                )
            ],
            mutation=False,
            retry_precondition="name a price field the execution dataset exposes, then retry",
        )
    # Registration measured which prices are finite and positive wherever a row is tradable
    # (record `234`); the run's choice is judged against that fact here, where the choice is
    # made, instead of scanning the table again for the one price it chose.
    positive = registration.execution_prices or ()
    if fill.trade_price not in positive:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[
                Failure.bounded(
                    code="execution.price_not_positive",
                    status=Status.PRECONDITION,
                    requirement=(
                        "the run's trade_price must be finite and positive on every tradable "
                        "row of the execution dataset"
                    ),
                    observed=(
                        f"trade_price {fill.trade_price!r}; registration measured "
                        f"{', '.join(positive) or 'no field'} as positive on every tradable "
                        f"row of {binding.dataset!r}"
                    ),
                    fix=(
                        f"repair {fill.trade_price!r} in the prepared source and register "
                        f"{binding.dataset!r} again, or fill at one of "
                        f"{', '.join(positive) or 'the fields the table can offer'}"
                    ),
                )
            ],
            mutation=False,
            retry_precondition="fix the execution price or choose another, then retry",
        )
    return ExecutionTable(
        registration.dataset_id,
        ExecutionTableSpec(
            source=workspace.source(str(registration.source)),
            trade_at_field=registration.available_at,
            instrument_field=registration.instrument_field,
            is_tradable_field=registration.fields[role.is_tradable].strip(),
            price_fields=prices,
        ),
        fill,
    )


def bound_execution_horizon(workspace: Workspace, definition: RunDefinition) -> ExecutionHorizon:
    """The run's candidate execution instants, cut from the sessions the workspace already read.

    The horizon is the execution table's distinct instants inside `(start, end]`, and the
    workspace reads that table's distinct instants once per command to derive the run's schedule
    (`derived_schedule`). Before record `238` the ordering judgment scanned the table for its
    horizon, preflight scanned it again to prove every event a target, and the schedule's
    scan made three reads of one column for one fact (`experiments/exp_238`: three
    `candidate_instants` and two `distinct_values` per `vqapr run`).
    """
    binding = definition.execution
    if binding is None or definition.start is None or definition.end is None:
        raise ValueError("an execution horizon requires an execution dataset, a start and an end")
    return ExecutionHorizon.between(
        workspace.evaluation_times(binding.dataset, between=_session_bounds(definition)),
        start_time=definition.start,
        end_time=definition.end,
    )


class RunFacts:
    """What one run declaration resolves to, each fact read at most once per command.

    The judgments and the freeze both need the run's schedule, its execution table and horizon,
    its loaded components and its venue, and each used to derive them for itself (record `238`
    counted five reads of the execution table's instant column and four imports of the strategy
    in one `vqapr run`). Every fact here is read the first time any asker asks and handed to
    every later one -- **including a failure to read it**: the exception is stored and raised
    again to each asker, so a dataset that does not resolve blocks every judgment that needed it
    with the same cause (`docs/issues/archive/077`) and refuses the freeze with the same error,
    exactly as it did when each read for itself. `_schedule_once` was this shape for one fact.
    """

    __slots__ = ("_definition", "_settled", "_workspace")

    def __init__(self, workspace: Workspace, definition: RunDefinition) -> None:
        self._workspace = workspace
        self._definition = definition
        self._settled: dict[str, tuple[object, BaseException | None]] = {}

    def _once(self, key: str, read: Callable[[], object]) -> object:
        if key not in self._settled:
            try:
                self._settled[key] = (read(), None)
            except Exception as error:  # stored, then raised to every asker; never swallowed
                self._settled[key] = (None, error)
        value, error = self._settled[key]
        if error is not None:
            raise error
        return value

    def schedule(self) -> Schedule:
        """The run's one decide schedule (`derived_schedule`)."""
        return self._once("schedule", lambda: derived_schedule(self._workspace, self._definition))  # type: ignore[return-value]

    def execution_table(self) -> ExecutionTable:
        """The execution dataset bound to the run's fill (`bound_execution_table`)."""
        return self._once(  # type: ignore[return-value]
            "execution_table", lambda: bound_execution_table(self._workspace, self._definition)
        )

    def horizon(self) -> ExecutionHorizon:
        """The candidate execution instants inside the run (`bound_execution_horizon`)."""
        return self._once(  # type: ignore[return-value]
            "horizon", lambda: bound_execution_horizon(self._workspace, self._definition)
        )

    def component(self, component_id: str, loader: Callable[..., Any]) -> Any:
        """One registered component, loaded once by `loader` (a strategy, a datamodel)."""
        return self._once(
            f"component:{component_id}",
            lambda: loader(
                self._workspace.component(component_id), project_root=self._workspace.project_root
            ),
        )

    def exchange(self) -> Exchange:
        """The run's venue, loaded once."""
        exchange_id = self._definition.exchange
        if exchange_id is None:
            raise ValueError("the run declares no exchange")
        return self._once(  # type: ignore[return-value]
            "exchange",
            lambda: load_exchange(
                self._workspace.component(exchange_id), project_root=self._workspace.project_root
            ),
        )


@dataclass(frozen=True, slots=True)
class UnresolvedTargets:
    """The events no execution instant serves, split by what would serve them.

    A decide-after-close run with `within: 1d` was refused on every Friday, once by the ordering
    judgment and again by the freeze, and the second refusal told its author to widen a run end
    that was not the problem (report 2026-09-11, record `259`). The two causes want different
    repairs, so they are told apart here, once, for both doors:

    - `waiting` -- the rule admits an instant after the decision, only further away than
      `within`. `within` is wall-clock time, so a weekend or a holiday outlasts `1d`, and no end
      fixes it. Each row is (event id, decision, the instant it would fill at).
    - `past_end` -- the rule admits no instant after the decision before the run's end at all:
      the run's end, or the table's, is the problem. Each row is (event id, decision).

    `last_fill` is the latest instant a served event fills at, a `waiting` one counted at the
    instant a wider `within` gives it: an end after it and before
    the first `past_end` decision keeps every fill and drops the decisions nothing can serve --
    the end record `237` calls the only correct one for a decide-after-close, fill-next-close run.
    """

    waiting: tuple[tuple[str, datetime, datetime], ...]
    past_end: tuple[tuple[str, datetime], ...]
    last_fill: datetime | None

    def __bool__(self) -> bool:
        return bool(self.waiting or self.past_end)


def unresolved_targets(
    table: ExecutionTable,
    events: Iterable[ScheduledEvent],
    *,
    end: datetime,
    horizon: ExecutionHorizon,
) -> UnresolvedTargets:
    """Every event `select_target` cannot bind, and whether dropping `within` would bind it.

    Asked again without `within` only for the events that failed, so a run that passes costs
    what it did.
    """
    unbounded = (
        None if table.fill.within is None else replace(table, fill=replace(table.fill, within=None))
    )
    waiting: list[tuple[str, datetime, datetime]] = []
    past_end: list[tuple[str, datetime]] = []
    last_fill: datetime | None = None
    for event in events:
        decision = event.evaluation_time
        target = table.select_target(decision_time=decision, end_time=end, horizon=horizon)
        if target is not None:
            last_fill = target.target_at if last_fill is None else max(last_fill, target.target_at)
            continue
        later = (
            None
            if unbounded is None
            else unbounded.select_target(decision_time=decision, end_time=end, horizon=horizon)
        )
        if later is None:
            past_end.append((str(event.event_id), decision))
        else:
            waiting.append((str(event.event_id), decision, later.target_at))
            # Counted at the instant a wider `within` gives it: the end suggested for the
            # `past_end` decisions must not drop a fill the window's repair brings back.
            last_fill = later.target_at if last_fill is None else max(last_fill, later.target_at)
    return UnresolvedTargets(tuple(waiting), tuple(past_end), last_fill)


def _wait(gap: timedelta) -> str:
    """`2d 23h 59m`: a wait as a reader counts it, to the minute, rounded up."""
    minutes = math.ceil(gap.total_seconds() / 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    return " ".join(f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n)


def _window_for(gap: timedelta) -> str:
    """The smallest `within` in the duration grammar that admits `gap`, in its largest unit."""
    for unit, size in (("d", timedelta(days=1)), ("h", timedelta(hours=1))):
        if gap >= size:
            return f"{math.ceil(gap / size)}{unit}"
    return f"{max(1, math.ceil(gap / timedelta(minutes=1)))}m"


def unresolved_target_failures(
    unresolved: UnresolvedTargets,
    fill: FillRule,
    *,
    code: str,
    requirement: str,
    subject: str,
    end: datetime,
    source: FailureSource | None = None,
) -> list[Failure]:
    """One failure per cause, each listing only its own events, the same from either door.

    `subject` is how the door names the rule (the judgment names the strategy, the freeze the
    rule and the end). The events are listed identically by both, which is what lets
    `check` recognise the freeze restating what the judgments already said.
    """
    zone = ZoneInfo(fill.timezone)
    failures: list[Failure] = []
    if unresolved.waiting:
        event, decision, instant = max(unresolved.waiting, key=lambda row: row[2] - row[1])
        gap = instant - decision
        failures.append(
            Failure.bounded(
                code,
                requirement,
                observed=(
                    f"{subject}; {len(unresolved.waiting)} event(s) whose next such instant "
                    f"lies beyond `within: {fill.within}` -- the longest wait is {_wait(gap)}, "
                    f"{event} from {decision.astimezone(zone).isoformat()} to "
                    f"{instant.astimezone(zone).isoformat()}"
                ),
                examples=[row[0] for row in unresolved.waiting],
                example_total=len(unresolved.waiting),
                fix=(
                    "`within` counts wall-clock time from the decision, not sessions, so a weekend "
                    f"or a holiday outlasts `{fill.within}`: set `within: \"{_window_for(gap)}\"` "
                    "(the longest wait in this run) or drop it, or decide before the instant the "
                    "decision should fill at. A later run end does not help these"
                ),
                status=Status.PRECONDITION,
                source=source,
            )
        )
    if unresolved.past_end:
        first = unresolved.past_end[0][1]
        last_fill = unresolved.last_fill
        if last_fill is not None and last_fill + timedelta(seconds=1) < first:
            kept = (last_fill + timedelta(seconds=1)).astimezone(zone).isoformat()
            fix = (
                "end the run after its last fill and before that decision -- "
                f"`end: \"{kept}\"` keeps every earlier fill -- or, if the execution table has "
                "instants after "
                f"{end.isoformat()}, move the end past the one that decision fills at"
            )
        else:
            fix = (
                f"extend the run end past {end.isoformat()} through the instant the decision "
                "fills at, move the decision earlier, or loosen the fill's `at`/`after`"
            )
        failures.append(
            Failure.bounded(
                code,
                requirement,
                observed=(
                    f"{subject}; {len(unresolved.past_end)} event(s) with no such instant "
                    f"before the run end {end.isoformat()}, the first deciding at "
                    f"{first.astimezone(zone).isoformat()}"
                ),
                examples=[row[0] for row in unresolved.past_end],
                example_total=len(unresolved.past_end),
                fix=fix,
                status=Status.PRECONDITION,
                source=source,
            )
        )
    return failures
