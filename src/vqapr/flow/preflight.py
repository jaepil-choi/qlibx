"""Resolve a detached, immutable run declaration before any run mutation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    validate_execution_input,
)
from vqapr.exchange.listings import TradeRule
from vqapr.exchange.venue import Exchange
from vqapr.extension.component import ComponentRef
from vqapr.extension.loading import load_constraint, load_exchange, load_strategy_model
from vqapr.flow.run import FrozenAgenda, FrozenRun, RunDefinition
from vqapr.models.strategy_model import StrategyModel
from vqapr.runtime.agendas import OperationAgenda
from vqapr.workspace import Workspace


def _validate_component(workspace: Workspace, component: ComponentRef) -> ComponentRef:
    """Reject a declaration that is not the workspace's registered component."""
    registered = workspace.component(str(component.component_id))
    if registered != component:
        raise ValueError(f"component reference drift for {component.component_id!r}")
    return registered


def _freeze_agenda(
    workspace: Workspace,
    *,
    agenda_id: str,
    expected_role: object,
    start: datetime,
    end: datetime,
) -> FrozenAgenda:
    agenda = workspace.agenda(agenda_id)
    if not isinstance(agenda, OperationAgenda):  # defensive against a malformed workspace boundary
        raise TypeError("workspace agenda must be an OperationAgenda")
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
    """Check declared valuation input availability without reading physical source bytes."""
    dataset_id = getattr(requirement, "dataset_id", None)
    fields = getattr(requirement, "fields", None)
    if not isinstance(requirement, DataRequirement):
        raise TypeError("requirement must be a DataRequirement")
    registration = workspace.dataset(dataset_id)
    missing = tuple(field for field in fields if field not in registration.fields)
    if missing:
        raise ValueError(
            f"dataset {dataset_id!r} does not provide required fields: {', '.join(missing)}"
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
    """Stage and round-trip the Flow-owned initial Strategy payload."""
    try:
        strategy.memory = memory
        payload = BytesIO()
        strategy.save_payload(payload)
        frozen_payload = payload.getvalue()
        restored = load_strategy_model(component, project_root=workspace.project_root)
        restored.memory = memory
        restored.load_payload(BytesIO(frozen_payload))
        round_trip = BytesIO()
        restored.save_payload(round_trip)
        if round_trip.getvalue() != frozen_payload:
            raise ValueError("payload round-trip changed its bytes")
    except Exception as error:
        raise ValueError(
            f"strategy initial payload for {component.component_id!r} cannot be staged"
        ) from error
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
                )
            )
        absolute = abs(quantity)
        if absolute < rule.minimum_quantity:
            failures.append(
                Failure.bounded(
                    "preflight.account.minimum_quantity",
                    "each initial holding must meet its listing minimum_quantity",
                    observed=f"{instrument_id}: {absolute}",
                )
            )
        if (
            not rule.fractional_allowed
            and (absolute / rule.quantity_step).to_integral_value() != absolute / rule.quantity_step
        ):
            failures.append(
                Failure.bounded(
                    "preflight.account.quantity_step",
                    "each initial holding must align to its listing quantity_step",
                    observed=f"{instrument_id}: {absolute}",
                )
            )
        if not rule.fractional_allowed and absolute != absolute.to_integral_value():
            failures.append(
                Failure.bounded(
                    "preflight.account.fractional_quantity",
                    "each initial holding must satisfy its listing fractional quantity rule",
                    observed=f"{instrument_id}: {absolute}",
                )
            )
        if mode is AccountMode.LONG_ONLY and quantity < Decimal("0"):
            failures.append(
                Failure.bounded(
                    "preflight.account.mode",
                    "a long-only initial account must not contain short holdings",
                    observed=f"{instrument_id}: {quantity}",
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
    missing = tuple(
        instrument_id for instrument_id in instruments if instrument_id not in listings
    )
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
            )
        )
    if untradable:
        failures.append(
            Failure.bounded(
                code="preflight.universe.untradable_listing",
                requirement="the Exchange must permit a side for every traded instrument",
                observed=repr(untradable),
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

    A callback may return ``NoDecision``, but preflight cannot assume that it will. If an
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
                    "every strategy occurrence must have an exact execution target inside the "
                    "run horizon; extend end through the required execution snapshot, or choose "
                    "a fill selector whose target exists after that decision"
                ),
                observed=(
                    f"selector={selector}, end={end.isoformat()}, "
                    f"unresolved={len(missing)}"
                ),
                examples=[
                    f"{occurrence.occurrence_id}: "
                    f"{occurrence.evaluation_time.isoformat()}"
                    for occurrence in missing
                ],
                example_total=len(missing),
            )
        ],
        mutation=False,
        retry_precondition=(
            "extend the run end through the missing execution snapshot, correct the execution "
            "table, or choose a fill selector that resolves inside the horizon, then retry"
        ),
    )


def preflight_run(workspace_or_root: Workspace | str, definition: RunDefinition) -> FrozenRun:
    """Freeze one workspace snapshot into a run-ready declaration.

    This resolves declarations, the static agenda merge, and each strategy occurrence's exact
    execution target. It does not inspect callback results; instead it proves that an intent the
    callback may return has somewhere to execute before any callback mutates account state.

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
    _require_execution_authority(definition)
    if definition.start is None or definition.end is None:
        raise ValueError("preflight requires aware start and end bounds")
    start = require_tz_aware(definition.start, name="start")
    end = require_tz_aware(definition.end, name="end")
    if start.astimezone(UTC) > end.astimezone(UTC):
        raise ValueError("start must not be after end")

    strategy = workspace.strategy_config(definition.strategy.agenda_id)
    if strategy != definition.strategy:
        raise ValueError("strategy configuration reference drift")
    strategy = type(strategy)(
        _validate_component(workspace, strategy.component), strategy.agenda_id, strategy.agenda_role
    )
    loaded_strategy = load_strategy_model(strategy.component, project_root=workspace.project_root)
    initial_payload = _validate_initial_model_state(
        workspace, strategy.component, loaded_strategy, definition.initial_model_memory
    )

    valuation = workspace.valuation_config(definition.valuation.agenda_id)
    if valuation != definition.valuation:
        raise ValueError("valuation configuration reference drift")
    # Valuation subscribes to nothing: it reads the prices the venue already published to fill
    # against, so it contributes no DataRequirement to the frozen run.
    requirements: list[DataRequirement] = []

    monitoring = None
    if definition.monitoring is not None:
        monitoring = workspace.monitoring_policy(definition.monitoring.agenda_id)
        if monitoring != definition.monitoring:
            raise ValueError("monitoring policy reference drift")

    constraints = tuple(
        _validate_component(workspace, constraint)
        for constraint in definition.constraints.constraints
    )
    frozen_constraints = type(definition.constraints)(constraints)
    strategy_requirements = loaded_strategy.requirements()
    requirements.extend(strategy_requirements)
    loaded_constraints: tuple[Constraint, ...] = tuple(
        load_constraint(constraint, project_root=workspace.project_root)
        for constraint in constraints
    )
    constraint_requirements = tuple(
        requirement
        for constraint in loaded_constraints
        for requirement in constraint.requirements()
    )
    requirements.extend(constraint_requirements)

    # Unconditional: `_require_execution_authority` has already refused a definition without
    # them, so the universe and account checks below can no longer be skipped by omission.
    exchange = _validate_component(workspace, definition.exchange)
    loaded_exchange = load_exchange(exchange, project_root=workspace.project_root)
    execution_input = workspace.execution_input(definition.execution_input_id or "")
    validate_execution_input(execution_input).raise_if_failed()
    _validate_execution_requirements(loaded_exchange, execution_input)
    _validate_instrument_universe(definition.instruments, loaded_exchange)
    _validate_initial_account(
        definition.initial_account_snapshot, definition.initial_account_mode, loaded_exchange
    )
    sources = _freeze_sources(workspace, tuple(requirements), execution_input.table.source)
    datasets_by_id = {
        requirement.dataset_id: workspace.dataset(str(requirement.dataset_id))
        for requirement in requirements
    }
    datasets = tuple(datasets_by_id[dataset_id] for dataset_id in sorted(datasets_by_id))

    strategy_agenda = _freeze_agenda(
        workspace,
        agenda_id=strategy.agenda_id,
        expected_role=strategy.agenda_role,
        start=start,
        end=end,
    )
    valuation_agenda = _freeze_agenda(
        workspace,
        agenda_id=valuation.agenda_id,
        expected_role=valuation.agenda_role,
        start=start,
        end=end,
    )
    monitoring_agenda = (
        _freeze_agenda(
            workspace,
            agenda_id=monitoring.agenda_id,
            expected_role=monitoring.agenda_role,
            start=start,
            end=end,
        )
        if monitoring is not None
        else None
    )
    _validate_execution_targets(
        execution_input,
        strategy_agenda,
        start=start,
        end=end,
    )

    return FrozenRun(
        strategy=strategy,
        valuation=valuation,
        constraints=frozen_constraints,
        strategy_agenda=strategy_agenda,
        valuation_agenda=valuation_agenda,
        monitoring=monitoring,
        monitoring_agenda=monitoring_agenda,
        exchange=exchange,
        execution_input=execution_input,
        start=start,
        end=end,
        initial_account_snapshot=definition.initial_account_snapshot,
        initial_account_mode=definition.initial_account_mode,
        initial_model_memory=definition.initial_model_memory,
        initial_payload=initial_payload,
        instruments=definition.instruments,
        strategy_requirements=strategy_requirements,
        constraint_requirements=constraint_requirements,
        requirements=tuple(requirements),
        datasets=datasets,
        sources=sources,
    )


__all__ = ["preflight_run"]
