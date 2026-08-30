"""Load fingerprinted project-local extension instances through checked paths.

Internal-transition: this is the physical home of the component loading authority.
`vqapr.extension.loading` is a temporary forwarding adapter over this module and is the ONLY door
callers in `src/` use to reach it -- a new public name here is re-exported there rather than
imported from here. Do not add new logic to the adapter, and do not import this module directly from
outside `_internal/`. Both halves of that rule, and the conditions the hard deletion is admitted
under, are in `docs/design/agent-first-surface.md`. Stated by document rather than by goal id: this
note pinned the deletion to a goal id until 2026-08-30, by which time that id named a different,
completed goal (`docs/issues/029`).
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from vqapr._internal.extensions.component import ComponentKind, ComponentRef
from vqapr._internal.extensions.fingerprint import fingerprint_component
from vqapr.constraints.constraint import Constraint
from vqapr.data.requirements import DataRequirement
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, FailureSource, VqaprError
from vqapr.exchange.listings import ExchangeRulesView
from vqapr.exchange.venue import AcademicExchange, Exchange
from vqapr.exchange.venues.krx import KrxExchange
from vqapr.models.data_model import DataModel
from vqapr.models.strategy_model import StrategyModel

_STAGE = "component.load"


def _failure(
    code: str,
    requirement: str,
    observed: str,
    *,
    fix: str,
    explain: ExplainTopic,
    source: FailureSource | None = None,
) -> VqaprError:
    return VqaprError(
        stage=_STAGE,
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded(
                code, requirement, observed=observed, fix=fix, explain=explain, source=source
            )
        ],
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
            fix=f"restore or fix permissions on the component source at {path}",
            explain=ExplainTopic.SOURCE_ACCESS,
            source=FailureSource(file=str(path)),
        ) from error
    # The drift refusal that stood here is gone. It refused a run whose source had been edited
    # since registration and named "re-register the component" as the repair -- which
    # `register_component` then refused, demanding a new identity instead. A reader following
    # either message arrived at the other (`docs/implementations/057`). Editing a registered
    # component is the ordinary development loop and must not cost four steps.
    #
    # Nothing is lost by letting the edited source load: the fingerprint is still computed here,
    # and the run record stamps the digest of what was ACTUALLY loaded, so a run still states
    # which bytes produced it. The gate became a receipt (issue 009).
    #
    # Keyed on `current` rather than on `ref.fingerprint`, because those now differ whenever the
    # source moved. Keying on the registered value would map two different sources onto one
    # module name, and `sys.modules` would hand back the first one loaded -- an edit that appeared
    # to have no effect, which is worse than the refusal this replaced.
    module_name = f"_vqapr_component_{current}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise _failure(
            f"{_STAGE}.module_invalid",
            "component path must identify a loadable Python module",
            str(path),
            fix=f"point the component reference at a loadable .py file, not {path}",
            explain=ExplainTopic.DECLARATION_SHAPE,
            source=FailureSource(file=str(path)),
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
            fix=(
                "fix the exception raised while constructing the component from its "
                "registered config"
            ),
            explain=ExplainTopic.COMPONENT_CONTRACT,
            source=FailureSource(file=str(path)),
        ) from error


def as_loaded_fingerprint(
    ref: ComponentRef, *, project_root: str | Path | None = None
) -> str:
    """The fingerprint of the source on disk NOW, which may differ from the registered one.

    Since the drift refusal was removed (issue 009), an edited component loads and runs. The run
    record must therefore state what it actually ran rather than what was registered, or a run
    whose source moved would carry a digest describing bytes it never executed -- a stale receipt,
    which is worse than the gate it replaced because it looks authoritative.

    Separate from `_load` so the loaders' return types stay what their callers expect. The read
    is one file and one sha256, which `check` already performs per component.
    """
    path = (
        ref.path
        if ref.path.is_absolute() or project_root is None
        else Path(project_root) / ref.path
    )
    try:
        return fingerprint_component(
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
            fix=f"restore or fix permissions on the component source at {path}",
            explain=ExplainTopic.SOURCE_ACCESS,
            source=FailureSource(file=str(path)),
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
        fix=(
            f"change {method_name}()'s parameters so it accepts exactly {wanted[1]} "
            "positional arguments"
        ),
        explain=ExplainTopic.COMPONENT_CONTRACT,
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
            fix=f"implement {label}.requirements() so it declares the component's data needs",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    try:
        requirements = declaration()
    except Exception as error:
        raise _failure(
            f"{_STAGE}.requirements_failed",
            f"{label}.requirements() must complete before run",
            f"{type(error).__name__}: {error}",
            fix=f"fix the exception raised inside {label}.requirements()",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        ) from error
    if not isinstance(requirements, tuple) or not all(
        isinstance(item, DataRequirement) for item in requirements
    ):
        raise _failure(
            f"{_STAGE}.requirements_invalid",
            f"{label}.requirements() must return a tuple of DataRequirement values",
            repr(requirements),
            fix=f"return a tuple of DataRequirement values from {label}.requirements()",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    return requirements


def load_data_model(ref: ComponentRef, *, project_root: str | Path | None = None) -> DataModel:
    model = _load(ref, kind=ComponentKind.DATA_MODEL, project_root=project_root)
    if not isinstance(model, DataModel):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered DataModel object must implement the public DataModel contract",
            type(model).__name__,
            fix="make the registered object a subclass of vqapr.models.data_model.DataModel",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    requirements = _requirements(model, label="DataModel", required=True)
    if not requirements:
        raise _failure(
            f"{_STAGE}.requirements_invalid",
            "DataModel.requirements() must return a non-empty tuple of DataRequirement values",
            repr(requirements),
            fix="return at least one DataRequirement from DataModel.requirements()",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    return model


def load_strategy_model(
    ref: ComponentRef, *, project_root: str | Path | None = None
) -> StrategyModel:
    strategy = _load(ref, kind=ComponentKind.STRATEGY_MODEL, project_root=project_root)
    if not isinstance(strategy, StrategyModel):
        strategy = _adapt_authored_strategy(strategy, ref)
    if not isinstance(strategy, StrategyModel):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered StrategyModel object must implement the public StrategyModel contract",
            type(strategy).__name__,
            fix=(
                "make the registered object a subclass of "
                "vqapr.models.strategy_model.StrategyModel"
            ),
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    _validate_callback_signature(strategy, base=StrategyModel, method_name="on_occurrence")
    _requirements(strategy, label="StrategyModel", required=True)
    return strategy



def _adapt_authored_strategy(loaded: object, ref: ComponentRef) -> object:
    """Wrap a model written against the authoring contract so the engine can run it.

    A registered component may be authored against either contract. Refusing the
    authoring one here would mean a model that runs perfectly through `Project.simulate`
    cannot be registered by the CLI that exists to register it - the loader would be the
    only thing standing between the supported way to write a model and the supported way
    to install one.

    The engine contract is left untouched: this adapts inward, it does not widen what the
    engine accepts.
    """
    from vqapr.authoring import StrategyModel as AuthoringStrategyModel

    authored = type(loaded)
    if not isinstance(loaded, AuthoringStrategyModel):
        return loaded

    from vqapr._internal.strategy_bridge import AdaptedStrategy

    config = dict(getattr(ref, "config", {}) or {})
    config.pop("strategy_id", None)
    return AdaptedStrategy(
        authored_module=authored.__module__,
        authored_qualname=authored.__qualname__,
        strategy_id=str(ref.component_id),
        authored_config=config,
    )


def load_constraint(ref: ComponentRef, *, project_root: str | Path | None = None) -> Constraint:
    constraint = _load(ref, kind=ComponentKind.CONSTRAINT, project_root=project_root)
    if not isinstance(constraint, Constraint):
        raise _failure(
            f"{_STAGE}.wrong_type",
            "registered Constraint object must implement the public Constraint contract",
            type(constraint).__name__,
            fix="make the registered object a subclass of vqapr.constraints.constraint.Constraint",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    _requirements(constraint, label="Constraint", required=True)
    _constraint_identity(ref, constraint)
    return constraint


def _constraint_identity(ref: ComponentRef, constraint: Constraint) -> None:
    """Refuse a Constraint registered under an id it does not answer to.

    `SimulationFlow` requires the loaded constraints to carry exactly the ids the FrozenRun
    declared, and it enforced that with a bare `ValueError` at assembly. Nothing before it looked,
    so `check` returned `ok:true` on all five phases and `run` then died with `stage: unhandled`
    and an empty `failures` list -- the framework reporting itself broken when the registration was
    wrong. Registering `NoShort` as `noshort` crashed; the same file as `no-short` ran clean, and
    nothing said so.

    This is the one place that can answer the question for every caller. `conformance` dispatches
    here for `ComponentKind.CONSTRAINT`, so `vqapr register` refuses at registration; `preflight`
    loads constraints through here, so `vqapr check` refuses before a run is spent and `vqapr run`
    refuses before assembly. Checking the LOADED object rather than the source is what catches a
    `constraint_id` computed at runtime, which no static read of the file can see.

    It cannot be the ONLY place, because it can only ask once per load. A `constraint_id` that
    returns a different string on each access satisfies this check at registration and again at
    `check`, and still disagrees by run assembly; `_require_constraint_identity` in
    `flow/simulation.py` is what catches that, and red-teaming confirmed the path is live.
    """
    declared = str(ref.component_id)
    answered = constraint.constraint_id
    if answered == declared:
        return
    raise _failure(
        f"{_STAGE}.constraint_id_mismatch",
        "a Constraint must be registered under the id its own constraint_id returns",
        f"registered as {declared!r}, constraint_id returns {answered!r}",
        # Three remedies, because which one is right depends on the component. A class with a
        # hardcoded id has two; one that takes its id as a constructor argument -- as the shipped
        # `NoShort` does -- has a third, and omitting it would send that user to edit a file the
        # package ships.
        fix=(
            f"register the component as {answered!r}; or change the class's constraint_id to "
            f"return {declared!r}; or, if the class takes its id as a constructor argument "
            f"(the shipped NoShort takes `constraint_id`), pass {declared!r} to it through the "
            f"registration's config mapping"
        ),
        explain=ExplainTopic.COMPONENT_CONTRACT,
        source=FailureSource(file=str(ref.path)),
    )


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
            fix=f"subclass one of the shipped profiles ({names}) instead of Exchange directly",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    if type(exchange).execute is not profile.execute:
        raise _failure(
            f"{_STAGE}.execution_profile_invalid",
            f"{profile.__name__} subclasses must retain {profile.__name__}.execute() semantics",
            type(exchange).__name__,
            fix=(
                f"remove the override of execute() and inherit {profile.__name__}.execute() "
                "unchanged"
            ),
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    if not isinstance(getattr(exchange, "rules", None), ExchangeRulesView):
        raise _failure(
            f"{_STAGE}.execution_profile_invalid",
            "an Exchange must expose its own ExchangeRulesView",
            type(exchange).__name__,
            fix="expose a `rules` attribute that is an ExchangeRulesView on the Exchange subclass",
            explain=ExplainTopic.COMPONENT_CONTRACT,
        )
    _requirements(exchange, label="Exchange", required=False)
    return exchange
