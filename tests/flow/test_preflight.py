from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import FailureFamily, VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.exchange.venue import AcademicExchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_exchange
from vqapr.flow.model_state import prepare_model_state
from vqapr.flow.preflight import preflight_run
from vqapr.flow.run import ConstraintSet, RunDefinition, StrategyConfig
from vqapr.public import register_dataset
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

_ZONE = ZoneInfo("Asia/Seoul")


def _occurrence(
    identifier: str, role: OperationRole, local_time: time
) -> OperationOccurrence:
    return OperationOccurrence(
        identifier,
        role,
        LocalInstantDeclaration(date(2024, 3, 5), local_time, "Asia/Seoul", 0, "+09:00"),
    )


def _agenda(identifier: str, role: OperationRole, *hours: int) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=identifier,
        role=role,
        timezone="Asia/Seoul",
        occurrences=tuple(
            _occurrence(f"{identifier}-{hour}", role, time(hour)) for hour in hours
        ),
        provenance="test fixture",
    )


def _component(root: Path, identifier: str, kind: ComponentKind) -> ComponentRef:
    path = root / f"{identifier}.py"
    source = (
        "from vqapr.authoring import Hold\n"
        "from vqapr.models.strategy_model import StrategyModel\n"
        f"class {identifier.title().replace('-', '')}(StrategyModel):\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def decide(self, context):\n"
        "        return Hold(reason='fixture')\n"
        if kind is ComponentKind.STRATEGY_MODEL
        else "from vqapr.constraints.constraint import Constraint\n"
        f"class {identifier.title().replace('-', '')}(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        # The id the component is REGISTERED under, not a fixed string. A Constraint must answer
        # to its own component id -- `SimulationFlow` has always required it and `load_constraint`
        # now refuses the mismatch -- so a helper that hardcoded `'fixture'` built components that
        # could never have run. These fixtures never assembled a Flow, which is the only reason
        # the invariant went unnoticed here.
        f"        return {identifier!r}\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def project(self, call):\n"
        "        return None\n"
        "    def monitor(self, call, account, bounds):\n"
        "        return None\n"
    )
    path.write_text(
        source,
        encoding="utf-8",
    )
    return ComponentRef.of(
        identifier,
        kind,
        path,
        identifier.title().replace("-", ""),
        fingerprint=fingerprint_component(
            path, kind=kind, object_name=identifier.title().replace("-", "")
        ),
    )


def _setup(
    root: Path,
    model_price_parquet: Path,
    *,
    with_execution: bool = True,
    selector: FillSelector = FillSelector.SAME_DAY,
    strategy_times: tuple[time, ...] = (time(9), time(10)),
) -> tuple[Workspace, RunDefinition]:
    """A registered workspace and a declaration for it.

    `with_execution` defaults to True because an execution price is mandatory: preflight refuses a
    declaration without one, so a definition lacking it is not a run a caller could ever have.
    Tests that assert the refusal itself pass False.
    """
    workspace = Workspace.create(root)
    strategy_component = _component(root, "strategy", ComponentKind.STRATEGY_MODEL)
    constraint_component = _component(root, "limit", ComponentKind.CONSTRAINT)
    for component in (strategy_component, constraint_component):
        workspace.register_component(component)
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(
        root,
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("session_date", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", model_price_parquet),
    )
    workspace = Workspace.open(root)
    strategy_agenda = OperationAgenda.from_occurrences(
        agenda_id="strategy",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=tuple(
            _occurrence(
                (
                    f"strategy-{instant.hour}"
                    if instant.minute == 0
                    else f"strategy-{instant.strftime('%H%M')}"
                ),
                OperationRole.STRATEGY_CALLBACK,
                instant,
            )
            for instant in strategy_times
        ),
        provenance="test fixture",
    )
    valuation_agenda = _agenda("valuation", OperationRole.VALUATION, 9)
    monitoring_agenda = _agenda("monitoring", OperationRole.MONITORING, 16)
    for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda):
        workspace.register_agenda(agenda)
    strategy = StrategyConfig(strategy_component, "strategy", OperationRole.STRATEGY_CALLBACK)
    valuation = ValuationConfig(
        "valuation",
        OperationRole.VALUATION,
    )
    monitoring = MonitoringPolicy("monitoring", OperationRole.MONITORING)
    workspace.register_strategy_config(strategy)
    workspace.register_valuation_config(valuation)
    workspace.register_monitoring_policy(monitoring)
    # Same root as the tests' own `_execution_exchange` calls, so the shared
    # `execution-source` declaration stays byte-identical rather than conflicting.
    exchange_component = (
        _execution_exchange(
            workspace,
            root,
            identifier="setup-exchange",
            selector=selector,
        )
        if with_execution
        else None
    )
    return workspace, RunDefinition(
        strategy,
        valuation,
        ConstraintSet((constraint_component,)),
        monitoring,
        exchange=exchange_component,
        execution_input_id="execution" if with_execution else None,
        start=datetime(2024, 3, 5, 9, tzinfo=_ZONE),
        # The execution fixture fills at 15:30. Keeping end at 10:00 made every supposedly
        # run-ready definition in this file physically impossible: an intent from either
        # strategy callback had no target inside its frozen horizon.
        end=datetime(2024, 3, 5, 15, 30, tzinfo=_ZONE),
        initial_account_snapshot=AccountSnapshot(0, Decimal("100"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        initial_model_memory={"cadence": [1]},
        instruments=("ABC",),
    )


def _execution_exchange(
    workspace: Workspace,
    root: Path,
    *,
    identifier: str = "exchange",
    access: str = "ListingAccess.SIGNED",
    step: str = "Decimal('1')",
    minimum: str = "Decimal('1')",
    fractional: str = "False",
    register_input: bool = True,
    selector: FillSelector = FillSelector.SAME_DAY,
) -> ComponentRef:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{identifier}.py"
    path.write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Exchange(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'ABC': TradeRule('ABC', "
        f"{step}, {minimum}, {fractional}, {access})}})\n",
        encoding="utf-8",
    )
    component = ComponentRef.of(
        identifier,
        ComponentKind.EXCHANGE,
        path,
        "Exchange",
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.EXCHANGE, object_name="Exchange"
        ),
    )
    workspace.register_component(component)
    execution_path = root / "execution.parquet"
    if register_input:
        connection = duckdb.connect()
        try:
            connection.execute(
                f"""COPY (
                    SELECT * FROM (VALUES
                        (TIMESTAMPTZ '2024-03-05 09:30:00+09', 'ABC', true, 9.0),
                        (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'ABC', true, 10.0)
                    ) AS t(trade_at, instrument, is_tradable, close)
                ) TO '{execution_path.as_posix()}' (FORMAT PARQUET)"""
            )
        finally:
            connection.close()
    execution = ExecutionInputRegistration.of(
        "execution",
        ExecutionTableSpec(
            SourceSpec.of("execution-source", execution_path),
            "trade_at",
            "instrument",
            "is_tradable",
            {"close": "close"},
        ),
        FillConvention(selector, time(15, 30), "Asia/Seoul", "close"),
    )
    if register_input:
        workspace.register_execution_input(execution)
    return component


def test_preflight_freezes_independent_inclusive_slices_and_static_merge(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)

    frozen = preflight_run(workspace, definition)

    assert [item.occurrence_id for item in frozen.strategy_agenda.occurrences] == [
        "strategy-9",
        "strategy-10",
    ]
    assert [item.occurrence_id for item in frozen.valuation_agenda.occurrences] == ["valuation-9"]
    assert frozen.monitoring_agenda is not None
    assert frozen.monitoring_agenda.occurrences == ()
    assert [item.occurrence_id for item in frozen.static_occurrences] == [
        "strategy-9",
        "valuation-9",
        "strategy-10",
    ]
    assert frozen.constraints is not definition.constraints
    assert frozen.constraints.constraints[0].component_id == "limit"
    assert frozen.instruments == definition.instruments
    assert frozen.strategy_requirements == ()
    assert frozen.constraint_requirements == ()
    assert (
        frozen.initial_model_state_ref
        == prepare_model_state(frozen.initial_model_memory, frozen.initial_payload).ref
    )
    assert frozen.identity == preflight_run(workspace, definition).identity
    changed_account = replace(
        frozen,
        initial_account_snapshot=AccountSnapshot(0, Decimal("101"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
    )
    changed_model_state = replace(frozen, initial_model_memory={"cadence": [2]})
    changed_source = replace(
        frozen,
        sources=(SourceSpec.of("prices-source", tmp_path / "changed.parquet"),),
    )
    exchange = _component(tmp_path, "exchange", ComponentKind.EXCHANGE)
    execution = ExecutionInputRegistration.of(
        "execution",
        ExecutionTableSpec(
            SourceSpec.of("execution-source", tmp_path / "execution.parquet"),
            "trade_at",
            "instrument",
            "is_tradable",
            {"close": "close"},
        ),
        FillConvention(FillSelector.SAME_DAY, time(15, 30), "Asia/Seoul", "close"),
    )
    frozen_execution = replace(frozen, exchange=exchange, execution_input=execution)
    changed_fill = replace(
        frozen_execution,
        execution_input=ExecutionInputRegistration(
            execution.execution_input_id,
            execution.table,
            FillConvention(FillSelector.NEXT_ELIGIBLE, time(15, 30), "Asia/Seoul", "close"),
        ),
    )
    assert changed_account.identity != frozen.identity
    assert changed_model_state.identity != frozen.identity
    assert changed_source.identity != frozen.identity
    assert changed_fill.identity != frozen_execution.identity
    assert (
        frozen.physical_source_guarantee
        == "Configuration and declaration objects are frozen; physical source bytes are not."
    )


def test_preflight_refuses_a_last_strategy_occurrence_with_no_execution_target(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """A finite `next_eligible` run must not fail only after earlier callbacks mutate state.

    The first callback at 10:00 resolves to the 15:30 snapshot. The last callback fires exactly at
    15:30, so `next_eligible` needs a later snapshot, but `end` is also 15:30.
    Before this check, preflight returned a supposedly run-ready declaration and the simulation
    raised a bare `ValueError` only if the last callback produced an intent.
    """
    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        selector=FillSelector.NEXT_ELIGIBLE,
        strategy_times=(time(10), time(15, 30)),
    )

    with pytest.raises(VqaprError) as caught:
        preflight_run(workspace, definition)

    error = caught.value
    assert error.stage == "preflight.execution"
    assert error.family is FailureFamily.EXCHANGE
    assert error.mutation is False
    failure = error.failures[0]
    assert failure.code == "preflight.execution.target_outside_horizon"
    assert failure.example_total == 1
    assert failure.examples == ("strategy-1530: 2024-03-05T15:30:00+09:00",)
    assert "selector=next_eligible" in (failure.observed or "")
    assert "end=2024-03-05T15:30:00+09:00" in (failure.observed or "")
    assert "extend end" in failure.requirement


def test_preflight_requires_academic_exchange_and_initial_account_compatibility(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    exchange = _execution_exchange(workspace, tmp_path)
    compatible = replace(
        definition,
        exchange=exchange,
        execution_input_id="execution",
        initial_account_snapshot=AccountSnapshot(0, Decimal("100"), {"ABC": Decimal("2")}),
    )

    assert isinstance(
        load_exchange(exchange, project_root=workspace.project_root), AcademicExchange
    )
    assert preflight_run(workspace, compatible).exchange == exchange
    with pytest.raises(VqaprError, match="unlisted_instrument"):
        preflight_run(workspace, replace(compatible, instruments=("ABC", "MISSING")))

    duck_path = tmp_path / "duck.py"
    duck_path.write_text(
        "class Duck:\n"
        "    exchange_id = 'duck'\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def execute(self, orders, account, snapshot):\n"
        "        return None\n",
        encoding="utf-8",
    )
    duck = ComponentRef.of(
        "duck",
        ComponentKind.EXCHANGE,
        duck_path,
        "Duck",
        fingerprint=fingerprint_component(
            duck_path, kind=ComponentKind.EXCHANGE, object_name="Duck"
        ),
    )
    workspace.register_component(duck)
    with pytest.raises(VqaprError, match="wrong_type"):
        preflight_run(workspace, replace(compatible, exchange=duck))

    cases = (
        (
            "unlisted",
            AccountSnapshot(0, Decimal("100"), {"MISSING": Decimal("2")}),
            "unlisted_holding",
        ),
        (
            "minimum",
            AccountSnapshot(0, Decimal("100"), {"ABC": Decimal("0.5")}),
            "minimum_quantity",
        ),
        (
            "step",
            AccountSnapshot(0, Decimal("100"), {"ABC": Decimal("1.5")}),
            "quantity_step",
        ),
    )
    for _name, snapshot, code in cases:
        with pytest.raises(VqaprError, match=code):
            preflight_run(workspace, replace(compatible, initial_account_snapshot=snapshot))

    # A holding the venue will never fill, in an instrument the run does not trade -- the
    # money is stuck in something unsellable and preflight says so before the run starts.
    # Closing a *short* on a long-only listing is permitted (buying back to zero), so only
    # `NONE` is genuinely unclosable.
    no_sell_path = tmp_path / "no-sell" / "no_sell.py"
    no_sell_path.parent.mkdir(parents=True, exist_ok=True)
    no_sell_path.write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Exchange(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({\n"
        "            'ABC': TradeRule('ABC', Decimal('1'), Decimal('1'), False,"
        " ListingAccess.SIGNED),\n"
        "            'STUCK': TradeRule('STUCK', Decimal('1'), Decimal('1'), False,"
        " ListingAccess.NONE),\n"
        "        })\n",
        encoding="utf-8",
    )
    no_sell = ComponentRef.of(
        "no-sell",
        ComponentKind.EXCHANGE,
        no_sell_path,
        "Exchange",
        fingerprint=fingerprint_component(
            no_sell_path, kind=ComponentKind.EXCHANGE, object_name="Exchange"
        ),
    )
    workspace.register_component(no_sell)
    with pytest.raises(VqaprError, match="holding_not_closable"):
        preflight_run(
            workspace,
            replace(
                compatible,
                exchange=no_sell,
                initial_account_snapshot=AccountSnapshot(
                    0, Decimal("100"), {"STUCK": Decimal("1")}
                ),
            ),
        )

    fractional = _execution_exchange(
        workspace,
        tmp_path / "fractional",
        identifier="fractional",
        step="Decimal('0.1')",
        fractional="False",
        register_input=False,
    )
    with pytest.raises(VqaprError, match="fractional_quantity"):
        preflight_run(
            workspace,
            replace(
                compatible,
                exchange=fractional,
                initial_account_snapshot=AccountSnapshot(
                    0, Decimal("100"), {"ABC": Decimal("1.5")}
                ),
            ),
        )

    signed = replace(
        compatible,
        initial_account_snapshot=AccountSnapshot(0, Decimal("100"), {"ABC": Decimal("-2")}),
    )
    with pytest.raises(VqaprError, match="mode"):
        preflight_run(workspace, signed)
    assert (
        preflight_run(
            workspace, replace(signed, initial_account_mode=AccountMode.SIGNED)
        ).initial_account_mode
        is AccountMode.SIGNED
    )


def test_preflight_is_detached_and_rejects_reference_or_component_drift(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    frozen = preflight_run(workspace, definition)
    definition.strategy.component.config["changed"] = 1

    assert frozen.strategy.component.config == {}
    with pytest.raises(ValueError, match="strategy configuration reference drift"):
        preflight_run(workspace, definition)

    memory = {"nested": [1]}
    workspace, definition = _setup(tmp_path / "memory", model_price_parquet)
    definition = replace(definition, initial_model_memory=memory)
    frozen = preflight_run(workspace, definition)
    memory["nested"].append(2)
    assert definition.initial_model_memory == {"nested": [1]}
    assert frozen.initial_model_memory == {"nested": [1]}
    workspace, definition = _setup(tmp_path / "drift", model_price_parquet)
    (tmp_path / "drift" / "strategy.py").write_text(
        "class Strategy:\n    changed = True\n", encoding="utf-8"
    )
    # An edited SOURCE no longer refuses AS DRIFT: that gate became a receipt (issue 009), so
    # the edited file is loaded and judged on its merits. This replacement is not a StrategyModel,
    # so it is refused for what it actually is -- a contract violation -- rather than for having
    # changed. The distinction is the point: editing a registered component is the ordinary
    # development loop, and only a component that cannot do its job should stop a run.
    with pytest.raises(VqaprError, match="component.load.wrong_type"):
        preflight_run(workspace, definition)


    workspace, definition = _setup(tmp_path / "config-drift", model_price_parquet)
    registered = workspace._components["strategy"]
    registered.config["changed"] = True
    drifted_strategy = StrategyConfig(
        registered, definition.strategy.agenda_id, definition.strategy.agenda_role
    )
    workspace._strategy_configs[drifted_strategy.agenda_id] = drifted_strategy
    # A mutated CONFIG is likewise no longer refused as drift. It reaches the component, which
    # cannot construct from a key it does not declare, so the refusal names that instead. Same
    # principle as the source edit above: judged on whether it works, not on whether it moved.
    with pytest.raises(VqaprError, match="component.load.construction_failed"):
        preflight_run(workspace, replace(definition, strategy=drifted_strategy))


def test_preflight_refuses_a_run_that_declares_no_execution_price(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """An observation dataset is optional; an execution price is not.

    A Strategy may declare no requirement and decide nothing, and running it is still a run. But
    every run values its book and fills against prices a venue published, so the execution input
    is the one registration that is mandatory from the start.

    This was refused only inside `run()`, as a bare `ValueError`, *after* `preflight_run` had
    already returned a `FrozenRun` it called run-ready. Two consequences: the CLI reported it as
    `stage: "unhandled"` (the framework looking broken rather than the declaration being
    incomplete), and the universe and account checks below were skipped entirely.
    """
    workspace, definition = _setup(
        tmp_path / "no-execution", model_price_parquet, with_execution=False
    )

    with pytest.raises(VqaprError, match=r"preflight\.execution\.missing") as failure:
        preflight_run(workspace, definition)

    error = failure.value
    assert error.stage == "preflight.execution"
    assert error.family is FailureFamily.EXCHANGE
    assert error.mutation is False
    # Typed, so an agent parses a verdict instead of reading a traceback.
    assert error.as_dict()["failures"][0]["code"] == "preflight.execution.missing"
    assert "register an execution input" in error.retry_precondition


def test_a_run_without_an_execution_price_is_refused_before_it_is_frozen(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`preflight_run` promises a *run-ready* declaration, so it must not hand back a reject.

    Freezing first and refusing in `run()` meant the two checks below never ran: a definition
    naming an instrument the Exchange does not list could be frozen and only fail later.
    """
    workspace, definition = _setup(
        tmp_path / "unlisted", model_price_parquet, with_execution=False
    )
    unlisted = replace(definition, instruments=("NOT-LISTED",))

    # The execution refusal comes first, and it is the reason the universe check is reachable
    # at all once an execution input is supplied.
    with pytest.raises(VqaprError, match=r"preflight\.execution\.missing"):
        preflight_run(workspace, unlisted)

    workspace, definition = _setup(tmp_path / "listed", model_price_parquet)

    with pytest.raises(VqaprError, match=r"preflight\.universe\.unlisted_instrument"):
        preflight_run(workspace, replace(definition, instruments=("NOT-LISTED",)))


def test_a_venue_regime_without_its_execution_price_is_refused_before_the_run(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The third state must not exist: regime declared, data absent, run proceeding anyway.

    A KRX price limit is computed from the session base price. If the registered execution input
    does not carry one, the run would produce numbers that look limit-aware and are not. Preflight
    refuses, and names the feature to switch off rather than only the missing column.
    """
    root = tmp_path / "regime"
    workspace, definition = _setup(root, model_price_parquet)
    path = root / "limited.py"
    path.write_text(
        "from vqapr.exchange.venues.krx import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=True)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    component = ComponentRef.of(
        "limited",
        ComponentKind.EXCHANGE,
        path,
        "Exchange",
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.EXCHANGE, object_name="Exchange"
        ),
    )
    workspace.register_component(component)

    with pytest.raises(VqaprError, match=r"preflight\.execution\.requirement_missing") as error:
        preflight_run(workspace, replace(definition, exchange=component))
    failure = error.value.as_dict()["failures"][0]
    assert "price_limit" in failure["observed"], "the message names the feature to switch off"
    assert "switched off" in failure["requirement"]

    # The same venue with the regime off needs nothing extra and freezes cleanly.
    off_path = root / "unlimited.py"
    off_path.write_text(
        "from vqapr.exchange.venues.krx import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=False)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    off = ComponentRef.of(
        "unlimited",
        ComponentKind.EXCHANGE,
        off_path,
        "Exchange",
        fingerprint=fingerprint_component(
            off_path, kind=ComponentKind.EXCHANGE, object_name="Exchange"
        ),
    )
    workspace.register_component(off)
    assert preflight_run(workspace, replace(definition, exchange=off)).exchange == off


def test_a_listing_that_permits_no_side_is_refused_as_its_own_problem(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """A published benchmark in the traded universe is not a missing registration.

    The venue lists `KOSPI200` so it can be quoted, and permits no side on it. Reporting that as
    `unlisted` invites someone to register a listing that already exists.
    """
    root = tmp_path / "untradable"
    workspace, definition = _setup(root, model_price_parquet)
    path = root / "tracked.py"
    path.write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        "class Exchange(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__(\n"
        "            {'ABC': TradeRule('ABC', Decimal('1'), Decimal('1'), False,"
        " ListingAccess.SIGNED),\n"
        "             'KOSPI200': TradeRule('KOSPI200', Decimal('1'), Decimal('1'), False,"
        " ListingAccess.NONE)},\n"
        "            'academic',\n"
        "        )\n",
        encoding="utf-8",
    )
    component = ComponentRef.of(
        "tracked",
        ComponentKind.EXCHANGE,
        path,
        "Exchange",
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.EXCHANGE, object_name="Exchange"
        ),
    )
    workspace.register_component(component)
    tracked = replace(definition, exchange=component)

    # Publishing it is fine; the run simply does not trade it.
    assert preflight_run(workspace, tracked).exchange == component

    with pytest.raises(VqaprError, match=r"preflight\.universe\.untradable_listing") as e:
        preflight_run(workspace, replace(tracked, instruments=("ABC", "KOSPI200")))
    codes = [failure["code"] for failure in e.value.as_dict()["failures"]]
    assert codes == ["preflight.universe.untradable_listing"], (
        "a listed instrument must not also be reported as unlisted"
    )


def test_preflight_rejects_missing_requirement_and_invalid_bounds(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    # Valuation no longer declares a requirement -- it reads the execution table -- so the
    # missing-requirement contract is proved by a consumer that still has one: a Constraint.
    workspace, definition = _setup(tmp_path / "constraint-requirement", model_price_parquet)
    constraint_path = tmp_path / "constraint-requirement" / "limit.py"
    constraint_path.write_text(
        "from vqapr.constraints.constraint import Constraint\n"
        "from vqapr.data.lookback import RowsLookback\n"
        "from vqapr.data.requirements import DataRequirement\n"
        "class Limit(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        "        return 'limit'\n"
        "    def requirements(self):\n"
        "        return (DataRequirement.of('absent', 'close', "
        "lookback=RowsLookback(1)),)\n"
        "    def project(self, call):\n"
        "        return None\n"
        "    def monitor(self, call, account, bounds):\n"
        "        return None\n",
        encoding="utf-8",
    )
    constraint = ComponentRef.of(
        "limit",
        ComponentKind.CONSTRAINT,
        constraint_path,
        "Limit",
        fingerprint=fingerprint_component(
            constraint_path, kind=ComponentKind.CONSTRAINT, object_name="Limit"
        ),
    )
    workspace._components[constraint.component_id] = constraint
    invalid_constraint = RunDefinition(
        definition.strategy,
        definition.valuation,
        ConstraintSet((constraint,)),
        definition.monitoring,
        start=definition.start,
        end=definition.end,
        instruments=definition.instruments,
    )
    with pytest.raises(VqaprError):
        preflight_run(workspace, invalid_constraint)

    with pytest.raises(ValueError, match="timezone-aware"):
        RunDefinition(
            definition.strategy,
            definition.valuation,
            definition.constraints,
            start=datetime(2024, 3, 5, 9),
            end=definition.end,
            instruments=definition.instruments,
        )
    with pytest.raises(ValueError, match="start must not be after end"):
        RunDefinition(
            definition.strategy,
            definition.valuation,
            definition.constraints,
            start=definition.end,
            end=definition.start,
            instruments=definition.instruments,
        )
    with pytest.raises(ValueError, match="declared together"):
        RunDefinition(
            definition.strategy,
            definition.valuation,
            definition.constraints,
            start=definition.start,
            end=definition.end,
            initial_account_snapshot=AccountSnapshot(0, Decimal("100"), {}),
            instruments=definition.instruments,
        )
    with pytest.raises(TypeError, match="Model memory"):
        RunDefinition(
            definition.strategy,
            definition.valuation,
            definition.constraints,
            start=definition.start,
            end=definition.end,
            initial_model_memory=("not-json",),  # type: ignore[arg-type]
            instruments=definition.instruments,
        )


def test_a_constraint_that_does_not_answer_to_its_id_is_refused_before_the_run(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`vqapr check` runs this phase, so refusing here is refusing before a run is spent.

    `register` now refuses the mismatch outright, so this is the case that door does not cover: a
    workspace populated directly, which is what every fixture here does and what a caller using the
    Python surface does. Preflight is the last gate before `SimulationFlow.__init__`, where the
    same disagreement used to surface as `stage: "unhandled"` with an empty `failures` list.

    The check is on the loaded object, so a `constraint_id` assembled at runtime is caught too.
    """
    root = tmp_path / "mismatch"
    workspace, definition = _setup(root, model_price_parquet)
    path = root / "drifted.py"
    path.write_text(
        "from vqapr.constraints.constraint import Constraint\n"
        "class Drifted(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        "        return '-'.join(['position', 'cap'])\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def project(self, call):\n"
        "        return None\n"
        "    def monitor(self, call, account, bounds):\n"
        "        return None\n",
        encoding="utf-8",
    )
    drifted = ComponentRef.of(
        "limit",
        ComponentKind.CONSTRAINT,
        path,
        "Drifted",
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.CONSTRAINT, object_name="Drifted"
        ),
    )
    workspace.register_component(drifted)

    with pytest.raises(VqaprError) as caught:
        preflight_run(workspace, replace(definition, constraints=ConstraintSet((drifted,))))

    error = caught.value
    assert error.stage == "component.load"
    assert [failure.code for failure in error.failures] == [
        "component.load.constraint_id_mismatch"
    ]
    assert "'limit'" in error.failures[0].observed
    assert "'position-cap'" in error.failures[0].observed
