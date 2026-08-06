"""Exact-cost batch matching with Qlib-derived clipping arithmetic.

The clipping order is derived from Microsoft Qlib qlib/backtest/exchange.py lines 786-952 in
snapshot main@79633dd (MIT). qlibx uses immutable DTOs, batch preflight, and structured diagnostics.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, model_validator

from qlibx.domain import Fill, Side
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.execution.instruments import (
    CompiledInstrument,
    CompiledInstrumentSet,
    EtfInstrument,
    FactorInstrument,
    IndexInstrument,
    Instrument,
    StockInstrument,
)
from qlibx.models import QlibxModel


class CostRule(QlibxModel):
    rule_id: str = Field(min_length=1)
    product_type: str = Field(pattern=r"^(stock|etf)$")
    side: Side
    effective_from: datetime
    effective_to: datetime | None = None
    rate: float = Field(ge=0)
    minimum_cost: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_interval(self) -> "CostRule":
        if self.effective_from.tzinfo is None:
            raise ValueError("cost rule times must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None:
                raise ValueError("cost rule times must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be after effective_from")
        return self


class KrxExchangeConfig(QlibxModel):
    exchange_id: str = "XKRX"
    schedule_version: str = Field(min_length=1)
    cost_rules: tuple[CostRule, ...]
    participation_rate: float | None = Field(default=None, gt=0, le=1)
    impact_rate: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def reject_overlapping_rules(self) -> "KrxExchangeConfig":
        for index, left in enumerate(self.cost_rules):
            for right in self.cost_rules[index + 1 :]:
                if (left.product_type, left.side) != (right.product_type, right.side):
                    continue
                left_end = left.effective_to or datetime.max.replace(
                    tzinfo=left.effective_from.tzinfo
                )
                right_end = right.effective_to or datetime.max.replace(
                    tzinfo=right.effective_from.tzinfo
                )
                if left.effective_from < right_end and right.effective_from < left_end:
                    raise ValueError("cost rules for the same exact selector must not overlap")
        return self


@dataclass(frozen=True, slots=True)
class Order:
    instrument_id: str
    side: Side
    quantity: float

    def __post_init__(self) -> None:
        if not self.instrument_id or not math.isfinite(self.quantity) or self.quantity < 0:
            raise ValueError("order requires an instrument and finite non-negative quantity")


@dataclass(frozen=True, slots=True)
class MarketQuote:
    instrument_id: str
    price: float
    available_volume: float | None = None
    total_market_volume: float | None = None


@dataclass(frozen=True, slots=True)
class FillDiagnostic:
    instrument_id: str
    requested_quantity: float
    dealt_quantity: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchBatchResult:
    fills: tuple[Fill, ...]
    diagnostics: tuple[FillDiagnostic, ...]
    ending_cash: float
    ending_holdings: tuple[tuple[str, float], ...]


class KrxExchange:
    """Frozen exchange registration compiled before batch execution."""

    def __init__(self, config: KrxExchangeConfig) -> None:
        self._config = config
        self._instruments: list[Instrument] = []
        self._instrument_ids: set[str] = set()

    def add_instrument(self, instrument: Instrument) -> None:
        if instrument.exchange_id != self._config.exchange_id:
            raise ValueError("instrument exchange_id does not match the registered exchange")
        if instrument.instrument_id in self._instrument_ids:
            raise ValueError("instrument_id is already registered")
        self._instrument_ids.add(instrument.instrument_id)
        self._instruments.append(instrument)

    def compile(self) -> CompiledInstrumentSet:
        compiled: list[CompiledInstrument] = []
        for instrument in self._instruments:
            if isinstance(instrument, (IndexInstrument, FactorInstrument)):
                continue
            if not isinstance(instrument, (StockInstrument, EtfInstrument)):
                raise TypeError(f"unsupported instrument model: {type(instrument).__name__}")
            compiled.append(
                CompiledInstrument(
                    index=len(compiled),
                    instrument_id=instrument.instrument_id,
                    product_type=instrument.kind,
                    lot_size=instrument.lot_size,
                    currency=instrument.currency,
                )
            )
        return CompiledInstrumentSet(tuple(compiled))

    def match_batch(
        self,
        *,
        event_id: str,
        event_time: datetime,
        orders: tuple[Order, ...],
        quotes: tuple[MarketQuote, ...],
        cash: float,
        holdings: dict[str, float],
    ) -> OperationOutcome:
        if event_time.tzinfo is None:
            raise ValueError("execution event_time must be timezone-aware")
        terms = self.compile().by_id()
        quote_by_id = {quote.instrument_id: quote for quote in quotes}
        resolved: list[tuple[Order, MarketQuote, CompiledInstrument, CostRule]] = []
        errors: list[OperationError] = []
        for index, order in enumerate(orders):
            instrument = terms.get(order.instrument_id)
            quote = quote_by_id.get(order.instrument_id)
            rule = self._resolve_cost(instrument, order.side, event_time) if instrument else None
            if instrument is None:
                errors.append(self._error(event_id, index, order, "INSTRUMENT_UNSUPPORTED"))
            elif quote is None or not math.isfinite(quote.price) or quote.price <= 0:
                errors.append(self._error(event_id, index, order, "EXECUTION_QUOTE_MISSING"))
            elif rule is None:
                errors.append(self._error(event_id, index, order, "EXACT_COST_RULE_MISSING"))
            else:
                resolved.append((order, quote, instrument, rule))
        if errors:
            return OperationOutcome(status=OutcomeStatus.UNSUPPORTED, errors=tuple(errors))

        candidate_cash = cash
        candidate_holdings = dict(holdings)
        fills: list[Fill] = []
        diagnostics: list[FillDiagnostic] = []
        for index, (order, quote, instrument, rule) in enumerate(resolved):
            quantity = order.quantity
            reasons: list[str] = []
            if self._config.participation_rate is not None and quote.available_volume is not None:
                capacity = max(quote.available_volume * self._config.participation_rate, 0)
                if quantity > capacity:
                    quantity = capacity
                    reasons.append("VOLUME_LIMIT")

            market_value = (
                quote.total_market_volume * quote.price
                if quote.total_market_volume is not None
                else 0
            )
            proposed_value = quantity * quote.price
            impact = (
                self._config.impact_rate * (proposed_value / market_value) ** 2
                if market_value > 0
                else self._config.impact_rate
            )
            effective_rate = rule.rate + impact

            if order.side is Side.SELL:
                held = max(candidate_holdings.get(order.instrument_id, 0), 0)
                if quantity > held:
                    quantity = held
                    reasons.append("HOLDING_LIMIT")
                if not math.isclose(quantity, held):
                    rounded = self._round_lot(quantity, instrument.lot_size)
                    if rounded != quantity:
                        reasons.append("LOT_ROUNDING")
                    quantity = rounded
                value = quantity * quote.price
                cost = self._cost(value, effective_rate, rule.minimum_cost)
                if candidate_cash + value < cost:
                    quantity = 0
                    reasons.append("COST_EXCEEDS_CASH")
            else:
                affordable = self._max_buy_quantity(
                    cash=candidate_cash,
                    price=quote.price,
                    lot_size=instrument.lot_size,
                    rate=effective_rate,
                    minimum_cost=rule.minimum_cost,
                )
                if quantity > affordable:
                    quantity = affordable
                    reasons.append("CASH_LIMIT")
                rounded = self._round_lot(quantity, instrument.lot_size)
                if rounded != quantity:
                    reasons.append("LOT_ROUNDING")
                quantity = rounded

            value = quantity * quote.price
            cost = self._cost(value, effective_rate, rule.minimum_cost)
            if value <= 1e-5 and "ZERO_VALUE" not in reasons:
                reasons.append("ZERO_VALUE")
            fill_seed = (
                f"{event_id}:{index}:{order.instrument_id}:{quantity}:{quote.price}".encode()
            )
            fill = Fill(
                fill_id=f"fill-{hashlib.sha256(fill_seed).hexdigest()[:24]}",
                instrument_id=order.instrument_id,
                side=order.side,
                requested_quantity=order.quantity,
                dealt_quantity=quantity,
                price=quote.price,
                trade_value=value,
                total_cost=cost,
                cost_rule_id=rule.rule_id,
                schedule_version=self._config.schedule_version,
            )
            fills.append(fill)
            diagnostics.append(
                FillDiagnostic(
                    instrument_id=order.instrument_id,
                    requested_quantity=order.quantity,
                    dealt_quantity=quantity,
                    reasons=tuple(reasons),
                )
            )
            signed_quantity = quantity if order.side is Side.BUY else -quantity
            candidate_holdings[order.instrument_id] = (
                candidate_holdings.get(order.instrument_id, 0) + signed_quantity
            )
            candidate_cash += value - cost if order.side is Side.SELL else -(value + cost)

        result = MatchBatchResult(
            fills=tuple(fills),
            diagnostics=tuple(diagnostics),
            ending_cash=candidate_cash,
            ending_holdings=tuple(sorted(candidate_holdings.items())),
        )
        return OperationOutcome(status=OutcomeStatus.COMPLETE, result=result)

    def _resolve_cost(
        self,
        instrument: CompiledInstrument | None,
        side: Side,
        event_time: datetime,
    ) -> CostRule | None:
        if instrument is None:
            return None
        matches = [
            rule
            for rule in self._config.cost_rules
            if rule.product_type == instrument.product_type
            and rule.side is side
            and rule.effective_from <= event_time
            and (rule.effective_to is None or event_time < rule.effective_to)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _cost(value: float, rate: float, minimum_cost: float) -> float:
        if value <= 1e-5:
            return 0
        return max(value * rate, minimum_cost)

    @classmethod
    def _max_buy_quantity(
        cls,
        *,
        cash: float,
        price: float,
        lot_size: int,
        rate: float,
        minimum_cost: float,
    ) -> float:
        high = max(math.floor(cash / (price * lot_size)), 0)
        low = 0
        while low < high:
            middle = (low + high + 1) // 2
            quantity = middle * lot_size
            value = quantity * price
            if value + cls._cost(value, rate, minimum_cost) <= cash:
                low = middle
            else:
                high = middle - 1
        return float(low * lot_size)

    @staticmethod
    def _round_lot(quantity: float, lot_size: int) -> float:
        return math.floor((quantity + 1e-12) / lot_size) * lot_size

    @staticmethod
    def _error(event_id: str, index: int, order: Order, code: str) -> OperationError:
        seed = hashlib.sha256(
            f"{event_id}:{index}:{order.instrument_id}:{code}".encode()
        ).hexdigest()
        return OperationError(
            operation="exchange.match_batch",
            stage_path="exchange.match_batch.preflight",
            error_code=code,
            context={"instrument_id": order.instrument_id, "side": order.side.value},
            commit_status=CommitStatus.NONE,
            retry_preconditions=("register an exact supported instrument, quote, and cost rule",),
            idempotency_identity=event_id,
            error_id=f"error-{seed[:24]}",
        )
