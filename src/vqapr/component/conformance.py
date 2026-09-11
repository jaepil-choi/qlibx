"""One verdict on whether a component honours its extension contract.

Canon §10.2 says the four extension points *"enter through the same door and pass the same
conformance"*. Registration is that door (`prepare_component` below proves,
`project/registration.py` writes), and it already proves a
component **loads**: the fingerprint matches, the object constructs, it implements its contract
type, and it declares its data requirements.

Loading is not conformance. A component can construct perfectly and still be unusable, because the
methods Flow will call are not the methods it defined. Renaming a parameter of
`Compliance.observe`, or dropping `DataModel.compute` onto a class that inherits an abstract stub,
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

**Shipped, and here rather than in `testing/`.** Canon 10.3 ships this instead of keeping it in
`tests/`, so a user can prove their own component before registering it rather than reading our
test suite to guess the contract. That is a packaging fact, not a layering one, and for a while it
bought a package of its own -- which put `extension/prepare.py` below the suite it calls while
the suite imported `extension/loading.py` back. A cycle, at module scope, that only import order
kept quiet. Registration is the door and conformance is what the door proves, so the two live
together (record `193`); `vqapr.public` re-exports `conformance`, which is how a user reaches it
and why the move costs them nothing.

So this suite answers exactly one question: **will Flow be able to call this component at all.**
Arity is decidable before a run; the returned value is not. Checking the first here and the second
there is the whole division of labour, and widening either one into the other's territory would
trade a real verdict for a guess.

`prepare_component` is the registration side of the same door: fingerprint the source, build the
`ComponentRef`, and prove the component conforms. It writes nothing -- the workspace does.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vqapr.component.compliance.base import Compliance
from vqapr.component.datamodel import DataModel
from vqapr.component.exchange.base import Exchange
from vqapr.component.fingerprint import fingerprint_component
from vqapr.component.loading import (
    accepts_contract_call,
    load_compliance,
    load_data_model,
    load_exchange,
    load_strategy_model,
    positional_arity,
)
from vqapr.component.reference import ComponentKind, ComponentRef
from vqapr.component.strategy.base import StrategyModel
from vqapr.domain.errors import (
    Diagnosis,
    Failure,
    FailureSource,
    Stage,
    Status,
    VqaprError,
    collector,
)

__all__ = [
    "STAGE",
    "conformance",
    "prepare_component",
]


STAGE = Stage.REGISTER
"""Conformance is the proving half of registration, so its refusals are the `register` stage's."""


_RETRY = "fix the component to match its contract, then register it again"


_CONTRACT_METHODS: dict[ComponentKind, tuple[tuple[type, str], ...]] = {
    ComponentKind.DATA_MODEL: ((DataModel, "compute"),),
    ComponentKind.STRATEGY_MODEL: (
        (StrategyModel, "decide"),
        (StrategyModel, "requirements"),
    ),
    ComponentKind.COMPLIANCE: ((Compliance, "observe"),),
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
    ComponentKind.COMPLIANCE: load_compliance,
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
    (`validate_economic_intent`, `_validated_output`, `Compliance.observe`'s isinstance check).
    """
    for base, name in _CONTRACT_METHODS[kind]:
        implementation = getattr(type(component), name, None)
        if implementation is None:
            found.add(
                Failure.bounded(
                    "component.method_missing",
                    f"{base.__name__}.{name}() must be implemented",
                    status=Status.CONTRACT,
                    observed=type(component).__name__,
                    fix=f"implement {name}() on the component so it satisfies {base.__name__}",
                )
            )
            continue
        if not callable(implementation) and not isinstance(implementation, property):
            actual = type(implementation).__name__
            found.add(
                Failure.bounded(
                    "component.method_not_callable",
                    f"{base.__name__}.{name} must be a method, not a value",
                    status=Status.CONTRACT,
                    observed=f"{type(component).__name__}.{name} is {actual}",
                    fix=f"define {name} as a method on the component, not as a {actual} attribute",
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
                "component.signature_invalid",
                f"{base.__name__}.{name}() must accept {wanted[1]} positional arguments",
                status=Status.CONTRACT,
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
            )
        )


def conformance(ref: ComponentRef, *, project_root: str | Path | None = None) -> Diagnosis:
    """Judge one component against the contract its kind declares.

    Returns a `Diagnosis` rather than raising, so a caller can collect every problem at once.
    `raise_if_failed()` turns it into the same typed `VqaprError` every other stage raises.
    """
    if not isinstance(ref, ComponentRef):
        raise TypeError("ref must be a ComponentRef")
    found = collector(STAGE)

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
                    "component.import_failed",
                    "component must load before its contract can be judged",
                    status=Status.CRASHED,
                    observed=f"{type(error).__name__}: {error}",
                    fix=(
                        "fix the exception raised while loading the component, then "
                        "register it again; the traceback is in `cause`"
                    ),
                    cause=error,
                )
            )
        return found.done(retry=_RETRY)

    _check_methods(component, ref.kind, found)
    return found.done(retry=_RETRY)


def _unreadable(kind_label: str, error: OSError, path: str | Path) -> VqaprError:
    """The source could not be read: MISSING (404) when it is not there, UNAVAILABLE (503) else.

    One OSError became one 503, and 503 is the class the skills tell an agent to retry unchanged
    -- while a path that resolved wrongly never clears by retrying, and the refusal's own
    `retry_precondition` said so (`docs/issues/094`). A path that is not there is the submission's
    to fix (`Status.MISSING`: "the path it names is not there"); a permission or disk fault is the
    machine's, and stays 503.
    """
    if isinstance(error, FileNotFoundError | NotADirectoryError | IsADirectoryError):
        return VqaprError(
            stage=Stage.REGISTER,
            failures=[
                Failure.bounded(
                    "component.source_missing",
                    f"{kind_label} source must be a Python file that exists",
                    status=Status.MISSING,
                    observed=f"nothing at {path}",
                    fix=(
                        f"point `path` at the {kind_label} source file. A relative `path` "
                        "resolves against the declaration file's own directory, not the project "
                        "root or the working directory"
                    ),
                    cause=error,
                    source=FailureSource(file=str(path)),
                )
            ],
            mutation=False,
            retry_precondition="correct the component's `path`, then retry",
        )
    return VqaprError(
        stage=Stage.REGISTER,
        failures=[
            Failure.bounded(
                "component.source_unreadable",
                f"{kind_label} source must be a readable Python file",
                # UNAVAILABLE (503), not CONTRACT: fingerprinting failed on an OSError while
                # reading a file that exists at `path` -- the declared path and kind are already
                # fine, only the filesystem read failed, which is what the machine's status
                # describes.
                status=Status.UNAVAILABLE,
                observed=str(error),
                fix=f"fix permissions on the {kind_label} source file at {path}",
                cause=error,
                source=FailureSource(file=str(path)),
            )
        ],
        mutation=False,
        retry_precondition="repair the component source, then retry",
    )


_LABELS = {
    ComponentKind.DATA_MODEL: "DataModel",
    ComponentKind.STRATEGY_MODEL: "StrategyModel",
    ComponentKind.COMPLIANCE: "Compliance",
    ComponentKind.EXCHANGE: "Exchange",
}


def prepare_component(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    kind: ComponentKind,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Fingerprint the source and prove the component conforms; write nothing.

    The half of registration that can refuse. Split from the write so a declaration document can
    prove every component it names before any of them is persisted (`Workspace.transaction`), and
    so a single `register_*` below is exactly this plus one write.
    """
    label = _LABELS[kind]
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
    return ref
