from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.findings import ConstraintFinding
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.references import ModelStateRef
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import ExactExecutionTarget, FillConvention, FillSelector
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    exact_execution_snapshot,
    validate_execution_input,
)
from vqapr.exchange.venue import AcademicExchange, ListingRule, Side
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, FrozenAgenda, FrozenRun, StrategyConfig
from vqapr.flow.run_state import LifecycleKind, RunStateRepository
from vqapr.flow.simulation import AcceptedIntent, SimulationFlow
from vqapr.models.strategy_model import NoDecision, StrategyModel
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    IntentSourceRef,
    PortfolioTarget,
    validate_economic_intent,
)
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")


_BUDGET = Budget(
    PortfolioDirection.LONG_ONLY, Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")
)
_SOURCE = IntentSourceRef("strategy-source", "0" * 64)


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset access: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source access: {raw_source_id}")


class _Strategy(StrategyModel):
    def __init__(self, results: tuple[NoDecision | EconomicPortfolioIntent, ...]) -> None:
        self.results = iter(results)
        self.seen: list[tuple[str, datetime, int]] = []

    def on_occurrence(self, context: object) -> NoDecision | EconomicPortfolioIntent:
        occurrence = context.occurrence
        assert not hasattr(context, "future_occurrences")
        assert not hasattr(context, "execution_table")
        self.seen.append(
            (occurrence.occurrence_id, occurrence.evaluation_time, context.account.version)
        )
        self.memory = {"calls": len(self.seen)}
        return next(self.results)


class _PayloadFaultStrategy(_Strategy):
    def __init__(self) -> None:
        super().__init__((NoDecision("unreachable"),))
        self._save_count = 0

    def save_payload(self, target: object) -> None:
        self._save_count += 1
        if self._save_count == 1:
            raise RuntimeError("payload fault")


def _component(identifier: str, kind: ComponentKind) -> ComponentRef:
    return ComponentRef.of(
        identifier, kind, Path(f"{identifier}.py"), "Component", fingerprint="0" * 64
    )


def _occurrence(identifier: str, role: OperationRole, at: datetime) -> OperationOccurrence:
    return OperationOccurrence(
        identifier,
        role,
        LocalInstantDeclaration(
            at.date(), at.timetz().replace(tzinfo=None), "Asia/Seoul", 0, "+09:00"
        ),
    )


def _agenda(identifier: str, role: OperationRole, *times: datetime) -> FrozenAgenda:
    return FrozenAgenda(
        identifier,
        role,
        tuple(_occurrence(f"{identifier}-{i}", role, at) for i, at in enumerate(times)),
    )


def _requirement() -> DataRequirement:
    return DataRequirement.of("valuation", "prices", fields=("close",), lookback=RowsLookback(1))


class _Constraint(Constraint):
    @property
    def constraint_id(self) -> str:
        return "risk"

    def requirements(self) -> tuple[DataRequirement, ...]:
        return ()

    def project(self, window: ModelWindow, instruments: tuple[str, ...]) -> ConstraintBounds:
        return ConstraintBounds(
            {instrument: Decimal("0") for instrument in instruments},
            {instrument: Decimal("1") for instrument in instruments},
        )

    def validate_intended(
        self, intent: EconomicPortfolioIntent, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        return ConstraintFinding(
            self.constraint_id, True, Decimal("0"), Decimal("1"), Decimal("0"), {}
        )

    def evaluate(self, account: AccountSnapshot, marks: object) -> ConstraintFinding:
        return ConstraintFinding(
            self.constraint_id, True, Decimal("0"), Decimal("1"), Decimal("0"), {}
        )


_ACCOUNT = AccountSnapshot(0, Decimal("100"), {})


def _state(account: AccountSnapshot = _ACCOUNT) -> RunStateRepository:
    return RunStateRepository(initial_account=AccountState(account))


def _exchange() -> AcademicExchange:
    return AcademicExchange(
        {
            instrument: ListingRule(
                instrument,
                Decimal("0.001"),
                Decimal("0.001"),
                True,
                frozenset({Side.BUY, Side.SELL}),
            )
            for instrument in ("A", "B")
        }
    )


def _frozen(
    callbacks: tuple[datetime, ...],
    *,
    valuations: tuple[datetime, ...] = (),
    monitoring: tuple[datetime, ...] = (),
    end: datetime | None = None,
    execution: ExecutionInputRegistration | None = None,
    account: AccountSnapshot = _ACCOUNT,
    datasets: tuple[DatasetRegistration, ...] = (),
    sources: tuple[SourceSpec, ...] = (),
) -> FrozenRun:
    strategy = StrategyConfig(
        _component("strategy", ComponentKind.STRATEGY_MODEL),
        "strategy",
        OperationRole.STRATEGY_CALLBACK,
    )
    valuation = ValuationConfig("valuation", OperationRole.VALUATION, _requirement())
    monitor = MonitoringPolicy("monitoring", OperationRole.MONITORING) if monitoring else None
    bounds = (
        {"start": callbacks[0] if callbacks else (valuations + monitoring)[0], "end": end}
        if end is not None
        else {}
    )
    return FrozenRun(
        strategy,
        valuation,
        ConstraintSet((_component("risk", ComponentKind.CONSTRAINT),)),
        _agenda("strategy", OperationRole.STRATEGY_CALLBACK, *callbacks),
        _agenda("valuation", OperationRole.VALUATION, *valuations),
        monitor,
        _agenda("monitoring", OperationRole.MONITORING, *monitoring) if monitor else None,
        exchange=_component("academic", ComponentKind.EXCHANGE) if execution else None,
        execution_input=execution,
        initial_account_snapshot=account,
        initial_account_mode=AccountMode.LONG_ONLY,
        datasets=datasets,
        sources=sources,
        **bounds,
    )


def _flow(frozen: FrozenRun, strategy: StrategyModel, state: RunStateRepository) -> SimulationFlow:
    return SimulationFlow(
        frozen,
        strategy,
        state,
        window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(_requirement(),),
        ),
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_exchange(),
        constraints=(_Constraint(),),
        marks_for_occurrence=lambda _, __, account: {
            instrument: Decimal("10") for instrument in account.positions
        },
    )


def _parquet(path: Path, rows: str) -> Path:
    connection = duckdb.connect()
    try:
        connection.execute(f"COPY ({rows}) TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return path


def _execution(
    path: Path, selector: FillSelector = FillSelector.SAME_DAY
) -> ExecutionInputRegistration:
    return ExecutionInputRegistration.of(
        "execution",
        ExecutionTableSpec(
            SourceSpec.of("execution-source", path),
            "trade_at",
            "instrument",
            "is_tradable",
            {"close": "close"},
        ),
        FillConvention(selector, time(15, 30), "Asia/Seoul", "close"),
    )


@pytest.mark.uc("UC-TIME-002")
def test_daily_observations_and_intraday_callbacks_are_agenda_owned_not_row_owned() -> None:
    nine = datetime(2024, 3, 5, 9, tzinfo=KST)
    ten = datetime(2024, 3, 5, 10, tzinfo=KST)
    strategy = _Strategy((NoDecision("observe"), NoDecision("observe")))

    result = _flow(_frozen((nine, ten), end=ten), strategy, _state()).run()

    assert [trace.occurrence.occurrence_id for trace in result.occurrences] == [
        "strategy-0",
        "strategy-1",
    ]
    assert [seen[1] for seen in strategy.seen] == [nine, ten]


@pytest.mark.uc("UC-TIME-002")
def test_minutely_observations_do_not_create_daily_callback_occurrences(tmp_path: Path) -> None:
    source = _parquet(
        tmp_path / "minute.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 03:59:00+00', 'A', 1.0),
          (TIMESTAMPTZ '2024-03-05 04:00:00+00', 'A', 2.0),
          (TIMESTAMPTZ '2024-03-05 04:01:00+00', 'A', 3.0)
        ) AS t(available_at, instrument, close)
    """,
    )
    workspace = Workspace.create(tmp_path / "workspace")
    workspace.register_dataset(
        DatasetRegistration.of(
            "prices",
            "source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("source", source),
    )
    requirement = DataRequirement.of(
        "strategy", "prices", fields=("close",), lookback=RowsLookback(3)
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 5, 4, tzinfo=UTC),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
    )

    assert [row["close"] for row in window.observations(requirement).rows] == [1.0, 2.0]
    assert (
        len(
            _flow(
                _frozen(
                    (datetime(2024, 3, 5, 13, tzinfo=KST),),
                    end=datetime(2024, 3, 5, 13, tzinfo=KST),
                ),
                _Strategy((NoDecision("daily"),)),
                _state(),
            )
            .run()
            .occurrences
        )
        == 1
    )


@pytest.mark.uc("UC-TIME-002")
def test_pit_includes_equality_excludes_one_microsecond_later_and_callback_needs_no_matching_row(
    tmp_path: Path,
) -> None:
    source = _parquet(
        tmp_path / "pit.parquet",
        """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 04:00:00+09', 'A', 1.0),
          (TIMESTAMPTZ '2024-03-05 04:00:00.000001+09', 'A', 2.0)
        ) AS t(available_at, instrument, close)
    """,
    )
    workspace = Workspace.create(tmp_path / "workspace")
    workspace.register_dataset(
        DatasetRegistration.of(
            "prices",
            "source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("source", source),
    )
    requirement = DataRequirement.of(
        "strategy", "prices", fields=("close",), lookback=RowsLookback(2)
    )
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 5, 4, tzinfo=KST),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
    )

    assert [row["close"] for row in window.observations(requirement).rows] == [1.0]
    assert (
        _flow(
            _frozen(
                (datetime(2024, 3, 5, 5, tzinfo=KST),),
                end=datetime(2024, 3, 5, 5, tzinfo=KST),
            ),
            _Strategy((NoDecision("no row required"),)),
            _state(),
        )
        .run()
        .final_state.current_model_state_ref
        is not None
    )


@pytest.mark.uc("UC-TIME-002")
def test_callback_free_valuation_and_monitoring_are_independent_agendas() -> None:
    noon = datetime(2024, 3, 5, 12, tzinfo=KST)
    frozen = _frozen(
        (),
        valuations=(noon,),
        monitoring=(noon.replace(minute=5),),
        end=noon.replace(minute=5),
    )

    result = _flow(frozen, _Strategy(()), _state()).run()

    assert [trace.occurrence.role for trace in result.occurrences] == [
        OperationRole.VALUATION,
        OperationRole.MONITORING,
    ]


@pytest.mark.uc("UC-TIME-002")
def test_strategy_payload_has_no_timing_authority_and_flow_stamps_current_occurrence() -> None:
    payload = EconomicPortfolioIntent(
        UUID(int=1), "strategy", (), Decimal("1"), _BUDGET, (_SOURCE,), 0, None
    )
    at = datetime(2024, 3, 5, 4, tzinfo=KST)
    target = ExactExecutionTarget(
        UUID(int=2),
        "execution",
        datetime(2024, 3, 5, 15, 30, tzinfo=KST),
        FillSelector.SAME_DAY,
        "close",
    )
    assert validate_economic_intent(payload) is payload
    accepted = AcceptedIntent(
        payload, _occurrence("current", OperationRole.STRATEGY_CALLBACK, at), at, target
    )
    assert accepted.decision_time == at


@pytest.mark.uc("UC-TIME-002")
def test_callback_provenance_must_match_frozen_strategy_prior_state_and_actual_source(
    tmp_path: Path,
) -> None:
    source_path = _parquet(
        tmp_path / "strategy.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 09:00:00+09' AS available_at,
               'A' AS instrument, 10.0 AS close
        """,
    )
    workspace = Workspace.create(tmp_path / "workspace")
    registration = DatasetRegistration.of(
        "prices",
        "source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    )
    source = SourceSpec.of("source", source_path)
    workspace.register_dataset(registration, source)
    requirement = DataRequirement.of(
        "strategy", "prices", fields=("close",), lookback=RowsLookback(1)
    )
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    execution = _execution(
        _parquet(
            tmp_path / "execution.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()

    class ReadingStrategy(StrategyModel):
        def __init__(self, intent: EconomicPortfolioIntent) -> None:
            self.intent = intent

        def on_occurrence(self, context: object) -> EconomicPortfolioIntent:
            context.window.observations(requirement)
            return self.intent

    def intent(
        *,
        strategy_id: str = "strategy",
        model_state_ref: ModelStateRef | None = None,
        source_refs: tuple[IntentSourceRef, ...] = (IntentSourceRef("source", digest),),
    ) -> EconomicPortfolioIntent:
        return EconomicPortfolioIntent(
            UUID(int=10),
            strategy_id,
            (),
            Decimal("1"),
            _BUDGET,
            source_refs,
            0,
            model_state_ref,
        )

    frozen = _frozen(
        (callback,),
        valuations=(target,),
        end=target,
        execution=execution,
        datasets=(registration,),
        sources=(source,),
    )

    def flow(candidate: EconomicPortfolioIntent, state: RunStateRepository) -> SimulationFlow:
        return SimulationFlow(
            frozen,
            ReadingStrategy(candidate),
            state,
            window_for_occurrence=lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=("A",),
                store=DuckDbObservationStore(workspace),
                allowed_requirements=(requirement,),
            ),
            account=Account(mode=AccountMode.LONG_ONLY),
            exchange=_exchange(),
            constraints=(_Constraint(),),
            marks_for_occurrence=lambda _, __, account: {
                instrument: Decimal("10") for instrument in account.positions
            },
        )

    assert flow(intent(), _state()).run().final_state.pending_accepted_intent is None

    for invalid in (
        intent(strategy_id="other"),
        intent(model_state_ref=ModelStateRef("1" * 64)),
        intent(source_refs=(IntentSourceRef("source", "0" * 64),)),
    ):
        state = _state()
        with pytest.raises(ValueError):
            flow(invalid, state).run()
        assert state.current.account == AccountState(_ACCOUNT)
        assert state.current.pending_accepted_intent is None
        assert state.current.lifecycle_trace == ()


@pytest.mark.uc("UC-TIME-002")
def test_fill_target_is_strictly_later_exact_and_uses_venue_local_date(tmp_path: Path) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "execution.parquet",
            """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 04:00:00+09', 'A', true, 1.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 2.0),
          (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 3.0)
        ) AS t(trade_at, instrument, is_tradable, close)
    """,
        )
    )
    selected = registration.fill.select_target(
        registration,
        decision_time=datetime(2024, 3, 5, 4, tzinfo=KST),
        end_time=datetime(2024, 3, 6, 16, tzinfo=KST),
    )

    assert selected is not None
    assert selected.target_at == datetime(2024, 3, 5, 6, 30, tzinfo=UTC)
    assert selected.target_at > datetime(2024, 3, 4, 19, tzinfo=UTC)


@pytest.mark.uc("UC-TIME-002")
def test_no_equal_or_after_end_target_is_not_accepted(tmp_path: Path) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "only-close.parquet",
            """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'A' AS instrument, true AS is_tradable, 1.0 AS close
    """,
        )
    )
    close = datetime(2024, 3, 5, 15, 30, tzinfo=KST)

    assert (
        registration.fill.select_target(registration, decision_time=close, end_time=close) is None
    )
    assert (
        registration.fill.select_target(
            registration,
            decision_time=datetime(2024, 3, 5, 4, tzinfo=KST),
            end_time=datetime(2024, 3, 5, 15, tzinfo=KST),
        )
        is None
    )


@pytest.mark.uc("UC-TIME-002")
def test_execution_snapshot_never_silently_omits_held_values_or_falls_back_for_nav(
    tmp_path: Path,
) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "gap.parquet",
            """
        SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
               'target' AS instrument, true AS is_tradable, 1.0 AS close
    """,
        )
    )

    snapshot = exact_execution_snapshot(
        registration.table,
        target_at=datetime(2024, 3, 5, 15, 30, tzinfo=KST),
        target_instruments=("target",),
        held_instruments=("held",),
        trade_price="close",
    )

    assert snapshot.missing_target_instruments == ()
    assert snapshot.missing_held_instruments == ("held",)
    assert [row.instrument for row in snapshot.rows] == ["target"]


@pytest.mark.uc("UC-TIME-002")
def test_operation_agenda_normalizes_cross_zone_order_and_rejects_unresolved_dst() -> None:
    same_utc = datetime(2024, 3, 5, 4, tzinfo=UTC)
    seoul = _occurrence("seoul", OperationRole.STRATEGY_CALLBACK, same_utc.astimezone(KST))
    new_york = OperationOccurrence(
        "new-york",
        OperationRole.STRATEGY_CALLBACK,
        LocalInstantDeclaration(date(2024, 3, 4), time(23), "America/New_York", 0, "-05:00"),
    )

    seoul_agenda = OperationAgenda.from_occurrences(
        agenda_id="seoul",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(seoul,),
        provenance="fixture",
    )
    new_york_agenda = OperationAgenda.from_occurrences(
        agenda_id="new-york",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="America/New_York",
        occurrences=(new_york,),
        provenance="fixture",
    )
    assert [
        item.evaluation_time.astimezone(UTC)
        for item in seoul_agenda.occurrences + new_york_agenda.occurrences
    ] == [same_utc, same_utc]
    with pytest.raises(ValueError):
        LocalInstantDeclaration(date(2024, 3, 10), time(2, 30), "America/New_York", 0, "-05:00")


@pytest.mark.uc("UC-TIME-002")
def test_duplicate_execution_keys_and_timing_failures_are_rejected_before_acceptance(
    tmp_path: Path,
) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "duplicate.parquet",
            """
        SELECT * FROM (VALUES
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 1.0),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 1.0)
        ) AS t(trade_at, instrument, is_tradable, close)
    """,
        )
    )

    diagnosis = validate_execution_input(registration)
    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_input.register.key.duplicate"
    ]


@pytest.mark.uc("UC-TIME-002")
def test_frozen_agenda_trace_is_canonical_and_non_selected_density_does_not_change_it() -> None:
    nine = datetime(2024, 3, 5, 9, tzinfo=KST)
    ten = datetime(2024, 3, 5, 10, tzinfo=KST)
    first = _frozen((nine, ten), valuations=(nine,))
    second = _frozen((nine, ten), valuations=(nine,))

    assert first.identity == second.identity
    assert [(item.role, item.occurrence_id) for item in first.static_occurrences] == [
        (OperationRole.STRATEGY_CALLBACK, "strategy-0"),
        (OperationRole.VALUATION, "valuation-0"),
        (OperationRole.STRATEGY_CALLBACK, "strategy-1"),
    ]


@pytest.mark.uc("UC-TIME-002")
def test_shared_constraint_identity_is_the_only_constraint_authority() -> None:
    class DifferentConstraint(_Constraint):
        @property
        def constraint_id(self) -> str:
            return "other"

    constraint = _component("risk", ComponentKind.CONSTRAINT)
    frozen = _frozen((datetime(2024, 3, 5, 9, tzinfo=KST),))
    with pytest.raises(ValueError, match="ConstraintSet identity"):
        SimulationFlow(
            frozen,
            _Strategy((NoDecision("x"),)),
            _state(),
            window_for_occurrence=lambda _: None,
            account=Account(mode=AccountMode.LONG_ONLY),
            exchange=_exchange(),
            constraints=(DifferentConstraint(),),
            marks_for_occurrence=lambda *_: {},
        )
    assert frozen.constraints.constraints == (_component("risk", ComponentKind.CONSTRAINT),)
    assert ConstraintSet((constraint,)).constraints == (constraint,)


@pytest.mark.uc("UC-TIME-002")
@pytest.mark.uc("UC-TIME-002")
def test_typed_intent_runs_pending_to_due_academic_fill_feedback_and_finalization(
    tmp_path: Path,
) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "execution.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    intent = EconomicPortfolioIntent(
        UUID(int=1),
        "strategy",
        (PortfolioTarget("A", weight=Decimal("1")),),
        Decimal("0"),
        _BUDGET,
        (),
        0,
        None,
    )
    frozen = _frozen((callback, target), valuations=(target,), end=target, execution=registration)
    state = _state()
    strategy = _Strategy((intent, NoDecision("after due")))

    result = _flow(frozen, strategy, state).run()

    assert [type(trace).__name__ for trace in result.occurrences] == [
        "OccurrenceTrace",
        "DueExecutionTrace",
        "OccurrenceTrace",
        "OccurrenceTrace",
    ]
    assert result.final_state.account is not None
    assert result.final_state.account.snapshot == AccountSnapshot(
        1, Decimal("0"), {"A": Decimal("10")}
    )
    assert result.final_state.pending_accepted_intent is None
    assert len(result.final_state.feedback) == 1
    assert [trace.kind for trace in result.final_state.lifecycle_trace] == [
        LifecycleKind.ACCEPTED_INTENT,
        LifecycleKind.DUE_EXECUTED,
        LifecycleKind.NO_DECISION,
    ]
    assert result.final_state.finalization is not None
    assert strategy.seen[-1][2] == 1

    replay = _flow(frozen, _Strategy((intent, NoDecision("after due"))), _state()).run()
    assert replay.final_state.account == result.final_state.account
    assert [trace.kind for trace in replay.final_state.lifecycle_trace] == [
        trace.kind for trace in result.final_state.lifecycle_trace
    ]


@pytest.mark.uc("UC-TIME-002")
def test_target_only_absence_rejects_an_unreconciled_cash_plan_before_fills(tmp_path: Path) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "absent.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    intent = EconomicPortfolioIntent(
        UUID(int=2),
        "strategy",
        (PortfolioTarget("B", quantity=Decimal("1")),),
        Decimal("1"),
        _BUDGET,
        (),
        0,
        None,
    )
    state = _state()
    with pytest.raises(ValueError, match="complete desired positions"):
        _flow(
            _frozen((callback,), valuations=(target,), end=target, execution=registration),
            _Strategy((intent,)),
            state,
        ).run()

    assert state.current.account == AccountState(_ACCOUNT)
    assert state.current.pending_accepted_intent is not None


@pytest.mark.uc("UC-TIME-002")
def test_callback_payload_fault_does_not_publish_recorder_or_state() -> None:
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    state = _state()
    before_ref = state.current.current_model_state_ref

    with pytest.raises(RuntimeError, match="payload fault"):
        _flow(_frozen((callback,), end=callback), _PayloadFaultStrategy(), state).run()

    assert state.current.account == AccountState(_ACCOUNT)
    assert state.current.current_model_state_ref == before_ref
    assert state.current.recorder_rows == {}
    assert state.current.lifecycle_trace == ()


@pytest.mark.uc("UC-TIME-002")
def test_held_value_gap_blocks_due_execution_before_liquidation(tmp_path: Path) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "held-gap.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'B' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    initial = AccountSnapshot(0, Decimal("90"), {"A": Decimal("1")})
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    intent = EconomicPortfolioIntent(
        UUID(int=3),
        "strategy",
        (PortfolioTarget("B", quantity=Decimal("1")),),
        Decimal("1"),
        _BUDGET,
        (),
        0,
        None,
    )
    state = _state(initial)

    with pytest.raises(ValueError, match="held instruments"):
        _flow(
            _frozen(
                (callback,),
                valuations=(target,),
                end=target,
                execution=registration,
                account=initial,
            ),
            _Strategy((intent,)),
            state,
        ).run()

    assert state.current.account == AccountState(initial)
    assert state.current.pending_accepted_intent is not None


@pytest.mark.uc("UC-TIME-002")
def test_omitted_holding_is_liquidated_through_the_due_flow(tmp_path: Path) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "liquidate.parquet",
            """
            SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 10.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', true, 10.0)
            ) AS t(trade_at, instrument, is_tradable, close)
            """,
        )
    )
    initial = AccountSnapshot(0, Decimal("90"), {"A": Decimal("1")})
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    intent = EconomicPortfolioIntent(
        UUID(int=4),
        "strategy",
        (PortfolioTarget("B", quantity=Decimal("1")),),
        Decimal("0.9"),
        _BUDGET,
        (),
        0,
        None,
    )

    result = _flow(
        _frozen(
            (callback,), valuations=(target,), end=target, execution=registration, account=initial
        ),
        _Strategy((intent,)),
        _state(initial),
    ).run()

    assert result.final_state.account is not None
    assert result.final_state.account.snapshot == AccountSnapshot(
        1, Decimal("90"), {"B": Decimal("1")}
    )
    assert [entry.fill.instrument_id for entry in result.final_state.account.fill_history] == [
        "A",
        "B",
    ]
    assert result.final_state.account.fill_history[0].fill.dealt_quantity == Decimal("-1")
