"""Run an authoring-protocol Constraint on the retained engine.

`vqapr.authoring.Constraint` is what an author writes: named `inputs()`, a `project()`
that returns bounds, a `validate()` over a normalized decision, and a `monitor()` over a
committed account. The retained engine executes a different, older protocol whose methods
take engine-internal windows, snapshots and mark batches.

This is the constraint counterpart of `agent_first` for models and `pit_bridge` for reads:
the third and last of the disjoint-protocol seams. Nothing here reimplements a constraint's
economics - the author's own `project`/`validate` decide, and this only translates the
shapes each side expects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from vqapr.constraints.constraint import Constraint as _EngineConstraint

__all__ = (
    "AdaptedConstraint",
    "adapt_constraint",
    "constraint_adapter_config",
    "legacy_constraint_class",
)


def _named_observations(window: Any, aliases: Mapping[str, Any]) -> Mapping[str, tuple]:
    """Project the engine's window onto the alias-keyed reads an author declared."""
    from vqapr._internal.pit_bridge import observation_rows, requirement_for

    reads: dict[str, tuple] = {}
    for alias, declaration in aliases.items():
        requirement = requirement_for(alias, declaration)
        batch = window.observations(requirement)
        reads[alias] = observation_rows(
            batch.rows,
            instrument_field="instrument",
            available_at_field="available_at",
            fields=declaration.fields,
        )
    return reads


def legacy_constraint_class(authored: type, *, name: str) -> type:
    """Build a legacy-protocol Constraint class that delegates to an authored one.

    The returned class is engine-facing only. It is never handed back to an author, so it
    carries the engine's `constraint_id`/`requirements`/`evaluate`/`validate_intended`
    surface while the authored instance keeps deciding.
    """
    from vqapr.authoring import Constraint as AuthoringConstraint
    from vqapr.constraints.constraint import Constraint as EngineConstraint

    if not isinstance(authored, type) or not issubclass(authored, AuthoringConstraint):
        raise TypeError("authored must be a subclass of vqapr.authoring.Constraint")
    if not isinstance(name, str) or not name or any(c.isspace() for c in name):
        raise ValueError("name must be a non-empty string without whitespace")

    class _Adapted(EngineConstraint):
        """One authored Constraint, wearing the engine's protocol."""

        def __init__(self, **config: object) -> None:
            # Fresh per construction, matching the model boundary: an authored constraint
            # never accumulates state across the run through this adapter.
            self._authored = authored(**config)
            self._aliases = dict(self._authored.inputs())

        @property
        def constraint_id(self) -> str:
            return name

        def requirements(self) -> tuple:
            from vqapr._internal.pit_bridge import requirement_for

            return tuple(
                requirement_for(alias, declaration)
                for alias, declaration in self._aliases.items()
            )

        def project(self, window: Any, instruments: Sequence[str]) -> Any:
            call = _ProjectionCall(
                reads=_named_observations(window, self._aliases),
                instruments=tuple(instruments),
                evaluation_time=getattr(window, "evaluation_time", None),
            )
            return self._authored.project(call)

        def validate_intended(self, intent: Any, bounds: Any) -> Any:
            return self._authored.validate(_authoring_decision(intent), bounds)

        def evaluate(self, window: Any, account: Any, marks: Any, bounds: Any) -> Any:
            call = _ProjectionCall(
                reads=_named_observations(window, self._aliases),
                instruments=tuple(getattr(bounds, "lower_weights", {})),
                evaluation_time=getattr(window, "evaluation_time", None),
                account=_marked_account(
                account, marks, getattr(window, "evaluation_time", None)
            ),
            )
            return _engine_finding(
            self._authored.monitor(call, bounds), constraint_id=self._name
        )

    _Adapted.__name__ = f"Adapted{authored.__name__}"
    _Adapted.__qualname__ = _Adapted.__name__
    return _Adapted


class _ProjectionCall:
    """The alias-keyed view an authored Constraint receives.

    Deliberately read-only and bounded: it exposes the declared reads, the universe and
    the evaluation instant, and nothing that would let a constraint reach the engine.
    """

    __slots__ = ("_account", "_evaluation_time", "_instruments", "_reads")

    def __init__(
        self,
        *,
        reads: Mapping[str, tuple],
        instruments: tuple[str, ...],
        evaluation_time: object = None,
        account: object = None,
    ) -> None:
        self._reads = dict(reads)
        self._instruments = instruments
        self._evaluation_time = evaluation_time
        self._account = account

    @property
    def instruments(self) -> tuple[str, ...]:
        return self._instruments

    @property
    def evaluation_time(self) -> object:
        return self._evaluation_time

    @property
    def account(self) -> object:
        return self._account

    def read(self, alias: str) -> tuple:
        if alias not in self._reads:
            raise KeyError(
                f"{alias!r} was not declared in inputs(); a Constraint reads only what "
                "it declared"
            )
        return self._reads[alias]


def adapt_constraint(declaration: Any) -> type:
    """Turn one `simulation.ConstraintDeclaration` into an engine-ready class."""
    return legacy_constraint_class(declaration.constraint, name=declaration.name)


def constraint_adapter_config(declaration: Any, *, run_id: str | None = None) -> dict:
    """The config `AdaptedConstraint` reconstructs itself from.

    Same reason as the strategy path: the loader re-imports a component's module and looks
    the class up by name, so a class generated at runtime can never be found. The authored
    constraint is named by import path instead of captured.
    """
    from vqapr.authoring import Constraint as AuthoringConstraint

    authored = declaration.constraint
    if not isinstance(authored, type) or not issubclass(authored, AuthoringConstraint):
        raise TypeError("declaration.constraint must be a vqapr.authoring.Constraint")
    if "<locals>" in authored.__qualname__:
        raise ValueError(
            f"{authored.__qualname__} is defined inside another scope; the loader resolves "
            "a constraint by module and qualname, so it must live at module scope"
        )
    return {
        "authored_module": authored.__module__,
        "authored_qualname": authored.__qualname__,
        # The engine requires a loaded constraint's own constraint_id to equal the
        # component id it was registered under, so the run prefix has to travel with it.
        "constraint_name": (
            f"{run_id}-{declaration.name}" if run_id else declaration.name
        ),
        "authored_config": dict(declaration.config),
    }


class AdaptedConstraint(_EngineConstraint):
    """The one registrable constraint component: an authored constraint in engine clothing."""

    def __init__(
        self,
        *,
        authored_module: str,
        authored_qualname: str,
        constraint_name: str,
        authored_config: dict | None = None,
    ) -> None:
        import importlib

        module = importlib.import_module(authored_module)
        authored = module
        for part in authored_qualname.split("."):
            authored = getattr(authored, part)

        self._name = constraint_name
        self._authored = authored(**dict(authored_config or {}))
        self._aliases = dict(self._authored.inputs())

    @property
    def constraint_id(self) -> str:
        return self._name

    def requirements(self) -> tuple:
        from vqapr._internal.pit_bridge import requirement_for

        return tuple(
            requirement_for(alias, declaration)
            for alias, declaration in self._aliases.items()
        )

    def project(self, window: Any, instruments: Sequence[str]) -> Any:
        call = _ProjectionCall(
            reads=_named_observations(window, self._aliases),
            instruments=tuple(instruments),
            evaluation_time=getattr(window, "evaluation_time", None),
        )
        return _engine_bounds(self._authored.project(call))

    def validate_intended(self, intent: Any, bounds: Any) -> Any:
        return _engine_finding(
            self._authored.validate(_authoring_decision(intent), bounds),
            constraint_id=self._name,
        )

    def evaluate(self, window: Any, account: Any, marks: Any, bounds: Any) -> Any:
        call = _ProjectionCall(
            reads=_named_observations(window, self._aliases),
            instruments=tuple(getattr(bounds, "lower", {})),
            evaluation_time=getattr(window, "evaluation_time", None),
            account=_marked_account(
                account, marks, getattr(window, "evaluation_time", None)
            ),
        )
        return _engine_finding(
            self._authored.monitor(call, bounds), constraint_id=self._name
        )



def _authoring_decision(intent: Any) -> Any:
    """Present the engine's accepted intent as the Rebalance an author declared.

    `Constraint.validate` is specified against a normalized `Rebalance`, so handing it the
    engine's own intent would make every authored constraint reach for attributes the
    public contract never promised.
    """
    from vqapr.authoring import Rebalance

    if isinstance(intent, Rebalance):
        return intent
    return Rebalance(
        target_weights={target.instrument_id: target.weight for target in intent.targets},
        cash_weight=intent.cash_target,
        budget=intent.budget,
    )



def _engine_finding(finding: Any, *, constraint_id: str) -> Any:
    """Translate an authored finding onto the engine's own.

    The engine's finding additionally carries `constraint_id` and `input_lineage`, both
    framework-owned - an author states only what was measured against which bound.
    """
    from vqapr.public import ConstraintFinding as EngineFinding

    if isinstance(finding, EngineFinding):
        return finding
    return EngineFinding(
        constraint_id,
        finding.passed,
        finding.measured,
        finding.bound,
        finding.excess,
        {},
    )



def _marked_account(account: Any, marks: Any, observed_at: Any = None) -> Any:
    """The account view a monitoring constraint receives, carrying its valuation.

    `evaluate` is handed the committed marks alongside the account, but they were being
    dropped, so an authored `monitor` saw cash and quantities with `nav=None`. Any
    weight-based rule - which is most real constraints - is uncomputable from that, so it
    could only ever return an honest non-judgement.

    NAV comes from the mark batch's own total, never synthesized from cash and positions.
    """
    from vqapr.authoring import EconomicAccountView

    # A MarkBatch carries values and quantities but no timestamp of its own - the instant
    # belongs to the occurrence being monitored, which is why it is passed in rather than
    # read off the batch. NAV and its instant stay coupled: both present or both absent.
    total = getattr(marks, "total_value", None)
    if total is None or observed_at is None:
        total, observed_at = None, None
    return EconomicAccountView(
        cash=account.cash,
        positions=dict(account.positions),
        nav=total,
        nav_observed_at=observed_at,
    )


def _engine_bounds(bounds: Any) -> Any:
    """Translate authoring ConstraintBounds onto the engine's lower/upper naming."""
    from vqapr.public import ConstraintBounds as EngineBounds

    if isinstance(bounds, EngineBounds):
        return bounds
    return EngineBounds(dict(bounds.lower_weights), dict(bounds.upper_weights))
