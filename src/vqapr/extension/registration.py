"""Validate, fingerprint, and persist project-local extension references."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_data_model, load_strategy_model
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
        raise _unreadable("DataModel", error) from error
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


def register_strategy_model(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """등록 시점에 StrategyModel을 실제로 load/construct한 뒤에만 보관한다.

    fingerprint만 기록하면 깨진 strategy가 깨끗하게 등록되고 run 한복판에서 처음 터진다.
    그러면 실패가 가리키는 stage가 진짜 원인(register)이 아니라 엉뚱한 곳이 된다.
    """
    target = Path(path).resolve()
    try:
        fingerprint = fingerprint_component(
            target,
            kind=ComponentKind.STRATEGY_MODEL,
            object_name=object_name,
            config=config,
        )
    except OSError as error:
        raise _unreadable("StrategyModel", error) from error
    ref = ComponentRef.of(
        raw_component_id,
        ComponentKind.STRATEGY_MODEL,
        target,
        object_name,
        config=config,
        fingerprint=fingerprint,
    )
    load_strategy_model(ref)
    Workspace.create(project_root).register_component(ref)
    return ref
