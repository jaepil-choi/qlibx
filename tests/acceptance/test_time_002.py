from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import ExactExecutionTarget, FillConvention, FillSelector
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    exact_execution_snapshot,
    validate_execution_input,
)
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, FrozenAgenda, FrozenRun, StrategyConfig
from vqapr.flow.run_state import LifecycleKind, RunStateRepository
from vqapr.flow.simulation import AcceptedIntent, SimulationFlow
from vqapr.models.strategy_model import NoDecision, StrategyModel
from vqapr.portfolio.intents import PortfolioTarget, validate_economic_intent
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class _Intent:
    intent_id: UUID
    strategy_id: str
    targets: tuple[PortfolioTarget, ...]
    cash_target: Decimal
    budget: object
    source_refs: tuple[object, ...]
    account_version_seen: int
    model_state_ref: None = None


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset access: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source access: {raw_source_id}")


class _NoExecution:
    def execute(self, *args: object) -> object:
        raise AssertionError("this scenario must not execute")


class _Strategy(StrategyModel):
    def __init__(self, results: tuple[NoDecision | _Intent, ...]) -> None:
        self.results = iter(results)
        self.seen: list[tuple[str, datetime, int]] = []

    def on_occurrence(self, context: object) -> NoDecision | _Intent:
        occurrence = context.occurrence
        assert not hasattr(context, "future_occurrences")
        assert not hasattr(context, "execution_table")
        self.seen.append(
            (occurrence.occurrence_id, occurrence.evaluation_time, context.account.version)
        )
        self.memory = {"calls": len(self.seen)}
        return next(self.results)


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


def _frozen(
    callbacks: tuple[datetime, ...],
    *,
    valuations: tuple[datetime, ...] = (),
    monitoring: tuple[datetime, ...] = (),
    end: datetime | None = None,
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
        ConstraintSet(()),
        _agenda("strategy", OperationRole.STRATEGY_CALLBACK, *callbacks),
        _agenda("valuation", OperationRole.VALUATION, *valuations),
        monitor,
        _agenda("monitoring", OperationRole.MONITORING, *monitoring) if monitor else None,
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
        account=Account(AccountSnapshot(0, Decimal("100"), {}), mode=AccountMode.LONG_ONLY),
        exchange=_NoExecution(),
        constraints=(),
        marks_for_occurrence=lambda *_: {},
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

    result = _flow(_frozen((nine, ten)), strategy, RunStateRepository()).run()

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
                _frozen((datetime(2024, 3, 5, 13, tzinfo=KST),)),
                _Strategy((NoDecision("daily"),)),
                RunStateRepository(),
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
            _frozen((datetime(2024, 3, 5, 5, tzinfo=KST),)),
            _Strategy((NoDecision("no row required"),)),
            RunStateRepository(),
        )
        .run()
        .final_state.current_model_state_ref
        is not None
    )


@pytest.mark.uc("UC-TIME-002")
def test_callback_free_valuation_and_monitoring_are_independent_agendas() -> None:
    noon = datetime(2024, 3, 5, 12, tzinfo=KST)
    frozen = _frozen((), valuations=(noon,), monitoring=(noon.replace(minute=5),))

    result = _flow(frozen, _Strategy(()), RunStateRepository()).run()

    assert [trace.occurrence.role for trace in result.occurrences] == [
        OperationRole.VALUATION,
        OperationRole.MONITORING,
    ]


@pytest.mark.uc("UC-TIME-002")
def test_strategy_payload_has_no_timing_authority_and_flow_stamps_current_occurrence() -> None:
    payload = _Intent(UUID(int=1), "strategy", (), Decimal("1"), "budget", (), 0)
    at = datetime(2024, 3, 5, 4, tzinfo=KST)
    target = ExactExecutionTarget(
        UUID(int=2),
        "execution",
        datetime(2024, 3, 5, 15, 30, tzinfo=KST),
        FillSelector.SAME_DAY,
        "close",
    )
    timed = type("Timed", (), {})()
    for field in (
        "intent_id",
        "strategy_id",
        "targets",
        "cash_target",
        "budget",
        "source_refs",
        "account_version_seen",
        "model_state_ref",
    ):
        setattr(timed, field, getattr(payload, field))
    timed.decision_time = at

    with pytest.raises(ValueError, match="decision_time"):
        validate_economic_intent(timed)
    accepted = AcceptedIntent(
        payload, _occurrence("current", OperationRole.STRATEGY_CALLBACK, at), at, target
    )
    assert accepted.decision_time == at


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
    class DifferentConstraint:
        constraint_id = "other"

        def evaluate(self, account: object, marks: object) -> object:
            raise AssertionError("identity mismatch must fail before evaluation")

    constraint = _component("risk", ComponentKind.CONSTRAINT)
    frozen = _frozen((datetime(2024, 3, 5, 9, tzinfo=KST),))
    with pytest.raises(ValueError, match="exactly match"):
        SimulationFlow(
            frozen,
            _Strategy((NoDecision("x"),)),
            RunStateRepository(),
            window_for_occurrence=lambda _: None,
            account=Account(
                AccountSnapshot(0, Decimal("1"), {}),
                mode=AccountMode.LONG_ONLY,
            ),
            exchange=_NoExecution(),
            constraints=(DifferentConstraint(),),
            marks_for_occurrence=lambda *_: {},
        )
    assert frozen.constraints.constraints == ()
    assert ConstraintSet((constraint,)).constraints == (constraint,)


@pytest.mark.uc("UC-TIME-002")
def test_latest_replacement_and_failure_preserve_pending_authority() -> None:
    first = type("Pending", (), {"pending_id": "first"})()
    latest = type("Pending", (), {"pending_id": "latest"})()
    state = RunStateRepository(pending_accepted_intent=first)

    no_decision = state.accept_no_decision({"calls": 1}, detail=NoDecision("warmup"))
    replaced = state.accept_intent({"calls": 2}, latest, detail=latest)
    before_failed_replacement = state.current
    with pytest.raises(TypeError):
        state.accept_intent({"calls": 3}, object(), recorder=object())

    assert no_decision.pending_accepted_intent is first
    assert replaced.pending_accepted_intent is latest
    assert state.current is before_failed_replacement
    assert state.current.recorder_rows == {}
    assert [item.kind for item in state.current.lifecycle_trace] == [
        LifecycleKind.NO_DECISION,
        LifecycleKind.ACCEPTED_INTENT,
    ]


@pytest.mark.uc("UC-TIME-002")
def test_due_completion_consumes_only_matching_pending_and_leaves_no_pending_for_finalization() -> (
    None
):
    pending = type("Pending", (), {"pending_id": "accepted-10"})()
    state = RunStateRepository(pending_accepted_intent=pending)

    with pytest.raises(RuntimeError, match="does not match"):
        state.complete_due(
            pending_id="old-09",
            account_declaration={"cash": 1},
            account_version=1,
            fill="fill",
            mark="mark",
        )
    completed = state.complete_due(
        pending_id="accepted-10",
        account_declaration={"cash": 1},
        account_version=1,
        fill="fill",
        mark="mark",
        feedback=("feedback",),
    )

    assert completed.pending_accepted_intent is None
    assert completed.feedback == ("feedback",)
    assert completed.lifecycle_trace[-1].kind is LifecycleKind.DUE_EXECUTED
