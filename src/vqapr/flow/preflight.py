"""Resolve a detached, immutable run declaration before any run mutation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.authoring import StrategyModel
from vqapr.constraints.constraint import Constraint
from vqapr.data.datasets import lookback_fits_grain, require_grain
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    VqaprError,
)
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    validate_execution_input,
)
from vqapr.exchange.listings import TradeRule
from vqapr.exchange.venue import Exchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.loading import (
    load_constraint,
    load_data_model,
    load_exchange,
    load_strategy_model,
)
from vqapr.flow.frozen import FrozenAgenda, FrozenDataModel, FrozenRun, FrozenStrategy
from vqapr.flow.run import (
    ConstraintSet,
    DataModelEntry,
    RunDefinition,
    StrategyConfig,
    StrategyEntry,
)
from vqapr.runtime.agendas import OperationAgenda, OperationRole
from vqapr.workspace import Workspace


def derived_agenda(workspace: Workspace, definition: RunDefinition) -> OperationAgenda:
    """The run's one agenda -- every session, at `at` -- built from what the run declares.

    Record `148`: an agenda is no longer a registered declaration. A run says which sessions
    (`sessions_from`, a dataset's own days, or `sessions` listed) and at what venue-local wall
    time every model is called, and this builds the `OperationAgenda` the flow already runs on,
    id `<run_id>.sessions`. `OperationAgenda.daily` owns the occurrence ids, fold and offset, so
    a DST session is refused rather than guessed. The book is valued at the instant the venue
    fills and monitored right after each commit, so there is no second agenda to build.
    """
    sessions: Iterable[datetime | date] = (
        workspace.evaluation_times(definition.sessions_from)
        if definition.sessions_from is not None
        else definition.sessions
    )
    assert definition.at is not None
    if definition.start is not None and definition.end is not None:
        # Cut on DATES before an occurrence is built, not on occurrences after (`docs/issues/069`:
        # a run of 15 sessions built 735 occurrences, with their fold and offset proofs and the
        # agenda's identity over them, three times per command). An occurrence on venue-local
        # day `d` at `at` lies inside `[start, end]` only if `d` lies between the bounds' local
        # dates, so this keeps a superset of what `inclusive_slice` keeps and changes nothing
        # it would have answered. `daily` still owns the date conversion and the DST refusal.
        zone = ZoneInfo(definition.timezone)
        first = definition.start.astimezone(zone).date()
        last = definition.end.astimezone(zone).date()

        def _local_date(session: datetime | date) -> date:
            if isinstance(session, datetime):
                return (session.astimezone(zone) if session.tzinfo is not None else session).date()
            return session

        sessions = tuple(
            session for session in sessions if first <= _local_date(session) <= last
        )
    return OperationAgenda.daily(
        agenda_id=definition.agenda_id,
        role=OperationRole.STRATEGY_CALLBACK,
        sessions=sessions,
        at=definition.at,
        timezone=definition.timezone,
        provenance=f"run {definition.run_id}",
    )


def _freeze_agenda(
    agenda: OperationAgenda,
    *,
    expected_role: OperationRole,
    start: datetime,
    end: datetime,
) -> FrozenAgenda:
    agenda_id = agenda.agenda_id
    if agenda.role is not expected_role:
        raise ValueError(
            f"agenda {agenda_id!r} role {agenda.role!s} does not match owner role {expected_role!s}"
        )
    # OperationAgenda construction retains and proves every local fold/offset. Calling this
    # method additionally makes malformed externally supplied agendas fail before a run exists.
    for occurrence in agenda.occurrences:
        proof = occurrence.local_instant
        if proof.instant.utcoffset() is None:
            raise ValueError(f"agenda {agenda_id!r} occurrence lacks an offset proof")
    return FrozenAgenda(
        agenda_id=agenda.agenda_id,
        agenda_role=agenda.role,
        occurrences=agenda.inclusive_slice(start, end),
        timezone=agenda.timezone,
        content_identity=agenda.content_identity,
        provenance_identity=agenda.provenance_identity,
    )


def _validate_requirement(workspace: Workspace, requirement: object) -> SourceSpec:
    """Check declared valuation input availability without reading physical source bytes.

    A requirement names a dataset and one field, so both halves are checked here: the dataset must
    be registered, and it must expose that field.
    """
    if not isinstance(requirement, DataRequirement):
        raise TypeError("requirement must be a DataRequirement")
    registration = workspace.dataset(str(requirement.dataset_id))
    require_grain(registration)
    mismatch = lookback_fits_grain(requirement.lookback, registration.grain)
    if mismatch is not None:
        raise TypeError(f"dataset {str(requirement.dataset_id)!r}: {mismatch}")
    if requirement.field_id not in registration.fields:
        raise ValueError(
            f"dataset {str(requirement.dataset_id)!r} does not provide required field: "
            f"{requirement.field_id}"
        )
    return workspace.source(str(registration.source))


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
    memory: object,
) -> bytes:
    """Stage and round-trip the Flow-owned initial Strategy payload.

    Three separate steps, each with its own `try` and its own name in the refusal
    (`docs/issues/076`). One block around all three could only say "cannot be staged", so a
    `load_payload` that hit `EOFError` on an empty source and a `save_payload` that was not
    deterministic produced the SAME sentence -- and the author could not tell which of their two
    methods to open. The `from error` chain carries the original; `cli.run.preflight_refusal`
    renders it.
    """
    component_id = component.component_id

    def staged(step: str) -> ValueError:
        return ValueError(
            f"strategy initial payload for {component_id!r} cannot be staged: {step}"
        )

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
        rule = exchange.listings.get(instrument_id)
        if rule is None:
            failures.append(
                Failure.bounded(
                    "preflight.account.unlisted_holding",
                    "every initial holding must have a listing on the selected Exchange",
                    observed=instrument_id,
                    fix=(
                        f"add a listing for {instrument_id} to the Exchange, or drop it from "
                        "the initial account"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                )
            )
            continue
        assert isinstance(rule, TradeRule)
        if not rule.permits_position(quantity, -quantity):
            failures.append(
                Failure.bounded(
                    "preflight.account.holding_not_closable",
                    "each initial holding must be closable on the selected Exchange",
                    observed=f"{instrument_id}: {rule.access.value}",
                    fix=(
                        f"permit closing access for {instrument_id} on the Exchange, or drop "
                        "the holding from the initial account"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                )
            )
        absolute = abs(quantity)
        if absolute < rule.minimum_quantity:
            failures.append(
                Failure.bounded(
                    "preflight.account.minimum_quantity",
                    "each initial holding must meet its listing minimum_quantity",
                    observed=f"{instrument_id}: {absolute}",
                    fix=(
                        f"raise the {instrument_id} holding to at least the listing "
                        f"minimum_quantity ({rule.minimum_quantity}), or drop it from the "
                        "initial account"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
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
                    "preflight.account.quantity_step",
                    "each initial holding must align to its listing quantity_step",
                    observed=f"{instrument_id}: {absolute}",
                    fix=(
                        f"round the {instrument_id} holding to a multiple of the listing "
                        f"quantity_step ({rule.quantity_step}); {nearest_hint}"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                )
            )
        if not rule.fractional_allowed and absolute != absolute.to_integral_value():
            failures.append(
                Failure.bounded(
                    "preflight.account.fractional_quantity",
                    "each initial holding must satisfy its listing fractional quantity rule",
                    observed=f"{instrument_id}: {absolute}",
                    fix=(
                        f"round the {instrument_id} holding to a whole quantity, or set the "
                        "listing's fractional_allowed to permit fractional holdings"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                )
            )
        if mode is AccountMode.LONG_ONLY and quantity < Decimal("0"):
            failures.append(
                Failure.bounded(
                    "preflight.account.mode",
                    "a long-only initial account must not contain short holdings",
                    observed=f"{instrument_id}: {quantity}",
                    fix=(
                        f"remove the short {instrument_id} holding from the initial account, "
                        "or declare the account mode as not long-only"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                )
            )
    if failures:
        raise VqaprError(
            stage="preflight.account",
            family=FailureFamily.EXCHANGE,
            failures=failures,
            mutation=False,
            retry_precondition=("correct the initial account or Exchange listing, then retry"),
        )


def _validate_execution_requirements(exchange: Exchange, execution_input: object) -> None:
    """Prove the venue's declared regimes have the execution prices they need.

    A venue computes its own regimes -- a KRX price limit is the base price times a declared rate
    -- so it needs a number the user registered, never a conclusion the user derived. When that
    number is absent the run is refused *before* it starts, and the message names the feature to
    switch off rather than only the missing column. Running with the regime silently inert would
    produce a result that looks like a limit-aware backtest and is not one.
    """
    requirements = tuple(getattr(exchange, "execution_requirements", tuple)())
    if not requirements:
        return
    declared = set(execution_input.table.price_fields)
    missing = tuple(
        requirement for requirement in requirements if requirement.price not in declared
    )
    if not missing:
        return
    raise VqaprError(
        stage="preflight.execution",
        family=FailureFamily.EXCHANGE,
        failures=[
            Failure.bounded(
                code="preflight.execution.requirement_missing",
                requirement=(
                    "the execution input must declare every price the Exchange requires, "
                    "or the feature that needs it must be switched off"
                ),
                observed=", ".join(
                    f"{item.feature} needs price {item.price!r}" for item in missing
                ),
                fix=(
                    "register the missing price fields on the execution input, or construct "
                    "the Exchange with the features that need them disabled"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
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
    listings = exchange.listings
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
                code="preflight.universe.unlisted_instrument",
                requirement="every frozen run instrument must have an Exchange listing",
                observed=repr(missing),
                fix=(
                    "add an Exchange listing for each missing instrument, or remove it from "
                    "the run's traded instrument universe"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
            )
        )
    if untradable:
        failures.append(
            Failure.bounded(
                code="preflight.universe.untradable_listing",
                requirement="the Exchange must permit a side for every traded instrument",
                observed=repr(untradable),
                fix=(
                    "remove each untradable instrument from the traded universe and read it "
                    "as data instead, or update the Exchange listing to permit a side"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
            )
        )
    raise VqaprError(
        stage="preflight.universe",
        family=FailureFamily.EXCHANGE,
        failures=failures,
        mutation=False,
        retry_precondition="register complete listings or remove unlisted instruments, then retry",
    )


def _require_execution_authority(definition: RunDefinition) -> None:
    """Refuse a run that declares no execution price.

    An observation dataset is optional: a Strategy may declare no requirement and decide nothing,
    and a run of it is still a run. **An execution price is not optional.** Every run values its
    book and fills against the prices a venue published, so the execution input is the one
    registration that is mandatory from the start.

    It is refused here rather than in `RunDefinition`, which is a pure value object built by
    callers who supply the pairing another way, and rather than in `run()`, which is far too late:
    this function promises a *run-ready* declaration, so returning a `FrozenRun` that `run()` will
    reject contradicts its own contract. Late refusal also left
    `_validate_instrument_universe` and `_validate_initial_account` skipped entirely, so a run
    could freeze with unlisted instruments and never be told.
    """
    if definition.exchange is not None and definition.execution_input_id is not None:
        return
    raise VqaprError(
        stage="preflight.execution",
        family=FailureFamily.EXCHANGE,
        failures=[
            Failure.bounded(
                code="preflight.execution.missing",
                requirement=(
                    "a run must declare an Exchange and an execution input; the execution price "
                    "is required even when the Strategy reads no observation dataset"
                ),
                observed=(
                    f"exchange={definition.exchange!r}, "
                    f"execution_input_id={definition.execution_input_id!r}"
                ),
                fix=(
                    "declare both an Exchange and an execution input on the RunDefinition "
                    "before calling preflight_run"
                ),
                explain=ExplainTopic.DECLARATION_SHAPE,
            )
        ],
        mutation=False,
        retry_precondition=(
            "register an execution input and declare it with its Exchange, then retry"
        ),
    )


def _validate_execution_targets(
    execution_input: ExecutionInputRegistration,
    strategy_agenda: FrozenAgenda,
    *,
    start: datetime,
    end: datetime,
) -> None:
    """Prove every strategy callback can bind an accepted intent before the run starts.

    A callback may return ``Hold``, but preflight cannot assume that it will. If an
    occurrence has no exact target under the declared fill convention, an intent accepted there
    would fail only after every earlier callback had already mutated account state. The horizon,
    selector, and callback instants are all frozen facts, so that refusal belongs here.

    The horizon is read once. Calling ``select_target`` without it would rescan the execution
    table once per occurrence -- both slower and vulnerable to observing different bytes while
    preflight is supposed to be proving one run.
    """
    horizon = execution_input.fill.build_horizon(
        execution_input,
        start_time=start,
        end_time=end,
    )
    missing = tuple(
        occurrence
        for occurrence in strategy_agenda.occurrences
        if execution_input.fill.select_target(
            execution_input,
            decision_time=occurrence.evaluation_time,
            end_time=end,
            horizon=horizon,
        )
        is None
    )
    if not missing:
        return

    selector = execution_input.fill.selector.value.lower()
    raise VqaprError(
        stage="preflight.execution",
        family=FailureFamily.EXCHANGE,
        failures=[
            Failure.bounded(
                code="preflight.execution.target_outside_horizon",
                requirement=(
                    "every strategy occurrence must have an exact execution target strictly "
                    "later than the occurrence and inside the run horizon; extend end through "
                    "the required execution snapshot, or choose a fill selector whose target "
                    "exists after that decision"
                ),
                observed=(f"selector={selector}, end={end.isoformat()}, unresolved={len(missing)}"),
                examples=[
                    f"{occurrence.occurrence_id}: {occurrence.evaluation_time.isoformat()}"
                    for occurrence in missing
                ],
                example_total=len(missing),
                fix=(
                    f"widen the run end past {end.isoformat()} to cover the required "
                    f"execution snapshot, or choose a fill selector other than {selector!r} "
                    "whose target resolves inside the horizon"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
            )
        ],
        mutation=False,
        retry_precondition=(
            "extend the run end through the missing execution snapshot, correct the execution "
            "table, or choose a fill selector that resolves inside the horizon, then retry"
        ),
    )


def _freeze_strategy(
    workspace: Workspace,
    entry: StrategyEntry,
    *,
    decide: OperationAgenda,
    execution_input: ExecutionInputRegistration,
    start: datetime,
    end: datetime,
) -> FrozenStrategy:
    """One strategy's layer: its component, its constraints, and the run's decide agenda sliced.

    Every strategy of a run is called on the run's sessions at `at` (record `148`); the
    binding that used to be registered per strategy is derived here.
    """
    registered = workspace.component(entry.component_id)
    if registered.kind is not ComponentKind.STRATEGY_MODEL:
        raise ValueError(
            f"strategy {entry.component_id!r} is registered as {registered.kind.value}, not as "
            "a strategy"
        )
    config = StrategyConfig(registered, decide.agenda_id, OperationRole.STRATEGY_CALLBACK)
    loaded_strategy = load_strategy_model(config.component, project_root=workspace.project_root)
    initial_payload = _validate_initial_model_state(
        workspace, config.component, loaded_strategy, entry.initial_model_memory
    )
    constraints = tuple(_registered_constraint(workspace, name) for name in entry.constraints)
    strategy_requirements = tuple(loaded_strategy.requirements())
    loaded_constraints: tuple[Constraint, ...] = tuple(
        load_constraint(constraint, project_root=workspace.project_root)
        for constraint in constraints
    )
    constraint_requirements = tuple(
        requirement
        for constraint in loaded_constraints
        for requirement in constraint.requirements()
    )
    agenda = _freeze_agenda(decide, expected_role=config.agenda_role, start=start, end=end)
    _validate_execution_targets(execution_input, agenda, start=start, end=end)
    return FrozenStrategy(
        config=config,
        constraints=ConstraintSet(constraints),
        agenda=agenda,
        requirements=strategy_requirements,
        constraint_requirements=constraint_requirements,
        initial_model_memory=entry.initial_model_memory,
        initial_payload=initial_payload,
    )


def _freeze_datamodel(
    workspace: Workspace,
    entry: DataModelEntry,
    *,
    decide: OperationAgenda,
    start: datetime,
    end: datetime,
) -> FrozenDataModel:
    """One datamodel's layer: its component, the run's sessions sliced, and its output.

    Refuses an output dataset id that is already registered, here rather than after the last
    session: a run that computed for an hour and then found its name taken would have wasted
    the hour, and `check` asks the same question for the same reason.
    """
    registered = workspace.component(entry.component_id)
    if registered.kind is not ComponentKind.DATA_MODEL:
        raise ValueError(
            f"datamodel {entry.component_id!r} is registered as {registered.kind.value}, not as "
            "a datamodel"
        )
    if any(str(item.dataset_id) == entry.dataset_id for item in workspace.datasets):
        raise VqaprError(
            stage="preflight.datamodel",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="preflight.datamodel.output_registered",
                    requirement="a datamodel run writes a dataset that does not exist yet",
                    observed=f"{entry.dataset_id!r} is already registered",
                    fix=(
                        f"declare a new dataset_id for {entry.component_id!r}, or remove the "
                        f"existing {entry.dataset_id} registration from the workspace first"
                    ),
                    explain=ExplainTopic.WORKSPACE_STATE,
                )
            ],
            mutation=False,
            retry_precondition="choose a new output dataset_id, then retry",
        )
    model = load_data_model(registered, project_root=workspace.project_root)
    agenda = _freeze_agenda(
        decide, expected_role=OperationRole.STRATEGY_CALLBACK, start=start, end=end
    )
    return FrozenDataModel(
        component=registered,
        agenda=agenda,
        dataset_id=entry.dataset_id,
        value_fields=entry.value_fields,
        requirements=tuple(model.requirements()),
        initial_model_memory=entry.initial_model_memory,
    )


def _registered_constraint(workspace: Workspace, component_id: str) -> ComponentRef:
    ref = workspace.component(component_id)
    if ref.kind is not ComponentKind.CONSTRAINT:
        raise ValueError(
            f"constraint {component_id!r} is registered as {ref.kind.value}, not as a constraint"
        )
    return ref


def _registered_exchange(workspace: Workspace, component_id: str) -> ComponentRef:
    ref = workspace.component(component_id)
    if ref.kind is not ComponentKind.EXCHANGE:
        raise ValueError(
            f"exchange {component_id!r} is registered as {ref.kind.value}, not as an exchange"
        )
    return ref


def preflight_run(workspace_or_root: Workspace | str, definition: RunDefinition) -> FrozenRun:
    """Freeze one workspace snapshot into a run-ready declaration.

    The run layer is resolved once -- venue, execution input, sessions, universe, account --
    and each strategy the run names is frozen on top of it (design §4.1). This proves
    that every callback of every strategy has somewhere to execute before any account mutates,
    and collects the union of everything the strategies and their constraints read: that union
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
    if definition.datamodels:
        return _preflight_datamodel_run(workspace, definition)
    _require_execution_authority(definition)
    if definition.start is None or definition.end is None:
        raise ValueError("preflight requires aware start and end bounds")
    start = require_tz_aware(definition.start, name="start")
    end = require_tz_aware(definition.end, name="end")
    if start.astimezone(UTC) > end.astimezone(UTC):
        raise ValueError("start must not be after end")

    # The one agenda the run declares by its sessions and wall time (record `148`).
    decide = derived_agenda(workspace, definition)

    # Unconditional: `_require_execution_authority` has already refused a definition without
    # them, so the universe and account checks below can no longer be skipped by omission.
    exchange = _registered_exchange(workspace, definition.exchange or "")
    loaded_exchange = load_exchange(exchange, project_root=workspace.project_root)
    execution_input = workspace.execution_input(definition.execution_input_id or "")
    validate_execution_input(execution_input).raise_if_failed()
    _validate_execution_requirements(loaded_exchange, execution_input)
    _validate_instrument_universe(definition.instruments, loaded_exchange)
    _validate_initial_account(
        definition.initial_account_snapshot, definition.initial_account_mode, loaded_exchange
    )

    strategies = tuple(
        _freeze_strategy(
            workspace, entry, decide=decide, execution_input=execution_input, start=start, end=end
        )
        for entry in definition.strategies
    )
    # Valuation subscribes to nothing: it reads the prices the venue already published to fill
    # against, so it contributes no DataRequirement. The union is what the strategies and their
    # constraints read, deduplicated, in the order first declared.
    requirements: list[DataRequirement] = []
    for layer in strategies:
        for requirement in (*layer.requirements, *layer.constraint_requirements):
            if requirement not in requirements:
                requirements.append(requirement)
    sources = _freeze_sources(workspace, tuple(requirements), execution_input.table.source)
    datasets_by_id = {
        requirement.dataset_id: workspace.dataset(str(requirement.dataset_id))
        for requirement in requirements
    }
    datasets = tuple(datasets_by_id[dataset_id] for dataset_id in sorted(datasets_by_id))

    return FrozenRun(
        run_id=definition.run_id,
        strategies=strategies,
        exchange=exchange,
        execution_input=execution_input,
        start=start,
        end=end,
        initial_account_snapshot=definition.initial_account_snapshot,
        initial_account_mode=definition.initial_account_mode,
        instruments=definition.instruments,
        requirements=tuple(requirements),
        datasets=datasets,
        sources=sources,
    )


def _preflight_datamodel_run(workspace: Workspace, definition: RunDefinition) -> FrozenRun:
    """Freeze a datamodel run: the same sessions, no venue, no execution input, no account.

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
    decide = derived_agenda(workspace, definition)
    datamodels = tuple(
        _freeze_datamodel(workspace, entry, decide=decide, start=start, end=end)
        for entry in definition.datamodels
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
        strategies=(),
        datamodels=datamodels,
        start=start,
        end=end,
        instruments=definition.instruments,
        requirements=tuple(requirements),
        datasets=datasets,
        sources=sources,
    )


__all__ = ["preflight_run"]
