"""Validate, fingerprint, and persist project-local extension references.

**The four extension points enter through one door.** Canon 10.2 says a user-authored component
is named by a `ComponentRef`, checked, and registered the same way whichever kind it is. That is
one function here, specialised per kind by which loader proves it.

The load is the point. Recording a fingerprint alone lets a broken component register cleanly and
fail in the middle of a run, where the reported stage names the run rather than the registration
that actually caused it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import (
    load_constraint,
    load_data_model,
    load_exchange,
    load_strategy_model,
)
from vqapr.workspace import Workspace

_STAGE = "component.register"


def _unreadable(kind_label: str, error: OSError) -> VqaprError:
    return VqaprError(
        stage=_STAGE,
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded(
                f"{_STAGE}.source_unreadable",
                f"{kind_label} source must be a readable Python file",
                observed=str(error),
            )
        ],
        mutation=False,
        retry_precondition="create or repair the component source, then retry",
    )


def _register(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    kind: ComponentKind,
    label: str,
    load: Callable[[ComponentRef], object],
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Fingerprint the source, prove the object loads, then persist the reference.

    Nothing is written until the load succeeds, so a workspace never holds a reference to a
    component that cannot be constructed.
    """
    target = Path(path).resolve()
    try:
        fingerprint = fingerprint_component(
            target,
            kind=kind,
            object_name=object_name,
            config=config,
        )
    except OSError as error:
        raise _unreadable(label, error) from error
    ref = ComponentRef.of(
        raw_component_id,
        kind,
        target,
        object_name,
        config=config,
        fingerprint=fingerprint,
    )
    load(ref)
    Workspace.create(project_root).register_component(ref)
    return ref


def register_data_model(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local DataModel after proving it loads."""
    return _register(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.DATA_MODEL,
        label="DataModel",
        load=load_data_model,
        config=config,
    )


def register_strategy_model(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local StrategyModel after proving it loads."""
    return _register(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.STRATEGY_MODEL,
        label="StrategyModel",
        load=load_strategy_model,
        config=config,
    )


def register_constraint(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local Constraint after proving it loads.

    `load_constraint` checks the public Constraint contract and that the component declares its
    data requirements, so a constraint that cannot state what it reads is refused here rather
    than at the first occurrence that projects it.
    """
    return _register(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.CONSTRAINT,
        label="Constraint",
        load=load_constraint,
        config=config,
    )


def register_exchange(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Register a project-local Exchange after proving it loads.

    `load_exchange` is the strictest of the four: it requires one of the shipped execution
    profiles, refuses a subclass that replaces `execute()` -- whose realism claim would be
    unverified -- and requires the component to expose its own `ExchangeRulesView`. Registering
    through this door is what makes those checks happen before a run rather than during one.
    """
    return _register(
        project_root,
        raw_component_id,
        path,
        object_name,
        kind=ComponentKind.EXCHANGE,
        label="Exchange",
        load=load_exchange,
        config=config,
    )
