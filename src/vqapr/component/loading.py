"""Load a registered component and adapt it to the contract the engine calls.

This module is the extension loading authority, and `vqapr.component.loading` is where it lives.

**It was not always.** Until record `110` the implementation sat in
`vqapr._internal.extensions.loading` with a four-line forwarding shim at this path, whose
docstring promised deletion "when the internal-transition closes". That promise was made in a file
marked temporary and was still true six months later, by which point a boundary test pinned the
shim's existence. Record `110` discharged it the other way: the shim's path became the real
module's path, so no caller changed a line and the temporary file stopped existing rather than
being renewed. See `docs/design/agent-first-surface.md` for the surface ruling this serves.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

from vqapr.component.compliance.base import Compliance
from vqapr.component.datamodel import DataModel
from vqapr.component.exchange.academic import AcademicExchange
from vqapr.component.exchange.base import Exchange
from vqapr.component.exchange.krx import KrxExchange
from vqapr.component.fingerprint import fingerprint_component
from vqapr.component.reference import ComponentRef
from vqapr.component.strategy.base import StrategyModel
from vqapr.data.requirement import DataRequirement
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.domain.listing import ExchangeRulesView
from vqapr.domain.memory import normalize_memory
from vqapr.domain.wiring import Role


def _failure(
    code: str,
    requirement: str,
    observed: str,
    *,
    fix: str,
    status: Status,
    source: FailureSource | None = None,
    cause: BaseException | None = None,
) -> VqaprError:
    """One refusal under the `load` stage. `cause` is the exception in hand, when there is one."""
    return VqaprError(
        stage=Stage.LOAD,
        failures=[
            Failure.bounded(
                code,
                requirement,
                status=status,
                observed=observed,
                fix=fix,
                source=source,
                cause=cause,
            )
        ],
        mutation=False,
        retry_precondition="fix and register the component again, then retry",
    )


def _load(
    ref: ComponentRef,
    *,
    kind: Role,
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
        raise _source_lost(path, error) from error
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
    module = _execute(path, f"_vqapr_component_{current}")
    try:
        candidate = getattr(module, ref.object_name)
        return candidate(**dict(ref.config))
    except Exception as error:
        raise _construction_failed(path, error) from error


def _execute(path: Path, module_name: str) -> ModuleType:
    """Run a component file as a module; the one door a component's source is executed through.

    `_load` builds the registered object from what this returns, and `authored_classes` finds
    the authored class in it by the object (record `252`). The file is loaded by its PATH, so
    its directory is not on the import path -- a component is one file, and its fingerprint
    covers that file alone (owner decision 2026-09-04, `docs/issues/archive/065`).
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise _failure(
            "component.module_invalid",
            "component path must identify a loadable Python module",
            str(path),
            fix=f"point the component reference at a loadable .py file, not {path}",
            status=Status.CONTRACT,
            source=FailureSource(file=str(path)),
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise _construction_failed(path, error) from error
    return module


def _construction_failed(path: Path, error: BaseException) -> VqaprError:
    """The author's code raised while its module ran or its object was built: 502, theirs."""
    return _failure(
        "component.construction_failed",
        "component object must load and construct from its registered config",
        f"{type(error).__name__}: {error}",
        fix=_construction_fix(path, error),
        status=Status.CRASHED,
        source=FailureSource(file=str(path)),
        cause=error,
    )


def _construction_fix(path: Path, error: BaseException) -> str:
    """The repair, naming the one-file rule when the missing module sits beside the component.

    `import helper` of a `helper.py` in the component's own directory is correct Python for a
    script and fails here, and "fix the exception" sent the author to fix an import that was right
    for the file's location (`docs/issues/report-2026-09-11-a-component-cannot-import-a-module-
    beside-it-...`, record `252`). Only a module that is really there beside it gets this text:
    any other `ModuleNotFoundError` is the author's missing dependency, as before.
    """
    missing = error.name if isinstance(error, ModuleNotFoundError) else None
    if missing:
        top = missing.split(".")[0]
        if (path.parent / f"{top}.py").is_file() or (path.parent / top / "__init__.py").is_file():
            return (
                f"`{top}` sits beside {path.name}, but a component's directory is not on the "
                "import path: a component is one file, loaded by its path, and its fingerprint "
                f"covers that file alone. Put the shared code in {path.name} itself, or in a "
                "package installed in this environment (or on PYTHONPATH), then register again"
            )
    return (
        "fix the exception raised while constructing the component from its "
        "registered config; the traceback is in `cause`"
    )


_AUTHORED_BASES: dict[Role, type] = {
    Role.STRATEGY_MODEL: StrategyModel,
    Role.DATA_MODEL: DataModel,
    Role.COMPLIANCE: Compliance,
}


def authored_classes(path: Path, kind: Role) -> tuple[str, ...]:
    """The leaf classes `path` defines that ARE the kind's authoring base, found by the object.

    Registration's kind route (`vqapr register strategy <id> <file>`) parses the file first -- a
    file with two strategies is refused for having two, not for whatever its import does -- and
    asks this only when parsing cannot see the base: a class inheriting it through a module the
    file imports, `class Leaf(common.Base)`. The YAML route loads that file by the object and
    registered it while the kind route said "defines 0" (record `252`). A class the file merely
    imports is not the file's (`__module__`), and a base another of its classes extends is
    scaffolding for the leaf, as in the parse.
    """
    base = _AUTHORED_BASES[kind]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    module = _execute(path, f"_vqapr_probe_{digest}")
    try:
        defined = [
            (name, value)
            for name, value in vars(module).items()
            if isinstance(value, type)
            and value.__module__ == module.__name__
            and issubclass(value, base)
        ]
    finally:
        sys.modules.pop(module.__name__, None)
    extended = {parent for _, cls in defined for parent in cls.__mro__[1:]}
    return tuple(name for name, cls in defined if cls not in extended)


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
        raise _source_lost(path, error) from error


def _source_lost(path: Path, error: OSError) -> VqaprError:
    """A registered component's source could not be read at load time.

    404 when the file is gone -- a name was registered and nothing is at the path it recorded,
    which is the submission's to repair -- and 503 only when a file that exists could not be read
    (`docs/issues/094`; the same split `conformance.py` makes at registration).
    """
    if isinstance(error, FileNotFoundError | NotADirectoryError | IsADirectoryError):
        return _failure(
            "component.source_missing",
            f"component source must still exist at {path}",
            f"nothing at {path}",
            fix=(
                f"restore the component source at {path}, or register the component again from "
                "where it lives now"
            ),
            status=Status.MISSING,
            source=FailureSource(file=str(path)),
            cause=error,
        )
    return _failure(
        "component.source_unreadable",
        f"component source must remain readable at {path}",
        str(error),
        fix=f"fix permissions on the component source at {path}",
        status=Status.UNAVAILABLE,
        source=FailureSource(file=str(path)),
        cause=error,
    )


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
        "component.signature_invalid",
        f"{base.__name__}.{method_name}() must accept {wanted[1]} positional arguments",
        f"takes {'any number' if observed[1] == -1 else observed[1]} ({observed[0]} required)",
        fix=(
            f"change {method_name}()'s parameters so it accepts exactly {wanted[1]} "
            "positional arguments"
        ),
        status=Status.CONTRACT,
    )


def _requirements(component: object, *, label: str, required: bool) -> tuple[DataRequirement, ...]:
    declaration = getattr(component, "requirements", None)
    if declaration is None:
        if not required:
            return ()
        raise _failure(
            "component.requirements_missing",
            f"{label}.requirements() must be declared before run",
            type(component).__name__,
            fix=f"implement {label}.requirements() so it declares the component's data needs",
            status=Status.CONTRACT,
        )
    try:
        requirements = declaration()
    except Exception as error:
        raise _failure(
            "component.requirements_failed",
            f"{label}.requirements() must complete before run",
            f"{type(error).__name__}: {error}",
            fix=f"fix the exception raised inside {label}.requirements(); the traceback is in "
            "`cause`",
            status=Status.CRASHED,
            cause=error,
        ) from error
    if not isinstance(requirements, tuple) or not all(
        isinstance(item, DataRequirement) for item in requirements
    ):
        raise _failure(
            "component.requirements_invalid",
            f"{label}.requirements() must return a tuple of DataRequirement values",
            repr(requirements),
            fix=f"return a tuple of DataRequirement values from {label}.requirements()",
            status=Status.CONTRACT,
        )
    return requirements


def load_data_model(ref: ComponentRef, *, project_root: str | Path | None = None) -> DataModel:
    model = _load(ref, kind=Role.DATA_MODEL, project_root=project_root)
    if not isinstance(model, DataModel):
        raise _failure(
            "component.wrong_type",
            "registered DataModel object must implement the public DataModel contract",
            type(model).__name__,
            fix="make the registered object a subclass of vqapr.authoring.DataModel",
            status=Status.CONTRACT,
        )
    # `requirements()` is derived from `inputs()` and may legitimately be empty -- `Model.inputs()`
    # says so in its own docstring: a Model may derive its values from memory alone. This used to
    # refuse an empty tuple, contradicting the contract it had just loaded.
    _requirements(model, label="DataModel", required=False)
    return model


def load_strategy_model(
    ref: ComponentRef, *, project_root: str | Path | None = None
) -> StrategyModel:
    strategy = _load(ref, kind=Role.STRATEGY_MODEL, project_root=project_root)
    if not isinstance(strategy, StrategyModel):
        raise _failure(
            "component.wrong_type",
            "registered StrategyModel object must implement the public StrategyModel contract",
            type(strategy).__name__,
            fix="make the registered object a subclass of vqapr.authoring.StrategyModel",
            status=Status.CONTRACT,
        )
    _validate_callback_signature(strategy, base=StrategyModel, method_name="decide")
    # `required=False` as for the other two roles: `Model.inputs()` says declaring nothing is
    # legitimate, and a Strategy that rebalances to fixed weights reads no data at all.
    _requirements(strategy, label="StrategyModel", required=False)
    return strategy



def load_compliance(ref: ComponentRef, *, project_root: str | Path | None = None) -> Compliance:
    rule = _load(ref, kind=Role.COMPLIANCE, project_root=project_root)
    if not isinstance(rule, Compliance):
        raise _failure(
            "component.wrong_type",
            "registered Compliance object must implement the public Compliance contract",
            type(rule).__name__,
            fix="make the registered object a subclass of vqapr.authoring.Compliance",
            status=Status.CONTRACT,
        )
    # Not `_requirements(...)`: a rule declares its reads with `inputs()` like every other Model
    # role does since record `128`, and declaring nothing is legitimate -- `NoShort` is a rule
    # about a holding's sign and reads no data at all.
    _compliance_identity(ref, rule)
    return rule


def _compliance_identity(ref: ComponentRef, rule: Compliance) -> None:
    """Refuse a Compliance rule registered under an id it does not answer to.

    `strategy_loop` requires the loaded rules to carry exactly the ids the FrozenRun declared,
    and it enforced that with a bare `ValueError` at assembly. Nothing before it looked, so `check`
    returned `ok:true` on all five phases and `run` then died with `stage: unhandled` and an empty
    `failures` list -- the framework reporting itself broken when the registration was wrong.
    Registering `NoShort` as `noshort` crashed; the same file as `no-short` ran clean, and nothing
    said so.

    This is the one place that can answer the question for every caller. `conformance` dispatches
    here for `Role.COMPLIANCE`, so `vqapr register` refuses at registration; `preflight`
    loads rules through here, so `vqapr check` refuses before a run is spent and `vqapr run`
    refuses before assembly. Checking the LOADED object rather than the source is what catches a
    `compliance_id` computed at runtime, which no static read of the file can see.

    It cannot be the ONLY place, because it can only ask once per load. A `compliance_id` that
    returns a different string on each access satisfies this check at registration and again at
    `check`, and still disagrees by run assembly; `_require_compliance_identity` in
    `run/engine/context.py` is what catches that, and red-teaming confirmed the path is live.
    """
    declared = str(ref.component_id)
    answered = rule.compliance_id
    if answered == declared:
        return
    raise _failure(
        "component.compliance_id_mismatch",
        "a Compliance rule must be registered under the id its own compliance_id returns",
        f"registered as {declared!r}, compliance_id returns {answered!r}",
        # Three remedies, because which one is right depends on the component. A class with a
        # hardcoded id has two; one that takes its id as a constructor argument -- as the shipped
        # `NoShort` does -- has a third, and omitting it would send that user to edit a file the
        # package ships.
        fix=(
            f"register the component as {answered!r}; or change the class's compliance_id to "
            f"return {declared!r}; or, if the class takes its id as a constructor argument "
            f"(the shipped NoShort takes `compliance_id`), pass {declared!r} to it through the "
            f"registration's config mapping"
        ),
        status=Status.CONTRACT,
        source=FailureSource(file=str(ref.path)),
    )


SHIPPED_EXECUTION_PROFILES: tuple[type[Exchange], ...] = (AcademicExchange, KrxExchange)
"""The execution profiles this package implements end to end.

A run may only execute through a profile whose venue semantics are implemented and documented
here. A user subclass may add listings and costs, but it may not silently replace ``execute`` with
its own matching behaviour, because the resulting realism claim would be unverified.
"""


def load_exchange(ref: ComponentRef, *, project_root: str | Path | None = None) -> Exchange:
    exchange = _load(ref, kind=Role.EXCHANGE, project_root=project_root)
    if not isinstance(exchange, SHIPPED_EXECUTION_PROFILES):
        names = ", ".join(base.__name__ for base in SHIPPED_EXECUTION_PROFILES)
        raise _failure(
            "component.wrong_type",
            f"registered Exchange object must be one of the shipped profiles: {names}",
            type(exchange).__name__,
            fix=f"subclass one of the shipped profiles ({names}) instead of Exchange directly",
            status=Status.CONTRACT,
        )
    profile = next(base for base in SHIPPED_EXECUTION_PROFILES if isinstance(exchange, base))
    if type(exchange).execute is not profile.execute:
        raise _failure(
            "component.execution_profile_invalid",
            f"{profile.__name__} subclasses must retain {profile.__name__}.execute() semantics",
            type(exchange).__name__,
            fix=(
                f"remove the override of execute() and inherit {profile.__name__}.execute() "
                "unchanged"
            ),
            status=Status.CONTRACT,
        )
    if not isinstance(getattr(exchange, "rules", None), ExchangeRulesView):
        raise _failure(
            "component.execution_profile_invalid",
            "an Exchange must expose its own ExchangeRulesView",
            type(exchange).__name__,
            fix="expose a `rules` attribute that is an ExchangeRulesView on the Exchange subclass",
            status=Status.CONTRACT,
        )
    # The venue's settings are recorded with the run (design §6.1), so they must be the portable
    # mapping a record can hold. Refused here, before a run is spent on a venue whose declaration
    # cannot be written down.
    declared = getattr(exchange, "settings", None)
    try:
        if not isinstance(declared, Mapping):
            raise TypeError(f"settings must be a mapping; got {type(declared).__name__}")
        normalize_memory(dict(declared))
    except Exception as error:
        raise _failure(
            "component.execution_profile_invalid",
            "an Exchange's settings must be a portable mapping (strict JSON) the record can carry",
            f"{type(exchange).__name__}.settings: {type(error).__name__}: {error}",
            fix=(
                "return a mapping of plain values from `settings` -- spell a Decimal as a string "
                "-- so the run can record what the venue models"
            ),
            status=Status.CONTRACT,
            cause=error,
        ) from error
    _requirements(exchange, label="Exchange", required=False)
    return exchange
