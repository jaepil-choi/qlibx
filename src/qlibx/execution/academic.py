"""Zero-friction signed accounting for explicitly hypothetical research."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from qlibx.domain import Side
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.models import QlibxModel


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("academic event times must be timezone-aware")
    return value


class AcademicInstrumentKind(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"
    FACTOR = "factor"


class AcademicPriceSemantics(StrEnum):
    TRADED_REFERENCE = "traded_reference"
    TRACKING_ONLY_REFERENCE = "tracking_only_reference"
    SYNTHETIC_UNIT_PRICE = "synthetic_unit_price"


_PRICE_SEMANTICS = {
    AcademicInstrumentKind.STOCK: AcademicPriceSemantics.TRADED_REFERENCE,
    AcademicInstrumentKind.ETF: AcademicPriceSemantics.TRADED_REFERENCE,
    AcademicInstrumentKind.INDEX: AcademicPriceSemantics.TRACKING_ONLY_REFERENCE,
    AcademicInstrumentKind.FACTOR: AcademicPriceSemantics.SYNTHETIC_UNIT_PRICE,
}


class AcademicExchangeProfile(QlibxModel):
    """Fixed v1 realism declaration for hypothetical signed execution."""

    profile_id: Literal["academic.zero-friction.signed-fractional.v1"] = (
        "academic.zero-friction.signed-fractional.v1"
    )
    exchange_id: Literal["ACADEMIC"] = "ACADEMIC"
    execution_timing: Literal["next_session_close"] = "next_session_close"
    direction_policy: Literal["hypothetical_short"] = "hypothetical_short"
    fill_policy: Literal["full_fill"] = "full_fill"
    quantity_policy: Literal["fractional"] = "fractional"
    transaction_cost_rate: float = Field(default=0.0, ge=0)
    tax_rate: float = Field(default=0.0, ge=0)
    slippage_rate: float = Field(default=0.0, ge=0)
    market_impact_rate: float = Field(default=0.0, ge=0)
    borrow_cost_rate: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def require_zero_friction(self) -> AcademicExchangeProfile:
        values = (
            self.transaction_cost_rate,
            self.tax_rate,
            self.slippage_rate,
            self.market_impact_rate,
            self.borrow_cost_rate,
        )
        if any(not math.isfinite(value) or value != 0 for value in values):
            raise ValueError("academic v1 requires every friction term to be exactly zero")
        return self


class AcademicInstrumentListing(QlibxModel):
    instrument_id: str = Field(min_length=1)
    kind: AcademicInstrumentKind
    exchange_id: Literal["ACADEMIC"] = "ACADEMIC"
    currency: str = Field(min_length=3, max_length=3)
    dataset_id: str = Field(min_length=1)
    price_role: str = Field(min_length=1)
    price_semantics: AcademicPriceSemantics

    @model_validator(mode="after")
    def require_kind_price_semantics(self) -> AcademicInstrumentListing:
        expected = _PRICE_SEMANTICS[self.kind]
        if self.price_semantics is not expected:
            raise ValueError(
                f"{self.kind.value} requires price_semantics={expected.value}"
            )
        return self


class AcademicRunSpec(QlibxModel):
    """Frozen input for exact signed portfolio execution."""

    spec_schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    portfolio_artifact_ids: tuple[str, ...] = Field(min_length=1)
    initial_nav: float = Field(gt=0)
    base_currency: str = Field(min_length=3, max_length=3)
    listings: tuple[AcademicInstrumentListing, ...] = Field(min_length=1)
    session_closes: tuple[datetime, ...] = Field(min_length=1)
    profile: AcademicExchangeProfile = AcademicExchangeProfile()

    @model_validator(mode="after")
    def validate_frozen_run(self) -> AcademicRunSpec:
        if not math.isfinite(self.initial_nav):
            raise ValueError("initial_nav must be finite")
        if len(self.portfolio_artifact_ids) != len(set(self.portfolio_artifact_ids)):
            raise ValueError("portfolio artifact IDs must be unique")
        instruments = tuple(item.instrument_id for item in self.listings)
        if len(instruments) != len(set(instruments)):
            raise ValueError("academic instrument listings must be unique")
        if any(item.currency != self.base_currency for item in self.listings):
            raise ValueError("academic listing currency must match base_currency")
        closes = tuple(_require_aware(value) for value in self.session_closes)
        if closes != tuple(sorted(set(closes))):
            raise ValueError("session_closes must be unique and sorted")
        return self

    def frozen_config_fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"run_id"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class AcademicTargetWeight(QlibxModel):
    instrument_id: str = Field(min_length=1)
    weight: float

    @model_validator(mode="after")
    def require_finite_weight(self) -> AcademicTargetWeight:
        if not math.isfinite(self.weight):
            raise ValueError("academic target weight must be finite")
        return self


class AcademicQuote(QlibxModel):
    instrument_id: str = Field(min_length=1)
    event_time: datetime
    price: float = Field(gt=0)
    dataset_id: str = Field(min_length=1)
    registration_identity: str = Field(min_length=1)
    physical_fingerprint: str = Field(min_length=1)
    price_role: str = Field(min_length=1)
    selected_field: str = Field(min_length=1)
    observation_time: datetime
    available_at: datetime

    @model_validator(mode="after")
    def validate_quote(self) -> AcademicQuote:
        _require_aware(self.event_time)
        _require_aware(self.observation_time)
        _require_aware(self.available_at)
        if not math.isfinite(self.price):
            raise ValueError("academic quote price must be finite")
        if self.observation_time != self.event_time:
            raise ValueError("academic quote must exactly match the execution event")
        if self.available_at > self.event_time:
            raise ValueError("academic quote was not available at the execution event")
        return self


class AcademicPositionState(QlibxModel):
    instrument_id: str = Field(min_length=1)
    quantity: float
    average_entry_price: float | None = Field(default=None, gt=0)
    mark_price: float | None = Field(default=None, gt=0)
    marked_at: datetime | None = None
    realized_pnl: float = 0.0

    @model_validator(mode="after")
    def validate_position(self) -> AcademicPositionState:
        values = (self.quantity, self.realized_pnl)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("academic position values must be finite")
        if self.quantity != 0 and self.average_entry_price is None:
            raise ValueError("an open academic position requires an average entry price")
        if self.quantity == 0 and self.average_entry_price is not None:
            raise ValueError("a flat academic position cannot retain an average entry price")
        if self.marked_at is not None:
            _require_aware(self.marked_at)
        return self


class AcademicPortfolioState(QlibxModel):
    state_schema_version: Literal[1] = 1
    portfolio_id: str = Field(min_length=1)
    base_currency: str = Field(min_length=3, max_length=3)
    initial_nav: float = Field(gt=0)
    financing_balance: float
    positions: tuple[AcademicPositionState, ...] = ()
    version: int = Field(default=0, ge=0)
    event_cursor: int = Field(default=0, ge=0)
    as_of: datetime | None = None

    @model_validator(mode="after")
    def validate_state(self) -> AcademicPortfolioState:
        if not math.isfinite(self.initial_nav) or not math.isfinite(self.financing_balance):
            raise ValueError("academic state balances must be finite")
        instruments = tuple(item.instrument_id for item in self.positions)
        if instruments != tuple(sorted(set(instruments))):
            raise ValueError("academic positions must be unique and sorted")
        if self.as_of is not None:
            _require_aware(self.as_of)
        return self

    @classmethod
    def seed(cls, spec: AcademicRunSpec) -> AcademicPortfolioState:
        return cls(
            portfolio_id=f"academic:{spec.run_id}",
            base_currency=spec.base_currency,
            initial_nav=spec.initial_nav,
            financing_balance=spec.initial_nav,
        )


class AcademicPortfolioSnapshot(QlibxModel):
    portfolio_id: str
    event_time: datetime
    version: int = Field(ge=0)
    event_cursor: int = Field(ge=0)
    financing_balance: float
    nav: float
    gross_exposure: float = Field(ge=0)
    net_exposure: float
    realized_pnl: float
    unrealized_pnl: float
    positions: tuple[AcademicPositionState, ...]


class AcademicFill(QlibxModel):
    fill_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    side: Side
    requested_quantity: float = Field(gt=0)
    dealt_quantity: float = Field(gt=0)
    signed_quantity_change: float
    target_quantity: float
    price: float = Field(gt=0)
    notional: float = Field(gt=0)
    financing_change: float
    position_before: float
    position_after: float
    target_weight: float
    transaction_cost: Literal[0.0] = 0.0
    tax: Literal[0.0] = 0.0
    slippage_cost: Literal[0.0] = 0.0
    market_impact_cost: Literal[0.0] = 0.0
    borrow_cost: Literal[0.0] = 0.0
    hypothetical: Literal[True] = True
    profile_id: Literal["academic.zero-friction.signed-fractional.v1"] = (
        "academic.zero-friction.signed-fractional.v1"
    )


class AcademicMatchResult(QlibxModel):
    event_id: str
    event_time: datetime
    before: AcademicPortfolioSnapshot
    after: AcademicPortfolioSnapshot
    state: AcademicPortfolioState
    target_weights: tuple[AcademicTargetWeight, ...]
    fills: tuple[AcademicFill, ...]
    quotes: tuple[AcademicQuote, ...]
    turnover: float = Field(ge=0)
    total_cost: Literal[0.0] = 0.0


class AcademicExchange:
    """Full-fill venue for hypothetical signed fractional positions only."""

    def __init__(
        self,
        *,
        profile: AcademicExchangeProfile,
        listings: tuple[AcademicInstrumentListing, ...],
    ) -> None:
        self._profile = profile
        self._listings = {item.instrument_id: item for item in listings}
        if len(self._listings) != len(listings):
            raise ValueError("academic instrument listings must be unique")

    def match_batch(
        self,
        *,
        event_id: str,
        event_time: datetime,
        targets: tuple[AcademicTargetWeight, ...],
        quotes: tuple[AcademicQuote, ...],
        state: AcademicPortfolioState,
    ) -> OperationOutcome:
        _require_aware(event_time)
        errors = self._preflight(
            event_id=event_id,
            event_time=event_time,
            targets=targets,
            quotes=quotes,
            state=state,
        )
        if errors:
            return OperationOutcome(status=OutcomeStatus.UNSUPPORTED, errors=errors)

        quote_by_id = {item.instrument_id: item for item in quotes}
        target_by_id = {item.instrument_id: item.weight for item in targets}
        positions = {item.instrument_id: item for item in state.positions}
        marked = tuple(
            self._marked_position(position, quote_by_id.get(position.instrument_id), event_time)
            for position in state.positions
        )
        marked_state = state.model_copy(update={"positions": marked, "as_of": event_time})
        before = self._snapshot(marked_state, event_time)
        if before.nav <= 0:
            return OperationOutcome(
                status=OutcomeStatus.UNSUPPORTED,
                errors=(
                    self._error(
                        event_id,
                        "ACADEMIC_NAV_NON_POSITIVE",
                        {"nav": before.nav},
                    ),
                ),
            )

        all_instruments = sorted(set(positions) | set(target_by_id))
        candidate_positions = dict(positions)
        candidate_financing = state.financing_balance
        fills: list[AcademicFill] = []
        for index, instrument_id in enumerate(all_instruments):
            old = candidate_positions.get(
                instrument_id,
                AcademicPositionState(instrument_id=instrument_id, quantity=0),
            )
            quote = quote_by_id.get(instrument_id)
            weight = target_by_id.get(instrument_id, 0.0)
            if quote is None:
                continue  # preflight guarantees only flat, untargeted positions can omit a quote
            target_quantity = weight * before.nav / quote.price
            delta = target_quantity - old.quantity
            if delta == 0:
                candidate_positions[instrument_id] = old.model_copy(
                    update={"mark_price": quote.price, "marked_at": event_time}
                )
                continue
            updated = self._apply_fill(old, target_quantity, quote.price, event_time)
            candidate_positions[instrument_id] = updated
            candidate_financing -= delta * quote.price
            side = Side.BUY if delta > 0 else Side.SELL
            seed = (
                f"{event_id}:{index}:{instrument_id}:{delta:.17g}:{quote.price:.17g}"
            )
            fills.append(
                AcademicFill(
                    fill_id=f"academic-fill-{hashlib.sha256(seed.encode()).hexdigest()[:24]}",
                    event_id=event_id,
                    instrument_id=instrument_id,
                    side=side,
                    requested_quantity=abs(delta),
                    dealt_quantity=abs(delta),
                    signed_quantity_change=delta,
                    target_quantity=target_quantity,
                    price=quote.price,
                    notional=abs(delta * quote.price),
                    financing_change=-(delta * quote.price),
                    position_before=old.quantity,
                    position_after=target_quantity,
                    target_weight=weight,
                )
            )

        next_state = AcademicPortfolioState(
            portfolio_id=state.portfolio_id,
            base_currency=state.base_currency,
            initial_nav=state.initial_nav,
            financing_balance=candidate_financing,
            positions=tuple(candidate_positions[key] for key in sorted(candidate_positions)),
            version=state.version + 1,
            event_cursor=state.event_cursor + 1,
            as_of=event_time,
        )
        after = self._snapshot(next_state, event_time)
        turnover = sum(item.notional for item in fills) / before.nav
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=AcademicMatchResult(
                event_id=event_id,
                event_time=event_time,
                before=before,
                after=after,
                state=next_state,
                target_weights=tuple(sorted(targets, key=lambda item: item.instrument_id)),
                fills=tuple(fills),
                quotes=tuple(sorted(quotes, key=lambda item: item.instrument_id)),
                turnover=turnover,
            ),
        )

    def _preflight(
        self,
        *,
        event_id: str,
        event_time: datetime,
        targets: tuple[AcademicTargetWeight, ...],
        quotes: tuple[AcademicQuote, ...],
        state: AcademicPortfolioState,
    ) -> tuple[OperationError, ...]:
        errors: list[OperationError] = []
        target_ids = tuple(item.instrument_id for item in targets)
        quote_ids = tuple(item.instrument_id for item in quotes)
        if len(target_ids) != len(set(target_ids)):
            errors.append(self._error(event_id, "ACADEMIC_TARGET_DUPLICATE", {}))
        if len(quote_ids) != len(set(quote_ids)):
            errors.append(self._error(event_id, "ACADEMIC_QUOTE_DUPLICATE", {}))
        quote_by_id = {item.instrument_id: item for item in quotes}
        required = set(target_ids) | {
            item.instrument_id for item in state.positions if item.quantity != 0
        }
        for instrument_id in sorted(required):
            listing = self._listings.get(instrument_id)
            quote = quote_by_id.get(instrument_id)
            if listing is None:
                errors.append(
                    self._error(
                        event_id,
                        "ACADEMIC_LISTING_MISSING",
                        {"instrument_id": instrument_id},
                    )
                )
            elif quote is None:
                errors.append(
                    self._error(
                        event_id,
                        "ACADEMIC_QUOTE_MISSING",
                        {"instrument_id": instrument_id},
                    )
                )
            elif (
                quote.event_time != event_time
                or quote.dataset_id != listing.dataset_id
                or quote.price_role != listing.price_role
            ):
                errors.append(
                    self._error(
                        event_id,
                        "ACADEMIC_QUOTE_CONTRACT_MISMATCH",
                        {"instrument_id": instrument_id},
                    )
                )
        return tuple(errors)

    @staticmethod
    def _marked_position(
        position: AcademicPositionState,
        quote: AcademicQuote | None,
        event_time: datetime,
    ) -> AcademicPositionState:
        if quote is None:
            return position
        return position.model_copy(
            update={"mark_price": quote.price, "marked_at": event_time}
        )

    @staticmethod
    def _apply_fill(
        position: AcademicPositionState,
        target_quantity: float,
        price: float,
        event_time: datetime,
    ) -> AcademicPositionState:
        old_quantity = position.quantity
        old_average = position.average_entry_price
        realized = position.realized_pnl
        delta = target_quantity - old_quantity
        if old_quantity == 0:
            average = price
        elif target_quantity == 0:
            assert old_average is not None
            realized += abs(old_quantity) * (price - old_average) * math.copysign(
                1.0, old_quantity
            )
            average = None
        elif math.copysign(1.0, target_quantity) != math.copysign(1.0, old_quantity):
            assert old_average is not None
            realized += abs(old_quantity) * (price - old_average) * math.copysign(
                1.0, old_quantity
            )
            average = price
        elif abs(target_quantity) > abs(old_quantity):
            assert old_average is not None
            average = (
                abs(old_quantity) * old_average + abs(delta) * price
            ) / abs(target_quantity)
        else:
            assert old_average is not None
            realized += abs(delta) * (price - old_average) * math.copysign(
                1.0, old_quantity
            )
            average = old_average
        return AcademicPositionState(
            instrument_id=position.instrument_id,
            quantity=target_quantity,
            average_entry_price=average,
            mark_price=price,
            marked_at=event_time,
            realized_pnl=realized,
        )

    @staticmethod
    def _snapshot(
        state: AcademicPortfolioState,
        event_time: datetime,
    ) -> AcademicPortfolioSnapshot:
        market_values = tuple(
            position.quantity * (position.mark_price or 0.0)
            for position in state.positions
        )
        nav = state.financing_balance + sum(market_values)
        gross_value = sum(abs(value) for value in market_values)
        net_value = sum(market_values)
        realized = sum(position.realized_pnl for position in state.positions)
        unrealized = sum(
            (position.mark_price - position.average_entry_price) * position.quantity
            for position in state.positions
            if position.mark_price is not None and position.average_entry_price is not None
        )
        return AcademicPortfolioSnapshot(
            portfolio_id=state.portfolio_id,
            event_time=event_time,
            version=state.version,
            event_cursor=state.event_cursor,
            financing_balance=state.financing_balance,
            nav=nav,
            gross_exposure=gross_value / nav if nav > 0 else 0.0,
            net_exposure=net_value / nav if nav > 0 else 0.0,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            positions=state.positions,
        )

    @staticmethod
    def _error(
        event_id: str,
        code: str,
        context: dict[str, object],
    ) -> OperationError:
        seed = hashlib.sha256(f"{event_id}:{code}:{context}".encode()).hexdigest()[:24]
        return OperationError(
            operation="academic.exchange.match_batch",
            stage_path="academic.exchange.match_batch.preflight",
            error_code=code,
            context=context,
            commit_status=CommitStatus.NONE,
            retry_preconditions=(
                "provide exact hypothetical listings, PIT quotes, and a positive NAV",
            ),
            idempotency_identity=event_id,
            error_id=f"error-{seed}",
        )
