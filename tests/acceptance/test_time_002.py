from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import duckdb
import pytest

import vqapr.flow.strategy.execution as execution_phase
from vqapr.account.account import Account, AccountMode
from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintCall,
    ConstraintFinding,
    EconomicAccountView,
    Hold,
    Rebalance,
    StrategyModel,
)
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountSnapshot, AccountState
from vqapr.domain.agendas import OperationAgenda, OperationOccurrence
from vqapr.domain.errors import VqaprError
from vqapr.domain.values import LocalInstantDeclaration
from vqapr.exchange.conventions import ExactExecutionTarget, FillConvention, FillSelector
from vqapr.exchange.execution_table import (
    ExecutionTable,
    ExecutionTableSpec,
    exact_execution_snapshot,
    validate_execution_table,
)
from vqapr.exchange.listings import ListingAccess
from vqapr.exchange.venue import AcademicExchange, TradeRule
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.engine.artifacts import (
    AccountCommitEvidence,
    CallbackEvidence,
    DueExecutionEvidence,
    FeedbackEvidence,
    MarkEvidence,
    SimulationFailure,
    SimulationFailureKind,
    SimulationStage,
)
from vqapr.flow.declaration.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.project.run import ConstraintSet, StrategyConfig
from vqapr.flow.engine.run_state import LifecycleKind, RunStateRepository
from vqapr.flow.strategy.loop import AcceptedIntent, DueExecutionTrace, StrategyEventLoop
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    IntentSourceRef,
    validate_economic_intent,
)
from vqapr.public import register_dataset
from vqapr.project.store import Workspace

KST = ZoneInfo("Asia/Seoul")


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
    def __init__(self, results: tuple[Hold | Rebalance, ...]) -> None:
        self.results = iter(results)
        self.seen: list[tuple[str, datetime, dict[str, Decimal]]] = []

    def decide(self, context: object) -> Hold | Rebalance:
        occurrence = context.occurrence
        assert not hasattr(context, "future_occurrences")
        assert not hasattr(context, "execution_table")
        self.seen.append(
            # The view carries no version (a framework fact, record `132`); what it shows of
            # the account's progress is the committed book itself.
            (occurrence.occurrence_id, occurrence.evaluation_time, dict(context.account.positions))
        )
        self.memory = {"calls": len(self.seen)}
        return next(self.results)


class _PayloadFaultStrategy(_Strategy):
    def __init__(self) -> None:
        super().__init__((Hold(reason="unreachable"),))
        self._save_count = 0

    def save_payload(self, target: object) -> None:
        self._save_count += 1
        if self._save_count == 1:
            raise RuntimeError("payload fault")


def _component(identifier: str, kind: ComponentKind) -> ComponentRef:
    return ComponentRef.of(
        identifier, kind, Path(f"{identifier}.py"), "Component", fingerprint="0" * 64
    )


def _occurrence(identifier: str, at: datetime) -> OperationOccurrence:
    return OperationOccurrence(
        identifier,
        LocalInstantDeclaration(
            at.date(), at.timetz().replace(tzinfo=None), "Asia/Seoul", 0, "+09:00"
        ),
    )


def _agenda(identifier: str, *times: datetime) -> FrozenAgenda:
    return FrozenAgenda(
        identifier,
        tuple(_occurrence(f"{identifier}-{i}", at) for i, at in enumerate(times)),
    )


def _requirement() -> DataRequirement:
    return DataRequirement.of("prices", "close", lookback=RowsLookback(1))


class _Constraint(Constraint):
    @property
    def constraint_id(self) -> str:
        return "risk"

    def requirements(self) -> tuple[DataRequirement, ...]:
        return (_requirement(),)

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        return ConstraintBounds(
            lower_weights={instrument: Decimal("0") for instrument in call.instruments},
            upper_weights={instrument: Decimal("1") for instrument in call.instruments},
        )

    def monitor(
        self,
        call: ConstraintCall,
        account: EconomicAccountView,
        bounds: ConstraintBounds,
    ) -> ConstraintFinding:
        return ConstraintFinding(
            passed=True, measured=Decimal("0"), bound=Decimal("1"), excess=Decimal("0"), details={}
        )


_ACCOUNT = AccountSnapshot(0, Decimal("100"), {})


def _state(
    account: AccountSnapshot = _ACCOUNT, constraint_ids: tuple[str, ...] = ("risk", "academic")
) -> RunStateRepository:
    return RunStateRepository(
        initial_account=AccountState(account),
        initial_component_memory={constraint_id: None for constraint_id in constraint_ids},
    )


def _exchange() -> AcademicExchange:
    return AcademicExchange(
        {
            instrument: TradeRule(
                instrument,
                Decimal("0.001"),
                Decimal("0.001"),
                True,
                ListingAccess.SIGNED,
            )
            for instrument in ("A", "B")
        }
    )


def _frozen(
    callbacks: tuple[datetime, ...],
    *,
    end: datetime | None = None,
    execution: ExecutionTable | None = None,
    account: AccountSnapshot = _ACCOUNT,
    datasets: tuple[DatasetRegistration, ...] = (),
    sources: tuple[SourceSpec, ...] = (),
    constraints: ConstraintSet | None = None,
    strategy_requirements: tuple[DataRequirement, ...] = (),
) -> FrozenRun:
    """A frozen run with the one agenda a run has since record `148`: its callbacks.

    There is no valuation or monitoring agenda to declare: the book is valued at the instant the
    venue fills and the declared constraints judge it right after each commit.
    """
    strategy = StrategyConfig(
        _component("strategy", ComponentKind.STRATEGY_MODEL),
        "strategy",
    )
    bounds = {"start": callbacks[0], "end": end} if end is not None else {}
    layer = FrozenStrategy(
        config=strategy,
        constraints=(
            constraints
            if constraints is not None
            else ConstraintSet((_component("risk", ComponentKind.CONSTRAINT),))
        ),
        agenda=_agenda("strategy", *callbacks),
        requirements=strategy_requirements,
        constraint_requirements=(
            (_requirement(),) if constraints is None or constraints.constraints else ()
        ),
    )
    return FrozenRun(
        run_id="test",
        strategy=layer,
        exchange=_component("academic", ComponentKind.EXCHANGE) if execution else None,
        execution=execution,
        initial_account_snapshot=account,
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A", "B"),
        requirements=tuple(strategy_requirements) + layer.constraint_requirements,
        datasets=datasets,
        sources=sources,
        **bounds,
        writes="test-weights",
    )


def _flow(
    frozen: FrozenRun,
    strategy: StrategyModel,
    state: RunStateRepository,
    constraints: tuple[Constraint, ...] = (_Constraint(),),
    constraint_window_for_occurrence: object = None,
    strategy_window_for_occurrence: object = None,
) -> StrategyEventLoop:
    return StrategyEventLoop(
        frozen,
        strategy,
        state,
        strategy_window_for_occurrence=strategy_window_for_occurrence
        or (
            lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=("A",),
                store=DuckDbObservationStore(_Catalog()),
                allowed_requirements=frozen.strategy.requirements,
                consumer_id="test-consumer",
            )
        ),
        constraint_window_for_occurrence=constraint_window_for_occurrence
        or (
            lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=("A",),
                store=DuckDbObservationStore(_Catalog()),
                allowed_requirements=(_requirement(),),
                consumer_id="test-consumer",
            )
        ),
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_exchange(),
        constraints=constraints,
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
) -> ExecutionTable:
    return ExecutionTable.of(
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
    strategy = _Strategy((Hold(reason="observe"), Hold(reason="observe")))

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
          (TIMESTAMPTZ '2024-03-05 03:59:00+00', 'A', 1.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 04:00:00+00', 'A', 2.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 04:01:00+00', 'A', 3.0::DOUBLE)
        ) AS t(available_at, instrument, close)
    """,
    )
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(
        tmp_path / "workspace",
        DatasetRegistration.of(
            "prices",
            "source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("source", source),
    )
    workspace = Workspace.open(tmp_path / "workspace")
    requirement = DataRequirement.of("prices", "close", lookback=RowsLookback(3))
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 5, 4, tzinfo=UTC),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )

    assert [row["close"] for row in window.observations(requirement).rows] == [1.0, 2.0]
    assert (
        len(
            _flow(
                _frozen(
                    (datetime(2024, 3, 5, 13, tzinfo=KST),),
                    end=datetime(2024, 3, 5, 13, tzinfo=KST),
                ),
                _Strategy((Hold(reason="daily"),)),
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
          (TIMESTAMPTZ '2024-03-05 04:00:00+09', 'A', 1.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 04:00:00.000001+09', 'A', 2.0::DOUBLE)
        ) AS t(available_at, instrument, close)
    """,
    )
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(
        tmp_path / "workspace",
        DatasetRegistration.of(
            "prices",
            "source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("source", source),
    )
    workspace = Workspace.open(tmp_path / "workspace")
    requirement = DataRequirement.of("prices", "close", lookback=RowsLookback(2))
    window = ModelWindow(
        evaluation_time=datetime(2024, 3, 5, 4, tzinfo=KST),
        instruments=("A",),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )

    assert [row["close"] for row in window.observations(requirement).rows] == [1.0]
    assert (
        _flow(
            _frozen(
                (datetime(2024, 3, 5, 5, tzinfo=KST),),
                end=datetime(2024, 3, 5, 5, tzinfo=KST),
            ),
            _Strategy((Hold(reason="no row required"),)),
            _state(),
        )
        .run()
        .final_state.current_model_state_ref
        is not None
    )


@pytest.mark.uc("UC-TIME-002")
def test_empty_constraint_set_needs_no_constraint_window() -> None:
    at = datetime(2024, 3, 5, 12, tzinfo=KST)
    frozen = _frozen((at,), end=at, constraints=ConstraintSet(()))

    def unexpected_constraint_window(_: OperationOccurrence) -> ModelWindow:
        raise AssertionError("empty ConstraintSet must not request a constraint window")

    result = _flow(
        frozen,
        _Strategy((Hold(reason="unconstrained"),)),
        _state(constraint_ids=("academic",)),
        (),
        unexpected_constraint_window,
    ).run()

    assert len(result.occurrences) == 1
    assert result.final_state.pending_accepted_intent is None


@pytest.mark.uc("UC-TIME-002")
def test_monitoring_projects_at_the_fill_instant_and_reuses_its_projected_bounds(
    tmp_path: Path,
) -> None:
    """Monitoring judges the committed book right after the fill, as of the fill instant.

    Record `148`: there is no monitoring occurrence of its own. The constraint projects once at
    the callback (for the intent's bounds) and once more at the fill instant (for the judgment),
    and the judgment measures against the bounds IT projected there, not the ones the callback
    saw: the two projections are separate reads at separate cutoffs, and pairing the later
    measurement with the earlier bounds would report a breach against a limit that had since
    moved.
    """
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    fill = datetime(2024, 3, 5, 15, 30, tzinfo=KST)

    class RecordingConstraint(_Constraint):
        def __init__(self) -> None:
            self.projections: list[tuple[datetime, ConstraintBounds]] = []
            self.actual: tuple[datetime, ConstraintBounds] | None = None

        def project(self, call: ConstraintCall) -> ConstraintBounds:
            bounds = super().project(call)
            self.projections.append((call.evaluation_time, bounds))
            return bounds

        def monitor(
            self,
            call: ConstraintCall,
            account: EconomicAccountView,
            bounds: ConstraintBounds,
        ) -> ConstraintFinding:
            self.actual = (call.evaluation_time, bounds)
            return ConstraintFinding(
                passed=False,
                measured=Decimal("1"),
                bound=Decimal("0"),
                excess=Decimal("1"),
                details={},
            )

    constraint = RecordingConstraint()
    result = _flow(
        _frozen(
            (callback,),
            end=fill,
            execution=_execution(
                _parquet(
                    tmp_path / "execution.parquet",
                    """
                    SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                           'A' AS instrument, true AS is_tradable, 10.0 AS close
                    """,
                )
            ),
        ),
        _Strategy((Rebalance(target_weights={}, cash_weight=Decimal("1"), budget=_BUDGET),)),
        _state(),
        (constraint,),
    ).run()

    assert [cutoff for cutoff, _ in constraint.projections] == [callback, fill]
    assert constraint.actual == (fill, constraint.projections[1][1])
    # The finding rides the due execution's own result: monitoring is part of the commit.
    due = result.occurrences[-1]
    assert isinstance(due, DueExecutionTrace)
    assert due.result.monitoring is not None
    assert due.result.report.passed is False
    assert result.final_state.account is not None
    assert result.final_state.account.snapshot.version == 1
    # And what it measured reached the run's own table, dated by the fill instant it judged.
    findings = result.final_state.recorder_rows["vqapr.monitoring"]
    assert [(row["constraint"], row["passed"]) for row in findings] == [("risk", False)]
    assert [row["event_time"] for row in findings] == [fill]


@pytest.mark.uc("UC-TIME-002")
def test_strategy_payload_has_no_timing_authority_and_flow_stamps_current_occurrence() -> None:
    # A stamped intent on purpose, not a decision: what is under test is that the intent the
    # Flow produces carries no timing of its own, and only the stamped object has an identity
    # for a timing claim to hang on.
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
        payload, _occurrence("current", at), at, target
    )
    assert accepted.decision_time == at


@pytest.mark.uc("UC-TIME-002")
def test_the_flow_stamps_provenance_from_what_the_callback_actually_read(
    tmp_path: Path,
) -> None:
    """The guarantee that replaced a refusal.

    This test used to hand the Flow three intents carrying a wrong `strategy_id`, a wrong
    `model_state_ref`, and a wrong `source_refs`, and assert each was refused without mutation.
    Record `125` removed the way to be wrong: a callback returns `Hold` or `Rebalance`, and the
    Flow stamps all three from the run it is executing. There is no longer a mismatched intent to
    construct, so the property worth asserting is the one the refusal existed to protect --
    provenance describes what was READ, not what was claimed.

    The strategy below reads its declared window and returns a bare `Rebalance`. Everything
    checked afterwards is a value it never named.
    """
    source_path = _parquet(
        tmp_path / "strategy.parquet",
        """
        SELECT TIMESTAMPTZ '2024-03-05 09:00:00+09' AS available_at,
               'A' AS instrument, 10.0::DOUBLE AS close
        """,
    )
    registration = DatasetRegistration.of(
        "prices",
        "source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    )
    source = SourceSpec.of("source", source_path)
    register_dataset(tmp_path / "workspace", registration, source)
    workspace = Workspace.open(tmp_path / "workspace")
    requirement = DataRequirement.of("prices", "close", lookback=RowsLookback(1))
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
        def requirements(self) -> tuple[DataRequirement, ...]:
            return (requirement,)

        def decide(self, context: object) -> Rebalance:
            context.window.observations(requirement)
            return Rebalance(target_weights={}, cash_weight=Decimal("1"), budget=_BUDGET)

    frozen = _frozen(
        (callback,),
        end=target,
        execution=execution,
        datasets=(registration,),
        sources=(source,),
        strategy_requirements=(requirement,),
    )

    result = StrategyEventLoop(
        frozen,
        ReadingStrategy(),
        _state(),
        strategy_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(workspace),
            allowed_requirements=(requirement,),
            consumer_id="reading-strategy",
        ),
        # No consumer: a constraint window serves every loaded constraint, and
        # `project_constraints` takes a view per constraint. Built the way orchestration builds it.
        constraint_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(workspace),
            allowed_requirements=(_requirement(),),
        ),
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_exchange(),
        constraints=(_Constraint(),),
    ).run()

    stamped = next(
        trace.result
        for trace in result.occurrences
        if isinstance(getattr(trace, "result", None), EconomicPortfolioIntent)
    )
    # The source actually read, at the digest it actually carried.
    assert stamped.source_refs == (IntentSourceRef("source", digest),)
    # The frozen component, not a string the callback chose.
    assert stamped.strategy_id == str(frozen.strategy.config.component.component_id)
    # The account the callback was handed.
    assert stamped.account_version_seen == _ACCOUNT.version
    # Deterministic, so a replayed run mints the same identity for the same occurrence.
    first_occurrence = frozen.dispatch_order(frozen.strategy)[0]
    assert stamped.intent_id == uuid5(
        NAMESPACE_URL, f"{stamped.strategy_id}/{first_occurrence.occurrence_id}"
    )
    assert result.final_state.pending_accepted_intent is None


@pytest.mark.uc("UC-TIME-002")
def test_no_decision_does_not_hash_an_unread_declared_source(tmp_path: Path) -> None:
    requirement = DataRequirement.of("prices", "close", lookback=RowsLookback(1))
    registration = DatasetRegistration.of(
        "prices",
        "missing-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    )
    source = SourceSpec.of("missing-source", tmp_path / "unread.parquet")
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)

    class PassiveStrategy(_Strategy):
        def requirements(self) -> tuple[DataRequirement, ...]:
            return (requirement,)

    result = _flow(
        _frozen(
            (callback,),
            end=callback,
            datasets=(registration,),
            sources=(source,),
            strategy_requirements=(requirement,),
        ),
        PassiveStrategy((Hold(reason="no observation read"),)),
        _state(),
    ).run()

    assert result.final_state.lifecycle_trace[0].kind is LifecycleKind.NO_DECISION
    evidence = result.final_state.lifecycle_trace[0].detail
    assert evidence.strategy_accesses == ()
    assert evidence.actual_source_refs == ()


@pytest.mark.uc("UC-TIME-002")
def test_callback_data_failure_retains_window_owner_and_rolls_back(tmp_path: Path) -> None:
    requirement = DataRequirement.of("prices", "close", lookback=RowsLookback(1))
    registration = DatasetRegistration.of(
        "prices",
        "missing-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    )
    source = SourceSpec.of("missing-source", tmp_path / "missing.parquet")
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)

    class ReadingStrategy(_Strategy):
        def requirements(self) -> tuple[DataRequirement, ...]:
            return (requirement,)

        def decide(self, context: object) -> Hold:
            context.window.observations(requirement)
            return Hold(reason="unreachable")

    class MissingCatalog:
        def dataset(self, _dataset_id: str) -> DatasetRegistration:
            return registration

        def source(self, _source_id: str) -> SourceSpec:
            return source

    frozen = _frozen(
        (callback,),
        end=callback,
        datasets=(registration,),
        sources=(source,),
        strategy_requirements=(requirement,),
    )
    state = _state()

    with pytest.raises(SimulationFailure, match=r"missing\.parquet") as raised:
        _flow(
            frozen,
            ReadingStrategy(()),
            state,
            strategy_window_for_occurrence=lambda occurrence: ModelWindow(
                evaluation_time=occurrence.evaluation_time,
                instruments=("A",),
                store=DuckDbObservationStore(MissingCatalog()),
                allowed_requirements=(requirement,),
                consumer_id="test-consumer",
            ),
        ).run()

    failure = raised.value
    assert failure.stage is SimulationStage.CALLBACK_WINDOW
    assert failure.failed_requirement == frozen.strategy.requirements
    assert failure.mutation is False
    assert state.current.lifecycle_trace == ()


@pytest.mark.uc("UC-TIME-002")
def test_intent_target_outside_frozen_universe_is_rejected(tmp_path: Path) -> None:
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    execution = _execution(
        _parquet(
            tmp_path / "execution.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'C' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    intent = Rebalance(
        target_weights={"C": Decimal("0")},
        cash_weight=Decimal("1"),
        budget=_BUDGET,
    )
    state = _state()

    with pytest.raises(SimulationFailure, match="frozen instrument universe") as raised:
        _flow(
            _frozen((callback,), end=target, execution=execution),
            _Strategy((intent,)),
            state,
        ).run()

    failure = raised.value
    assert failure.stage is SimulationStage.CALLBACK_INTENT
    # The decision went in; a stamped intent came out and is what the failure names. Identity
    # cannot be compared across that boundary any more, so compare the economics that crossed it.
    assert failure.failed_requirement.targets[0].instrument_id == "C"
    assert failure.mutation is False
    assert state.current.pending_accepted_intent is None
    assert state.current.lifecycle_trace == ()


@pytest.mark.uc("UC-TIME-002")
def test_constraint_projection_failure_retains_constraint_owner() -> None:
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)

    class FailingConstraint(_Constraint):
        def project(self, call: ConstraintCall) -> ConstraintBounds:
            raise RuntimeError("constraint projection fault")

    constraint = FailingConstraint()
    state = _state()
    with pytest.raises(SimulationFailure, match="constraint projection fault") as raised:
        _flow(
            _frozen((callback,), end=callback),
            _Strategy((Hold(reason="unreachable"),)),
            state,
            constraints=(constraint,),
        ).run()

    failure = raised.value
    assert failure.stage is SimulationStage.CALLBACK_INTENT
    assert failure.failed_requirement is constraint
    assert failure.mutation is False
    assert state.current.lifecycle_trace == ()


@pytest.mark.uc("UC-TIME-002")
def test_callback_publication_failure_is_not_classified_as_intent() -> None:
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    state = RunStateRepository(
        initial_account=AccountState(_ACCOUNT),
        initial_component_memory={"risk": None, "academic": None},
        before_swap=lambda _candidate: (_ for _ in ()).throw(
            RuntimeError("callback publication fault")
        ),
    )

    with pytest.raises(SimulationFailure, match="callback publication fault") as raised:
        _flow(
            _frozen((callback,), end=callback),
            _Strategy((Hold(reason="no decision"),)),
            state,
        ).run()

    failure = raised.value
    assert failure.stage is SimulationStage.CALLBACK_PUBLICATION
    assert failure.mutation is False
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
    selected = registration.select_target(
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

    assert registration.select_target(decision_time=close, end_time=close) is None
    assert (
        registration.select_target(
            decision_time=datetime(2024, 3, 5, 4, tzinfo=KST),
            end_time=datetime(2024, 3, 5, 15, tzinfo=KST),
        )
        is None
    )


@pytest.mark.uc("UC-TIME-002")
@pytest.mark.parametrize(
    ("callback", "end"),
    (
        (
            datetime(2024, 3, 5, 15, 30, tzinfo=KST),
            datetime(2024, 3, 5, 15, 30, tzinfo=KST),
        ),
        (
            datetime(2024, 3, 5, 4, tzinfo=KST),
            datetime(2024, 3, 5, 15, tzinfo=KST),
        ),
    ),
)
def test_flow_no_target_failure_retains_execution_owner_and_existing_pending(
    tmp_path: Path,
    callback: datetime,
    end: datetime,
) -> None:
    registration = _execution(
        _parquet(
            tmp_path / f"no-target-{callback.hour}.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    intent = Rebalance(
        target_weights={},
        cash_weight=Decimal("1"),
        budget=_BUDGET,
    )
    prior = type("PriorPending", (), {"pending_id": "prior"})()
    state = RunStateRepository(
        initial_account=AccountState(_ACCOUNT),
        initial_component_memory={"risk": None, "academic": None},
        pending_accepted_intent=prior,
    )
    frozen = _frozen((callback,), end=end, execution=registration)
    flow = _flow(frozen, _Strategy((intent,)), state)
    before = state.current

    with pytest.raises(SimulationFailure, match="no exact execution target") as raised:
        flow._callback.dispatch(frozen.strategy.agenda.occurrences[0])

    failure = raised.value
    assert failure.stage is SimulationStage.CALLBACK_INTENT
    assert failure.failed_requirement is frozen.execution
    assert failure.mutation is False
    assert state.current is before
    assert state.current.pending_accepted_intent is prior


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
    seoul = _occurrence("seoul", same_utc.astimezone(KST))
    new_york = OperationOccurrence(
        "new-york",
        LocalInstantDeclaration(date(2024, 3, 4), time(23), "America/New_York", 0, "-05:00"),
    )

    seoul_agenda = OperationAgenda(
        agenda_id="seoul",
        timezone="Asia/Seoul",
        occurrences=(seoul,),
    )
    new_york_agenda = OperationAgenda(
        agenda_id="new-york",
        timezone="America/New_York",
        occurrences=(new_york,),
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
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 1.0::DOUBLE),
          (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 1.0::DOUBLE)
        ) AS t(trade_at, instrument, is_tradable, close)
    """,
        )
    )

    diagnosis = validate_execution_table(registration)
    assert not diagnosis.ok
    assert [failure.code for failure in diagnosis.failures] == [
        "execution_table.key_duplicate"
    ]


@pytest.mark.uc("UC-TIME-002")
def test_frozen_agenda_trace_is_canonical_and_dispatches_only_callbacks() -> None:
    """Two freezes of the same declarations share one identity, and the static dispatch order
    is the strategy's own agenda and nothing else: since record `148` valuation and monitoring
    have no occurrences to merge in."""
    nine = datetime(2024, 3, 5, 9, tzinfo=KST)
    ten = datetime(2024, 3, 5, 10, tzinfo=KST)
    first = _frozen((nine, ten))
    second = _frozen((nine, ten))

    assert first.identity == second.identity
    order = first.dispatch_order(first.strategy)
    assert [item.occurrence_id for item in order] == ["strategy-0", "strategy-1"]


@pytest.mark.uc("UC-TIME-002")
def test_shared_constraint_identity_is_the_only_constraint_authority() -> None:
    class DifferentConstraint(_Constraint):
        @property
        def constraint_id(self) -> str:
            return "other"

    constraint = _component("risk", ComponentKind.CONSTRAINT)
    frozen = _frozen((datetime(2024, 3, 5, 9, tzinfo=KST),))
    # A structured refusal, not a bare `ValueError`. The guard used to raise one, which carries no
    # body, so it surfaced through the CLI as `stage: "unhandled"` with an empty `failures` list --
    # the framework announcing its own breakage when a component was registered under the wrong id.
    with pytest.raises(VqaprError) as caught:
        StrategyEventLoop(
            frozen,
            _Strategy((Hold(reason="x"),)),
            _state(),
            strategy_window_for_occurrence=lambda _: None,
            constraint_window_for_occurrence=lambda _: None,
            account=Account(mode=AccountMode.LONG_ONLY),
            exchange=_exchange(),
            constraints=(DifferentConstraint(),),
        )
    assert [failure.code for failure in caught.value.failures] == [
        "constraint.identity_mismatch"
    ]
    # The refusal names both sides, so a reader does not have to diff two ids by eye.
    assert "'other'" in caught.value.failures[0].observed
    assert "'risk'" in caught.value.failures[0].observed
    assert frozen.strategy.constraints.constraints == (
        _component("risk", ComponentKind.CONSTRAINT),
    )
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
    intent = Rebalance(
        target_weights={"A": Decimal("1")},
        cash_weight=Decimal("0"),
        budget=_BUDGET,
    )
    frozen = _frozen((callback, target), end=target, execution=registration)
    state = _state()
    strategy = _Strategy((intent, Hold(reason="after due")))

    result = _flow(frozen, strategy, state).run()

    # The fill is the valuation: no separate valuation occurrence follows it (record `148`).
    assert [type(trace).__name__ for trace in result.occurrences] == [
        "OccurrenceTrace",
        "DueExecutionTrace",
        "OccurrenceTrace",
    ]
    assert result.final_state.account is not None
    assert result.final_state.account.snapshot == AccountSnapshot(
        1, Decimal("0"), {"A": Decimal("10")}
    )
    assert result.final_state.pending_accepted_intent is None
    assert len(result.final_state.feedback) == 1
    # Monitoring judges the committed, marked book before the feedback is published.
    assert [trace.kind for trace in result.final_state.lifecycle_trace] == [
        LifecycleKind.ACCEPTED_INTENT,
        LifecycleKind.ACCOUNT_COMMITTED,
        LifecycleKind.MARKED,
        LifecycleKind.MONITORED,
        LifecycleKind.FEEDBACK_PUBLISHED,
        LifecycleKind.NO_DECISION,
    ]
    callback_evidence = result.final_state.lifecycle_trace[0].detail
    commit_evidence = result.final_state.lifecycle_trace[1].detail
    mark_evidence = result.final_state.lifecycle_trace[2].detail
    feedback_evidence = result.final_state.lifecycle_trace[4].detail
    assert isinstance(callback_evidence, CallbackEvidence)
    assert isinstance(commit_evidence, AccountCommitEvidence)
    assert isinstance(mark_evidence, MarkEvidence)
    assert isinstance(feedback_evidence, FeedbackEvidence)
    due_evidence = result.final_state.feedback[0]
    assert isinstance(due_evidence, DueExecutionEvidence)
    assert due_evidence.commit == commit_evidence
    assert due_evidence.mark == mark_evidence
    assert due_evidence.feedback == feedback_evidence
    assert callback_evidence.run_identity == frozen.identity
    assert callback_evidence.agenda == frozen.strategy.agenda
    assert callback_evidence.occurrence.occurrence_id == "strategy-0"
    assert callback_evidence.current_model_state_ref == frozen.strategy.initial_model_state_ref
    assert callback_evidence.committed_model_state_ref != callback_evidence.current_model_state_ref
    assert commit_evidence.execution_snapshot.missing_target_instruments == ()
    assert commit_evidence.execution_snapshot.duplicate_instruments == ()
    assert commit_evidence.fill_convention.declaration_identity == (
        "SAME_DAY",
        "15:30:00",
        "Asia/Seoul",
        "close",
        None,
        None,
    )
    assert commit_evidence.target.identity == commit_evidence.pending.target.identity
    assert mark_evidence.run_identity == feedback_evidence.run_identity == frozen.identity
    assert feedback_evidence.candidates == (commit_evidence.dealt_fills, mark_evidence.marks)
    assert result.final_state.finalization is not None
    assert strategy.seen[-1][2], "the callback after the fill must see the filled book"
    # The NAV is measured at the fill instant, and dated by it: `event_time` and `observed_at`
    # are both the fill, not the decision that led to it (record `148`).
    nav_rows = [
        row
        for row in result.final_state.recorder_rows["vqapr.account"]
        if row["instrument"] == "_ACCOUNT"
    ]
    assert [(row["event_time"], row["observed_at"], row["stage"]) for row in nav_rows] == [
        (target, target, "VALUATION")
    ]
    assert nav_rows[0]["nav"] == Decimal("100")

    replay = _flow(frozen, _Strategy((intent, Hold(reason="after due"))), _state()).run()
    assert replay.final_state.account == result.final_state.account
    assert [trace.kind for trace in replay.final_state.lifecycle_trace] == [
        trace.kind for trace in result.final_state.lifecycle_trace
    ]


@pytest.mark.uc("UC-TIME-002")
def test_no_decision_preserves_existing_pending_until_due(tmp_path: Path) -> None:
    first = datetime(2024, 3, 5, 9, tzinfo=KST)
    second = datetime(2024, 3, 5, 10, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    registration = _execution(
        _parquet(
            tmp_path / "execution.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    intent = Rebalance(
        target_weights={"A": Decimal("1")},
        cash_weight=Decimal("0"),
        budget=_BUDGET,
    )

    result = _flow(
        _frozen((first, second), end=target, execution=registration),
        _Strategy((intent, Hold(reason="keep pending"))),
        _state(),
    ).run()

    assert [trace.kind for trace in result.final_state.lifecycle_trace] == [
        LifecycleKind.ACCEPTED_INTENT,
        LifecycleKind.NO_DECISION,
        LifecycleKind.ACCOUNT_COMMITTED,
        LifecycleKind.MARKED,
        LifecycleKind.MONITORED,
        LifecycleKind.FEEDBACK_PUBLISHED,
    ]
    commit = result.final_state.lifecycle_trace[2].detail
    assert commit.pending.intent.targets[0].instrument_id == "A"
    assert result.final_state.pending_accepted_intent is None


@pytest.mark.uc("UC-TIME-002")
def test_target_only_absence_publishes_typed_zero_dealt_fill(tmp_path: Path) -> None:
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
    intent = Rebalance(
        target_weights={"B": Decimal("0")},
        cash_weight=Decimal("1"),
        budget=_BUDGET,
    )
    state = _state()
    result = _flow(
        _frozen((callback,), end=target, execution=registration),
        _Strategy((intent,)),
        state,
    ).run()

    commit = next(
        trace.detail
        for trace in result.final_state.lifecycle_trace
        if trace.kind is LifecycleKind.ACCOUNT_COMMITTED
    )
    assert isinstance(commit, AccountCommitEvidence)
    fill = commit.dealt_fills.fills[0]
    assert fill.dealt_quantity == 0
    assert fill.reason.value == "absent"
    assert result.final_state.account is not None
    assert result.final_state.account.snapshot == AccountSnapshot(1, Decimal("100"), {})
    assert result.final_state.pending_accepted_intent is None


@pytest.mark.uc("UC-TIME-002")
def test_callback_payload_fault_does_not_publish_recorder_or_state() -> None:
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    state = _state()
    before_ref = state.current.current_model_state_ref
    frozen = _frozen((callback,), end=callback)

    with pytest.raises(SimulationFailure, match="payload fault") as raised:
        _flow(frozen, _PayloadFaultStrategy(), state).run()

    failure = raised.value
    assert failure.stage is SimulationStage.CALLBACK_STATE
    assert failure.failed_requirement is frozen.strategy.config
    assert failure.kind is SimulationFailureKind.PRE_COMMIT
    assert failure.mutation is False
    assert state.current.account == AccountState(_ACCOUNT)
    assert state.current.current_model_state_ref == before_ref
    assert state.current.recorder_rows == {}
    assert state.current.lifecycle_trace == ()


@pytest.mark.uc("UC-TIME-002")
def test_a_held_instrument_absent_from_the_venue_is_carried_not_refused(tmp_path: Path) -> None:
    """A delisting is a market fact, so the run continues and the position stays put.

    Canon 6.1 splits the one snapshot three ways, and an absent row belongs to zero-dealt
    evidence rather than batch failure. Refusing instead would end any real run in its first
    week, because delistings arrive constantly in a large universe.
    """
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
    intent = Rebalance(
        target_weights={"B": Decimal("0")},
        cash_weight=Decimal("1"),
        budget=_BUDGET,
    )
    state = _state(initial)

    _flow(
        _frozen((callback,), end=target, execution=registration, account=initial),
        _Strategy((intent,)),
        state,
    ).run()

    # The unpriceable holding survives the due execution untouched.
    assert state.current.account.snapshot.positions["A"] == Decimal("1")
    assert state.current.pending_accepted_intent is None


@pytest.mark.uc("UC-TIME-002")
def test_due_failures_preserve_pre_and_post_commit_authority_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registration = _execution(
        _parquet(
            tmp_path / "failure-lineage.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    intent = Rebalance(
        target_weights={"A": Decimal("1")},
        cash_weight=Decimal("0"),
        budget=_BUDGET,
    )
    state = _state()

    def required_valuation_failure(*_: object, **__: object) -> object:
        raise RuntimeError("required valuation unavailable")

    # Valuation is no longer a separate subscription: the book is valued from the execution
    # snapshot the fill was priced against, so that reader is the seam that can fail after commit.
    # The due path binds the helper in the execution phase's module (record `147`).
    monkeypatch.setattr(
        execution_phase, "_marks_from_execution_snapshot", required_valuation_failure
    )
    with pytest.raises(SimulationFailure) as raised:
        _flow(
            _frozen((callback,), end=target, execution=registration),
            _Strategy((intent,)),
            state,
        ).run()

    failure = raised.value
    assert failure.kind is SimulationFailureKind.FAILED_AFTER_COMMIT
    assert failure.mutation is True
    assert failure.root_version == state.current.version
    assert failure.model_version == state.current.model_state_commit_count
    assert failure.account_version == 1
    assert failure.pending_id is None
    assert failure.correlation_id == failure.frozen_run_identity
    assert state.current.pending_accepted_intent is None


@pytest.mark.uc("UC-TIME-002")
@pytest.mark.parametrize(
    ("boundary", "stage", "after_commit", "root_version"),
    (
        ("data", SimulationStage.DUE_SNAPSHOT, False, 1),
        ("order", SimulationStage.DUE_ORDER_PLANNING, False, 1),
        ("exchange", SimulationStage.DUE_EXCHANGE_EXECUTION, False, 1),
        ("account", SimulationStage.DUE_ACCOUNT_PREPARATION, False, 1),
        ("valuation", SimulationStage.DUE_VALUATION_SELECTION, True, 2),
        # Four publications precede the feedback since record `148`: the callback, the commit,
        # the mark, and the monitoring that judges the marked book right after it.
        ("publication", SimulationStage.DUE_FEEDBACK_PUBLICATION, True, 4),
    ),
)
def test_due_fault_boundaries_report_their_actual_owner_and_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    stage: SimulationStage,
    after_commit: bool,
    root_version: int,
) -> None:
    registration = _execution(
        _parquet(
            tmp_path / f"{boundary}.parquet",
            """
            SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                   'A' AS instrument, true AS is_tradable, 10.0 AS close
            """,
        )
    )
    callback = datetime(2024, 3, 5, 9, tzinfo=KST)
    target = datetime(2024, 3, 5, 15, 30, tzinfo=KST)
    intent = Rebalance(
        target_weights={"A": Decimal("1")},
        cash_weight=Decimal("0"),
        budget=_BUDGET,
    )
    frozen = _frozen((callback,), end=target, execution=registration)
    state = _state()
    flow = _flow(frozen, _Strategy((intent,)), state)

    def fail(*_: object, **__: object) -> object:
        raise RuntimeError(f"{boundary} fault")

    if boundary == "data":
        monkeypatch.setattr(execution_phase, "exact_execution_snapshot", fail)
    elif boundary == "order":
        monkeypatch.setattr(execution_phase, "plan_orders", fail)
    elif boundary == "exchange":
        monkeypatch.setattr(AcademicExchange, "execute", fail)
    elif boundary == "account":
        monkeypatch.setattr(flow._context.account, "prepare_fill", fail)
    elif boundary == "publication":
        monkeypatch.setattr(state, "prepare_feedback", fail)
    else:
        # Valuation now reads the execution snapshot the fill was priced from, so the seam that
        # can fault is that reader rather than a separate observation subscription.
        monkeypatch.setattr(execution_phase, "_marks_from_execution_snapshot", fail)

    with pytest.raises(SimulationFailure) as raised:
        flow.run()

    failure = raised.value
    assert failure.stage is stage
    assert failure.kind is (
        SimulationFailureKind.FAILED_AFTER_COMMIT
        if after_commit
        else SimulationFailureKind.PRE_COMMIT
    )
    assert failure.mutation is after_commit
    assert failure.retry_precondition.requires_replay_from_root is True
    stamped_pending = state.current.pending_accepted_intent
    assert failure.pending_id == (None if after_commit else str(stamped_pending.intent.intent_id))
    assert failure.retry_precondition.required_pending_id == failure.pending_id
    assert failure.root_version == state.current.version == root_version
    assert failure.account_version == (1 if after_commit else 0)
    if after_commit:
        assert state.current.pending_accepted_intent is None
    else:
        assert state.current.pending_accepted_intent is not None

    if boundary == "data":
        assert failure.failed_requirement is registration
    elif boundary == "order":
        assert failure.failed_requirement.targets[0].instrument_id == "A"
    elif boundary == "exchange":
        assert failure.failed_requirement == frozen.exchange
    elif boundary == "account":
        assert failure.failed_requirement == AccountState(_ACCOUNT)
    elif boundary == "valuation":
        # Valuation has no configuration of its own since record `148`; the owner the failure
        # names is the strategy agenda whose fill instant the book was being valued at.
        assert failure.failed_requirement is frozen.strategy.agenda
    else:
        assert isinstance(failure.failed_requirement, FeedbackEvidence)


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
    intent = Rebalance(
        target_weights={"B": Decimal("0.1")},
        cash_weight=Decimal("0.9"),
        budget=_BUDGET,
    )

    result = _flow(
        _frozen((callback,), end=target, execution=registration, account=initial),
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
