from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.component.exchange.academic import AcademicExchange
from vqapr.component.fingerprint import fingerprint_component
from vqapr.component.loading import load_exchange
from vqapr.component.reference import ComponentRef
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.execution_table import ExecutionTable, ExecutionTableSpec
from vqapr.data.source import SourceSpec
from vqapr.data.verification import verify_source
from vqapr.domain.account import AccountMode, AccountSnapshot
from vqapr.domain.errors import Stage, Status, VqaprError
from vqapr.domain.fill import FillRule
from vqapr.domain.memory import prepare_model_state
from vqapr.domain.wiring import Role
from vqapr.flow.declaration.preflight import derived_agenda, preflight_run
from vqapr.project.run import RunAgenda, RunDefinition, RunExecution, RunFill, StrategyEntry
from vqapr.project.store import Workspace
from vqapr.public import register_dataset, register_instruments

_ZONE = ZoneInfo("Asia/Seoul")
SESSION = date(2024, 3, 5)
"""The one session the execution fixture prices: 09:30 and 15:30 on this day."""


def _component(root: Path, identifier: str, kind: Role) -> ComponentRef:
    path = root / f"{identifier}.py"
    source = (
        "from vqapr.authoring import Hold\n"
        "from vqapr.authoring import StrategyModel\n"
        f"class {identifier.title().replace('-', '')}(StrategyModel):\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def decide(self, context):\n"
        "        return Hold(reason='fixture')\n"
        if kind is Role.STRATEGY_MODEL
        else "from vqapr.authoring import Compliance\n"
        f"class {identifier.title().replace('-', '')}(Compliance):\n"
        "    @property\n"
        "    def compliance_id(self):\n"
        # The id the component is REGISTERED under, not a fixed string. A rule must answer to
        # its own component id -- `strategy_loop` has always required it and `load_compliance`
        # refuses the mismatch -- so a helper that hardcoded `'fixture'` built components that
        # could never have run.
        f"        return {identifier!r}\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def observe(self, call):\n"
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
    strategy_component = _component(root, "strategy", Role.STRATEGY_MODEL)
    rule_component = _component(root, "limit", Role.COMPLIANCE)
    for component in (strategy_component, rule_component):
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
            days=days,
        )
        if with_execution
        else None
    )
    return workspace, RunDefinition(
        run_id="preflight",
        strategy=StrategyEntry("strategy", {"cadence": [1]}),
        compliance=("limit",),
        timezone="Asia/Seoul",
        agenda=RunAgenda(every="1d", at=(at,)),
        exchange=None if exchange_component is None else str(exchange_component.component_id),
        execution=(
            RunExecution(
                dataset="execution",
                trade_price="close",
                fill=RunFill(at=time(15, 30)),
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
    days: tuple[date, ...] = (SESSION,),
) -> ComponentRef:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{identifier}.py"
    path.write_text(
        "from decimal import Decimal\n"
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
        "class Exchange(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({'ABC': TradeRule('ABC', "
        f"{step}, {minimum}, {fractional}, {access})}})\n",
        encoding="utf-8",
    )
    component = ComponentRef.of(
        identifier,
        Role.EXCHANGE,
        path,
        "Exchange",
        fingerprint=fingerprint_component(
            path, kind=Role.EXCHANGE, object_name="Exchange"
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
        diagnosis, _, measured = verify_source(registration, source)
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
    assert layer.compliance.rules[0].component_id == "limit"
    assert frozen.instruments == definition.instruments
    assert layer.requirements == ()
    assert layer.compliance_requirements == ()
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
    exchange = _component(tmp_path, "exchange", Role.EXCHANGE)
    execution = ExecutionTable.of(
        "execution",
        ExecutionTableSpec(
            SourceSpec.of("execution-source", tmp_path / "execution.parquet"),
            "trade_at",
            "instrument",
            "is_tradable",
            {"close": "close"},
        ),
        FillRule("close", "Asia/Seoul", at=time(15, 30)),
    )
    frozen_execution = replace(frozen, exchange=exchange, execution=execution)
    changed_fill = replace(
        frozen_execution,
        execution=ExecutionTable(
            execution.dataset_id,
            execution.table,
            FillRule("close", "Asia/Seoul", at=time(15, 30), within="1d"),
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
    workspace, definition = _setup(tmp_path, model_price_parquet, at=time(15, 30))

    with pytest.raises(VqaprError) as caught:
        preflight_run(workspace, definition)

    error = caught.value
    assert error.stage is Stage.FREEZE
    assert error.status is Status.PRECONDITION
    assert error.mutation is False
    failure = error.failures[0]
    assert failure.code == "execution.target_outside_horizon"
    assert failure.example_total == 1
    assert failure.examples == ("preflight.agenda-2024-03-05T1530",)
    assert "fill=the first execution instant after the decision" in (failure.observed or "")
    assert "end=2024-03-05T15:30:00+09:00" in (failure.observed or "")
    assert "extend the run end" in failure.fix


def test_preflight_requires_academic_exchange_and_initial_account_compatibility(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    exchange = _execution_exchange(workspace, tmp_path)
    compatible = definition.replace(
                     exchange='exchange',
                     execution=RunExecution(
                         dataset='execution',
                         trade_price='close',
                         fill=RunFill(at=time(15, 30)),
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
        Role.EXCHANGE,
        duck_path,
        "Duck",
        fingerprint=fingerprint_component(
            duck_path, kind=Role.EXCHANGE, object_name="Duck"
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
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
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
        Role.EXCHANGE,
        no_sell_path,
        "Exchange",
        fingerprint=fingerprint_component(
            no_sell_path, kind=Role.EXCHANGE, object_name="Exchange"
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
    definition = definition.replace(strategy=StrategyEntry('strategy', memory))
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
        "from vqapr.public import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=True)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    component = ComponentRef.of(
        "limited",
        Role.EXCHANGE,
        path,
        "Exchange",
        fingerprint=fingerprint_component(
            path, kind=Role.EXCHANGE, object_name="Exchange"
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
        "from vqapr.public import KrxExchange, krx_rules\n"
        "class Exchange(KrxExchange):\n"
        "    def __init__(self):\n"
        "        listings, instruments = krx_rules({'ABC': 'stock'}, price_limits=False)\n"
        "        super().__init__(listings)\n",
        encoding="utf-8",
    )
    off = ComponentRef.of(
        "unlimited",
        Role.EXCHANGE,
        off_path,
        "Exchange",
        fingerprint=fingerprint_component(
            off_path, kind=Role.EXCHANGE, object_name="Exchange"
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
        "from vqapr.public import AcademicExchange, TradeRule\n"
        "from vqapr.public import ListingAccess\n"
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
        Role.EXCHANGE,
        path,
        "Exchange",
        fingerprint=fingerprint_component(
            path, kind=Role.EXCHANGE, object_name="Exchange"
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
    # missing-requirement contract is proved by a consumer that still has one: a Compliance rule.
    workspace, definition = _setup(tmp_path / "rule-requirement", model_price_parquet)
    rule_path = tmp_path / "rule-requirement" / "limit.py"
    rule_path.write_text(
        "from vqapr.authoring import Compliance\n"
        "from vqapr.data.lookback import RowsLookback\n"
        "from vqapr.public import DataRequirement\n"
        "class Limit(Compliance):\n"
        "    @property\n"
        "    def compliance_id(self):\n"
        "        return 'limit'\n"
        "    def requirements(self):\n"
        "        return (DataRequirement.of('absent', 'close', "
        "lookback=RowsLookback(1)),)\n"
        "    def observe(self, call):\n"
        "        return None\n",
        encoding="utf-8",
    )
    rule = ComponentRef.of(
        "limit",
        Role.COMPLIANCE,
        rule_path,
        "Limit",
        fingerprint=fingerprint_component(
            rule_path, kind=Role.COMPLIANCE, object_name="Limit"
        ),
    )
    workspace._components[rule.component_id] = rule
    with pytest.raises(VqaprError):
        preflight_run(workspace, definition)

    with pytest.raises(ValueError, match="timezone-aware"):
        definition.replace(start=datetime(2024, 3, 5, 9))
    with pytest.raises(ValueError, match="start must not be after end"):
        definition.replace(start=definition.end, end=definition.start)
    with pytest.raises(ValueError, match="declared together"):
        definition.replace(initial_account_mode=None)
    with pytest.raises(TypeError, match="Model memory"):
        StrategyEntry("strategy", ("not-json",))  # type: ignore[arg-type]


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
        execution=RunExecution(dataset="absent", trade_price="close")
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

    from vqapr.project import store as store_module

    # The READ is what is counted, not the asking: since record `238` the workspace hands the
    # instants it read once to every judge and freeze that asks (the horizon asks too).
    calls: list[str] = []
    original = store_module.scan.distinct_values

    def counted(spec, field, **kwargs):
        calls.append(field)
        return original(spec, field, **kwargs)

    monkeypatch.setattr(store_module.scan, "distinct_values", counted)
    # A fresh snapshot: the one above already holds the instants `derived_agenda` read.
    failures, blocked = judgments(two_days, Workspace.open(tmp_path))
    assert blocked == [] and failures == [], (failures, blocked)
    assert calls == ["trade_at"], f"check read the sessions {len(calls)} times"

    calls.clear()
    frozen = preflight_run(tmp_path, two_days)
    assert calls == ["trade_at"], f"preflight read the sessions {len(calls)} times"
    assert len(frozen.strategy.agenda.occurrences) == 1


def test_an_on_last_agenda_reads_past_end_to_know_its_last_month_is_over(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `253`. Whether 29 March is March's last session is the next session's to say, and
    that session lies past `end`: the agenda reads on, fires on nothing it read past `end`, and
    shares its one read of the table with the horizon as before (record `238`)."""
    from vqapr.flow.declaration.preflight import bound_execution_horizon
    from vqapr.project import store as store_module

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(
            date(2024, 3, 27),
            date(2024, 3, 28),
            date(2024, 3, 29),
            date(2024, 4, 1),
            date(2024, 4, 2),
        ),
    )
    month_end = definition.replace(
        agenda=RunAgenda(every="1M", at=(time(15, 20),), on="last"),
        start=datetime(2024, 3, 1, tzinfo=_ZONE),
        end=datetime(2024, 3, 29, 15, 30, tzinfo=_ZONE),
    )

    assert [o.evaluation_time for o in derived_agenda(workspace, month_end).occurrences] == [
        datetime(2024, 3, 29, 15, 20, tzinfo=_ZONE)
    ], "April's sessions say March is over, and fire nothing themselves"
    before = month_end.replace(end=datetime(2024, 3, 28, 15, 30, tzinfo=_ZONE))
    assert derived_agenda(workspace, before).occurrences == (), (
        "March's last session is after this `end`, so the run holds no month-end"
    )

    calls: list[str] = []
    original = store_module.scan.distinct_values

    def counted(spec, field, **kwargs):
        calls.append(field)
        return original(spec, field, **kwargs)

    monkeypatch.setattr(store_module.scan, "distinct_values", counted)
    fresh = Workspace.open(tmp_path)
    derived_agenda(fresh, month_end)
    bound_execution_horizon(fresh, month_end)
    assert calls == ["trade_at"], f"the agenda and the horizon read the sessions {len(calls)} times"


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


def test_a_rule_that_does_not_answer_to_its_id_is_refused_before_the_run(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`vqapr check` runs this phase, so refusing here is refusing before a run is spent.

    `register` now refuses the mismatch outright, so this is the case that door does not cover: a
    workspace populated directly, which is what every fixture here does and what a caller using the
    Python surface does. Preflight is the last gate before `strategy_loop`, where the
    same disagreement used to surface as `stage: "unhandled"` with an empty `failures` list.

    The check is on the loaded object, so a `compliance_id` assembled at runtime is caught too.
    """
    root = tmp_path / "mismatch"
    workspace, definition = _setup(root, model_price_parquet)
    path = root / "drifted.py"
    path.write_text(
        "from vqapr.authoring import Compliance\n"
        "class Drifted(Compliance):\n"
        "    @property\n"
        "    def compliance_id(self):\n"
        "        return '-'.join(['position', 'cap'])\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def observe(self, call):\n"
        "        return None\n",
        encoding="utf-8",
    )
    drifted = ComponentRef.of(
        "limit",
        Role.COMPLIANCE,
        path,
        "Drifted",
        fingerprint=fingerprint_component(
            path, kind=Role.COMPLIANCE, object_name="Drifted"
        ),
    )
    with Workspace.transaction(workspace) as t:
        t.register_component(drifted)

    with pytest.raises(VqaprError) as caught:
        preflight_run(workspace, definition)

    error = caught.value
    assert error.stage is Stage.LOAD
    assert [failure.code for failure in error.failures] == [
        "component.compliance_id_mismatch"
    ]
    assert "'limit'" in error.failures[0].observed
    assert "'position-cap'" in error.failures[0].observed


def test_the_execution_horizon_is_cut_from_the_sessions_already_read_not_scanned_again(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `238`. One `vqapr run` read the execution table's instant column five times: the
    judgments and preflight each derived the agenda from its distinct instants, and the
    ordering judgment, preflight's target proof and the run each scanned the candidate instants
    for the horizon (`experiments/exp_238`, `08_run_factor`: `distinct_values` x2,
    `candidate_instants` x3). The horizon is the same column cut to `(start, end]`, so the
    judgments and the freeze now take it from the instants the workspace read once."""
    from vqapr.data import scan
    from vqapr.flow.declaration.judgments import judgments
    from vqapr.flow.declaration.preflight import bound_execution_horizon, bound_execution_table

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)),
    )
    assert definition.start is not None and definition.end is not None
    table = bound_execution_table(workspace, definition)
    scanned = table.build_horizon(start_time=definition.start, end_time=definition.end)
    cut = bound_execution_horizon(workspace, definition)
    assert cut.instants == scanned.instants, "the cut must be what the scan answered"
    # The run is 3/5 09:00 .. 15:30: the day's two prints after 09:00 are 09:30 and 15:30.
    assert [moment.astimezone(_ZONE).strftime("%m-%d %H:%M") for moment in cut.instants] == [
        "03-05 09:30",
        "03-05 15:30",
    ]

    candidates: list[object] = []
    instants: list[str] = []
    original_candidates = scan.candidate_instants
    original_instants = Workspace.evaluation_times

    def counting_candidates(*args, **kwargs):
        candidates.append(args)
        return original_candidates(*args, **kwargs)

    def counting_instants(self: Workspace, dataset_id: str, **kwargs):
        instants.append(dataset_id)
        return original_instants(self, dataset_id, **kwargs)

    monkeypatch.setattr(scan, "candidate_instants", counting_candidates)
    monkeypatch.setattr(Workspace, "evaluation_times", counting_instants)

    fresh = Workspace.open(tmp_path)
    failures, blocked = judgments(definition, fresh)
    assert failures == [] and blocked == [], (failures, blocked)
    frozen = preflight_run(fresh, definition)
    assert len(frozen.strategy.agenda.occurrences) == 1
    assert candidates == [], f"the horizon was scanned {len(candidates)} times"
    # Asked four times of one workspace object -- twice for the agenda, twice for the horizon
    # -- and the column was read once: the memo is the workspace's, not the callers'.
    assert instants == ["execution"] * 4


def test_one_door_reads_each_fact_of_a_run_once(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `241`: the judgments and the freeze read one `RunFacts`.

    `experiments/exp_238` counted, in one `vqapr run`, the agenda derived twice, the execution
    table bound twice, the strategy imported three times before the run's own instance and the
    venue twice. Through `verify_run` each is read once: the strategy twice in all, because its
    initial state is still proved on a second fresh instance (`docs/issues/archive/076`).
    """
    from vqapr.component import loading
    from vqapr.flow.declaration import preflight as preflight_module
    from vqapr.flow.declaration.verify import verify_run

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)),
    )
    signed = definition.replace(initial_account_mode=AccountMode.SIGNED)

    counts: dict[str, int] = {}

    def counting(name, original):
        def wrapped(*args, **kwargs):
            counts[name] = counts.get(name, 0) + 1
            return original(*args, **kwargs)

        return wrapped

    original_load = loading._load

    def counted_load(ref, *, kind, project_root=None):
        counts[f"load:{kind.value}"] = counts.get(f"load:{kind.value}", 0) + 1
        return original_load(ref, kind=kind, project_root=project_root)

    monkeypatch.setattr(loading, "_load", counted_load)
    for name in ("derived_agenda", "bound_execution_table", "bound_execution_horizon"):
        monkeypatch.setattr(
            preflight_module, name, counting(name, getattr(preflight_module, name))
        )
    from vqapr.project import store as store_module

    monkeypatch.setattr(
        store_module.scan, "distinct_values", counting("scan", store_module.scan.distinct_values)
    )

    verdict = verify_run(Workspace.open(tmp_path), signed)
    assert verdict.failures == () and verdict.blocked == () and verdict.frozen is not None, (
        verdict.failures,
        verdict.blocked,
        verdict.refusal,
    )
    assert counts == {
        "derived_agenda": 1,
        "bound_execution_table": 1,
        "bound_execution_horizon": 1,
        "scan": 1,
        "load:strategy_model": 2,
        "load:exchange": 1,
        "load:compliance": 1,
    }, counts


def test_the_run_takes_what_the_verification_loaded_and_read(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `242`: a `FrozenRun` is a record value and carries no live object, so the run used
    to import the strategy, the venue and every rule again and scan the execution horizon again
    on its first accepted intent. The verdict now carries `RunResources` -- the instances the
    verification loaded and the horizon it cut -- and `run` takes them: no import, no scan."""
    from vqapr.component import loading
    from vqapr.data import scan
    from vqapr.flow.declaration.preflight import bound_execution_horizon
    from vqapr.flow.declaration.verify import verify_run
    from vqapr.public import run as execute_run

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)),
    )
    verdict = verify_run(workspace, definition)
    frozen, resources = verdict.require_ready()
    assert resources.run_identity == frozen.identity
    assert resources.strategy is not None and resources.exchange is not None
    assert len(resources.rules) == 1
    assert resources.horizon is not None
    assert resources.horizon.instants == bound_execution_horizon(workspace, definition).instants

    # The fixture's rule is a stub whose `observe` returns nothing, so the run below is the
    # same declaration without it; what is counted is the run's own loading and scanning.
    plain = definition.replace(compliance=())
    frozen, resources = verify_run(Workspace.open(tmp_path), plain).require_ready()

    loads: list[str] = []
    original_load = loading._load

    def counted_load(ref, *, kind, project_root=None):
        loads.append(kind.value)
        return original_load(ref, kind=kind, project_root=project_root)

    scans: list[object] = []
    original_scan = scan.candidate_instants

    def counted_scan(*args, **kwargs):
        scans.append(args)
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(loading, "_load", counted_load)
    monkeypatch.setattr(scan, "candidate_instants", counted_scan)

    outcome = execute_run(tmp_path, frozen, workspace=workspace, resources=resources)
    assert outcome.ok, outcome.errors
    assert loads == [], f"the run imported again: {loads}"
    assert scans == [], "the run scanned the horizon again"

    # Resources frozen for another run are refused rather than trusted.
    other = plain.replace(run_id="other")
    stranger = verify_run(Workspace.open(tmp_path), other).require_ready()[0]
    with pytest.raises(ValueError, match="another frozen run"):
        execute_run(tmp_path, stranger, workspace=workspace, resources=resources)


def test_a_run_frames_what_each_callback_read_once(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `246`, the intent path: a callback that returns a `Rebalance` used to derive its
    source refs for the intent's stamp and again for the evidence (`experiments/exp_246`,
    `08_run_factor`: `_actual_source_refs` x2 per callback), and asked `inputs()` on every
    decision. One framing per callback, one asking per run, and the record is the same."""
    from vqapr.flow.declaration.verify import verify_run
    from vqapr.flow.run.callback import CallbackHandler
    from vqapr.public import run as execute_run

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)),
    )
    plain = definition.replace(compliance=())
    frozen, resources = verify_run(workspace, plain).require_ready()
    assert resources.strategy is not None

    framed: list[str] = []
    original_refs = CallbackHandler._actual_source_refs

    def counting_refs(self, window):  # type: ignore[no-untyped-def]
        framed.append("refs")
        return original_refs(self, window)

    asked: list[str] = []
    original_inputs = type(resources.strategy).inputs

    def counting_inputs(self):  # type: ignore[no-untyped-def]
        asked.append("inputs")
        return original_inputs(self)

    monkeypatch.setattr(CallbackHandler, "_actual_source_refs", counting_refs)
    monkeypatch.setattr(type(resources.strategy), "inputs", counting_inputs)

    outcome = execute_run(tmp_path, frozen, workspace=workspace, resources=resources)
    assert outcome.ok, outcome.errors
    from vqapr.authoring import Hold

    (simulation,) = outcome.results.values()
    assert any(not isinstance(trace.result, Hold) for trace in simulation.occurrences), (
        "the run must take the intent path"
    )
    callbacks = len(frozen.strategy.agenda.occurrences)
    assert callbacks == 1
    assert framed == ["refs"] * callbacks, f"{len(framed)} framings for {callbacks} callbacks"
    assert asked == ["inputs"], f"inputs() asked {len(asked)} times for one run"


def test_the_sessions_are_read_for_the_run_period_not_the_table(
    tmp_path: Path, model_price_parquet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `247`. Record `238` made the instant column one read per command, and that read was
    still the table's whole column: a ten-session run over a three-year table read 735 instants
    to keep ten (`experiments/exp_246`, `08_run_factor` #752). The workspace now reads the
    instants inside the run's period widened by a day each side -- enough for every venue-local
    date the agenda keeps and every instant the horizon keeps -- and both cuts are unchanged."""
    from datetime import timedelta

    from vqapr.flow.declaration.judgments import judgments
    from vqapr.flow.declaration.preflight import bound_execution_horizon, bound_execution_table
    from vqapr.project import store as store_module

    workspace, definition = _setup(
        tmp_path,
        model_price_parquet,
        days=(date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)),
    )
    assert definition.start is not None and definition.end is not None
    table = bound_execution_table(workspace, definition)
    scanned = table.build_horizon(start_time=definition.start, end_time=definition.end)

    bounds: list[tuple[object, object]] = []
    original = store_module.scan.distinct_values

    def counted(spec, field, **kwargs):
        bounds.append((kwargs.get("not_before"), kwargs.get("not_after")))
        return original(spec, field, **kwargs)

    monkeypatch.setattr(store_module.scan, "distinct_values", counted)
    fresh = Workspace.open(tmp_path)
    failures, blocked = judgments(definition, fresh)
    assert failures == [] and blocked == [], (failures, blocked)
    frozen = preflight_run(fresh, definition)
    assert bounds == [
        (definition.start - timedelta(days=1), definition.end + timedelta(days=1))
    ], f"the sessions were read {len(bounds)} times, bounded {bounds}"
    assert [
        occurrence.local_instant.local_date for occurrence in frozen.strategy.agenda.occurrences
    ] == [date(2024, 3, 5)], "the agenda is the run's period, as before"
    assert bound_execution_horizon(fresh, definition).instants == scanned.instants, (
        "the horizon is what the unbounded scan answered"
    )
