"""Validate, fingerprint, and persist project-local DataModel references."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_data_model
from vqapr.workspace import Workspace

_STAGE = "component.register"


def register_data_model(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    target = Path(path).resolve()
    try:
        fingerprint = fingerprint_component(
            target,
            kind=ComponentKind.DATA_MODEL,
            object_name=object_name,
            config=config,
        )
    except OSError as error:
        raise VqaprError(
            stage=_STAGE,
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    f"{_STAGE}.source_unreadable",
                    "DataModel source must be a readable Python file",
                    observed=str(error),
                )
            ],
            mutation=False,
            retry_precondition="create or repair the component source, then retry",
        ) from error
    ref = ComponentRef.of(
        raw_component_id,
        ComponentKind.DATA_MODEL,
        target,
        object_name,
        config=config,
        fingerprint=fingerprint,
    )
    load_data_model(ref)
    Workspace.create(project_root).register_component(ref)
    return ref
