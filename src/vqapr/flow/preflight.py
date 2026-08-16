"""Resolve a detached, immutable run declaration before any run mutation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from vqapr.domain.timestamps import require_tz_aware
from vqapr.extension.component import ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.flow.run import FrozenAgenda, FrozenRun, RunDefinition
from vqapr.runtime.agendas import OperationAgenda
from vqapr.workspace import Workspace


def _component_path(workspace: Workspace, component: ComponentRef) -> Path:
    path = component.path
    return path if path.is_absolute() else workspace.project_root / path


def _validate_component(workspace: Workspace, component: ComponentRef) -> ComponentRef:
    """Resolve one registered reference and reject source/configuration drift."""
    registered = workspace.component(str(component.component_id))
    if registered != component:
        raise ValueError(f"component reference drift for {component.component_id!r}")

    path = _component_path(workspace, registered)
    try:
        actual = fingerprint_component(
            path,
            kind=registered.kind,
            object_name=registered.object_name,
            config=registered.config,
        )
    except OSError as error:
        raise ValueError(
            f"component source for {registered.component_id!r} cannot be fingerprinted"
        ) from error
    if actual != registered.fingerprint:
        raise ValueError(f"component fingerprint drift for {registered.component_id!r}")
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


def _validate_requirement(workspace: Workspace, requirement: object) -> None:
    """Check declared valuation input availability without reading physical source bytes."""
    dataset_id = getattr(requirement, "dataset_id", None)
    fields = getattr(requirement, "fields", None)
    if not isinstance(dataset_id, str) or not isinstance(fields, tuple):
        raise TypeError("requirement must be a DataRequirement")
    registration = workspace.dataset(dataset_id)
    missing = tuple(field for field in fields if field not in registration.fields)
    if missing:
        raise ValueError(
            f"dataset {dataset_id!r} does not provide required fields: {', '.join(missing)}"
        )


def preflight_run(workspace: Workspace, definition: RunDefinition) -> FrozenRun:
    """Freeze one workspace snapshot into a run-ready declaration.

    This resolves only declarations and the static agenda merge. In particular it does
    not inspect callback results or select execution targets, because those require the
    callback's Flow-stamped decision time.
    """
    if not isinstance(workspace, Workspace):
        raise TypeError("workspace must be a Workspace")
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

    valuation = workspace.valuation_config(definition.valuation.agenda_id)
    if valuation != definition.valuation:
        raise ValueError("valuation configuration reference drift")
    _validate_requirement(workspace, valuation.mark_requirement)

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

    exchange = None
    execution_input = None
    if definition.exchange is not None:
        exchange = _validate_component(workspace, definition.exchange)
        execution_input = workspace.execution_input(definition.execution_input_id or "")

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
        initial_account=definition.initial_account,
        initial_model_state=definition.initial_model_state,
    )


__all__ = ["preflight_run"]
