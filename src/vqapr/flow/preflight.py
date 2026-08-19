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
from vqapr.domain.enums import Side
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import validate_execution_input
from vqapr.exchange.listings import ListingRule
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
        assert isinstance(rule, ListingRule)
        close_side = Side.SELL if quantity > 0 else Side.BUY
        if close_side not in rule.permitted_sides:
            failures.append(
                Failure.bounded(
                    "preflight.account.close_side_missing",
                    "each initial holding must be closable by a permitted listing side",
                    observed=f"{instrument_id}: {close_side.value}",
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


def _validate_instrument_universe(
    instruments: tuple[str, ...],
    exchange: Exchange,
) -> None:
    missing = tuple(
        instrument_id for instrument_id in instruments if instrument_id not in exchange.listings
    )
    if not missing:
        return
    raise VqaprError(
        stage="preflight.universe",
        family=FailureFamily.EXCHANGE,
        failures=[
            Failure.bounded(
                code="preflight.universe.unlisted_instrument",
                requirement="every frozen run instrument must have an Exchange listing",
                observed=repr(missing),
            )
        ],
        mutation=False,
        retry_precondition="register complete listings or remove unlisted instruments, then retry",
    )


def preflight_run(workspace_or_root: Workspace | str, definition: RunDefinition) -> FrozenRun:
    """Freeze one workspace snapshot into a run-ready declaration.

    This resolves only declarations and the static agenda merge. In particular it does
    not inspect callback results or select execution targets, because those require the
    callback's Flow-stamped decision time.
    """
    workspace = (
        workspace_or_root
        if isinstance(workspace_or_root, Workspace)
        else Workspace.open(workspace_or_root)
    )
    if not isinstance(definition, RunDefinition):
        raise TypeError("definition must be a RunDefinition")
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

    exchange = None
    execution_input = None
    if definition.exchange is not None:
        exchange = _validate_component(workspace, definition.exchange)
        loaded_exchange = load_exchange(exchange, project_root=workspace.project_root)
        execution_input = workspace.execution_input(definition.execution_input_id or "")
        validate_execution_input(execution_input).raise_if_failed()
        _validate_instrument_universe(definition.instruments, loaded_exchange)
        _validate_initial_account(
            definition.initial_account_snapshot, definition.initial_account_mode, loaded_exchange
        )
    sources = _freeze_sources(
        workspace,
        tuple(requirements),
        execution_input.table.source if execution_input is not None else None,
    )
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
