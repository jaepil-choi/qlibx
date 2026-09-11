"""Resolve a detached, immutable run declaration before any run mutation."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from vqapr.component.compliance.base import Compliance
from vqapr.component.exchange.base import Exchange
from vqapr.component.loading import (
    load_compliance,
    load_data_model,
    load_exchange,
    load_strategy_model,
)
from vqapr.component.reference import ComponentRef
from vqapr.component.strategy.base import StrategyModel
from vqapr.data.dataset import execution_price_fields, lookback_fits_grain, require_declared
from vqapr.data.execution_table import ExecutionTable, ExecutionTableSpec
from vqapr.data.requirement import DataRequirement
from vqapr.data.source import SourceSpec
from vqapr.domain.account import AccountMode, AccountSnapshot
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.domain.fill import ExecutionHorizon, FillRule
from vqapr.domain.identifiers import agenda_id
from vqapr.domain.instants import require_tz_aware
from vqapr.domain.listing import TradeRule
from vqapr.domain.memory import ModelMemory
from vqapr.domain.schedule import OperationAgenda, OperationOccurrence
from vqapr.domain.wiring import Role
from vqapr.flow.declaration.frozen import FrozenAgenda, FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.declaration.roster import require_declared_roster
from vqapr.workspace.registry import Workspace
from vqapr.workspace.run_definition import (
    ComplianceSet,
    DataModelEntry,
    RunDefinition,
    StrategyConfig,
    StrategyEntry,
)


def _session_bounds(definition: RunDefinition) -> tuple[datetime, datetime] | None:
    """The instants a run's agenda and horizon can need: its period, widened by a day each side.

    The agenda keeps a session by its venue-local DATE inside `[start, end]` and the horizon by
    the instant inside `(start, end]`, so both are cut from the same read (record `238`) -- and
    that read used to be the table's whole column, ten years of instants to keep one (record
    `247`). A day's width on either side covers every zone the local date can fall in, and the
    two cuts below stay exactly what they were. `None` when the run declares no period: the
    agenda then spans the table, as before.
    """
    if definition.start is None or definition.end is None:
        return None
    # An `on: last` agenda reads on past `end` (record `253`): whether `end`'s month is over is
    # the next session's to say, and one can be a month and a holiday away.
    past = LAST_DAY_LOOKAHEAD if definition.agenda.rule.on == "last" else timedelta(0)
    return (definition.start - timedelta(days=1), definition.end + timedelta(days=1) + past)


LAST_DAY_LOOKAHEAD = timedelta(days=45)
"""How far past `end` an `on: last` agenda reads its trading days: the rest of `end`'s month, the
holidays that can open the next one, and margin. The horizon is cut from the same read, to
`(start, end]`, so nothing past `end` reaches a run."""


def derived_agenda(workspace: Workspace, definition: RunDefinition) -> OperationAgenda:
    """The run's one agenda: its `agenda:` rule expanded over its trading days (design §3.4).

    The DAYS come from data and the INSTANTS from the rule (§3.3): a strategy run's trading days
    are the days its execution table has rows for -- a denser table adds instants to the market
    clock and not one day to the strategy clock, which is `UC-TIME-002`'s guarantee -- and a
    datamodel run, having no venue, names the dataset whose days count with `days_from`.
    `OperationAgenda.expand` owns the occurrence ids, fold and offset, so a DST wall time is
    refused rather than guessed. The book is valued at the instant the venue fills and monitored
    right after each commit, so there is no second agenda to build.
    """
    source = (
        definition.execution.dataset
        if definition.execution is not None
        else definition.agenda.days_from
    )
    if source is None:  # pragma: no cover -- `RunDefinition` refuses both shapes
        raise ValueError("a run's trading days come from its execution table or agenda.days_from")
    sessions: Iterable[datetime | date] = workspace.evaluation_times(
        source, between=_session_bounds(definition)
    )
    rule = definition.agenda.rule
    through: date | None = None
    if definition.start is not None and definition.end is not None:
        # Cut on DATES before an occurrence is built, not on occurrences after
        # (`docs/issues/archive/069`: a run of 15 sessions built 735 occurrences, with their fold
        # and offset proofs and the agenda's identity over them, three times per command). An
        # occurrence on venue-local day `d` at `at` lies inside `[start, end]` only if `d` lies
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
    return OperationAgenda.expand(
        agenda_id=agenda_id(definition.agenda_id),
        days=sessions,
        rule=rule,
        timezone=definition.timezone,
        through=through,
    )


def _freeze_agenda(agenda: OperationAgenda, *, start: datetime, end: datetime) -> FrozenAgenda:
    """The run's agenda, sliced to `[start, end]`, with its identity carried over.

    The agenda is derived by `derived_agenda` above and nowhere else, and `OperationAgenda.daily`
    already refuses a session whose wall time does not exist or happens twice; the role check
    and the offset re-proof this used to make guarded an external supply path that does not
    exist (record `182`).
    """
    return FrozenAgenda(
        agenda_id=agenda.agenda_id,
        occurrences=agenda.inclusive_slice(start, end),
        timezone=agenda.timezone,
        content_identity=agenda.content_identity,
    )


def _validate_requirement(workspace: Workspace, requirement: object) -> SourceSpec:
    """Check declared valuation input availability without reading physical source bytes.

    A requirement names a dataset and one field, so both halves are checked here: the dataset must
    be registered, and it must expose that field.
    """
    if not isinstance(requirement, DataRequirement):
        raise TypeError("requirement must be a DataRequirement")
    # Measured at registration and unchanged since (record `234`): the only physical question
    # preflight asks of a source is its identity.
    registration = workspace.require_verified(str(requirement.dataset_id))
    require_declared(registration)
    mismatch = lookback_fits_grain(requirement.lookback, registration.grain)
    if mismatch is not None:
        raise TypeError(f"dataset {str(requirement.dataset_id)!r}: {mismatch}")
    if requirement.field_id not in registration.fields:
        raise ValueError(
            f"dataset {str(requirement.dataset_id)!r} does not provide required field: "
            f"{requirement.field_id}"
        )
    return workspace.source(str(registration.source))


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
    workspace reads that table's distinct instants once per command to derive the run's agenda
    (`derived_agenda`). Before record `238` the ordering judgment scanned the table for its
    horizon, preflight scanned it again to prove every occurrence a target, and the agenda's
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

    The judgments and the freeze both need the run's agenda, its execution table and horizon,
    its loaded components and its venue, and each used to derive them for itself (record `238`
    counted five reads of the execution table's instant column and four imports of the strategy
    in one `vqapr run`). Every fact here is read the first time any asker asks and handed to
    every later one -- **including a failure to read it**: the exception is stored and raised
    again to each asker, so a dataset that does not resolve blocks every judgment that needed it
    with the same cause (`docs/issues/archive/077`) and refuses the freeze with the same error,
    exactly as it did when each read for itself. `_agenda_once` was this shape for one fact.
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

    def agenda(self) -> OperationAgenda:
        """The run's one decide agenda (`derived_agenda`)."""
        return self._once("agenda", lambda: derived_agenda(self._workspace, self._definition))  # type: ignore[return-value]

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


def _freeze_sources(
    workspace: Workspace, requirements: tuple[DataRequirement, ...], execution: SourceSpec | None
) -> tuple[SourceSpec, ...]:
    sources = [_validate_requirement(workspace, requirement) for requirement in requirements]
    if execution is not None:
        registered = workspace.source(str(execution.source_id))
        if registered != execution:
            raise ValueError(f"execution source declaration drift for {execution.source_id!r}")
        sources.append(registered)
    by_id = {source.source_id: source for source in sources}
    return tuple(by_id[source_id] for source_id in sorted(by_id))


def _validate_initial_model_state(
    workspace: Workspace,
    component: ComponentRef,
    strategy: StrategyModel,
    memory: ModelMemory,
) -> bytes:
    """Stage and round-trip the Flow-owned initial Strategy payload.

    Three separate steps, each with its own `try` and its own name in the refusal
    (`docs/issues/archive/076`). One block around all three could only say "cannot be staged", so a
    `load_payload` that hit `EOFError` on an empty source and a `save_payload` that was not
    deterministic produced the SAME sentence -- and the author could not tell which of their two
    methods to open. The `from error` chain carries the original; `cli.run.preflight_refusal`
    renders it.
    """
    component_id = component.component_id

    def staged(step: str) -> ValueError:
        return ValueError(f"strategy initial payload for {component_id!r} cannot be staged: {step}")

    try:
        strategy.memory = memory
        payload = BytesIO()
        strategy.save_payload(payload)
        frozen_payload = payload.getvalue()
    except Exception as error:
        raise staged("save_payload on a fresh instance") from error

    try:
        restored = load_strategy_model(component, project_root=workspace.project_root)
        restored.memory = memory
        restored.load_payload(BytesIO(frozen_payload))
    except Exception as error:
        raise staged("load_payload of those bytes on a second fresh instance") from error

    try:
        round_trip = BytesIO()
        restored.save_payload(round_trip)
    except Exception as error:
        raise staged("save_payload again") from error

    if round_trip.getvalue() != frozen_payload:
        raise ValueError(
            f"strategy initial payload for {component_id!r} cannot be staged: "
            "save_payload again wrote different bytes"
        )
    return frozen_payload


def _validate_initial_account(
    snapshot: AccountSnapshot | None,
    mode: AccountMode | None,
    exchange: Exchange,
) -> None:
    """Prove existing holdings can be closed by the loaded venue."""
    if snapshot is None or mode is None:
        return

    failures: list[Failure] = []
    for instrument_id, quantity in sorted(snapshot.positions.items()):
        rule = exchange.rules.listings.get(instrument_id)
        if rule is None:
            failures.append(
                Failure.bounded(
                    "account.unlisted_holding",
                    "every initial holding must have a listing on the selected Exchange",
                    observed=instrument_id,
                    fix=(
                        f"add a listing for {instrument_id} to the Exchange, or drop it from "
                        "the initial account"
                    ),
                    status=Status.PRECONDITION,
                )
            )
            continue
        assert isinstance(rule, TradeRule)
        if not rule.permits_position(quantity, -quantity):
            failures.append(
                Failure.bounded(
                    "account.holding_not_closable",
                    "each initial holding must be closable on the selected Exchange",
                    observed=f"{instrument_id}: {rule.access.value}",
                    fix=(
                        f"permit closing access for {instrument_id} on the Exchange, or drop "
                        "the holding from the initial account"
                    ),
                    status=Status.PRECONDITION,
                )
            )
        absolute = abs(quantity)
        if absolute < rule.minimum_quantity:
            failures.append(
                Failure.bounded(
                    "account.minimum_quantity",
                    "each initial holding must meet its listing minimum_quantity",
                    observed=f"{instrument_id}: {absolute}",
                    fix=(
                        f"raise the {instrument_id} holding to at least the listing "
                        f"minimum_quantity ({rule.minimum_quantity}), or drop it from the "
                        "initial account"
                    ),
                    status=Status.PRECONDITION,
                )
            )
        if (
            not rule.fractional_allowed
            and (absolute / rule.quantity_step).to_integral_value() != absolute / rule.quantity_step
        ):
            nearest_step = (absolute / rule.quantity_step).to_integral_value() * rule.quantity_step
            # ROUND_HALF_EVEN sends anything below half a step to zero, and "round to 0" reads as
            # a rounding instruction while actually meaning delete the holding. Name the smallest
            # real position instead, and say the other option out loud.
            nearest_hint = (
                f"nearest valid quantity is {nearest_step}"
                if nearest_step != 0
                else (
                    f"the smallest valid position is {rule.quantity_step}; "
                    "drop the holding if that is more than you meant to hold"
                )
            )
            failures.append(
                Failure.bounded(
                    "account.quantity_step",
                    "each initial holding must align to its listing quantity_step",
                    observed=f"{instrument_id}: {absolute}",
                    fix=(
                        f"round the {instrument_id} holding to a multiple of the listing "
                        f"quantity_step ({rule.quantity_step}); {nearest_hint}"
                    ),
                    status=Status.PRECONDITION,
                )
            )
        if not rule.fractional_allowed and absolute != absolute.to_integral_value():
            failures.append(
                Failure.bounded(
                    "account.fractional_quantity",
                    "each initial holding must satisfy its listing fractional quantity rule",
                    observed=f"{instrument_id}: {absolute}",
                    fix=(
                        f"round the {instrument_id} holding to a whole quantity, or set the "
                        "listing's fractional_allowed to permit fractional holdings"
                    ),
                    status=Status.PRECONDITION,
                )
            )
        if mode is AccountMode.LONG_ONLY and quantity < Decimal("0"):
            failures.append(
                Failure.bounded(
                    "account.mode",
                    "a long-only initial account must not contain short holdings",
                    observed=f"{instrument_id}: {quantity}",
                    fix=(
                        f"remove the short {instrument_id} holding from the initial account, "
                        "or declare the account mode as not long-only"
                    ),
                    status=Status.PRECONDITION,
                )
            )
    if failures:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=failures,
            mutation=False,
            retry_precondition=("correct the initial account or Exchange listing, then retry"),
        )


def _validate_execution_requirements(exchange: Exchange, execution_table: ExecutionTable) -> None:
    """Prove the venue's declared regimes have the execution prices they need.

    A venue computes its own regimes -- a KRX price limit is the base price times a declared rate
    -- so it needs a number the user registered, never a conclusion the user derived. When that
    number is absent the run is refused *before* it starts, and the message names the feature to
    switch off rather than only the missing column. Running with the regime silently inert would
    produce a result that looks like a limit-aware backtest and is not one.
    """
    requirements = exchange.execution_requirements()
    if not requirements:
        return
    declared = set(execution_table.table.price_fields)
    missing = tuple(
        requirement for requirement in requirements if requirement.price not in declared
    )
    if not missing:
        return
    raise VqaprError(
        stage=Stage.FREEZE,
        failures=[
            Failure.bounded(
                code="execution.requirement_missing",
                status=Status.MISSING,
                requirement=(
                    "the execution dataset must declare every price the Exchange requires, "
                    "or the feature that needs it must be switched off"
                ),
                observed=", ".join(
                    f"{item.feature} needs price {item.price!r}" for item in missing
                ),
                fix=(
                    "register the missing price fields on the execution dataset, or construct "
                    "the Exchange with the features that need them disabled"
                ),
            )
        ],
        mutation=False,
        retry_precondition=(
            "register the required execution price, or construct the Exchange with that "
            "feature disabled, then retry"
        ),
    )


def _validate_instrument_universe(
    instruments: tuple[str, ...],
    exchange: Exchange,
) -> None:
    """Prove every instrument the run will trade can be filled by the selected venue.

    Two different problems are separated. An *unlisted* instrument is a missing registration and
    the fix is to register it. A listed instrument the venue permits **no side** on is a venue
    judgement -- it publishes the instrument but will not fill it -- and the fix is to remove it
    from the traded universe and read it as data instead. Reporting both as "unlisted" would invite
    someone to register a listing that already exists.
    """
    listings = exchange.rules.listings
    missing = tuple(instrument_id for instrument_id in instruments if instrument_id not in listings)
    untradable = tuple(
        instrument_id
        for instrument_id in instruments
        if instrument_id in listings and not listings[instrument_id].tradable
    )
    if not missing and not untradable:
        return
    failures: list[Failure] = []
    if missing:
        failures.append(
            Failure.bounded(
                code="universe.unlisted_instrument",
                requirement="every frozen run instrument must have an Exchange listing",
                observed=repr(missing),
                fix=(
                    "add an Exchange listing for each missing instrument, or remove it from "
                    "the run's traded instrument universe"
                ),
                status=Status.PRECONDITION,
            )
        )
    if untradable:
        failures.append(
            Failure.bounded(
                code="universe.untradable_listing",
                requirement="the Exchange must permit a side for every traded instrument",
                observed=repr(untradable),
                fix=(
                    "remove each untradable instrument from the traded universe and read it "
                    "as data instead, or update the Exchange listing to permit a side"
                ),
                status=Status.PRECONDITION,
            )
        )
    raise VqaprError(
        stage=Stage.FREEZE,
        failures=failures,
        mutation=False,
        retry_precondition="register complete listings or remove unlisted instruments, then retry",
    )


def _require_execution_authority(definition: RunDefinition) -> None:
    """Refuse a run that declares no execution price.

    An observation dataset is optional: a Strategy may declare no requirement and decide nothing,
    and a run of it is still a run. **An execution price is not optional.** Every run values its
    book and fills against the prices a venue published, so the execution dataset is the one
    registration that is mandatory from the start.

    It is refused here rather than in `RunDefinition`, which is a pure value object built by
    callers who supply the pairing another way, and rather than in `run()`, which is far too late:
    this function promises a *run-ready* declaration, so returning a `FrozenRun` that `run()` will
    reject contradicts its own contract. Late refusal also left
    `_validate_instrument_universe` and `_validate_initial_account` skipped entirely, so a run
    could freeze with unlisted instruments and never be told.
    """
    if definition.exchange is not None and definition.execution is not None:
        return
    raise VqaprError(
        stage=Stage.FREEZE,
        failures=[
            Failure.bounded(
                code="execution.missing",
                status=Status.MISSING,
                requirement=(
                    "a run must declare an Exchange and an execution dataset with its fill; the "
                    "execution price is required even when the Strategy reads no observation "
                    "dataset"
                ),
                observed=(f"exchange={definition.exchange!r}, execution={definition.execution!r}"),
                fix=(
                    "declare both an Exchange and `execution: {dataset, fill}` on the "
                    "RunDefinition before calling preflight_run"
                ),
            )
        ],
        mutation=False,
        retry_precondition=(
            "register the venue table as a dataset with an execution role and declare it "
            "with its Exchange, then retry"
        ),
    )


@dataclass(frozen=True, slots=True)
class UnresolvedTargets:
    """The occurrences no execution instant serves, split by what would serve them.

    A decide-after-close run with `within: 1d` was refused on every Friday, once by the ordering
    judgment and again by the freeze, and the second refusal told its author to widen a run end
    that was not the problem (report 2026-09-11, record `259`). The two causes want different
    repairs, so they are told apart here, once, for both doors:

    - `waiting` -- the rule admits an instant after the decision, only further away than
      `within`. `within` is wall-clock time, so a weekend or a holiday outlasts `1d`, and no end
      fixes it. Each row is (occurrence id, decision, the instant it would fill at).
    - `past_end` -- the rule admits no instant after the decision before the run's end at all:
      the run's end, or the table's, is the problem. Each row is (occurrence id, decision).

    `last_fill` is the latest instant a served occurrence fills at, a `waiting` one counted at the
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
    occurrences: Iterable[OperationOccurrence],
    *,
    end: datetime,
    horizon: ExecutionHorizon,
) -> UnresolvedTargets:
    """Every occurrence `select_target` cannot bind, and whether dropping `within` would bind it.

    Asked again without `within` only for the occurrences that failed, so a run that passes costs
    what it did.
    """
    unbounded = (
        None if table.fill.within is None else replace(table, fill=replace(table.fill, within=None))
    )
    waiting: list[tuple[str, datetime, datetime]] = []
    past_end: list[tuple[str, datetime]] = []
    last_fill: datetime | None = None
    for occurrence in occurrences:
        decision = occurrence.evaluation_time
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
            past_end.append((str(occurrence.occurrence_id), decision))
        else:
            waiting.append((str(occurrence.occurrence_id), decision, later.target_at))
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
    """One failure per cause, each listing only its own occurrences, the same from either door.

    `subject` is how the door names the rule (the judgment names the strategy, the freeze the
    rule and the end). The occurrences are listed identically by both, which is what lets
    `check` recognise the freeze restating what the judgments already said.
    """
    zone = ZoneInfo(fill.timezone)
    failures: list[Failure] = []
    if unresolved.waiting:
        occurrence, decision, instant = max(unresolved.waiting, key=lambda row: row[2] - row[1])
        gap = instant - decision
        failures.append(
            Failure.bounded(
                code,
                requirement,
                observed=(
                    f"{subject}; {len(unresolved.waiting)} occurrence(s) whose next such instant "
                    f"lies beyond `within: {fill.within}` -- the longest wait is {_wait(gap)}, "
                    f"{occurrence} from {decision.astimezone(zone).isoformat()} to "
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
                    f"{subject}; {len(unresolved.past_end)} occurrence(s) with no such instant "
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


def _validate_execution_targets(
    execution_table: ExecutionTable,
    strategy_agenda: FrozenAgenda,
    *,
    horizon: ExecutionHorizon,
    end: datetime,
) -> None:
    """Prove every strategy callback can bind an accepted intent before the run starts.

    A callback may return ``Hold``, but preflight cannot assume that it will. If an
    occurrence has no exact target under the fill rule, an intent accepted there would fail only
    after every earlier callback had already mutated account state. The horizon, the rule and
    the callback instants are all frozen facts, so that refusal belongs here.

    The horizon is handed in, cut once per command from the instants the workspace read for the
    agenda (`bound_execution_horizon`). Calling ``select_target`` without it would rescan the
    execution table once per occurrence -- both slower and vulnerable to observing different
    bytes while preflight is supposed to be proving one run.
    """
    unresolved = unresolved_targets(
        execution_table, strategy_agenda.occurrences, end=end, horizon=horizon
    )
    if not unresolved:
        return

    raise VqaprError(
        stage=Stage.FREEZE,
        failures=unresolved_target_failures(
            unresolved,
            execution_table.fill,
            code="execution.target_outside_horizon",
            requirement=(
                "every strategy occurrence must have an execution instant after it that the "
                "fill rule admits, inside the run horizon"
            ),
            subject=f"fill={execution_table.fill.describe()}, end={end.isoformat()}",
            end=end,
        ),
        mutation=False,
        retry_precondition=(
            "extend the run end through the missing execution instant, correct the execution "
            "table, or loosen the fill rule, then retry"
        ),
    )


def _freeze_strategy(
    workspace: Workspace,
    entry: StrategyEntry,
    *,
    compliance: tuple[str, ...],
    decide: OperationAgenda,
    execution_table: ExecutionTable,
    horizon: ExecutionHorizon,
    facts: RunFacts,
    start: datetime,
    end: datetime,
) -> FrozenStrategy:
    """One strategy's layer: its component, the run's Compliance rules, and the decide agenda.

    Every strategy of a run is called on the run's sessions at `at` (record `148`); the
    binding that used to be registered per strategy is derived here. The strategy is the
    instance the judgments already loaded (`facts`); its initial state is still proved on a
    second fresh instance (`_validate_initial_model_state`, `docs/issues/archive/076`).
    """
    registered = workspace.component(entry.component_id)
    if registered.kind is not Role.STRATEGY_MODEL:
        raise ValueError(
            f"strategy {entry.component_id!r} is registered as {registered.kind.value}, not as "
            "a strategy"
        )
    config = StrategyConfig(registered, decide.agenda_id)
    loaded_strategy = facts.component(entry.component_id, load_strategy_model)
    initial_payload = _validate_initial_model_state(
        workspace, config.component, loaded_strategy, entry.initial_model_memory
    )
    rules = tuple(_registered_compliance(workspace, name) for name in compliance)
    strategy_requirements = tuple(loaded_strategy.requirements())
    loaded_rules: tuple[Compliance, ...] = tuple(
        facts.component(name, load_compliance) for name in compliance
    )
    compliance_requirements = tuple(
        requirement for rule in loaded_rules for requirement in rule.requirements()
    )
    agenda = _freeze_agenda(decide, start=start, end=end)
    _validate_execution_targets(execution_table, agenda, horizon=horizon, end=end)
    return FrozenStrategy(
        config=config,
        compliance=ComplianceSet(rules),
        agenda=agenda,
        requirements=strategy_requirements,
        compliance_requirements=compliance_requirements,
        initial_model_memory=entry.initial_model_memory,
        initial_payload=initial_payload,
    )


def _refuse_taken_output(workspace: Workspace, *, run_id: str, writes: str) -> None:
    """A run writes a dataset that does not exist yet -- either kind, one rule (design §2).

    Asked here rather than after the last session: a run that computed for an hour and then found
    its name taken would have wasted the hour, and `check` asks the same question for the same
    reason (`_judge_outputs`). Re-running a run whose output stands is done by withdrawing the
    output first (`vqapr rm dataset`), which is how a produced dataset is told from an authored
    one: only the former names a producer.
    """
    taken = next((item for item in workspace.datasets if str(item.dataset_id) == writes), None)
    # The run's own product is not a taken name: it stands from an earlier run of THIS run,
    # and whether to replace it is `run`'s question (`replace_record`), the same as its record.
    # What is refused here is a name that belongs to someone else -- authored, or another run's.
    if taken is not None and taken.produced_by != run_id:
        raise VqaprError(
            stage=Stage.FREEZE,
            failures=[
                Failure.bounded(
                    code="run.output_registered",
                    status=Status.CONFLICT,
                    requirement="a run writes a dataset that does not exist yet",
                    observed=f"{writes!r} is already registered",
                    fix=(
                        f"declare a new `writes` for run {run_id!r}, or withdraw the existing "
                        f"{writes} first: vqapr rm dataset {writes}"
                    ),
                )
            ],
            mutation=False,
            retry_precondition="choose a new `writes`, or withdraw the dataset, then retry",
        )


def _freeze_datamodel(
    workspace: Workspace,
    entry: DataModelEntry,
    *,
    decide: OperationAgenda,
    facts: RunFacts,
    start: datetime,
    end: datetime,
) -> FrozenDataModel:
    """One datamodel's layer: its component, the run's sessions sliced, and its output.

    Refuses an output dataset id that is already registered, here rather than after the last
    session: a run that computed for an hour and then found its name taken would have wasted
    the hour, and `check` asks the same question for the same reason.
    """
    registered = workspace.component(entry.component_id)
    if registered.kind is not Role.DATA_MODEL:
        raise ValueError(
            f"datamodel {entry.component_id!r} is registered as {registered.kind.value}, not as "
            "a datamodel"
        )
    model = facts.component(entry.component_id, load_data_model)
    agenda = _freeze_agenda(decide, start=start, end=end)
    return FrozenDataModel(
        component=registered,
        agenda=agenda,
        value_fields=entry.value_fields,
        requirements=tuple(model.requirements()),
        initial_model_memory=entry.initial_model_memory,
    )


def _registered_compliance(workspace: Workspace, component_id: str) -> ComponentRef:
    ref = workspace.component(component_id)
    if ref.kind is not Role.COMPLIANCE:
        raise ValueError(
            f"compliance rule {component_id!r} is registered as {ref.kind.value}, not as a "
            "compliance rule"
        )
    return ref


def _registered_exchange(workspace: Workspace, component_id: str) -> ComponentRef:
    ref = workspace.component(component_id)
    if ref.kind is not Role.EXCHANGE:
        raise ValueError(
            f"exchange {component_id!r} is registered as {ref.kind.value}, not as an exchange"
        )
    return ref


def preflight_run(
    workspace_or_root: Workspace | str,
    definition: RunDefinition,
    facts: RunFacts | None = None,
) -> FrozenRun:
    """Freeze one workspace snapshot into a run-ready declaration.

    The run layer is resolved once -- venue, execution dataset, sessions, universe, account --
    and each strategy the run names is frozen on top of it (design §4.1). This proves
    that every callback of every strategy has somewhere to execute before any account mutates,
    and collects the union of everything the strategy and the compliance rules read: that union
    is the panel set the run will build.

    *Run-ready* is the promise, so a declaration carrying no execution price is refused here
    rather than frozen and rejected later by `run()`.
    """
    workspace = (
        workspace_or_root
        if isinstance(workspace_or_root, Workspace)
        else Workspace.open(workspace_or_root)
    )
    if not isinstance(definition, RunDefinition):
        raise TypeError("definition must be a RunDefinition")
    # The facts the judgments read, when they were asked first (`verify.verify_run`); otherwise
    # this freeze reads them for itself, once.
    facts = facts if facts is not None else RunFacts(workspace, definition)
    if definition.datamodel is not None:
        return _preflight_datamodel_run(workspace, definition, facts)
    _require_execution_authority(definition)
    if definition.start is None or definition.end is None:
        raise ValueError("preflight requires aware start and end bounds")
    start = require_tz_aware(definition.start, name="start")
    end = require_tz_aware(definition.end, name="end")
    if start.astimezone(UTC) > end.astimezone(UTC):
        raise ValueError("start must not be after end")

    # The one agenda the run declares by its sessions and wall time (record `148`).
    decide = facts.agenda()

    # Unconditional: `_require_execution_authority` has already refused a definition without
    # them, so the universe and account checks below can no longer be skipped by omission.
    exchange = _registered_exchange(workspace, definition.exchange or "")
    # The venue needs to know what every ordered id IS (design §6.2). Which ids get ordered is
    # the strategy's to decide at run time; that NOTHING is declared is knowable now.
    require_declared_roster(workspace, run_id=definition.run_id)
    loaded_exchange = facts.exchange()
    execution_table = facts.execution_table()
    horizon = facts.horizon()
    _validate_execution_requirements(loaded_exchange, execution_table)
    _validate_instrument_universe(definition.instruments, loaded_exchange)
    _validate_initial_account(
        definition.initial_account_snapshot, definition.initial_account_mode, loaded_exchange
    )

    if definition.strategy is None:  # pragma: no cover -- `RunDefinition` refuses this
        raise ValueError("a strategy run declares no strategy")
    _refuse_taken_output(workspace, run_id=definition.run_id, writes=definition.writes)
    strategies = (
        _freeze_strategy(
            workspace,
            definition.strategy,
            compliance=definition.compliance,
            decide=decide,
            execution_table=execution_table,
            horizon=horizon,
            facts=facts,
            start=start,
            end=end,
        ),
    )
    # Valuation subscribes to nothing: it reads the prices the venue already published to fill
    # against, so it contributes no DataRequirement. The union is what the strategy and the
    # compliance rules read, deduplicated, in the order first declared.
    requirements: list[DataRequirement] = []
    for layer in strategies:
        for requirement in (*layer.requirements, *layer.compliance_requirements):
            if requirement not in requirements:
                requirements.append(requirement)
    sources = _freeze_sources(workspace, tuple(requirements), execution_table.table.source)
    datasets_by_id = {
        requirement.dataset_id: workspace.dataset(str(requirement.dataset_id))
        for requirement in requirements
    }
    datasets = tuple(datasets_by_id[dataset_id] for dataset_id in sorted(datasets_by_id))

    return FrozenRun(
        run_id=definition.run_id,
        writes=definition.writes,
        source_digests={
            str(source.source_id): workspace.source_digest(source) for source in sources
        },
        strategy=strategies[0],
        exchange=exchange,
        execution=execution_table,
        start=start,
        end=end,
        initial_account_snapshot=definition.initial_account_snapshot,
        initial_account_mode=definition.initial_account_mode,
        instruments=definition.instruments,
        requirements=tuple(requirements),
        datasets=datasets,
        sources=sources,
    )


def _preflight_datamodel_run(
    workspace: Workspace, definition: RunDefinition, facts: RunFacts
) -> FrozenRun:
    """Freeze a datamodel run: the same sessions, no venue, no execution dataset, no account.

    What a strategy run proves about its venue and its account does not apply -- a datamodel
    sees neither (architecture 4.4) -- so the layer is the universe, the period and the sessions,
    and each datamodel is frozen on top of it with the datasets it reads.
    """
    if definition.start is None or definition.end is None:
        raise ValueError("preflight requires aware start and end bounds")
    start = require_tz_aware(definition.start, name="start")
    end = require_tz_aware(definition.end, name="end")
    if start.astimezone(UTC) > end.astimezone(UTC):
        raise ValueError("start must not be after end")
    decide = facts.agenda()
    if definition.datamodel is None:  # pragma: no cover -- `RunDefinition` refuses this
        raise ValueError("a datamodel run declares no datamodel")
    _refuse_taken_output(workspace, run_id=definition.run_id, writes=definition.writes)
    datamodels = (
        _freeze_datamodel(
            workspace, definition.datamodel, decide=decide, facts=facts, start=start, end=end
        ),
    )
    requirements: list[DataRequirement] = []
    for layer in datamodels:
        for requirement in layer.requirements:
            if requirement not in requirements:
                requirements.append(requirement)
    sources = _freeze_sources(workspace, tuple(requirements), None)
    datasets_by_id = {
        requirement.dataset_id: workspace.dataset(str(requirement.dataset_id))
        for requirement in requirements
    }
    datasets = tuple(datasets_by_id[dataset_id] for dataset_id in sorted(datasets_by_id))
    return FrozenRun(
        run_id=definition.run_id,
        writes=definition.writes,
        source_digests={
            str(source.source_id): workspace.source_digest(source) for source in sources
        },
        datamodel=datamodels[0],
        start=start,
        end=end,
        instruments=definition.instruments,
        requirements=tuple(requirements),
        datasets=datasets,
        sources=sources,
    )


__all__ = ["RunFacts", "preflight_run"]
