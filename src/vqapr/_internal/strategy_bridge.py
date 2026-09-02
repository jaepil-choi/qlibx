"""Run an authoring-protocol StrategyModel through the engine's loader.

**Half of this module's reason is gone.** It used to build a whole `EconomicPortfolioIntent`
from an authored `Rebalance` -- minting the UUID, naming the strategy, rebuilding the source
refs from `window.accesses`, copying the account version. Record `125` moved that stamping into
`flow/simulation.py`, where the Flow was already deriving every one of those values in order to
check this module's copy of them. `_decide` now returns the author's decision unchanged.

What remains is the one translation that is still real: the engine calls
`on_occurrence(context)` with a `StrategyModelContext`, and an authored model expects
`decide(call)` with a bounded `StrategyCall`. Two capability surfaces over the same data. That
is the next convergence, and when it lands this file has nothing left to do.
"""

from __future__ import annotations

from typing import Any

from vqapr.models.strategy_model import StrategyModel as _EngineBase

__all__ = ("AdaptedStrategy", "adapter_config")


# `_authoring_bounds` was here, translating the engine's `ConstraintBounds` onto the authoring
# one because they were two classes with the same economics and different field names. Record
# `129` made them one class, so the translation became the identity function and is gone. This is
# the first of this file's two reasons to exist retiring; the other is `decide` against
# `on_occurrence`, and when that goes so does the file.


def _decide(authored, config, strategy_id, context, aliases, holder):
    """One occurrence: invoke the authored model and hand its decision to the Flow."""
    from vqapr._internal.models.agent_first import prepare_strategy_invocation

    prepared = prepare_strategy_invocation(
        authored,
        config,
        evaluation_time=context.occurrence.evaluation_time,
        account=_account_view(context),
        instruments=tuple(context.constraint_bounds.lower_weights),
        constraint_bounds=context.constraint_bounds,
        previous_state=holder.memory,
        history_resolver=_history_resolver(context),
        resolver=_context_resolver(context, aliases),
    )
    # The author's returned state is the only thing they carry forward.
    holder.memory = prepared.next_state

    # Declared, validated, and previously dropped on the floor: an authored diagnostic
    # table only means something if its rows reach the recorder that will persist them.
    recorder = getattr(holder, "recorder", None)
    if recorder is not None:
        for table_id, rows in prepared.diagnostics.items():
            if rows:
                recorder.append_batch(table_id, [dict(row) for row in rows])

    # Returned as authored. `Hold` and `Rebalance` are what the engine contract accepts now, so
    # there is nothing to convert -- the two decision algebras became one in record `125`.
    return prepared.decision


def _history_resolver(context: Any):
    """Serve a declared AccountHistoryInput from the engine's own account history.

    The engine already assembles the history a callback asked for; this only reshapes it
    into the bounded view the authoring contract specifies, preserving the declared field
    set and lookback so an author cannot read more than they declared.
    """

    def resolve(declaration: Any) -> Any:
        from vqapr.authoring import DeclaredAccountHistory

        history = getattr(context, "account_history", None)
        if history is None:
            raise ValueError(
                "this StrategyModel declared an AccountHistoryInput but the run supplied "
                "no account history to serve it"
            )
        series: dict[str, tuple] = {}
        panel: dict[str, dict] = {}
        for field in declaration.fields:
            if field in ("nav", "cash"):
                series[field] = tuple(history.series(field))
            else:
                panel[field] = {k: tuple(v) for k, v in history.panel(field).items()}
        return DeclaredAccountHistory(
            fields=declaration.fields,
            lookback=declaration.lookback,
            series=series,
            panel=panel,
        )

    return resolve


def _account_view(context: Any) -> Any:
    """The bounded economic view an authored strategy receives.

    `nav` and `nav_observed_at` are coupled: both None before any committed valuation,
    both set afterwards. They are read from the declared account history rather than
    synthesized from cash and positions - a NAV computed here would be a number the
    framework invented, under a name the author would reasonably trust.
    """
    from vqapr.authoring import EconomicAccountView

    account = context.account
    nav, observed_at = _committed_nav(context)
    return EconomicAccountView(
        cash=account.cash,
        positions=dict(account.positions),
        nav=nav,
        nav_observed_at=observed_at,
    )


def _committed_nav(context: Any) -> tuple[Any, Any]:
    """The most recent committed NAV and when it was observed, or (None, None).

    Absent history, or a history that never declared nav, means no valuation has been
    committed yet. That is a real state, not a gap to paper over with a zero.
    """
    history = getattr(context, "account_history", None)
    if history is None:
        return None, None
    try:
        navs = history.series("nav")
    except (KeyError, ValueError, AttributeError):
        return None, None
    if not navs or navs[-1] is None:
        return None, None

    # The engine's committed marks carry the instant each NAV was observed at. It is read
    # separately because a strategy declares `nav` without necessarily declaring
    # `observed_at`, and the public contract couples the two: a NAV without its instant
    # would be a number the author cannot place in time.
    at = _nav_observed_at(context)
    if at is None:
        return None, None
    return navs[-1], at


def _nav_observed_at(context: Any) -> Any:
    """When the most recent committed NAV was observed.

    Read from the account history's own marks rather than from a series: `observed_at` is
    an instrument-scoped panel field, so there is no account-level series carrying it,
    while every mark records the instant its NAV belongs to.
    """
    history = getattr(context, "account_history", None)
    marks = getattr(history, "_marks", None)
    if not marks:
        return None
    # `marked_at` is the mark's own instant. `observed_at` on a mark is per-instrument,
    # so it is the wrong scope for an account-level NAV.
    return getattr(marks[-1], "marked_at", None)


def _context_resolver(context: Any, aliases: dict[str, Any]):
    """Serve declared aliases from the window this occurrence was handed."""
    from vqapr.models.calls import declared_rows, observations

    def resolve(alias: str, declaration: Any, evaluation_time: Any) -> tuple:
        return observations(
            declared_rows(lambda r: context.window.observations(r).rows, declaration),
            instrument_field="instrument",
            available_at_field="available_at",
            fields=declaration.fields,
        )

    return resolve


def adapter_config(authored: type, *, strategy_id: str, config=None) -> dict:
    """The config `AdaptedStrategy` reconstructs itself from.

    The loader re-imports a component's module and looks the class up BY NAME at module
    scope, so a class generated at runtime can never be found. `AdaptedStrategy` is
    therefore a real module-level class that rebuilds the authored one from its import
    path, and this produces the config that names it.
    """
    from vqapr.authoring import StrategyModel as AuthoringStrategy

    if not isinstance(authored, type) or not issubclass(authored, AuthoringStrategy):
        raise TypeError("authored must be a subclass of vqapr.authoring.StrategyModel")
    if "<locals>" in authored.__qualname__:
        raise ValueError(
            f"{authored.__qualname__} is defined inside another scope; the loader "
            "resolves a strategy by module and qualname, so it must live at module scope"
        )
    return {
        "authored_module": authored.__module__,
        "authored_qualname": authored.__qualname__,
        "strategy_id": strategy_id,
        "authored_config": dict(config or {}),
    }


class AdaptedStrategy(_EngineBase):
    """The one registrable strategy component: an authored model in engine clothing.

    Resolved by the loader from this module by name, then reconstructed from the config
    `adapter_config` produced. The authored class is imported here rather than captured,
    because a captured object cannot survive the loader's fresh module import.
    """

    def __init__(
        self,
        *,
        authored_module: str,
        authored_qualname: str,
        strategy_id: str,
        authored_config: dict | None = None,
    ) -> None:
        super().__init__()
        import importlib

        module = importlib.import_module(authored_module)
        authored = module
        for part in authored_qualname.split("."):
            authored = getattr(authored, part)

        self._authored = authored
        self._strategy_id = strategy_id
        self._config = dict(authored_config or {})
        instance = authored(**self._config)
        self._aliases = dict(instance.inputs())
        self._authored_history = instance.account_history()
        self._authored_tables = tuple(instance.diagnostics())

    def requirements(self) -> tuple:
        from vqapr.models.calls import requirements_for

        return tuple(
            requirement
            for declaration in self._aliases.values()
            for requirement in requirements_for(declaration)
        )

    def tables(self) -> tuple:
        """Declare the authored DiagnosticTables so the recorder will accept their rows.

        Without this the engine only ever knows DEFAULT_TABLES, so an authored table's
        rows would be validated against its declared schema and then have nowhere to go.
        """
        from vqapr.evidence.recorder import TableSpec

        return tuple(
            TableSpec(table.table_id, tuple(table.semantic_fields))
            for table in self._authored_tables
        )

    def account_requirements(self) -> tuple:
        """Translate the authored AccountHistoryInput into the engine's declaration.

        The engine refuses to serve an account field a consumer never declared, so an
        authored history declaration has to reach it or the read fails at the callback.
        """
        from vqapr.account.history import AccountRequirement
        from vqapr.data.lookback import RowsLookback as EngineRows

        declared = self._authored_history
        if declared is None:
            return ()
        return (
            AccountRequirement.of(
                self._strategy_id,
                fields=declared.fields,
                lookback=EngineRows(rows=declared.lookback.rows),
            ),
        )

    def on_occurrence(self, context):
        return _decide(
            self._authored,
            self._config,
            self._strategy_id,
            context,
            self._aliases,
            self,
        )
