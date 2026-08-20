"""Load fingerprinted project-local extension instances through checked paths."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from vqapr.constraints.constraint import Constraint
from vqapr.data.requirements import DataRequirement
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.exchange.listings import ExchangeRulesView
from vqapr.exchange.venue import AcademicExchange, Exchange
from vqapr.exchange.venues.krx import KrxExchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.models.data_model import DataModel
from vqapr.models.strategy_model import StrategyModel

_STAGE = "component.load"


def _failure(code: str, requirement: str, observed: str) -> VqaprError:
    return VqaprError(
        stage=_STAGE,
        family=FailureFamily.DATA,
        failures=[Failure.bounded(code, requirement, observed=observed)],
        mutation=False,
        retry_precondition="fix and register the component again, then retry",
    )


def _load(
    ref: ComponentRef,
    *,
    kind: ComponentKind,
    project_root: str | Path | None = None,
) -> object:
    if not isinstance(ref, ComponentRef) or ref.kind is not kind:
        raise TypeError(f"ref must identify a {kind.value} component")
    path = (
        ref.path
        if ref.path.is_absolute() or project_root is None
        else Path(project_root) / ref.path
    )
    try:
        current = fingerprint_component(
            path,
            kind=ref.kind,
            object_name=ref.object_name,
            config=ref.config,
        )
    except OSError as error:
        raise _failure(
            f"{_STAGE}.source_unreadable",
            f"component source must remain readable at {path}",
            str(error),
        ) from error
    if current != ref.fingerprint:
        raise _failure(
            f"{_STAGE}.fingerprint_drift",
            "component source and config must match the registered fingerprint",
            f"registered={ref.fingerprint}, current={current}",
        )

    module_name = f"_vqapr_component_{ref.fingerprint}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise _failure(
            f"{_STAGE}.module_invalid",
            "component path must identify a loadable Python module",
            str(path),
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        candidate = getattr(module, ref.object_name)
        return candidate(**dict(ref.config))
    except Exception as error:
        raise _failure(
            f"{_STAGE}.construction_failed",
            "component object must load and construct from its registered config",
            f"{type(error).__name__}: {error}",
        ) from error


def positional_arity(target: object) -> tuple[int, int] | None:
    """How many positional arguments `target` requires, and how many it can absorb.

    Returns `(required, capacity)`, where capacity is `-1` for a `*args` target because it can
    take any number. Keyword-only parameters are excluded: Flow never passes one, so a component
    is free to add one with a default.

    This is the single definition of "can Flow call this", shared with the conformance suite so
    the load door and the suite cannot disagree about the same component.
    """
    try:
        parameters = inspect.signature(target).parameters.values()  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    required = 0
    capacity = 0
    for parameter in parameters:
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return (required, -1)
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue
        capacity += 1
        if parameter.default is inspect.Parameter.empty:
            required += 1
    return (required, capacity)


def accepts_contract_call(implementation: object, contract: object) -> bool:
    """Whether `implementation` can receive the positional call `contract` declares."""
    expected = positional_arity(contract)
    observed = positional_arity(implementation)
    if expected is None or observed is None:
        return True
    wanted = expected[1]
    required, capacity = observed
    return required <= wanted and (capacity == -1 or capacity >= wanted)


def _validate_callback_signature(component: object, *, base: type, method_name: str) -> None:
    """Reject a callback that cannot receive the call the contract declares.

    Flow calls the callback **positionally**, so the question is arity, not spelling. Renaming
    `context` to `ctx` produces an identical call and is allowed; adding a required parameter, or
    dropping one, means Flow's call cannot land and is refused.

    Annotations are not checked: a Strategy that always returns an intent may legitimately narrow
    its return type, and most components declare no annotation at all. Whether the callback
    returns the right *value* is decided at the call site during a run, where the value exists.
    """
    contract = getattr(base, method_name)
    implementation = getattr(type(component), method_name)
    if accepts_contract_call(implementation, contract):
        return
    wanted = positional_arity(contract)
    observed = positional_arity(implementation)
    if wanted is None or observed is None:  # pragma: no cover - the check above already passed
        return
    raise _failure(
        f"{_STAGE}.signature_invalid",
        f"{base.__name__}.{method_name}() must accept {wanted[1]} positional arguments",
        f"takes {'any number' if observed[1] == -1 else observed[1]} ({observed[0]} required)",
    )


def _requirements(component: object, *, label: str, required: bool) -> tuple[DataRequirement, ...]:
    declaration = getattr(component, "requirements", None)
    if declaration is None:
        if not required:
            return ()
        raise _failure(
            f"{_STAGE}.requirements_missing",
            f"{label}.requirements() must be declared before run",
            type(component).__name__,
        )
    try:
        requirements = declaration()
    except Exception as error:
        raise _failure(
            f"{_STAGE}.requirements_failed",
            f"{label}.requirements() must complete before run",
            f"{type(error).__name__}: {error}",
        ) from error
    if not isinstance(requirements, tuple) or not all(
        isinstance(item, DataRequirement) for item in requirements
    ):
        raise _failure(
            f"{_STAGE}.requirements_invalid",
            f"{label}.requirements() must return a tuple of DataRequirement values",
            repr(requirements),
        )
    return requirements


def load_data_model(ref: ComponentRef, *, project_root: str | Path | None = None) -> DataModel:
    model = _load(ref, kind=ComponentKind.DATA_MODEL, project_root=project_root)
    if not isinstance(model, DataModel):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered DataModel object must implement the public DataModel contract",
            type(model).__name__,
        )
    requirements = _requirements(model, label="DataModel", required=True)
    if not requirements:
        raise _failure(
            f"{_STAGE}.requirements_invalid",
            "DataModel.requirements() must return a non-empty tuple of DataRequirement values",
            repr(requirements),
        )
    return model


def load_strategy_model(
    ref: ComponentRef, *, project_root: str | Path | None = None
) -> StrategyModel:
    strategy = _load(ref, kind=ComponentKind.STRATEGY_MODEL, project_root=project_root)
    if not isinstance(strategy, StrategyModel):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered StrategyModel object must implement the public StrategyModel contract",
            type(strategy).__name__,
        )
    _validate_callback_signature(strategy, base=StrategyModel, method_name="on_occurrence")
    _requirements(strategy, label="StrategyModel", required=True)
    return strategy


def load_constraint(ref: ComponentRef, *, project_root: str | Path | None = None) -> Constraint:
    constraint = _load(ref, kind=ComponentKind.CONSTRAINT, project_root=project_root)
    if not isinstance(constraint, Constraint):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered Constraint object must implement the public Constraint contract",
            type(constraint).__name__,
        )
    _requirements(constraint, label="Constraint", required=True)
    return constraint


SHIPPED_EXECUTION_PROFILES: tuple[type, ...] = (AcademicExchange, KrxExchange)
"""The execution profiles this package implements end to end.

A run may only execute through a profile whose venue semantics are implemented and documented
here. A user subclass may add listings and costs, but it may not silently replace ``execute`` with
its own matching behaviour, because the resulting realism claim would be unverified.
"""


def load_exchange(ref: ComponentRef, *, project_root: str | Path | None = None) -> Exchange:
    exchange = _load(ref, kind=ComponentKind.EXCHANGE, project_root=project_root)
    profile = next(
        (base for base in SHIPPED_EXECUTION_PROFILES if isinstance(exchange, base)), None
    )
    if profile is None:
        names = ", ".join(base.__name__ for base in SHIPPED_EXECUTION_PROFILES)
        raise _failure(
            f"{_STAGE}.wrong_type",
            f"registered Exchange object must be one of the shipped profiles: {names}",
            type(exchange).__name__,
        )
    if type(exchange).execute is not profile.execute:
        raise _failure(
            f"{_STAGE}.execution_profile_invalid",
            f"{profile.__name__} subclasses must retain {profile.__name__}.execute() semantics",
            type(exchange).__name__,
        )
    if not isinstance(getattr(exchange, "rules", None), ExchangeRulesView):
        raise _failure(
            f"{_STAGE}.execution_profile_invalid",
            "an Exchange must expose its own ExchangeRulesView",
            type(exchange).__name__,
        )
    _requirements(exchange, label="Exchange", required=False)
    return exchange
