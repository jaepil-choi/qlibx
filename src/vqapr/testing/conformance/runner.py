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
contract declares is present, callable, and **accepts the positional call Flow will make**.
There is one implementation and two entrances — `pytest` and `vqapr register` — so a component
cannot pass one and fail another. There is deliberately no `vqapr check`: registration already
calls this code, and a component that is not registered is not yet anything Flow can run.

Its input is a `ComponentRef` (canon §10.3), which is the same type a shipped component and a
user-authored one both arrive as. There is deliberately no branch that can tell them apart, and
`academic` and `krx` are the first two implementations to pass it.

What it cannot check is deliberately absent, and the boundary is sharper than it looks. Whether a
callback returns the *declared type* is not knowable here either: an annotation can lie and most
components carry none, so the only honest verdict comes from the value itself at the call site.
The Flow already takes that verdict — `validate_economic_intent` for an intent, `_validated_output`
for computed rows, an `isinstance` gate for projected bounds — and it belongs there, where the
returned object exists.

So this suite answers exactly one question: **will Flow be able to call this component at all.**
Arity is decidable before a run; the returned value is not. Checking the first here and the second
there is the whole division of labour, and widening either one into the other's territory would
trade a real verdict for a guess.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vqapr.constraints.constraint import Constraint
from vqapr.domain.errors import (
    Diagnosis,
    ExplainTopic,
    Failure,
    FailureFamily,
    collector,
)
from vqapr.exchange.venue import Exchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.loading import (
    accepts_contract_call,
    load_constraint,
    load_data_model,
    load_exchange,
    load_strategy_model,
    positional_arity,
)
from vqapr.models.data_model import DataModel
from vqapr.models.strategy_model import StrategyModel

STAGE = "component.conformance"
_RETRY = "fix the component to match its contract, then register it again"


_CONTRACT_METHODS: dict[ComponentKind, tuple[tuple[type, str], ...]] = {
    ComponentKind.DATA_MODEL: ((DataModel, "compute"),),
    ComponentKind.STRATEGY_MODEL: (
        (StrategyModel, "decide"),
        (StrategyModel, "requirements"),
    ),
    ComponentKind.CONSTRAINT: (
        (Constraint, "project"),
        (Constraint, "monitor"),
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


def _signature_hint(arity: int) -> str:
    """The parameter list for a method of this arity, so the refusal shows the signature.

    `self` is always first; the rest are positional placeholders meant to be renamed. Only the
    count is checked -- the names are a template, and saying so beats making the reader translate
    a number back into a signature.
    """
    if arity <= 0:
        return ""
    return ", ".join(["self", *(f"arg{index}" for index in range(1, arity))])


def _check_methods(component: object, kind: ComponentKind, found: Any) -> None:
    """Every contract method must exist, be callable, and accept the call Flow will make.

    Flow calls these **positionally**, so the question is arity, not spelling. A component that
    renames `context` to `ctx` is called identically and passes; one that adds a required
    parameter, or drops one, cannot receive the call and fails.

    Annotations are not compared: narrowing a return type is legitimate, and most components
    declare no annotation at all. Whether a callback returns the *right type* is not decidable
    here — an annotation can lie — so the Flow enforces it at the call site instead
    (`validate_economic_intent`, `_validated_output`, `Constraint.project`'s isinstance check).
    """
    for base, name in _CONTRACT_METHODS[kind]:
        implementation = getattr(type(component), name, None)
        if implementation is None:
            found.add(
                Failure.bounded(
                    f"{STAGE}.method_missing",
                    f"{base.__name__}.{name}() must be implemented",
                    observed=type(component).__name__,
                    fix=f"implement {name}() on the component so it satisfies {base.__name__}",
                    explain=ExplainTopic.COMPONENT_CONTRACT,
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
                    fix=f"define {name} as a method on the component, not as a {actual} attribute",
                    explain=ExplainTopic.COMPONENT_CONTRACT,
                )
            )
            continue
        if isinstance(implementation, property):
            continue
        contract = getattr(base, name, None)
        if contract is None or accepts_contract_call(implementation, contract):
            continue
        wanted = positional_arity(contract)
        observed = positional_arity(implementation)
        if wanted is None or observed is None:
            continue
        found.add(
            Failure.bounded(
                f"{STAGE}.signature_invalid",
                f"{base.__name__}.{name}() must accept {wanted[1]} positional arguments",
                observed=(
                    f"{type(component).__name__}.{name} takes "
                    f"{'any number' if observed[1] == -1 else observed[1]}"
                    f" ({observed[0]} required)"
                ),
                # Emits the signature to write rather than the arity to satisfy. The code already
                # knows the shape, so making the reader translate a count back into parameters is
                # work the refusal can do for them.
                fix=(
                    f"define it as {name}({_signature_hint(wanted[1])}) so it accepts "
                    f"exactly {wanted[1]} positional arguments"
                ),
                explain=ExplainTopic.COMPONENT_CONTRACT,
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
                    fix=(
                        "fix the exception raised while loading the component, then "
                        "register it again"
                    ),
                    explain=ExplainTopic.COMPONENT_CONTRACT,
                )
            )
        return found.done(retry=_RETRY)

    _check_methods(component, ref.kind, found)
    return found.done(retry=_RETRY)


__all__ = ["STAGE", "conformance"]
