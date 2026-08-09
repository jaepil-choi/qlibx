from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from qlibx import (
    AcademicInstrumentKind,
    AcademicInstrumentListing,
    AcademicPriceSemantics,
    AcademicRunSpec,
    OutcomeStatus,
    QlibxProject,
)
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.errors import CommitStatus, OperationError, OperationOutcome
from qlibx.flow import (
    ACADEMIC_EXECUTION_CONTRACT,
    ACADEMIC_RUN_RESULT_CONTRACT,
)
from qlibx.portfolio import (
    ConstructionProfile,
    PortfolioConstructionResult,
    PortfolioWeight,
)

KST = ZoneInfo("Asia/Seoul")


def at(day: int) -> datetime:
    return datetime(2024, 1, day, 15, 30, tzinfo=KST)


def project(tmp_path: Path) -> QlibxProject:
    root = tmp_path / "academic-project"
    QlibxProject.init(root, apply=True)
    (root / "market.csv").write_text(
        "time,available_at,instrument,close\n"
        "2024-01-02T15:30:00+09:00,2024-01-02T15:30:00+09:00,A,100\n"
        "2024-01-02T15:30:00+09:00,2024-01-02T15:30:00+09:00,B,100\n"
        "2024-01-03T15:30:00+09:00,2024-01-03T15:30:00+09:00,A,100\n"
        "2024-01-03T15:30:00+09:00,2024-01-03T15:30:00+09:00,B,100\n"
        "2024-01-03T15:30:00+09:00,2024-01-03T15:30:00+09:00,E,50\n"
        "2024-01-03T15:30:00+09:00,2024-01-03T15:30:00+09:00,I,2500\n"
        "2024-01-03T15:30:00+09:00,2024-01-03T15:30:00+09:00,F,1.25\n"
        "2024-01-04T15:30:00+09:00,2024-01-04T15:30:00+09:00,A,105\n"
        "2024-01-04T15:30:00+09:00,2024-01-04T15:30:00+09:00,B,95\n"
        "2024-01-05T15:30:00+09:00,2024-01-05T15:30:00+09:00,A,110\n"
        "2024-01-05T15:30:00+09:00,2024-01-05T15:30:00+09:00,B,90\n",
        encoding="utf-8",
    )
    selected = QlibxProject.open(root)
    registered = selected.register_dataset(
        DatasetRegistration(
            dataset_id="academic-market",
            source="market.csv",
            source_format=SourceFormat.CSV,
            instrument_field="instrument",
            observation_time_field="time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("time", "available_at", "instrument"),
            semantic_bindings={"execution_price": "close"},
            source_provenance="bounded public AcademicExchange fixture",
        )
    )
    assert registered.status is OutcomeStatus.COMPLETE
    return selected


def listing(
    instrument_id: str,
    kind: AcademicInstrumentKind = AcademicInstrumentKind.STOCK,
) -> AcademicInstrumentListing:
    semantics = {
        AcademicInstrumentKind.STOCK: AcademicPriceSemantics.TRADED_REFERENCE,
        AcademicInstrumentKind.ETF: AcademicPriceSemantics.TRADED_REFERENCE,
        AcademicInstrumentKind.INDEX: AcademicPriceSemantics.TRACKING_ONLY_REFERENCE,
        AcademicInstrumentKind.FACTOR: AcademicPriceSemantics.SYNTHETIC_UNIT_PRICE,
    }[kind]
    return AcademicInstrumentListing(
        instrument_id=instrument_id,
        kind=kind,
        currency="KRW",
        dataset_id="academic-market",
        price_role="execution_price",
        price_semantics=semantics,
    )


def portfolio(
    evaluation_time: datetime,
    weights: tuple[tuple[str, float], ...],
    *,
    profile: ConstructionProfile = ConstructionProfile.HYPOTHETICAL_SIGNED,
) -> PortfolioConstructionResult:
    target_weights = tuple(
        PortfolioWeight(instrument=instrument, weight=weight)
        for instrument, weight in weights
    )
    gross = sum(abs(item.weight) for item in target_weights)
    return PortfolioConstructionResult(
        invocation_id=f"portfolio-{evaluation_time.date().isoformat()}",
        source_artifact_id="strategy-source",
        source_strategy_id="test.academic",
        evaluation_time=evaluation_time,
        profile=profile,
        original_weights=target_weights,
        target_weights=target_weights,
        requested_budget=gross,
        realized_gross=gross,
        realized_net=sum(item.weight for item in target_weights),
        cash_residual=0,
        diagnostics=("frozen test portfolio",),
    )


def publish_portfolio(
    selected: QlibxProject,
    payload: PortfolioConstructionResult,
) -> str:
    outcome = selected.artifacts.publish_model(
        logical_identity=f"test:{payload.invocation_id}",
        artifact_type="portfolio_construction_result",
        artifact_schema_version=2,
        producer_id="tests.academic.portfolio",
        payload=payload,
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return outcome.result.artifact_id


def run_spec(portfolio_ids: tuple[str, ...], *, run_id: str = "academic-public") -> AcademicRunSpec:
    return AcademicRunSpec(
        run_id=run_id,
        portfolio_artifact_ids=portfolio_ids,
        initial_nav=1_000.0,
        base_currency="KRW",
        listings=(listing("A"), listing("B")),
        session_closes=(at(2), at(3), at(4), at(5)),
    )


def two_portfolios(selected: QlibxProject) -> tuple[str, str]:
    return (
        publish_portfolio(selected, portfolio(at(2), (("A", 0.6), ("B", -0.4)))),
        publish_portfolio(selected, portfolio(at(4), (("A", -0.5), ("B", 0.5)))),
    )


def test_public_academic_facade_executes_stocks_at_next_session_close(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    portfolio_ids = two_portfolios(selected)

    outcome = selected.run_academic(run_spec(portfolio_ids))

    assert outcome.status is OutcomeStatus.COMPLETE
    assert len(outcome.result.execution_artifact_ids) == 2
    assert outcome.result.total_cost == 0
    assert outcome.result.final_snapshot.event_time == at(5)
    assert outcome.result.final_snapshot.nav == pytest.approx(1_100.0)
    assert outcome.result.final_snapshot.gross_exposure == pytest.approx(1.0)
    assert outcome.result.final_snapshot.net_exposure == pytest.approx(0.0)
    assert any(position.quantity < 0 for position in outcome.result.final_state.positions)

    first = selected.load_artifact(
        outcome.result.execution_artifact_ids[0],
        ACADEMIC_EXECUTION_CONTRACT,
    )
    assert first.result.payload.event_time == at(3)
    assert first.result.payload.portfolio_evaluation_time == at(2)
    assert {fill.instrument_id for fill in first.result.payload.match.fills} == {"A", "B"}
    assert all(fill.hypothetical for fill in first.result.payload.match.fills)
    dependency_kinds = {
        edge.dependency_kind for edge in first.result.envelope.dependencies
    }
    assert {"artifact", "config", "dataset"}.issubset(dependency_kinds)


def test_public_academic_replay_and_resume_are_idempotent(tmp_path: Path) -> None:
    selected = project(tmp_path)
    selected_spec = run_spec(two_portfolios(selected))
    baseline = selected.run_academic(selected_spec)

    resumed = selected.run_academic(selected_spec, resume=True)

    assert resumed.status is OutcomeStatus.COMPLETE
    assert resumed.result == baseline.result
    assert len(
        selected.artifacts.list_envelopes(artifact_type="academic_execution_result")
    ) == 2
    assert len(selected.artifacts.list_envelopes(artifact_type="academic_checkpoint")) == 2
    assert len(selected.artifacts.list_envelopes(artifact_type="academic_run_result")) == 1
    loaded = selected.load_artifact(
        resumed.diagnostics[0].artifact_id,
        ACADEMIC_RUN_RESULT_CONTRACT,
    )
    assert loaded.result.payload == baseline.result


def test_checkpoint_publication_failure_recovers_without_duplicate_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = project(tmp_path)
    selected_spec = run_spec(two_portfolios(selected), run_id="academic-recovery")
    original_publish = selected.artifacts.publish_model
    failed_once = False

    def fail_first_checkpoint(**kwargs: Any) -> OperationOutcome:
        nonlocal failed_once
        if kwargs["artifact_type"] == "academic_checkpoint" and not failed_once:
            failed_once = True
            return OperationOutcome(
                status=OutcomeStatus.FAILED,
                errors=(
                    OperationError(
                        operation="artifact.publish",
                        stage_path="artifact.publish.test_crash",
                        error_code="TEST_CHECKPOINT_CRASH",
                        commit_status=CommitStatus.NONE,
                        idempotency_identity=selected_spec.run_id,
                        error_id="error-test-checkpoint-crash",
                    ),
                ),
            )
        return original_publish(**kwargs)

    monkeypatch.setattr(selected.artifacts, "publish_model", fail_first_checkpoint)
    interrupted = selected.run_academic(selected_spec)
    assert interrupted.status is OutcomeStatus.FAILED
    assert len(
        selected.artifacts.list_envelopes(artifact_type="academic_execution_result")
    ) == 1
    assert not selected.artifacts.list_envelopes(artifact_type="academic_checkpoint")

    monkeypatch.setattr(selected.artifacts, "publish_model", original_publish)
    recovered = selected.run_academic(selected_spec, resume=True)

    assert recovered.status is OutcomeStatus.COMPLETE
    assert len(
        selected.artifacts.list_envelopes(artifact_type="academic_execution_result")
    ) == 2
    assert len(selected.artifacts.list_envelopes(artifact_type="academic_checkpoint")) == 2


def test_wrong_portfolio_profile_fails_before_checkpoint(tmp_path: Path) -> None:
    selected = project(tmp_path)
    artifact_id = publish_portfolio(
        selected,
        portfolio(
            at(2),
            (("A", 1.0),),
            profile=ConstructionProfile.EQUITY_LONG_ONLY,
        ),
    )

    outcome = selected.run_academic(run_spec((artifact_id,), run_id="wrong-profile"))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "ACADEMIC_PORTFOLIO_PROFILE_UNSUPPORTED"
    assert outcome.errors[0].commit_status is CommitStatus.NONE
    assert not selected.artifacts.list_envelopes(artifact_type="academic_checkpoint")


def test_academic_flow_accepts_stock_etf_index_and_synthetic_factor(
    tmp_path: Path,
) -> None:
    selected = project(tmp_path)
    artifact_id = publish_portfolio(
        selected,
        portfolio(
            at(2),
            (("A", 0.25), ("E", 0.25), ("I", -0.25), ("F", -0.25)),
        ),
    )
    selected_spec = AcademicRunSpec(
        run_id="all-academic-kinds",
        portfolio_artifact_ids=(artifact_id,),
        initial_nav=1_000.0,
        base_currency="KRW",
        listings=(
            listing("A", AcademicInstrumentKind.STOCK),
            listing("E", AcademicInstrumentKind.ETF),
            listing("I", AcademicInstrumentKind.INDEX),
            listing("F", AcademicInstrumentKind.FACTOR),
        ),
        session_closes=(at(2), at(3)),
    )

    outcome = selected.run_academic(selected_spec)

    assert outcome.status is OutcomeStatus.COMPLETE
    execution = selected.load_artifact(
        outcome.result.execution_artifact_ids[0],
        ACADEMIC_EXECUTION_CONTRACT,
    )
    assert {item.instrument_id for item in execution.result.payload.match.fills} == {
        "A",
        "E",
        "F",
        "I",
    }
    factor_quote = next(
        item
        for item in execution.result.payload.match.quotes
        if item.instrument_id == "F"
    )
    assert factor_quote.price == 1.25
