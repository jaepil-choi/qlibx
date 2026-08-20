"""One verdict on whether a component honours its extension contract.

Canon §10.2 says the four extension points *"enter through the same door and pass the same
conformance"*. Registration is that door (`extension/registration.py`), and it already proves a
component **loads**: the fingerprint matches, the object constructs, it implements its contract
type, and it declares its data requirements.

Loading is not conformance. A component can construct perfectly and still be unusable, because the
methods Flow will call are not the methods it defined. Renaming a parameter of
`Constraint.project`, or dropping `DataModel.compute` onto a class that inherits an abstract stub,
produces an object that registers cleanly and fails in the middle of a run — where the reported
stage names the run rather than the component that caused it.

**The suite is a superset of the load, never a copy of it.** `conformance()` calls the same
`load_*` function registration calls, then checks what loading does not: that every method the
contract declares is present, callable, and declares the parameters Flow will pass positionally.
That is why canon requires `pytest`, `vqapr check` and `vqapr register` to *"call the same
conformance code"* — there is one implementation and three entrances, so a component cannot pass
one and fail another.

Its input is a `ComponentRef` (canon §10.3), which is the same type a shipped component and a
user-authored one both arrive as. There is deliberately no branch that can tell them apart, and
`academic` and `krx` are the first two implementations to pass it.

What it cannot check is deliberately absent. Whether a callback returns a *useful* intent for real
data is only knowable during a run against real observations, so this suite makes no claim about
it. It answers exactly one question: will Flow be able to call this component at all.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from vqapr.constraints.constraint import Constraint
from vqapr.domain.errors import Diagnosis, Failure, FailureFamily, collector
from vqapr.exchange.venue import Exchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.loading import (
    load_constraint,
    load_data_model,
    load_exchange,
    load_strategy_model,
)
from vqapr.models.data_model import DataModel
from vqapr.models.strategy_model import StrategyModel

STAGE = "component.conformance"
_RETRY = "fix the component to match its contract, then register it again"


_CONTRACT_METHODS: dict[ComponentKind, tuple[tuple[type, str], ...]] = {
    ComponentKind.DATA_MODEL: (
        (DataModel, "compute"),
        (DataModel, "requirements"),
    ),
    ComponentKind.STRATEGY_MODEL: (
        (StrategyModel, "on_occurrence"),
        (StrategyModel, "requirements"),
    ),
    ComponentKind.CONSTRAINT: (
        (Constraint, "requirements"),
        (Constraint, "project"),
        (Constraint, "validate_intended"),
        (Constraint, "evaluate"),
    ),
    ComponentKind.EXCHANGE: ((Exchange, "execute"),),
}
"""Every method Flow calls on each kind, and the contract that declares its shape.

`Exchange` is a `Protocol` rather than an ABC, so nothing forces a registered venue to declare
`execute` at all; `load_exchange` requires a shipped profile, which supplies it. It is listed here
so the check is stated in one table rather than depending on which contract happens to be abstract.
"""

_LOADERS = {
    ComponentKind.DATA_MODEL: load_data_model,
    ComponentKind.STRATEGY_MODEL: load_strategy_model,
    ComponentKind.CONSTRAINT: load_constraint,
    ComponentKind.EXCHANGE: load_exchange,
}


def _parameters(target: Any) -> tuple[str, ...] | None:
    try:
        return tuple(inspect.signature(target).parameters)
    except (TypeError, ValueError):
        return None


def _check_methods(component: object, kind: ComponentKind, found: Any) -> None:
    """Every contract method must exist, be callable, and take the declared parameters.

    Flow calls these positionally, so a renamed or added required parameter is a real break.
    Annotations are not compared: narrowing a return type is legitimate, and most components
    declare no annotation at all.
    """
    for base, name in _CONTRACT_METHODS[kind]:
        implementation = getattr(type(component), name, None)
        if implementation is None:
            found.add(
                Failure.bounded(
                    f"{STAGE}.method_missing",
                    f"{base.__name__}.{name}() must be implemented",
                    observed=type(component).__name__,
                )
            )
            continue
        if not callable(implementation) and not isinstance(implementation, property):
            actual = type(implementation).__name__
            found.add(
                Failure.bounded(
                    f"{STAGE}.method_not_callable",
                    f"{base.__name__}.{name} must be a method, not a value",
                    observed=f"{type(component).__name__}.{name} is {actual}",
                )
            )
            continue
        if isinstance(implementation, property):
            continue
        expected = _parameters(getattr(base, name, None))
        observed = _parameters(implementation)
        if expected is None or observed is None or observed == expected:
            continue
        found.add(
            Failure.bounded(
                f"{STAGE}.signature_invalid",
                f"{base.__name__}.{name}() must declare parameters {expected}",
                observed=f"{type(component).__name__}.{name}{observed}",
            )
        )


def conformance(ref: ComponentRef, *, project_root: str | Path | None = None) -> Diagnosis:
    """Judge one component against the contract its kind declares.

    Returns a `Diagnosis` rather than raising, so a caller can collect every problem at once.
    `raise_if_failed()` turns it into the same typed `VqaprError` every other stage raises.
    """
    if not isinstance(ref, ComponentRef):
        raise TypeError("ref must be a ComponentRef")
    found = collector(STAGE, FailureFamily.DATA)

    try:
        component = _LOADERS[ref.kind](ref, project_root=project_root)
    except Exception as error:
        # The load door is part of conformance, not a separate gate. Its verdict is already
        # typed and specific, so it rides through rather than being restated here.
        body = getattr(error, "failures", None)
        if body:
            for failure in body:
                found.add(failure)
        else:
            found.add(
                Failure.bounded(
                    f"{STAGE}.load_failed",
                    "component must load before its contract can be judged",
                    observed=f"{type(error).__name__}: {error}",
                )
            )
        return found.done(retry=_RETRY)

    _check_methods(component, ref.kind, found)
    return found.done(retry=_RETRY)


__all__ = ["STAGE", "conformance"]
