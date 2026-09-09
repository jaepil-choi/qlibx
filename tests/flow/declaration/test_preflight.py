from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.account.account import AccountMode
from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.sources import SourceSpec
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.errors import Stage, Status, VqaprError
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionTable, ExecutionTableSpec
from vqapr.exchange.venue import AcademicExchange
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.loading import load_exchange
from vqapr.flow.declaration.preflight import derived_agenda, preflight_run
from vqapr.project.run import RunAgenda, RunDefinition, RunExecution, RunFill, StrategyEntry
from vqapr.domain.model_state import prepare_model_state
from vqapr.public import register_dataset, register_instruments
from vqapr.project.store import Workspace

_ZONE = ZoneInfo("Asia/Seoul")
SESSION = date(2024, 3, 5)
"""The one session the execution fixture prices: 09:30 and 15:30 on this day."""


def _component(root: Path, identifier: str, kind: ComponentKind) -> ComponentRef:
    path = root / f"{identifier}.py"
    source = (
        "from vqapr.authoring import Hold\n"
        "from vqapr.authoring import StrategyModel\n"
        f"class {identifier.title().replace('-', '')}(StrategyModel):\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def decide(self, context):\n"
        "        return Hold(reason='fixture')\n"
        if kind is ComponentKind.STRATEGY_MODEL
        else "from vqapr.authoring import Constraint\n"
        f"class {identifier.title().replace('-', '')}(Constraint):\n"
        "    @property\n"
        "    def constraint_id(self):\n"
        # The id the component is REGISTERED under, not a fixed string. A Constraint must answer
        # to its own component id -- `StrategyEventLoop` has always required it and `load_constraint`
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
    at: time = time(9),
    days: tuple[date, ...] = (SESSION,),
) -> tuple[Workspace, RunDefinition]:
    """A registered workspace and a declaration for it.

    `with_execution` defaults to True because an execution price is mandatory: preflight refuses a
    declaration without one, so a definition lacking it is not a run a caller could ever have.
    Tests that assert the refusal itself pass False.

    The run's trading days are the execution table's (design §3.3): `days`, one by default, and
    the strategy clock is `every: 1d` at `at`.
    """
    workspace = Workspace.create(root)
    strategy_component = _component(root, "strategy", ComponentKind.STRATEGY_MODEL)
    constraint_component = _component(root, "limit", ComponentKind.CONSTRAINT)
    for component in (strategy_component, constraint_component):
        with Workspace.transaction(workspace) as t:
            t.register_component(component)
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
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("prices-source", model_price_parquet),
    )
    # A strategy run needs the project to have declared what its instruments ARE (design
    # §6.2); preflight refuses `roster.absent` otherwise.
    register_instruments(root, {"ABC": "stock"})
    workspace = Workspace.open(root)
    # Same root as the tests' own `_execution_exchange` calls, so the shared
    # `execution-source` declaration stays byte-identical rather than conflicting.
    exchange_component = (
        _execution_exchange(
            workspace,
            root,
            identifier="setup-exchange",
            selector=selector,
            days=days,
        )
        if with_execution
        else None
    )
    return workspace, RunDefinition(
        run_id="preflight",
        strategy=StrategyEntry("strategy", ("limit",), {"cadence": [1]}),
        timezone="Asia/Seoul",
        agenda=RunAgenda(every="1d", at=(at,)),
        exchange=None if exchange_component is None else str(exchange_component.component_id),
        execution=(
            RunExecution(
                dataset="execution",
                fill=RunFill(
                    selector=selector.value.lower(),
                    at=time(15, 30),
                    timezone="Asia/Seoul",
                    trade_price="close",
                ),
            )
            if with_execution
            else None
        ),
        start=datetime(2024, 3, 5, 9, tzinfo=_ZONE),
        # The execution fixture fills at 15:30. Keeping end at 10:00 made every supposedly
        # run-ready definition in this file physically impossible: an intent from either
        # strategy callback had no target inside its frozen horizon.
        end=datetime(2024, 3, 5, 15, 30, tzinfo=_ZONE),
        initial_account_snapshot=AccountSnapshot(0, Decimal("100"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("ABC",),
        writes="preflight-weights",
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
    days: tuple[date, ...] = (SESSION,),
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
    with Workspace.transaction(workspace) as t:
        t.register_component(component)
    execution_path = root / "execution.parquet"
    if register_input:
        connection = duckdb.connect()
        try:
            # Two prints per trading day, 09:30 and 15:30 KST: the days are what the run's
            # agenda is expanded over (design §3.3), the instants what it fills against.
            rows = ",\n".join(
                f"(TIMESTAMPTZ '{day.isoformat()} 09:30:00+09', 'ABC', true, 9.0::DOUBLE),\n"
                f"(TIMESTAMPTZ '{day.isoformat()} 15:30:00+09', 'ABC', true, 10.0::DOUBLE)"
                for day in sorted(set(days))
            )
            connection.execute(
                f"""COPY (
                    SELECT * FROM (VALUES
{rows}
                    ) AS t(trade_at, instrument, is_tradable, close)
                ) TO '{execution_path.as_posix()}' (FORMAT PARQUET)"""
            )
        finally:
            connection.close()
    if register_input:
        # The venue table is a dataset with an execution role (record 185); the fill is the
        # run's, declared by `_setup` through `RunExecution`. Validated the way the public
        # door validates (the span is measured), then staged on the workspace object the
        # tests hold, so the state they read is the state that was written.
        registration = DatasetRegistration.of(
            "execution",
            "execution-source",
            instrument_field="instrument",
            available_at="trade_at",
            grain="instrument_instant",
            key_fields=("trade_at", "instrument"),
            fields={"close": "close", "is_tradable": "is_tradable"},
            field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
            execution={"is_tradable": "is_tradable"},
        )
        source = SourceSpec.of("execution-source", execution_path)
        diagnosis, _, measured = validate(registration, source)
        diagnosis.raise_if_failed()
        with Workspace.transaction(workspace) as t:
            t.register_dataset(measured, source)
    return component


def test_preflight_freezes_the_run_s_sessions_as_its_one_agenda(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Record `148`: the strategy's agenda is derived from the run, and it is the only one.

    There is no valuation agenda and no monitoring agenda to merge in: the book is valued at
    the instant the venue fills and judged right after each commit, so the dispatch order is
    the sessions at `at`, and nothing else.
    """
    workspace, definition = _setup(tmp_path, model_price_parquet)

    frozen = preflight_run(workspace, definition)

    layer = frozen.strategy
    assert layer.config.agenda_id == definition.agenda_id == "preflight.agenda"
    assert layer.agenda.agenda_id == definition.agenda_id
    assert layer.agenda.timezone == "Asia/Seoul"
    assert [item.occurrence_id for item in layer.agenda.occurrences] == [
        "preflight.agenda-2024-03-05T0900"
    ]
    (occurrence,) = layer.agenda.occurrences
    assert occurrence.evaluation_time == datetime(2024, 3, 5, 9, tzinfo=_ZONE)
    assert frozen.dispatch_order(layer) == layer.agenda.occurrences
    assert not hasattr(frozen, "valuation_agenda") and not hasattr(frozen, "monitoring_agenda")
    assert layer.constraints.constraints[0].component_id == "limit"
    assert frozen.instruments == definition.instruments
    assert layer.requirements == ()
    assert layer.constraint_requirements == ()
    assert (
        layer.initial_model_state_ref
        == prepare_model_state(layer.initial_model_memory, layer.initial_payload).ref
    )
    assert frozen.identity == preflight_run(workspace, definition).identity
    changed_account = replace(
        frozen,
        initial_account_snapshot=AccountSnapshot(0, Decimal("101"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
    )
    changed_model_state = replace(layer, initial_model_memory={"cadence": [2]})
    changed_source = replace(
        frozen,
        sources=(SourceSpec.of("prices-source", tmp_path / "changed.parquet"),),
    )
    exchange = _component(tmp_path, "exchange", ComponentKind.EXCHANGE)
    execution = ExecutionTable.of(
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
    frozen_execution = replace(frozen, exchange=exchange, execution=execution)
    changed_fill = replace(
        frozen_execution,
        execution=ExecutionTable(
            execution.dataset_id,
            execution.table,
            FillConvention(FillSelector.NEXT_ELIGIBLE, time(15, 30), "Asia/Seoul", "close"),
        ),
    )
    assert changed_account.identity != frozen.identity
    assert changed_model_state.identity != layer.identity, (
        "a strategy's opening memory is the strategy's own"
    )
    assert changed_source.identity != frozen.identity
    assert changed_fill.identity != frozen_execution.identity


def test_preflight_refuses_a_last_strategy_occurrence_with_no_execution_target(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """A finite `next_eligible` run must not fail only after earlier callbacks mutate state.

    The run asks its strategy at 15:30, exactly when the venue prints, so `next_eligible` needs a
    later snapshot -- but `end` is also 15:30. Before this check, preflight returned a supposedly
    run-ready declaration and the simulation raised a bare `ValueError` only if the callback
    produced an intent.
    """
    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        selector=FillSelector.NEXT_ELIGIBLE,
        at=time(15, 30),
    )

    with pytest.raises(VqaprError) as caught:
        preflight_run(workspace, definition)

    error = caught.value
    assert error.stage is Stage.FREEZE
    assert error.status is Status.PRECONDITION
    assert error.mutation is False
    failure = error.failures[0]
    assert failure.code == "execution.target_outside_horizon"
    assert failure.example_total == 1
    assert failure.examples == ("preflight.agenda-2024-03-05T1530: 2024-03-05T15:30:00+09:00",)
    assert "selector=next_eligible" in (failure.observed or "")
    assert "end=2024-03-05T15:30:00+09:00" in (failure.observed or "")
    assert "extend end" in failure.requirement


def test_preflight_requires_academic_exchange_and_initial_account_compatibility(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    exchange = _execution_exchange(workspace, tmp_path)
    compatible = definition.replace(
                     exchange='exchange',
                     execution=RunExecution(
                         dataset='execution',
                         fill=RunFill(
                             selector='same_day',
                             at=time(15, 30),
                             timezone='Asia/Seoul',
                             trade_price='close',
                         ),
                     ),
                     initial_account_snapshot=AccountSnapshot(
                         0, Decimal('100'), {'ABC': Decimal('2')}
                     ),
                 )

    assert isinstance(
        load_exchange(exchange, project_root=workspace.project_root), AcademicExchange
    )
    assert preflight_run(workspace, compatible).exchange == exchange
    assert isinstance(exchange, ComponentRef)
    with pytest.raises(VqaprError, match="unlisted_instrument"):
        preflight_run(workspace, compatible.replace(instruments=('ABC', 'MISSING')))

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
    with Workspace.transaction(workspace) as t:
        t.register_component(duck)
    with pytest.raises(VqaprError, match="wrong_type"):
        preflight_run(workspace, compatible.replace(exchange='duck'))

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
            preflight_run(workspace, compatible.replace(initial_account_snapshot=snapshot))

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
    with Workspace.transaction(workspace) as t:
        t.register_component(no_sell)
    with pytest.raises(VqaprError, match="holding_not_closable"):
        preflight_run(
            workspace,
            compatible.replace(
                exchange='no-sell',
                initial_account_snapshot=AccountSnapshot(
                    0, Decimal('100'), {'STUCK': Decimal('1')}
                ),
            ),
        )

    _execution_exchange(
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
            compatible.replace(
                exchange='fractional',
                initial_account_snapshot=AccountSnapshot(
                    0, Decimal('100'), {'ABC': Decimal('1.5')}
                ),
            ),
        )

    signed = compatible.replace(
                 initial_account_snapshot=AccountSnapshot(
                     0, Decimal('100'), {'ABC': Decimal('-2')}
                 ),
             )
    with pytest.raises(VqaprError, match="mode"):
        preflight_run(workspace, signed)
    assert (
        preflight_run(
            workspace, signed.replace(initial_account_mode=AccountMode.SIGNED)
        ).initial_account_mode
        is AccountMode.SIGNED
    )


def test_preflight_is_detached_and_rejects_reference_or_component_drift(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    frozen = preflight_run(workspace, definition)
    # The definition holds ids (record `139`); the registered component is what the frozen
    # strategy carries, detached from the registration object. Since record `148` there is no
    # separately registered binding that could drift from it: the strategy's config is built by
    # preflight from the registration and the run's own agenda.
    # The registration's config cannot be edited at all: it is read-only, which is what keeps
    # a frozen run detached from the workspace without copying on every read (record `145`).
    with pytest.raises(TypeError):
        workspace.component("strategy").config["changed"] = 1  # type: ignore[index]
    assert frozen.strategy.config.component == workspace.component("strategy")
    assert frozen.strategy.config.component.config == {}

    memory = {"nested": [1]}
    workspace, definition = _setup(tmp_path / "memory", model_price_parquet)
    definition = definition.replace(strategy=StrategyEntry('strategy', ('limit',), memory))
    frozen = preflight_run(workspace, definition)
    memory["nested"].append(2)
    assert definition.strategy.initial_model_memory == {"nested": [1]}
    assert frozen.strategy.initial_model_memory == {"nested": [1]}
    workspace, definition = _setup(tmp_path / "drift", model_price_parquet)
    (tmp_path / "drift" / "strategy.py").write_text(
        "class Strategy:\n    changed = True\n", encoding="utf-8"
    )
    # An edited SOURCE no longer refuses AS DRIFT: that gate became a receipt (issue 009), so
    # the edited file is loaded and judged on its merits. This replacement is not a StrategyModel,
    # so it is refused for what it actually is -- a contract violation -- rather than for having
    # changed. The distinction is the point: editing a registered component is the ordinary
    # development loop, and only a component that cannot do its job should stop a run.
    with pytest.raises(VqaprError, match=r"component\.wrong_type"):
        preflight_run(workspace, definition)


    workspace, definition = _setup(tmp_path / "config-drift", model_price_parquet)
    original = workspace._components["strategy"]
    registered = ComponentRef.of(
        str(original.component_id),
        original.kind,
        original.path,
        original.object_name,
        config={**original.config, "changed": True},
        fingerprint=original.fingerprint,
    )
    workspace._components["strategy"] = registered
    # A mutated CONFIG is likewise no longer refused as drift. It reaches the component, which
    # cannot construct from a key it does not declare, so the refusal names that instead. Same
    # principle as the source edit above: judged on whether it works, not on whether it moved.
    with pytest.raises(VqaprError, match=r"component\.construction_failed"):
        preflight_run(workspace, definition)


def test_preflight_refuses_a_run_that_declares_no_execution_price(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """An observation dataset is optional; an execution price is not.

    A Strategy may declare no requirement and decide nothing, and running it is still a run. But
    every run values its book and fills against prices a venue published, so the execution dataset
    is the one registration that is mandatory from the start.

    This was refused only inside `run()`, as a bare `ValueError`, *after* `preflight_run` had
    already returned a `FrozenRun` it called run-ready. Two consequences: the CLI reported it as
    `stage: "unhandled"` (the framework looking broken rather than the declaration being
    incomplete), and the universe and account checks below were skipped entirely.
    """
    workspace, definition = _setup(
        tmp_path / "no-execution", model_price_parquet, with_execution=False
    )

    with pytest.raises(VqaprError, match=r"execution\.missing") as failure:
        preflight_run(workspace, definition)

    error = failure.value
    assert error.stage is Stage.FREEZE
    # 404: a name the run needs -- its execution dataset -- was never given, so the submission
    # is what must change, not anything that ran.
    assert error.status is Status.MISSING
    assert error.mutation is False
    # Typed, so an agent parses a verdict instead of reading a traceback.
    assert error.as_dict()["failures"][0]["code"] == "execution.missing"
    assert "register the venue table as a dataset" in error.retry_precondition


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
    unlisted = definition.replace(instruments=('NOT-LISTED',))

    # The execution refusal comes first, and it is the reason the universe check is reachable
    # at all once an execution dataset is supplied.
    with pytest.raises(VqaprError, match=r"execution\.missing"):
        preflight_run(workspace, unlisted)

    workspace, definition = _setup(tmp_path / "listed", model_price_parquet)

    with pytest.raises(VqaprError, match=r"universe\.unlisted_instrument"):
        preflight_run(workspace, definition.replace(instruments=('NOT-LISTED',)))


def test_a_venue_regime_without_its_execution_price_is_refused_before_the_run(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The third state must not exist: regime declared, data absent, run proceeding anyway.

    A KRX price limit is computed from the session base price. If the registered execution dataset
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
    with Workspace.transaction(workspace) as t:
        t.register_component(component)

    with pytest.raises(VqaprError, match=r"execution\.requirement_missing") as error:
        preflight_run(workspace, definition.replace(exchange='limited'))
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
    with Workspace.transaction(workspace) as t:
        t.register_component(off)
    assert preflight_run(workspace, definition.replace(exchange='unlimited')).exchange == off


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
    with Workspace.transaction(workspace) as t:
        t.register_component(component)
    tracked = definition.replace(exchange='tracked')

    # Publishing it is fine; the run simply does not trade it.
    assert preflight_run(workspace, tracked).exchange == component

    with pytest.raises(VqaprError, match=r"universe\.untradable_listing") as e:
        preflight_run(workspace, tracked.replace(instruments=("ABC", "KOSPI200")))
    codes = [failure["code"] for failure in e.value.as_dict()["failures"]]
    assert codes == ["universe.untradable_listing"], (
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
        "from vqapr.authoring import Constraint\n"
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
    with pytest.raises(VqaprError):
        preflight_run(workspace, definition)

    with pytest.raises(ValueError, match="timezone-aware"):
        definition.replace(start=datetime(2024, 3, 5, 9))
    with pytest.raises(ValueError, match="start must not be after end"):
        definition.replace(start=definition.end, end=definition.start)
    with pytest.raises(ValueError, match="declared together"):
        definition.replace(initial_account_mode=None)
    with pytest.raises(TypeError, match="Model memory"):
        StrategyEntry("strategy", (), ("not-json",))  # type: ignore[arg-type]


def test_the_derived_agenda_fires_once_per_trading_day_at_the_declared_wall_time(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Design §3.3-3.4: the DAYS come from the execution table, the INSTANTS from `agenda`.

    Three trading days, written out of order and one of them twice; one occurrence per day, in
    the run's zone, at `at`; the ids and the fold/offset proof are `OperationAgenda.expand`'s, so
    two runs over the same days name the same occurrences.
    """
    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 7), date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 6)),
    )
    listed = definition.replace(
        agenda=RunAgenda(every="1d", at=(time(8, 30),)),
        end=datetime(2024, 3, 8, 15, 30, tzinfo=_ZONE),
    )

    agenda = derived_agenda(workspace, listed)

    assert agenda.agenda_id == listed.agenda_id == "preflight.agenda"
    assert agenda.timezone == "Asia/Seoul"
    assert [occurrence.occurrence_id for occurrence in agenda.occurrences] == [
        "preflight.agenda-2024-03-05T0830",
        "preflight.agenda-2024-03-06T0830",
        "preflight.agenda-2024-03-07T0830",
    ]
    assert [occurrence.evaluation_time for occurrence in agenda.occurrences] == [
        datetime(2024, 3, day, 8, 30, tzinfo=_ZONE) for day in (5, 6, 7)
    ]


def test_the_execution_tables_instants_collapse_to_venue_local_days(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`UC-TIME-002`, kept by date derivation (design §3.3): a denser table adds fill instants
    and never a decision day.

    The execution fixture prints twice a day, 09:30 and 15:30 KST; the agenda takes only their
    DATE in the run's zone, at `at`. The zone is the run's, not the table's: the same instants
    are the evening BEFORE in Honolulu, so a run declared there fires on those days. A table the
    run cannot find is a refusal, not a guess.
    """
    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7), date(2024, 3, 8)),
    )
    from_table = definition.replace(end=datetime(2024, 3, 9, 15, 30, tzinfo=_ZONE))

    agenda = derived_agenda(workspace, from_table)

    assert [occurrence.evaluation_time for occurrence in agenda.occurrences] == [
        datetime(2024, 3, day, 9, tzinfo=_ZONE) for day in (5, 6, 7, 8)
    ], "eight prints became four 09:00 decisions on the four venue days"

    honolulu = from_table.replace(
        timezone="Pacific/Honolulu", agenda=RunAgenda(every="1d", at=(time(7),))
    )
    assert [
        occurrence.local_instant.local_date
        for occurrence in derived_agenda(workspace, honolulu).occurrences
    ] == [date(2024, 3, day) for day in (4, 5, 6, 7)]

    absent = from_table.replace(
        execution=RunExecution(dataset="absent", fill=from_table.execution.fill)  # type: ignore[union-attr]
    )
    with pytest.raises(VqaprError):
        derived_agenda(workspace, absent)


def test_the_agenda_is_cut_on_dates_before_it_is_built_and_derived_once_per_command(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docs/issues/archive/069`: 735 occurrences were built three times per command and 15 kept.

    Two facts. The derived agenda holds only the sessions inside `[start, end]` -- the cut is on
    dates, before an occurrence and its offset proof exist -- and one `check` derives it once,
    one `preflight` once, rather than once per strategy inside two judges and again in preflight.
    """
    from vqapr.flow.declaration.judgments import judgments

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 5), date(2024, 3, 6), date(2024, 3, 7), date(2024, 3, 8)),
    )
    # The execution table has four trading days (3/5 .. 3/8); the run's period (`_setup`: 3/5
    # 09:00 to 15:30) admits one.
    two_days = definition

    agenda = derived_agenda(workspace, two_days)
    assert [occurrence.local_instant.local_date for occurrence in agenda.occurrences] == [
        date(2024, 3, 5)
    ], "the agenda is the run's period, not the table's whole span"

    calls: list[str] = []
    original = Workspace.evaluation_times

    def counted(self: Workspace, dataset_id: str) -> tuple[datetime, ...]:
        calls.append(dataset_id)
        return original(self, dataset_id)

    monkeypatch.setattr(Workspace, "evaluation_times", counted)
    failures, blocked = judgments(two_days, workspace)
    assert blocked == [] and failures == [], (failures, blocked)
    assert calls == ["execution"], f"check derived the agenda {len(calls)} times"

    calls.clear()
    frozen = preflight_run(tmp_path, two_days)
    assert calls == ["execution"], f"preflight derived the agenda {len(calls)} times"
    assert len(frozen.strategy.agenda.occurrences) == 1


def test_a_wall_time_the_clock_skips_is_refused_rather_than_guessed(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """02:30 on 2024-03-10 does not exist in New York; the run is refused, not moved an hour."""
    workspace, definition = _setup(tmp_path, model_price_parquet, days=(date(2024, 3, 10),))
    skipped = definition.replace(
        timezone="America/New_York",
        agenda=RunAgenda(every="1d", at=(time(2, 30),)),
        start=datetime(2024, 3, 9, tzinfo=_ZONE),
        end=datetime(2024, 3, 11, tzinfo=_ZONE),
    )

    with pytest.raises(ValueError, match="does not exist"):
        derived_agenda(workspace, skipped)
    with pytest.raises(ValueError, match="does not exist"):
        preflight_run(workspace, skipped)


def test_a_constraint_that_does_not_answer_to_its_id_is_refused_before_the_run(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`vqapr check` runs this phase, so refusing here is refusing before a run is spent.

    `register` now refuses the mismatch outright, so this is the case that door does not cover: a
    workspace populated directly, which is what every fixture here does and what a caller using the
    Python surface does. Preflight is the last gate before `StrategyEventLoop.__init__`, where the
    same disagreement used to surface as `stage: "unhandled"` with an empty `failures` list.

    The check is on the loaded object, so a `constraint_id` assembled at runtime is caught too.
    """
    root = tmp_path / "mismatch"
    workspace, definition = _setup(root, model_price_parquet)
    path = root / "drifted.py"
    path.write_text(
        "from vqapr.authoring import Constraint\n"
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
    with Workspace.transaction(workspace) as t:
        t.register_component(drifted)

    with pytest.raises(VqaprError) as caught:
        preflight_run(workspace, definition)

    error = caught.value
    assert error.stage is Stage.LOAD
    assert [failure.code for failure in error.failures] == [
        "component.constraint_id_mismatch"
    ]
    assert "'limit'" in error.failures[0].observed
    assert "'position-cap'" in error.failures[0].observed
