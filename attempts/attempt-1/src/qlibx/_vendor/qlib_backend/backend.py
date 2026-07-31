from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import qlib
from qlib.backtest.account import Account
from qlib.backtest.decision import Order, OrderDir
from qlib.config import C
from qlib.constant import REG_US

from .exchange import ScenarioExchange, build_quote_frame
from .result import (
    ACCOUNT_COLUMNS,
    FILL_COLUMNS,
    ORDER_COLUMNS,
    POSITION_COLUMNS,
    BackendRunResult,
)

DEFAULT_COST_POLICY = {
    "stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0},
    "etf": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0},
}

ACCOUNT_RECONCILIATION_TOLERANCE = 1e-8
ACCOUNT_RECONCILIATION_RELATIVE_TOLERANCE = 1e-12


@dataclass(frozen=True)
class ResumeState:
    next_position: int
    cash: float
    nav: float
    accumulated_return: float
    accumulated_cost: float
    accumulated_turnover: float
    adjusted_quantity: Mapping[str, float]
    quote_price: Mapping[str, float]
    next_order_number: int
    next_fill_number: int
    baseline_cash: float | None = None
    baseline_quantity: Mapping[str, int] | None = None
    previous_baseline_nav: float | None = None
    previous_active_nav: float | None = None
    next_capitalization_event_sequence: int = 0


@dataclass(frozen=True)
class MatchedCapitalizationInputs:
    signed_weights: pd.DataFrame | None
    observed: pd.DataFrame
    shortable: pd.DataFrame
    per_name_short_cap: float
    safety_multiplier: float = 1.0
    inventory_retention: str = "retained"


class QlibClosedLoopBackend:
    """Online target-to-order loop using real pyqlib Exchange and Account objects."""

    def run_targets(
        self,
        scenario: Any,
        target_weights: pd.DataFrame,
        *,
        signals: Mapping[str, pd.DataFrame] | None = None,
        selected_rules: pd.Series | None = None,
        research_rows: pd.DataFrame | None = None,
        observation_rows: pd.DataFrame | None = None,
        state_rows: pd.DataFrame | None = None,
        target_policy: Callable[[pd.Timestamp, Mapping[str, Any]], pd.Series] | None = None,
        signed_target_policy: Callable[[pd.Timestamp, Mapping[str, Any]], pd.Series] | None = None,
        matched_capitalization: MatchedCapitalizationInputs | None = None,
        start_position: int = 0,
        end_position: int | None = None,
        resume_state: ResumeState | None = None,
    ) -> BackendRunResult:
        if not C.registered:
            qlib.init(
                region=REG_US,
                expression_cache=None,
                dataset_cache=None,
            )
        market = _normalize_scenario(scenario)
        weights = _normalize_targets(target_weights, market["execution_price"])
        matched = _normalize_matched_capitalization(
            matched_capitalization, market["execution_price"]
        )
        if matched is not None and target_policy is not None:
            raise ValueError("matched_capitalization and target_policy cannot be used together")
        if matched is None and signed_target_policy is not None:
            raise ValueError("signed_target_policy requires matched_capitalization")
        if matched is not None:
            has_stored_weights = matched.signed_weights is not None
            has_adaptive_policy = signed_target_policy is not None
            if has_stored_weights == has_adaptive_policy:
                raise ValueError("matched_capitalization requires exactly one signed weight source")
        if matched is not None and resume_state is not None:
            matched_resume_values = (
                resume_state.baseline_cash,
                resume_state.baseline_quantity,
                resume_state.previous_baseline_nav,
                resume_state.previous_active_nav,
            )
            if any(value is None for value in matched_resume_values):
                raise ValueError("matched_capitalization resume_state is missing baseline state")
        if (
            matched is None
            and resume_state is not None
            and resume_state.baseline_quantity is not None
        ):
            raise ValueError("long-only resume_state must not contain matched capitalization state")
        stop_position = len(weights) if end_position is None else int(end_position)
        if start_position < 0 or start_position > len(weights):
            raise ValueError("start_position is outside the decision calendar")
        if stop_position < start_position or stop_position > len(weights):
            raise ValueError("end_position is outside the decision calendar")
        if start_position and resume_state is None:
            raise ValueError("resume_state is required when start_position is nonzero")
        if resume_state is not None and resume_state.next_position != start_position:
            raise ValueError("resume_state next_position does not match start_position")

        quote = build_quote_frame(
            market["execution_price"],
            market["position_unit_factor"],
            market["volume"],
            market["buyable"],
            market["sellable"],
            market["suspended"],
            market["upper_price_limit"],
            market["lower_price_limit"],
            max_volume_participation=market["max_volume_participation"],
            valuation_price=market["valuation_price"],
        )
        volume_threshold = None
        if market["max_volume_participation"] is not None:
            volume_threshold = ("cum", "$volume_limit")
        exchange = ScenarioExchange(
            quote_frame=quote,
            asset_class=market["asset_class"].to_dict(),
            cost_policy=market["cost_policy"],
            lot_size=market["lot_size"].to_dict(),
            freq="day",
            start_time=weights.index[0],
            end_time=weights.index[-1],
            codes=weights.columns.tolist(),
            deal_price="$deal_price",
            limit_threshold=("$limit_buy", "$limit_sell"),
            volume_threshold=volume_threshold,
            open_cost=0.0,
            close_cost=0.0,
            min_cost=0.0,
            impact_cost=0.0,
            trade_unit=None,
            subscribe_fields=[
                "$suspended",
                "$upper_price_limit",
                "$lower_price_limit",
            ],
        )

        account, previous_nav, order_number, fill_number = _build_account(market, resume_state)
        order_rows: list[dict[str, Any]] = []
        fill_rows: list[dict[str, Any]] = []
        position_rows: list[dict[str, Any]] = []
        account_rows: list[dict[str, Any]] = []
        feedback_rows: list[dict[str, Any]] = []
        reconciliation_errors: list[float] = []
        signed_position_rows: list[dict[str, Any]] = []
        capitalization_event_rows: list[dict[str, Any]] = []
        baseline_account_rows: list[dict[str, Any]] = []
        active_account_rows: list[dict[str, Any]] = []
        if matched is not None and resume_state is not None:
            baseline_quantity = (
                pd.Series(
                    resume_state.baseline_quantity,
                    index=weights.columns,
                    dtype="float64",
                )
                .fillna(0.0)
                .astype("int64")
            )
            baseline_cash = float(resume_state.baseline_cash)
            previous_baseline_nav = float(resume_state.previous_baseline_nav)
            previous_active_nav = float(resume_state.previous_active_nav)
            capitalization_event_sequence = int(resume_state.next_capitalization_event_sequence)
        else:
            baseline_quantity = pd.Series(0, index=weights.columns, dtype="int64")
            baseline_cash = float(market["baseline_booksize"])
            previous_baseline_nav = float(market["baseline_booksize"])
            previous_active_nav = float(market["active_booksize"])
            capitalization_event_sequence = 0

        for offset in range(start_position, stop_position):
            date = pd.Timestamp(weights.index[offset])
            factor = market["position_unit_factor"].loc[date]
            price = market["execution_price"].loc[date]
            valuation_price = market["valuation_price"].loc[date]
            lot_size = market["lot_size"]
            current_adjusted = pd.Series(
                {
                    instrument: account.current_position.get_stock_amount(instrument)
                    for instrument in weights.columns
                },
                dtype="float64",
            )
            current_physical_quantity = current_adjusted.mul(factor)
            pretrade_cash = float(account.current_position.get_cash())
            pretrade_market_value = current_physical_quantity.mul(price)
            pretrade_nav = pretrade_cash + float(pretrade_market_value.sum())
            if pretrade_nav <= 0:
                raise ValueError("Qlib pre-trade NAV must be positive")
            intended_weight: pd.Series | None = None
            signed_target_quantity: pd.Series | None = None
            if matched is not None:
                baseline_nav_before = baseline_cash + float(
                    baseline_quantity.astype("float64").mul(price).sum()
                )
                active_pretrade_nav = pretrade_nav - baseline_nav_before
                if active_pretrade_nav <= 0:
                    raise ValueError("active pre-trade NAV must be positive")
                current_signed_quantity = current_physical_quantity.sub(baseline_quantity)
                current_signed_weight = current_signed_quantity.mul(price).div(active_pretrade_nav)
                if signed_target_policy is None:
                    if matched.signed_weights is None:
                        raise RuntimeError("stored signed weights are missing")
                    proposed_weight = matched.signed_weights.loc[date]
                else:
                    proposed_weight = signed_target_policy(
                        date,
                        {
                            "last_feedback_date": (
                                None
                                if not active_account_rows
                                else active_account_rows[-1]["trade_date"]
                            ),
                            "last_portfolio_return": (
                                None
                                if not active_account_rows
                                else active_account_rows[-1]["portfolio_return"]
                            ),
                            "account_history": tuple(dict(row) for row in active_account_rows),
                            "fill_history": tuple(dict(row) for row in fill_rows),
                            "current_physical_quantity": current_physical_quantity.copy(),
                            "current_physical_weight": (
                                pretrade_market_value / pretrade_nav
                            ).astype("float64"),
                            "current_signed_quantity": current_signed_quantity.copy(),
                            "current_signed_weight": current_signed_weight.astype("float64"),
                            "current_baseline_quantity": baseline_quantity.copy(),
                            "current_cash_weight": (pretrade_cash - baseline_cash)
                            / active_pretrade_nav,
                            "current_nav": active_pretrade_nav,
                            "current_composite_nav": pretrade_nav,
                        },
                    )
                    proposed_weight = _normalize_policy_target(
                        proposed_weight,
                        weights.columns,
                        signed=True,
                    )
                intended_weight = proposed_weight.where(
                    matched.observed.loc[date] & market["universe"].loc[date],
                    0.0,
                )
                unavailable_short = intended_weight.lt(0.0) & (
                    ~matched.shortable.loc[date] | ~market["sellable"].loc[date]
                )
                intended_weight = intended_weight.mask(unavailable_short, 0.0)
                additions = _required_baseline_additions(
                    intended_weight=intended_weight,
                    baseline_quantity=baseline_quantity,
                    active_nav=active_pretrade_nav,
                    execution_price=price,
                    lot_size=lot_size,
                    per_name_short_cap=matched.per_name_short_cap,
                    safety_multiplier=matched.safety_multiplier,
                )
                debit = float(additions.astype("float64").mul(price).sum())
                if debit > baseline_cash + ACCOUNT_RECONCILIATION_TOLERANCE:
                    raise ValueError(
                        "matched capitalization funding reserve is insufficient: "
                        f"required={debit}, available={baseline_cash}"
                    )
                if additions.gt(0).any():
                    baseline_before = baseline_quantity.copy()
                    baseline_cash_before = baseline_cash
                    _apply_capitalization(
                        account=account,
                        additions=additions,
                        execution_price=price,
                        position_unit_factor=factor,
                        trade_date=date,
                    )
                    baseline_quantity = baseline_quantity.add(additions).astype("int64")
                    baseline_cash -= debit
                    if baseline_cash < -ACCOUNT_RECONCILIATION_TOLERANCE:
                        raise RuntimeError("matched capitalization baseline cash became negative")
                    for instrument, quantity in additions.loc[additions.gt(0)].items():
                        event_debit = float(quantity) * float(price[instrument])
                        capitalization_event_rows.append(
                            {
                                "trade_date": date,
                                "event_sequence": capitalization_event_sequence,
                                "instrument_id": str(instrument),
                                "event_type": (
                                    "activation"
                                    if int(baseline_before[instrument]) == 0
                                    else "top_up"
                                ),
                                "quantity": int(quantity),
                                "execution_price": float(price[instrument]),
                                "cash_change": -event_debit,
                                "baseline_quantity_before": int(baseline_before[instrument]),
                                "baseline_quantity_after": int(baseline_quantity[instrument]),
                                "baseline_cash_before": float(baseline_cash_before),
                                "baseline_cash_after": float(baseline_cash_before - event_debit),
                                "reason_code": "short_capacity",
                            }
                        )
                        capitalization_event_sequence += 1
                        baseline_cash_before -= event_debit
                    current_adjusted = pd.Series(
                        {
                            instrument: account.current_position.get_stock_amount(instrument)
                            for instrument in weights.columns
                        },
                        dtype="float64",
                    )
                    current_physical_quantity = current_adjusted.mul(factor)
                    pretrade_cash = float(account.current_position.get_cash())
                    pretrade_market_value = current_physical_quantity.mul(price)
                    capitalized_nav = pretrade_cash + float(pretrade_market_value.sum())
                    if not np.isclose(
                        capitalized_nav,
                        pretrade_nav,
                        atol=ACCOUNT_RECONCILIATION_TOLERANCE,
                        rtol=ACCOUNT_RECONCILIATION_RELATIVE_TOLERANCE,
                    ):
                        raise RuntimeError("matched capitalization changed composite NAV")
                raw_signed_target = intended_weight.mul(active_pretrade_nav).div(price)
                signed_target_quantity = _round_signed_target_quantity(raw_signed_target, lot_size)
                raw_target_physical = baseline_quantity.astype("float64").add(raw_signed_target)
                target_physical = baseline_quantity.add(signed_target_quantity).astype("int64")
                if target_physical.lt(0).any():
                    instrument = str(target_physical.idxmin())
                    raise ValueError(
                        "matched capitalization capacity is below signed target: "
                        f"instrument={instrument}"
                    )
                weights.loc[date] = target_physical.mul(price).div(pretrade_nav)
            elif target_policy is not None:
                decided = target_policy(
                    date,
                    {
                        "last_feedback_date": (
                            None if not account_rows else account_rows[-1]["trade_date"]
                        ),
                        "last_portfolio_return": (
                            None if not account_rows else account_rows[-1]["portfolio_return"]
                        ),
                        "account_history": tuple(dict(row) for row in account_rows),
                        "fill_history": tuple(dict(row) for row in fill_rows),
                        "current_physical_quantity": current_physical_quantity.copy(),
                        "current_physical_weight": (pretrade_market_value / pretrade_nav).astype(
                            "float64"
                        ),
                        "current_cash_weight": pretrade_cash / pretrade_nav,
                        "current_nav": pretrade_nav,
                    },
                )
                weights.loc[date] = _normalize_policy_target(
                    decided,
                    weights.columns,
                    signed=False,
                )
            if matched is None:
                raw_target_physical = _raw_target_quantity(weights.loc[date], pretrade_nav, price)
                target_physical = _round_target_quantity(raw_target_physical, lot_size)
            target_adjusted = target_physical.astype("float64").div(factor)
            delta = target_adjusted - current_adjusted

            # 같은 bar의 매도 대금을 Qlib buy cash limit가 사용할 수 있도록 매도를 먼저 처리합니다.
            order_specs = [
                (instrument, value) for instrument, value in delta.items() if value < -1e-12
            ] + [(instrument, value) for instrument, value in delta.items() if value > 1e-12]
            day_trade_value = 0.0
            day_trade_cost = 0.0
            dealt_order_amount: defaultdict[str, float] = defaultdict(float)
            for instrument, delta_adjusted in order_specs:
                direction = OrderDir.BUY if delta_adjusted > 0 else OrderDir.SELL
                requested_physical = round(abs(float(delta_adjusted)) * float(factor[instrument]))
                order_id = f"order-{order_number:08d}"
                order_number += 1
                order = Order(
                    stock_id=str(instrument),
                    amount=abs(float(delta_adjusted)),
                    direction=direction,
                    start_time=date,
                    end_time=date,
                )
                trade_val, trade_cost, _qlib_trade_price = exchange.deal_order(
                    order,
                    trade_account=account,
                    dealt_order_amount=dealt_order_amount,
                )
                dealt_order_amount[str(instrument)] += float(order.deal_amount)
                diagnostic = exchange.consume_last_diagnostic()
                filled_physical = round(float(order.deal_amount) * float(factor[instrument]))
                reason = _fill_reason(
                    direction=direction,
                    requested=requested_physical,
                    filled=filled_physical,
                    buyable=bool(market["buyable"].loc[date, instrument]),
                    sellable=bool(market["sellable"].loc[date, instrument]),
                )
                fill_id = f"fill-{fill_number:08d}"
                fill_number += 1
                order_rows.append(
                    {
                        "trade_date": date,
                        "order_id": order_id,
                        "instrument_id": str(instrument),
                        "direction": "buy" if direction == OrderDir.BUY else "sell",
                        "requested_quantity": requested_physical,
                        "raw_target_quantity": float(raw_target_physical[instrument]),
                        "target_quantity": int(target_physical[instrument]),
                        "lot_size": int(lot_size[instrument]),
                        "lot_rounding_quantity": float(
                            raw_target_physical[instrument] - target_physical[instrument]
                        ),
                    }
                )
                economic_price = (
                    float(trade_val) / filled_physical
                    if filled_physical
                    else float(price[instrument])
                )
                fill_rows.append(
                    {
                        "trade_date": date,
                        "fill_id": fill_id,
                        "order_id": order_id,
                        "instrument_id": str(instrument),
                        "filled_quantity": filled_physical,
                        "trade_price": economic_price,
                        "trade_value": float(trade_val),
                        "trade_cost": float(trade_cost),
                        "reason": reason,
                        "reason_code": diagnostic.reason_code,
                        "blocked_by": diagnostic.blocked_by,
                        "quantity_after_tradability": (
                            diagnostic.amount_after_tradability * float(factor[instrument])
                        ),
                        "quantity_after_volume": (
                            diagnostic.amount_after_volume * float(factor[instrument])
                        ),
                        "quantity_after_position": (
                            diagnostic.amount_after_position * float(factor[instrument])
                        ),
                        "quantity_after_cash": (
                            diagnostic.amount_after_cash * float(factor[instrument])
                        ),
                        "quantity_after_lot": (
                            diagnostic.amount_after_lot * float(factor[instrument])
                        ),
                        "asset_class": diagnostic.asset_class,
                        "execution_policy": diagnostic.execution_policy,
                        "effective_cost_rate": diagnostic.effective_cost_rate,
                        "short_enabled": diagnostic.short_enabled,
                    }
                )
                day_trade_value += float(trade_val)
                day_trade_cost += float(trade_cost)

            if matched is not None and matched.inventory_retention == "active_short_only":
                if intended_weight is None:
                    raise RuntimeError("matched capitalization intent is missing")
                composite_after_fill = pd.Series(
                    {
                        instrument: round(
                            float(account.current_position.get_stock_amount(instrument))
                            * float(factor[instrument])
                        )
                        for instrument in weights.columns
                    },
                    dtype="int64",
                )
                active_after_fill = composite_after_fill - baseline_quantity
                minimum_baseline = (-active_after_fill).clip(lower=0)
                minimum_baseline = minimum_baseline.where(
                    ~intended_weight.lt(-1e-12), baseline_quantity
                ).astype("int64")
                releases = (baseline_quantity - minimum_baseline).clip(lower=0)
                if releases.gt(0).any():
                    baseline_before = baseline_quantity.copy()
                    baseline_cash_before = baseline_cash
                    credit = float(releases.astype("float64").mul(price).sum())
                    _apply_decapitalization(
                        account=account,
                        releases=releases,
                        execution_price=price,
                        position_unit_factor=factor,
                        trade_date=date,
                    )
                    baseline_quantity = baseline_quantity.sub(releases).astype("int64")
                    baseline_cash += credit
                    for instrument, quantity in releases.loc[releases.gt(0)].items():
                        event_credit = float(quantity) * float(price[instrument])
                        capitalization_event_rows.append(
                            {
                                "trade_date": date,
                                "event_sequence": capitalization_event_sequence,
                                "instrument_id": str(instrument),
                                "event_type": "release",
                                "quantity": int(quantity),
                                "execution_price": float(price[instrument]),
                                "cash_change": event_credit,
                                "baseline_quantity_before": int(baseline_before[instrument]),
                                "baseline_quantity_after": int(baseline_quantity[instrument]),
                                "baseline_cash_before": float(baseline_cash_before),
                                "baseline_cash_after": float(baseline_cash_before + event_credit),
                                "reason_code": "active_short_only",
                            }
                        )
                        capitalization_event_sequence += 1
                        baseline_cash_before += event_credit

            account.update_current_position(date, date, exchange)
            account.update_portfolio_metrics(date, date)
            account.update_hist_positions(date)
            cash = float(account.current_position.get_cash())
            nav = float(account.current_position.calculate_value())
            net_return = 0.0 if previous_nav == 0 else nav / previous_nav - 1.0
            physical_quantities: dict[str, int] = {}
            position_value = 0.0
            for instrument in weights.columns:
                adjusted = account.current_position.get_stock_amount(instrument)
                physical = round(float(adjusted) * float(factor[instrument]))
                physical_quantities[str(instrument)] = physical
                if physical == 0:
                    continue
                market_value = float(physical * float(valuation_price[instrument]))
                position_value += market_value
                position_rows.append(
                    {
                        "trade_date": date,
                        "instrument_id": str(instrument),
                        "held_quantity": physical,
                        "market_value": market_value,
                        "asset_class": str(market["asset_class"].loc[instrument]),
                    }
                )
            reconciliation_error = abs(nav - (cash + position_value))
            _validate_account_reconciliation(
                nav=nav,
                cash=cash,
                position_value=position_value,
                tolerance=ACCOUNT_RECONCILIATION_TOLERANCE,
            )
            reconciliation_errors.append(reconciliation_error)
            account_rows.append(
                {
                    "trade_date": date,
                    "cash": cash,
                    "nav": nav,
                    "portfolio_return": net_return,
                    "trade_cost": day_trade_cost,
                    "turnover": 0.0 if previous_nav == 0 else day_trade_value / previous_nav,
                }
            )
            if matched is not None:
                if intended_weight is None or signed_target_quantity is None:
                    raise RuntimeError("matched capitalization decision is missing")
                baseline_market_value = float(
                    baseline_quantity.astype("float64").mul(valuation_price).sum()
                )
                if baseline_quantity.lt(0).any():
                    raise RuntimeError("matched capitalization baseline became negative")
                if baseline_cash < -ACCOUNT_RECONCILIATION_TOLERANCE:
                    raise RuntimeError("matched capitalization baseline cash became negative")
                baseline_nav = baseline_cash + baseline_market_value
                active_cash = cash - baseline_cash
                active_nav = nav - baseline_nav
                baseline_money_pnl = baseline_nav - previous_baseline_nav
                active_money_pnl = active_nav - previous_active_nav
                if not np.isclose(
                    nav,
                    baseline_nav + active_nav,
                    atol=ACCOUNT_RECONCILIATION_TOLERANCE,
                    rtol=ACCOUNT_RECONCILIATION_RELATIVE_TOLERANCE,
                ):
                    raise RuntimeError("composite/baseline/active NAV did not reconcile")
                for instrument in weights.columns:
                    composite_quantity = physical_quantities[str(instrument)]
                    baseline_held = int(baseline_quantity[instrument])
                    signed_position_rows.append(
                        {
                            "trade_date": date,
                            "instrument_id": str(instrument),
                            "intended_weight": float(intended_weight[instrument]),
                            "target_quantity": int(signed_target_quantity[instrument]),
                            "held_quantity": composite_quantity - baseline_held,
                            "baseline_quantity": baseline_held,
                            "composite_quantity": composite_quantity,
                        }
                    )
                baseline_account_rows.append(
                    {
                        "trade_date": date,
                        "cash": baseline_cash,
                        "nav": baseline_nav,
                        "money_pnl": baseline_money_pnl,
                        "return_denominator": float(market["baseline_return_denominator"]),
                        "portfolio_return": baseline_money_pnl
                        / float(market["baseline_return_denominator"]),
                        "trade_cost": 0.0,
                        "turnover": 0.0,
                    }
                )
                active_account_rows.append(
                    {
                        "trade_date": date,
                        "cash": active_cash,
                        "nav": active_nav,
                        "money_pnl": active_money_pnl,
                        "return_denominator": float(market["active_booksize"]),
                        "portfolio_return": active_money_pnl / float(market["active_booksize"]),
                        "trade_cost": day_trade_cost,
                        "turnover": day_trade_value / float(market["active_booksize"]),
                    }
                )
                feedback_rows.append(
                    {
                        "decision_date": date,
                        "feedback_date": (
                            pd.NaT if offset == 0 else pd.Timestamp(weights.index[offset - 1])
                        ),
                        "cash": active_cash,
                        "nav": active_nav,
                        "held_quantity": {
                            str(instrument): (
                                physical_quantities[str(instrument)]
                                - int(baseline_quantity[instrument])
                            )
                            for instrument in weights.columns
                        },
                    }
                )
                previous_baseline_nav = baseline_nav
                previous_active_nav = active_nav
            else:
                feedback_rows.append(
                    {
                        "decision_date": date,
                        "feedback_date": (
                            pd.NaT if offset == 0 else pd.Timestamp(weights.index[offset - 1])
                        ),
                        "cash": cash,
                        "nav": nav,
                        "held_quantity": physical_quantities,
                    }
                )
            previous_nav = nav

        orders = pd.DataFrame(order_rows, columns=ORDER_COLUMNS)
        fills = pd.DataFrame(fill_rows, columns=FILL_COLUMNS)
        positions = pd.DataFrame(position_rows, columns=POSITION_COLUMNS)
        if not orders.empty:
            orders = orders.astype(
                {
                    "requested_quantity": "int64",
                    "target_quantity": "int64",
                    "lot_size": "int64",
                }
            )
        else:
            orders = orders.astype(
                {
                    "requested_quantity": "int64",
                    "target_quantity": "int64",
                    "lot_size": "int64",
                }
            )
        fills = fills.astype(
            {
                "filled_quantity": "int64",
                "short_enabled": "bool",
            }
        )
        if not positions.empty:
            positions["held_quantity"] = positions["held_quantity"].astype("int64")
        else:
            positions = positions.astype({"held_quantity": "int64"})
        account_daily = pd.DataFrame(account_rows).set_index("trade_date")
        account_daily.index = pd.DatetimeIndex(account_daily.index, name="trade_date")
        account_daily = account_daily.loc[:, ACCOUNT_COLUMNS]

        signal_rows = _signal_rows(signals, weights)
        executed_dates = weights.index[start_position:stop_position]
        if not signal_rows.empty:
            signal_rows = signal_rows.loc[
                signal_rows["trade_date"].isin(executed_dates)
            ].reset_index(drop=True)
        result = BackendRunResult(
            decision_weights=weights.iloc[start_position:stop_position].copy(),
            order_rows=orders,
            fill_rows=fills,
            position_rows=positions,
            account_rows=account_daily,
            signal_rows=signal_rows,
            observation_rows=(
                pd.DataFrame() if observation_rows is None else observation_rows.copy()
            ),
            research_rows=(pd.DataFrame() if research_rows is None else research_rows.copy()),
            feedback_rows=pd.DataFrame(feedback_rows),
            state_rows=pd.DataFrame() if state_rows is None else state_rows.copy(),
            selected_rules=(
                pd.Series(dtype="object")
                if selected_rules is None
                else selected_rules.iloc[start_position:stop_position].copy()
            ),
            extra_tables=(
                {}
                if matched is None
                else {
                    "signed_positions": pd.DataFrame(signed_position_rows),
                    "capitalization_events": pd.DataFrame(
                        capitalization_event_rows,
                        columns=[
                            "trade_date",
                            "event_sequence",
                            "instrument_id",
                            "event_type",
                            "quantity",
                            "execution_price",
                            "cash_change",
                            "baseline_quantity_before",
                            "baseline_quantity_after",
                            "baseline_cash_before",
                            "baseline_cash_after",
                            "reason_code",
                        ],
                    ),
                    "baseline_account_daily": pd.DataFrame(baseline_account_rows),
                    "active_account_daily": pd.DataFrame(active_account_rows),
                }
            ),
            evidence={
                "execution_backend": "qlib",
                "qlib_version": qlib.__version__,
                "account_class": f"{type(account).__module__}.{type(account).__name__}",
                "exchange_class": f"{type(exchange).__module__}.{type(exchange).__name__}",
                "account_reconciliation_error": max(reconciliation_errors, default=0.0),
                "qlib_accumulated_info": _accumulated_info(account),
                "resume_state": _snapshot_state(
                    account,
                    market,
                    stop_position,
                    previous_nav,
                    order_number,
                    fill_number,
                    baseline_cash=(None if matched is None else baseline_cash),
                    baseline_quantity=(
                        None
                        if matched is None
                        else {
                            str(instrument): int(quantity)
                            for instrument, quantity in baseline_quantity.items()
                            if int(quantity) != 0
                        }
                    ),
                    previous_baseline_nav=(None if matched is None else previous_baseline_nav),
                    previous_active_nav=(None if matched is None else previous_active_nav),
                    next_capitalization_event_sequence=(
                        0 if matched is None else capitalization_event_sequence
                    ),
                ),
            },
        )
        result.evidence["result_hash"] = result.result_hash()
        return result


def _normalize_scenario(scenario: Any) -> dict[str, Any]:
    execution_price = _require_matrix(scenario.execution_price, "execution_price")
    if execution_price.empty:
        raise ValueError("execution_price must not be empty")
    if not np.isfinite(execution_price.to_numpy()).all() or (execution_price <= 0).any().any():
        raise ValueError("execution_price must contain finite positive prices")
    physical = execution_price.columns
    index = execution_price.index
    booksize = float(scenario.booksize)
    active_booksize = float(getattr(scenario, "active_booksize", booksize))
    if not np.isfinite(booksize) or booksize <= 0:
        raise ValueError("booksize must be finite and positive")
    if not np.isfinite(active_booksize) or active_booksize <= 0 or active_booksize > booksize:
        raise ValueError("active_booksize must be finite, positive, and no greater than booksize")
    baseline_booksize = booksize - active_booksize
    valuation_value = getattr(scenario, "valuation_price", None)
    valuation_price = (
        execution_price.copy()
        if valuation_value is None
        else _require_matrix(valuation_value, "valuation_price")
    )
    if not valuation_price.index.equals(index) or not valuation_price.columns.equals(physical):
        raise ValueError("valuation_price axes must match execution_price")
    if not np.isfinite(valuation_price.to_numpy()).all() or (valuation_price <= 0).any().any():
        raise ValueError("valuation_price must contain finite positive prices")
    universe = _require_matrix(scenario.universe, "universe")
    if not universe.index.equals(index):
        raise ValueError("universe index must match execution_price")
    if not universe.columns.isin(physical).all():
        raise ValueError("universe instruments must be physical instruments")

    def optional_matrix(value: Any, name: str, default: Any) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame(default, index=index, columns=physical)
        matrix = _require_matrix(value, name)
        if not matrix.index.equals(index) or not matrix.columns.equals(physical):
            raise ValueError(f"{name} axes must match execution_price")
        return matrix.copy()

    factor_value = getattr(scenario, "position_unit_factor", None)
    if factor_value is None:
        factor = pd.DataFrame(1.0, index=index, columns=physical)
    else:
        factor = _require_matrix(factor_value, "position_unit_factor")
        if not factor.index.equals(index) or not factor.columns.equals(physical):
            raise ValueError("position_unit_factor axes must match execution_price")
        factor = factor.astype("float64")
        if not np.isfinite(factor.to_numpy()).all() or not np.allclose(
            factor.to_numpy(), 1.0, atol=0.0, rtol=0.0
        ):
            raise ValueError(
                "position_unit_factor must be all ones; corporate-action "
                "normalization belongs to upstream ETL"
            )
    volume = optional_matrix(scenario.volume, "volume", 1e18).astype("float64")
    requested_buyable = optional_matrix(scenario.buyable, "buyable", True).astype(bool)
    requested_sellable = optional_matrix(scenario.sellable, "sellable", True).astype(bool)
    suspended = optional_matrix(getattr(scenario, "suspended", None), "suspended", False).astype(
        bool
    )
    upper_price_limit = optional_matrix(
        getattr(scenario, "upper_price_limit", None), "upper_price_limit", False
    ).astype(bool)
    lower_price_limit = optional_matrix(
        getattr(scenario, "lower_price_limit", None), "lower_price_limit", False
    ).astype(bool)
    buyable = requested_buyable & ~suspended & ~upper_price_limit
    sellable = requested_sellable & ~suspended & ~lower_price_limit
    asset_class = (
        pd.Series("stock", index=physical, dtype="object")
        if scenario.asset_class is None
        else scenario.asset_class.reindex(physical)
    )
    if asset_class.isna().any():
        raise ValueError("asset_class must explicitly cover every physical instrument")
    lot_size = (
        pd.Series(1, index=physical, dtype="int64")
        if scenario.lot_size is None
        else scenario.lot_size.reindex(physical)
    )
    if lot_size.isna().any() or (lot_size <= 0).any():
        raise ValueError("lot_size must contain positive integers")
    if not np.equal(lot_size, np.floor(lot_size)).all():
        raise ValueError("lot_size must contain integers")
    supplied_policy = scenario.cost_policy or {}
    cost_policy: dict[str, dict[str, float]] = {}
    for kind in asset_class.unique():
        raw = supplied_policy.get(kind, DEFAULT_COST_POLICY.get(kind))
        if raw is None:
            raise ValueError(f"missing cost policy for asset class: {kind}")
        missing = {"buy_rate", "sell_rate", "sell_tax"} - set(raw)
        if missing:
            raise ValueError(f"cost policy for {kind} is missing: {sorted(missing)}")
        cost_policy[str(kind)] = {key: float(raw[key]) for key in raw}
        if not np.isfinite(list(cost_policy[str(kind)].values())).all() or any(
            value < 0 for value in cost_policy[str(kind)].values()
        ):
            raise ValueError(f"cost policy for {kind} must contain finite non-negative rates")
    participation = scenario.max_volume_participation
    if participation is not None and not 0 < float(participation) <= 1:
        raise ValueError("max_volume_participation must be in (0, 1]")
    return {
        "execution_price": execution_price.astype("float64"),
        "valuation_price": valuation_price.astype("float64"),
        "universe": universe.astype(bool),
        "booksize": booksize,
        "active_booksize": active_booksize,
        "baseline_booksize": baseline_booksize,
        "baseline_return_denominator": (baseline_booksize if baseline_booksize > 0 else booksize),
        "position_unit_factor": factor,
        "volume": volume,
        "buyable": buyable,
        "sellable": sellable,
        "suspended": suspended,
        "upper_price_limit": upper_price_limit,
        "lower_price_limit": lower_price_limit,
        "asset_class": asset_class.astype("object"),
        "lot_size": lot_size.astype("int64"),
        "cost_policy": cost_policy,
        "max_volume_participation": participation,
    }


def _require_matrix(value: Any, name: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    if not isinstance(value.index, pd.DatetimeIndex):
        raise TypeError(f"{name} index must be a DatetimeIndex")
    if value.index.has_duplicates or not value.index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be unique and sorted")
    if value.columns.has_duplicates:
        raise ValueError(f"{name} columns must be unique")
    return value.copy()


def _normalize_targets(targets: pd.DataFrame, execution_price: pd.DataFrame) -> pd.DataFrame:
    matrix = _require_matrix(targets, "target_weights")
    if not matrix.index.equals(execution_price.index):
        raise ValueError("target_weights index must match execution_price")
    unknown = matrix.columns.difference(execution_price.columns)
    if len(unknown):
        raise ValueError(f"target_weights contains unknown instruments: {unknown.tolist()}")
    normalized = matrix.reindex(columns=execution_price.columns, fill_value=0.0).astype("float64")
    if not np.isfinite(normalized.to_numpy()).all() or (normalized < 0).any().any():
        raise ValueError("physical target weights must be finite and non-negative")
    if (normalized.sum(axis=1) > 1.0 + 1e-10).any():
        raise ValueError("physical target weights cannot exceed 100%")
    return normalized


def _normalize_matched_capitalization(
    value: MatchedCapitalizationInputs | None,
    execution_price: pd.DataFrame,
) -> MatchedCapitalizationInputs | None:
    if value is None:
        return None

    def aligned(matrix: pd.DataFrame, name: str) -> pd.DataFrame:
        normalized = _require_matrix(matrix, name)
        if not normalized.index.equals(execution_price.index) or not normalized.columns.equals(
            execution_price.columns
        ):
            raise ValueError(f"{name} axes must match execution_price")
        return normalized

    signed = None
    if value.signed_weights is not None:
        signed = aligned(value.signed_weights, "signed_weights").astype("float64")
        if not np.isfinite(signed.to_numpy()).all():
            raise ValueError("signed_weights must contain finite values")
    observed = aligned(value.observed, "observed").astype(bool)
    shortable = aligned(value.shortable, "shortable").astype(bool)
    cap = float(value.per_name_short_cap)
    safety = float(value.safety_multiplier)
    if not 0 < cap <= 1 or not np.isfinite(cap):
        raise ValueError("per_name_short_cap must be finite and in (0, 1]")
    if safety < 1 or not np.isfinite(safety):
        raise ValueError("safety_multiplier must be finite and at least 1")
    if value.inventory_retention not in {"retained", "active_short_only"}:
        raise ValueError("invalid matched capitalization inventory_retention")
    return MatchedCapitalizationInputs(
        signed_weights=signed,
        observed=observed,
        shortable=shortable,
        per_name_short_cap=cap,
        safety_multiplier=safety,
        inventory_retention=value.inventory_retention,
    )


def _normalize_policy_target(
    value: Any,
    instruments: pd.Index,
    *,
    signed: bool,
) -> pd.Series:
    label = "signed_target_policy" if signed else "target_policy"
    if not isinstance(value, pd.Series):
        raise TypeError(f"{label} must return a pandas Series")
    if value.index.has_duplicates:
        raise ValueError(f"{label} returned duplicate instruments")
    unknown = value.index.difference(instruments)
    missing = instruments.difference(value.index)
    if len(unknown) or len(missing):
        raise ValueError(
            f"{label} instruments do not match execution axes: "
            f"unknown={unknown.tolist()}, missing={missing.tolist()}"
        )
    result = value.reindex(instruments).astype("float64")
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError(f"{label} must contain finite weights")
    if signed:
        long_exposure = float(result.clip(lower=0.0).sum())
        short_exposure = float(-result.clip(upper=0.0).sum())
        if long_exposure > 1.0 + 1e-10 or short_exposure > 1.0 + 1e-10:
            raise ValueError(
                "signed_target_policy side exposure cannot exceed 100%: "
                f"long={long_exposure}, short={short_exposure}"
            )
        return result
    if (result < 0).any() or float(result.sum()) > 1.0 + 1e-10:
        raise ValueError(
            "target_policy returned invalid physical weights: "
            f"minimum={result.min()}, sum={result.sum()}"
        )
    return result


def _required_baseline_additions(
    *,
    intended_weight: pd.Series,
    baseline_quantity: pd.Series,
    active_nav: float,
    execution_price: pd.Series,
    lot_size: pd.Series,
    per_name_short_cap: float,
    safety_multiplier: float,
) -> pd.Series:
    additions = pd.Series(0, index=intended_weight.index, dtype="int64")
    needs_short_capacity = intended_weight.lt(-1e-12)
    if not needs_short_capacity.any():
        return additions
    capacity_notional = float(active_nav) * float(per_name_short_cap) * float(safety_multiplier)
    raw_required = capacity_notional / execution_price.loc[needs_short_capacity]
    lots = lot_size.loc[needs_short_capacity].astype("float64")
    required = (np.ceil((raw_required - 1e-10) / lots) * lots).astype("int64")
    additions.loc[needs_short_capacity] = (
        required - baseline_quantity.loc[needs_short_capacity]
    ).clip(lower=0)
    return additions


def _apply_capitalization(
    *,
    account: Account,
    additions: pd.Series,
    execution_price: pd.Series,
    position_unit_factor: pd.Series,
    trade_date: pd.Timestamp,
) -> None:
    for instrument, physical_quantity in additions.loc[additions.gt(0)].items():
        factor = float(position_unit_factor[instrument])
        adjusted_quantity = float(physical_quantity) / factor
        physical_price = float(execution_price[instrument])
        qlib_price = physical_price * factor
        order = Order(
            stock_id=str(instrument),
            amount=adjusted_quantity,
            direction=OrderDir.BUY,
            start_time=trade_date,
            end_time=trade_date,
        )
        account.current_position.update_order(
            order,
            trade_val=float(physical_quantity) * physical_price,
            cost=0.0,
            trade_price=qlib_price,
        )


def _apply_decapitalization(
    *,
    account: Account,
    releases: pd.Series,
    execution_price: pd.Series,
    position_unit_factor: pd.Series,
    trade_date: pd.Timestamp,
) -> None:
    for instrument, physical_quantity in releases.loc[releases.gt(0)].items():
        factor = float(position_unit_factor[instrument])
        adjusted_quantity = float(physical_quantity) / factor
        physical_price = float(execution_price[instrument])
        qlib_price = physical_price * factor
        order = Order(
            stock_id=str(instrument),
            amount=adjusted_quantity,
            direction=OrderDir.SELL,
            start_time=trade_date,
            end_time=trade_date,
        )
        account.current_position.update_order(
            order,
            trade_val=float(physical_quantity) * physical_price,
            cost=0.0,
            trade_price=qlib_price,
        )


def _build_account(
    market: Mapping[str, Any], resume_state: ResumeState | None
) -> tuple[Account, float, int, int]:
    if resume_state is None:
        account = Account(
            init_cash=float(market["booksize"]),
            freq="day",
            benchmark_config={"benchmark": None},
        )
        return account, float(market["booksize"]), 0, 0
    _validate_resume_state(market, resume_state)
    positions = {
        instrument: {
            "amount": float(amount),
            "price": float(resume_state.quote_price[instrument]),
        }
        for instrument, amount in resume_state.adjusted_quantity.items()
        if abs(float(amount)) > 1e-12
    }
    account = Account(
        init_cash=float(resume_state.cash),
        position_dict=positions,
        freq="day",
        benchmark_config={"benchmark": None},
    )
    # Qlib은 첫 report 분모로 init_cash를 사용하므로 resume 시 직전 NAV를 넣습니다.
    account.init_cash = float(resume_state.nav)
    account.accum_info.rtn = float(resume_state.accumulated_return)
    account.accum_info.cost = float(resume_state.accumulated_cost)
    account.accum_info.to = float(resume_state.accumulated_turnover)
    if resume_state.next_position > 0:
        previous_date = pd.Timestamp(
            market["execution_price"].index[resume_state.next_position - 1]
        )
        if account.portfolio_metrics is None:
            raise RuntimeError("Qlib portfolio metrics are unexpectedly disabled")
        account.portfolio_metrics.update_portfolio_metrics_record(
            trade_start_time=previous_date,
            account_value=float(resume_state.nav),
            cash=float(resume_state.cash),
            return_rate=0.0,
            total_turnover=float(resume_state.accumulated_turnover),
            turnover_rate=0.0,
            total_cost=float(resume_state.accumulated_cost),
            cost_rate=0.0,
            stock_value=float(resume_state.nav - resume_state.cash),
            bench_value=0.0,
        )
    return (
        account,
        float(resume_state.nav),
        int(resume_state.next_order_number),
        int(resume_state.next_fill_number),
    )


def _raw_target_quantity(
    weights: pd.Series,
    nav: float,
    execution_price: pd.Series,
) -> pd.Series:
    return weights.astype("float64") * float(nav) / execution_price.astype("float64")


def _round_target_quantity(raw_target_quantity: pd.Series, lot_size: pd.Series) -> pd.Series:
    quantity = np.floor((raw_target_quantity + 1e-10) / lot_size) * lot_size
    return quantity.astype("int64")


def _round_signed_target_quantity(raw_target_quantity: pd.Series, lot_size: pd.Series) -> pd.Series:
    raw = raw_target_quantity.astype("float64")
    lots = lot_size.astype("float64")
    positive = np.floor((raw + 1e-10) / lots) * lots
    negative = np.ceil((raw - 1e-10) / lots) * lots
    return pd.Series(
        np.where(raw.ge(0.0), positive, negative),
        index=raw.index,
        dtype="int64",
    )


def _validate_account_reconciliation(
    *, nav: float, cash: float, position_value: float, tolerance: float
) -> None:
    values = np.asarray([nav, cash, position_value], dtype="float64")
    if not np.isfinite(values).all():
        raise RuntimeError("Qlib account reconciliation contains non-finite values")
    error = abs(float(nav) - (float(cash) + float(position_value)))
    allowed_error = max(
        float(tolerance),
        abs(float(nav)) * ACCOUNT_RECONCILIATION_RELATIVE_TOLERANCE,
    )
    if error > allowed_error:
        raise RuntimeError(
            "Qlib account reconciliation exceeded tolerance: "
            f"error={error}, tolerance={allowed_error}"
        )


def _validate_resume_state(market: Mapping[str, Any], resume_state: ResumeState) -> None:
    scalar_values = np.asarray(
        [
            resume_state.cash,
            resume_state.nav,
            resume_state.accumulated_return,
            resume_state.accumulated_cost,
            resume_state.accumulated_turnover,
        ],
        dtype="float64",
    )
    if not np.isfinite(scalar_values).all():
        raise ValueError("resume_state contains non-finite account values")
    if resume_state.cash < -ACCOUNT_RECONCILIATION_TOLERANCE:
        raise ValueError("resume_state cash cannot be negative")
    if resume_state.nav <= 0:
        raise ValueError("resume_state NAV must be positive")
    if resume_state.accumulated_cost < 0 or resume_state.accumulated_turnover < 0:
        raise ValueError("resume_state accumulated cost and turnover must be non-negative")
    if resume_state.next_order_number < 0 or resume_state.next_fill_number < 0:
        raise ValueError("resume_state sequence numbers must be non-negative")

    instruments = set(market["execution_price"].columns)
    quantity_keys = set(resume_state.adjusted_quantity)
    quote_keys = set(resume_state.quote_price)
    unknown = quantity_keys - instruments
    if unknown:
        raise ValueError(f"resume_state contains unknown physical instruments: {sorted(unknown)}")
    if quote_keys != quantity_keys:
        raise ValueError("resume_state quote_price axes must match adjusted_quantity")

    position_value = 0.0
    for instrument in quantity_keys:
        amount = float(resume_state.adjusted_quantity[instrument])
        price = float(resume_state.quote_price[instrument])
        if not np.isfinite(amount) or amount < 0:
            raise ValueError("resume_state adjusted quantities must be finite and non-negative")
        if not np.isfinite(price) or price <= 0:
            raise ValueError("resume_state quote prices must be finite and positive")
        position_value += amount * price
    _validate_account_reconciliation(
        nav=float(resume_state.nav),
        cash=float(resume_state.cash),
        position_value=position_value,
        tolerance=ACCOUNT_RECONCILIATION_TOLERANCE,
    )
    matched_values = (
        resume_state.baseline_cash,
        resume_state.baseline_quantity,
        resume_state.previous_baseline_nav,
        resume_state.previous_active_nav,
    )
    if any(value is not None for value in matched_values):
        if any(value is None for value in matched_values):
            raise ValueError("resume_state matched capitalization state is incomplete")
        matched_scalars = np.asarray(
            [
                resume_state.baseline_cash,
                resume_state.previous_baseline_nav,
                resume_state.previous_active_nav,
            ],
            dtype="float64",
        )
        if not np.isfinite(matched_scalars).all():
            raise ValueError("resume_state matched capitalization values must be finite")
        if resume_state.baseline_cash < -ACCOUNT_RECONCILIATION_TOLERANCE:
            raise ValueError("resume_state baseline cash cannot be negative")
        if resume_state.previous_baseline_nav < -ACCOUNT_RECONCILIATION_TOLERANCE:
            raise ValueError("resume_state baseline NAV cannot be negative")
        if resume_state.previous_active_nav <= 0:
            raise ValueError("resume_state active NAV must be positive")
        baseline_quantity = resume_state.baseline_quantity or {}
        unknown_baseline = set(baseline_quantity).difference(instruments)
        if unknown_baseline:
            raise ValueError(
                "resume_state baseline contains unknown physical instruments: "
                f"{sorted(unknown_baseline)}"
            )
        for quantity in baseline_quantity.values():
            numeric = float(quantity)
            if not np.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
                raise ValueError("resume_state baseline quantities must be non-negative integers")
        if resume_state.next_position == 0:
            baseline_nav = float(market["baseline_booksize"])
        else:
            previous_mark = market["valuation_price"].iloc[resume_state.next_position - 1]
            baseline_nav = float(resume_state.baseline_cash)
            baseline_nav += sum(
                float(quantity) * float(previous_mark[instrument])
                for instrument, quantity in baseline_quantity.items()
            )
        baseline_error = abs(baseline_nav - float(resume_state.previous_baseline_nav))
        baseline_tolerance = max(
            ACCOUNT_RECONCILIATION_TOLERANCE,
            abs(baseline_nav) * ACCOUNT_RECONCILIATION_RELATIVE_TOLERANCE,
        )
        if baseline_error > baseline_tolerance:
            raise ValueError("resume_state baseline cash, quantity and NAV do not reconcile")
        projected_active_nav = float(resume_state.nav) - baseline_nav
        active_error = abs(projected_active_nav - float(resume_state.previous_active_nav))
        active_tolerance = max(
            ACCOUNT_RECONCILIATION_TOLERANCE,
            abs(projected_active_nav) * ACCOUNT_RECONCILIATION_RELATIVE_TOLERANCE,
        )
        if active_error > active_tolerance:
            raise ValueError("resume_state composite, baseline and active NAV do not reconcile")
    if resume_state.next_capitalization_event_sequence < 0:
        raise ValueError("resume_state capitalization event sequence must be non-negative")


def _accumulated_info(account: Account) -> dict[str, float]:
    return {
        "return": float(account.accum_info.get_return),
        "cost": float(account.accum_info.get_cost),
        "turnover": float(account.accum_info.get_turnover),
    }


def _fill_reason(
    *,
    direction: OrderDir,
    requested: int,
    filled: int,
    buyable: bool,
    sellable: bool,
) -> str:
    if direction == OrderDir.BUY and not buyable:
        return "buy_blocked"
    if direction == OrderDir.SELL and not sellable:
        return "sell_blocked"
    if filled == requested:
        return "filled"
    if filled > 0:
        return "partial_fill"
    return "unfilled"


def _signal_rows(signals: Mapping[str, pd.DataFrame] | None, weights: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "trade_date",
        "signal_name",
        "instrument_id",
        "signal_value",
        "max_observation_date",
    ]
    if not signals:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for name, matrix in signals.items():
        if not matrix.index.equals(weights.index) or matrix.columns.has_duplicates:
            raise ValueError(f"signal axes are invalid: {name}")
        for date, row in matrix.iterrows():
            prior = weights.index[weights.index < date]
            max_observation = pd.NaT if prior.empty else pd.Timestamp(prior[-1])
            for instrument, value in row.items():
                rows.append(
                    {
                        "trade_date": pd.Timestamp(date),
                        "signal_name": str(name),
                        "instrument_id": str(instrument),
                        "signal_value": float(value),
                        "max_observation_date": max_observation,
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def _snapshot_state(
    account: Account,
    market: Mapping[str, Any],
    next_position: int,
    nav: float,
    order_number: int,
    fill_number: int,
    *,
    baseline_cash: float | None = None,
    baseline_quantity: Mapping[str, int] | None = None,
    previous_baseline_nav: float | None = None,
    previous_active_nav: float | None = None,
    next_capitalization_event_sequence: int = 0,
) -> ResumeState:
    position = account.current_position
    adjusted = {
        instrument: float(position.get_stock_amount(instrument))
        for instrument in market["execution_price"].columns
        if abs(float(position.get_stock_amount(instrument))) > 1e-12
    }
    quote_price = {
        instrument: float(position.get_stock_price(instrument)) for instrument in adjusted
    }
    return ResumeState(
        next_position=int(next_position),
        cash=float(position.get_cash()),
        nav=float(nav),
        accumulated_return=float(account.accum_info.get_return),
        accumulated_cost=float(account.accum_info.get_cost),
        accumulated_turnover=float(account.accum_info.get_turnover),
        adjusted_quantity=adjusted,
        quote_price=quote_price,
        next_order_number=int(order_number),
        next_fill_number=int(fill_number),
        baseline_cash=(None if baseline_cash is None else float(baseline_cash)),
        baseline_quantity=(
            None
            if baseline_quantity is None
            else {
                str(instrument): int(quantity) for instrument, quantity in baseline_quantity.items()
            }
        ),
        previous_baseline_nav=(
            None if previous_baseline_nav is None else float(previous_baseline_nav)
        ),
        previous_active_nav=(None if previous_active_nav is None else float(previous_active_nav)),
        next_capitalization_event_sequence=int(next_capitalization_event_sequence),
    )
