from datetime import UTC, datetime

import pytest

from qlibx import (
    AcademicBatchRequest,
    AcademicExchange,
    AcademicExchangeProfile,
    AcademicInstrumentKind,
    AcademicInstrumentListing,
    AcademicPortfolioState,
    AcademicPriceSemantics,
    AcademicQuote,
    AcademicRunSpec,
    AcademicTargetWeight,
)
from qlibx.errors import OutcomeStatus

EVENT_1 = datetime(2024, 2, 1, 6, 30, tzinfo=UTC)
EVENT_2 = datetime(2024, 3, 4, 6, 30, tzinfo=UTC)


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


def quote(instrument_id: str, price: float, event_time: datetime) -> AcademicQuote:
    return AcademicQuote(
        instrument_id=instrument_id,
        event_time=event_time,
        price=price,
        dataset_id="academic-market",
        registration_identity="registration-1",
        physical_fingerprint="physical-1",
        price_role="execution_price",
        selected_field="close",
        observation_time=event_time,
        available_at=event_time,
    )


def spec(*instruments: AcademicInstrumentListing) -> AcademicRunSpec:
    return AcademicRunSpec(
        run_id="academic-test",
        portfolio_artifact_ids=("portfolio-1",),
        initial_nav=100.0,
        base_currency="KRW",
        listings=instruments,
        session_closes=(EVENT_1, EVENT_2),
    )


def match(venue: AcademicExchange, **kwargs: object):
    return venue.match_batch(AcademicBatchRequest(**kwargs))


def test_profile_rejects_non_zero_friction() -> None:
    with pytest.raises(ValueError, match="exactly zero"):
        AcademicExchangeProfile(transaction_cost_rate=0.001)


def test_listing_requires_price_semantics_for_each_instrument_kind() -> None:
    for kind in AcademicInstrumentKind:
        assert listing(f"item-{kind.value}", kind).kind is kind

    with pytest.raises(ValueError, match="synthetic_unit_price"):
        AcademicInstrumentListing(
            instrument_id="factor-1",
            kind=AcademicInstrumentKind.FACTOR,
            currency="KRW",
            dataset_id="academic-market",
            price_role="execution_price",
            price_semantics=AcademicPriceSemantics.TRADED_REFERENCE,
        )


def test_signed_fractional_rebalance_and_cross_zero_accounting() -> None:
    listings = (listing("A"), listing("B"))
    venue = AcademicExchange(profile=AcademicExchangeProfile(), listings=listings)
    state = AcademicPortfolioState.seed(spec(*listings))

    opened = match(
        venue,
        event_id="event-1",
        event_time=EVENT_1,
        targets=(
            AcademicTargetWeight(instrument_id="A", weight=0.6),
            AcademicTargetWeight(instrument_id="B", weight=-0.4),
        ),
        quotes=(quote("A", 10.0, EVENT_1), quote("B", 20.0, EVENT_1)),
        state=state,
    )

    assert opened.status is OutcomeStatus.COMPLETE
    assert [fill.dealt_quantity for fill in opened.result.fills] == [6.0, 2.0]
    assert [position.quantity for position in opened.result.state.positions] == [6.0, -2.0]
    assert opened.result.after.financing_balance == pytest.approx(80.0)
    assert opened.result.after.nav == pytest.approx(100.0)
    assert opened.result.after.gross_exposure == pytest.approx(1.0)
    assert opened.result.after.net_exposure == pytest.approx(0.2)
    assert opened.result.turnover == pytest.approx(1.0)

    flipped = match(
        venue,
        event_id="event-2",
        event_time=EVENT_2,
        targets=(
            AcademicTargetWeight(instrument_id="A", weight=-0.5),
            AcademicTargetWeight(instrument_id="B", weight=0.5),
        ),
        quotes=(quote("A", 12.0, EVENT_2), quote("B", 10.0, EVENT_2)),
        state=opened.result.state,
    )

    assert flipped.status is OutcomeStatus.COMPLETE
    positions = {item.instrument_id: item for item in flipped.result.state.positions}
    assert positions["A"].quantity == pytest.approx(-5.5)
    assert positions["B"].quantity == pytest.approx(6.6)
    assert positions["A"].realized_pnl == pytest.approx(12.0)
    assert positions["B"].realized_pnl == pytest.approx(20.0)
    assert flipped.result.before.nav == pytest.approx(132.0)
    assert flipped.result.after.nav == pytest.approx(132.0)
    assert flipped.result.after.realized_pnl == pytest.approx(32.0)
    assert flipped.result.after.unrealized_pnl == pytest.approx(0.0)
    assert all(fill.transaction_cost == 0 for fill in flipped.result.fills)
    assert all(fill.hypothetical for fill in flipped.result.fills)


def test_missing_quote_rejects_whole_batch_without_mutating_state() -> None:
    listings = (listing("A"), listing("B"))
    venue = AcademicExchange(profile=AcademicExchangeProfile(), listings=listings)
    state = AcademicPortfolioState.seed(spec(*listings))

    outcome = match(
        venue,
        event_id="missing-quote",
        event_time=EVENT_1,
        targets=(
            AcademicTargetWeight(instrument_id="A", weight=0.5),
            AcademicTargetWeight(instrument_id="B", weight=-0.5),
        ),
        quotes=(quote("A", 10.0, EVENT_1),),
        state=state,
    )

    assert outcome.status is OutcomeStatus.UNSUPPORTED
    assert outcome.errors[0].error_code == "ACADEMIC_QUOTE_MISSING"
    assert state == AcademicPortfolioState.seed(spec(*listings))


def test_absent_target_liquidates_existing_position() -> None:
    listings = (listing("A"), listing("B"))
    venue = AcademicExchange(profile=AcademicExchangeProfile(), listings=listings)
    state = AcademicPortfolioState.seed(spec(*listings))
    opened = match(
        venue,
        event_id="open",
        event_time=EVENT_1,
        targets=(AcademicTargetWeight(instrument_id="A", weight=0.333),),
        quotes=(quote("A", 7.0, EVENT_1),),
        state=state,
    )

    closed = match(
        venue,
        event_id="close",
        event_time=EVENT_2,
        targets=(AcademicTargetWeight(instrument_id="B", weight=0.25),),
        quotes=(quote("A", 8.0, EVENT_2), quote("B", 11.0, EVENT_2)),
        state=opened.result.state,
    )

    positions = {item.instrument_id: item for item in closed.result.state.positions}
    assert positions["A"].quantity == 0
    assert positions["A"].average_entry_price is None
    assert positions["B"].quantity == pytest.approx(closed.result.before.nav * 0.25 / 11.0)
