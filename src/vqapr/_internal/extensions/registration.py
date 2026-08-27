"""Validate, fingerprint, and persist project-local extension references.

Internal-transition: this is the physical home of the component registration authority as of
G002. `vqapr.extension.registration` is a temporary forwarding adapter over this module until
G004 hard deletion; do not add new logic to the adapter.

**The four extension points enter through one door.** Canon 10.2 says a user-authored component
is named by a `ComponentRef`, checked, and registered the same way whichever kind it is. That is
one function here, specialised per kind by which loader proves it.

The check is the point. Recording a fingerprint alone lets a broken component register cleanly and
fail in the middle of a run, where the reported stage names the run rather than the registration
that actually caused it.

**Registration runs the conformance suite, it does not reimplement it.** Canon 10.2 requires
`pytest`, `vqapr check` and `vqapr register` to call the same conformance code, so there is one
implementation in `testing/conformance/` and this is one of its entrances. A component cannot pass
here and fail there.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vqapr._internal.extensions.component import ComponentKind, ComponentRef
from vqapr._internal.extensions.fingerprint import fingerprint_component
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, FailureSource, VqaprError
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
