"""Load a fingerprinted project-local DataModel through one checked path."""

from __future__ import annotations

import importlib.util
import sys

from vqapr.data.requirements import DataRequirement
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.models.data_model import DataModel

_STAGE = "component.load"


def _failure(code: str, requirement: str, observed: str) -> VqaprError:
    return VqaprError(
        stage=_STAGE,
        family=FailureFamily.DATA,
        failures=[Failure.bounded(code, requirement, observed=observed)],
        mutation=False,
        retry_precondition="fix and register the component again, then retry",
    )


def load_data_model(ref: ComponentRef) -> DataModel:
    if not isinstance(ref, ComponentRef) or ref.kind is not ComponentKind.DATA_MODEL:
        raise TypeError("ref must identify a DataModel component")
    try:
        current = fingerprint_component(
            ref.path,
            kind=ref.kind,
            object_name=ref.object_name,
            config=ref.config,
        )
    except OSError as error:
        raise _failure(
            f"{_STAGE}.source_unreadable",
            f"component source must remain readable at {ref.path}",
            str(error),
        ) from error
    if current != ref.fingerprint:
        raise _failure(
            f"{_STAGE}.fingerprint_drift",
            "component source and config must match the registered fingerprint",
            f"registered={ref.fingerprint}, current={current}",
        )

    module_name = f"_vqapr_component_{ref.fingerprint}"
    spec = importlib.util.spec_from_file_location(module_name, ref.path)
    if spec is None or spec.loader is None:
        raise _failure(
            f"{_STAGE}.module_invalid",
            "component path must identify a loadable Python module",
            str(ref.path),
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        candidate = getattr(module, ref.object_name)
        model = candidate(**dict(ref.config))
    except Exception as error:
        raise _failure(
            f"{_STAGE}.construction_failed",
            "component object must load and construct from its registered config",
            f"{type(error).__name__}: {error}",
        ) from error
    if not isinstance(model, DataModel):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered DataModel object must implement the public DataModel contract",
            type(model).__name__,
        )
    try:
        requirements = model.requirements()
    except Exception as error:
        raise _failure(
            f"{_STAGE}.requirements_failed",
            "DataModel.requirements() must complete before compute",
            f"{type(error).__name__}: {error}",
        ) from error
    if (
        not isinstance(requirements, tuple)
        or not requirements
        or not all(isinstance(item, DataRequirement) for item in requirements)
    ):
        raise _failure(
            f"{_STAGE}.requirements_invalid",
            "DataModel.requirements() must return a non-empty tuple of DataRequirement values",
            repr(requirements),
        )
    return model
