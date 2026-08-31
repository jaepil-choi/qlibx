"""Validate, fingerprint, and persist project-local extension references.

This module is the extension registration authority, and `vqapr.extension.registration` is where
it lives.

**It was not always.** Until record `110` the implementation sat in
`vqapr._internal.extensions.registration`
with a four-line forwarding shim at this path, whose docstring promised deletion "when the
internal-transition closes". That promise was made in a file marked temporary and was still true six
months later, by which point a boundary test pinned the shim's existence. Record `110` discharged it
the other way: the shim's path became the real module's path, so no caller changed a line and the
temporary file stopped existing rather than being renewed. See
`docs/design/agent-first-surface.md` for the surface ruling this serves.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, FailureSource, VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.testing.conformance import conformance
from vqapr.workspace import Workspace

_STAGE = "component.register"


def _unreadable(kind_label: str, error: OSError, path: str | Path) -> VqaprError:
    return VqaprError(
        stage=_STAGE,
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded(
                f"{_STAGE}.source_unreadable",
                f"{kind_label} source must be a readable Python file",
                observed=str(error),
                # SOURCE_ACCESS, not COMPONENT_CONTRACT: fingerprinting failed on an OSError while
                # reading the file at `path` -- the declared path and kind are already fine, only
                # the filesystem read failed, which is exactly what SOURCE_ACCESS describes.
                fix=f"create or fix permissions on the {kind_label} source file at {path}",
                explain=ExplainTopic.SOURCE_ACCESS,
                source=FailureSource(file=str(path)),
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
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Fingerprint the source, prove the component conforms, then persist the reference.

    Nothing is written until conformance passes, so a workspace never holds a reference to a
    component Flow could not call.
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
        raise _unreadable(label, error, target) from error
    ref = ComponentRef.of(
        raw_component_id,
        kind,
        target,
        object_name,
        config=config,
        fingerprint=fingerprint,
    )
    conformance(ref, project_root=project_root).raise_if_failed()
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
        config=config,
    )
