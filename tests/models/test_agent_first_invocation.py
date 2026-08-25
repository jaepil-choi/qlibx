"""Behaviour tests for the private fresh-instance invocation boundary.

`vqapr._internal.models.agent_first` is the adapter that turns one immutable
`DataModel`/`StrategyModel` declaration plus injected resolvers into a validated
private result. These tests pin the three properties the boundary exists to guarantee:

1. a model instance never survives one invocation, so author `self` cannot carry state;
2. a model reads only what it declared, and undeclared history/aliases raise rather
   than returning silently-empty data;
3. returned rows, diagnostics and constraint bounds are checked against the declared
   schema and the callback universe before any result is handed back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr._internal.models.agent_first import (
    AccessToken,
    PreparedDataInvocation,
    PreparedStrategyInvocation,
    prepare_data_model_invocation,
    prepare_strategy_invocation,
)
from vqapr.authoring import (
    AccountHistoryInput,
    ConstraintBounds,
    DataModel,
    DatasetInput,
    DeclaredAccountHistory,
    DerivedRow,
    DiagnosticTable,
    EconomicAccountView,
    Hold,
    Observation,
    Output,
    Rebalance,
    RowsLookback,
    StrategyModel,
    StrategyResult,
)
from vqapr.portfolio.budgets import Budget, PortfolioDirection

EVALUATION_TIME = datetime(2024, 3, 1, 16, tzinfo=UTC)
UNIVERSE = ("000660", "005930")
BUDGET = Budget(
    direction=PortfolioDirection.LONG_ONLY,
    cash_lower=Decimal(0),
    cash_upper=Decimal(1),
    target_lower=Decimal(0),
    target_upper=Decimal(1),
)


def _account(cash: str = "1000") -> EconomicAccountView:
    return EconomicAccountView(
        cash=Decimal(cash), positions={}, nav=None, nav_observed_at=None
    )


def _bounds(instruments: tuple[str, ...] = UNIVERSE) -> ConstraintBounds:
    return ConstraintBounds(
        lower_weights={name: Decimal(0) for name in instruments},
        upper_weights={name: Decimal(1) for name in instruments},
    )


def _observation(instrument_id: str, value: str) -> Observation:
    return Observation(
        instrument_id=instrument_id,
        available_at=EVALUATION_TIME,
        values={"ret": Decimal(value)},
    )


def _resolver(alias, declaration, evaluation_time):
    assert evaluation_time == EVALUATION_TIME
    return (_observation("005930", "0.01"), _observation("000660", "0.02"))


def _empty_resolver(alias, declaration, evaluation_time):
    return ()


PRICES = DatasetInput(dataset_id="stock_daily", fields=("ret",), lookback=RowsLookback(rows=1))


# ----------------------------------------------------------------------------------
# Fresh instance per invocation
# ----------------------------------------------------------------------------------


class _CountingDataModel(DataModel):
    """Counts constructions on the class, and mutates `self` during compute()."""

    constructions = 0

    def __init__(self) -> None:
        type(self).constructions += 1
        self.seen = 0

    def inputs(self):
        return {"prices": PRICES}

    def output(self):
        return Output(semantic_fields=("signal",))

    def compute(self, call):
        self.seen += 1
        return (
            DerivedRow(instrument_id="005930", values={"signal": Decimal(self.seen)}),
        )


def test_each_data_invocation_constructs_a_new_instance():
    _CountingDataModel.constructions = 0

    first = prepare_data_model_invocation(
        _CountingDataModel, {}, evaluation_time=EVALUATION_TIME, resolver=_resolver
    )
    second = prepare_data_model_invocation(
        _CountingDataModel, {}, evaluation_time=EVALUATION_TIME, resolver=_resolver
    )

    assert _CountingDataModel.constructions == 2
    # `self.seen` restarts at 1 both times: a mutation in the first callback is invisible
    # to the second. This is the sentinel the plan requires - if the instance were reused
    # the second row would carry 2.
    assert first.rows[0].values["signal"] == Decimal(1)
    assert second.rows[0].values["signal"] == Decimal(1)


def test_config_is_detached_so_a_model_cannot_mutate_the_registered_config():
    class _ConfigModel(DataModel):
        def __init__(self, factor: str) -> None:
            self.factor = factor

        def inputs(self):
            return {}

        def output(self):
            return Output(semantic_fields=("signal",))

        def compute(self, call):
            return ()

    config = {"factor": "HML"}
    prepare_data_model_invocation(
        _ConfigModel, config, evaluation_time=EVALUATION_TIME, resolver=_empty_resolver
    )
    assert config == {"factor": "HML"}


# ----------------------------------------------------------------------------------
# Declared reads only
# ----------------------------------------------------------------------------------


class _UndeclaredAliasModel(DataModel):
    def inputs(self):
        return {"prices": PRICES}

    def output(self):
        return Output(semantic_fields=("signal",))

    def compute(self, call):
        return call.read("not_declared")


def test_reading_an_undeclared_alias_raises():
    with pytest.raises(KeyError, match="was not declared in inputs"):
        prepare_data_model_invocation(
            _UndeclaredAliasModel, {}, evaluation_time=EVALUATION_TIME, resolver=_resolver
        )


class _ReadingModel(DataModel):
    def inputs(self):
        return {"prices": PRICES}

    def output(self):
        return Output(semantic_fields=("signal",))

    def compute(self, call):
        observations = call.read("prices")
        return (
            DerivedRow(
                instrument_id="005930", values={"signal": Decimal(len(observations))}
            ),
        )


def test_access_tokens_record_what_was_read_without_carrying_observations():
    prepared = prepare_data_model_invocation(
        _ReadingModel, {}, evaluation_time=EVALUATION_TIME, resolver=_resolver
    )

    assert prepared.access_tokens == (
        AccessToken(alias="prices", dataset_id="stock_daily", observation_count=2),
    )
    assert not hasattr(prepared.access_tokens[0], "observations")
    assert prepared.rows[0].values["signal"] == Decimal(2)


def test_a_model_that_reads_nothing_records_no_access():
    class _Quiet(DataModel):
        def inputs(self):
            return {"prices": PRICES}

        def output(self):
            return Output(semantic_fields=("signal",))

        def compute(self, call):
            return ()

    prepared = prepare_data_model_invocation(
        _Quiet, {}, evaluation_time=EVALUATION_TIME, resolver=_resolver
    )
    assert prepared.access_tokens == ()


# ----------------------------------------------------------------------------------
# Output schema enforcement
# ----------------------------------------------------------------------------------


def test_a_row_that_misses_the_declared_output_schema_is_refused():
    class _WrongSchema(DataModel):
        def inputs(self):
            return {}

        def output(self):
            return Output(semantic_fields=("signal", "weight"))

        def compute(self, call):
            return (DerivedRow(instrument_id="005930", values={"signal": Decimal(1)}),)

    with pytest.raises(ValueError, match="does not match the declared Output schema"):
        prepare_data_model_invocation(
            _WrongSchema, {}, evaluation_time=EVALUATION_TIME, resolver=_empty_resolver
        )


def test_a_repeated_instrument_in_one_result_is_refused():
    class _Duplicate(DataModel):
        def inputs(self):
            return {}

        def output(self):
            return Output(semantic_fields=("signal",))

        def compute(self, call):
            return (
                DerivedRow(instrument_id="005930", values={"signal": Decimal(1)}),
                DerivedRow(instrument_id="005930", values={"signal": Decimal(2)}),
            )

    with pytest.raises(ValueError, match="must not repeat an instrument_id"):
        prepare_data_model_invocation(
            _Duplicate, {}, evaluation_time=EVALUATION_TIME, resolver=_empty_resolver
        )


def test_a_callback_exception_propagates_unchanged():
    class _Boom(DataModel):
        def inputs(self):
            return {}

        def output(self):
            return Output(semantic_fields=("signal",))

        def compute(self, call):
            raise RuntimeError("the model itself failed")

    with pytest.raises(RuntimeError, match="the model itself failed"):
        prepare_data_model_invocation(
            _Boom, {}, evaluation_time=EVALUATION_TIME, resolver=_empty_resolver
        )


# ----------------------------------------------------------------------------------
# Strategy: declared account history
# ----------------------------------------------------------------------------------


class _HoldingStrategy(StrategyModel):
    """Declares nothing beyond a decision; the default `account_history()` is None."""

    def decide(self, call):
        return StrategyResult(
            decision=Hold(reason="nothing-to-do"), next_state=None, diagnostics={}
        )


def test_a_strategy_that_declares_no_history_gets_an_unreadable_view():
    prepared = prepare_strategy_invocation(
        _HoldingStrategy,
        {},
        evaluation_time=EVALUATION_TIME,
        account=_account(),
        instruments=UNIVERSE,
        constraint_bounds=_bounds(),
        resolver=_empty_resolver,
    )
    assert isinstance(prepared, PreparedStrategyInvocation)
    assert isinstance(prepared.decision, Hold)


class _HistoryReadingStrategy(StrategyModel):
    def account_history(self):
        return AccountHistoryInput(fields=("nav",), lookback=RowsLookback(rows=3))

    def decide(self, call):
        navs = call.account_history.series("nav")
        return StrategyResult(
            decision=Hold(reason=f"saw-{len(navs)}-navs"), next_state=None, diagnostics={}
        )


def test_a_declared_history_is_served_through_the_injected_resolver():
    def history_resolver(declaration):
        assert declaration.fields == ("nav",)
        return DeclaredAccountHistory(
            fields=declaration.fields,
            lookback=declaration.lookback,
            series={"nav": (Decimal(100), Decimal(101))},
        )

    prepared = prepare_strategy_invocation(
        _HistoryReadingStrategy,
        {},
        evaluation_time=EVALUATION_TIME,
        account=_account(),
        instruments=UNIVERSE,
        constraint_bounds=_bounds(),
        history_resolver=history_resolver,
        resolver=_empty_resolver,
    )
    assert prepared.decision.reason == "saw-2-navs"


def test_a_declared_history_without_a_resolver_is_a_wiring_error():
    with pytest.raises(ValueError, match="no history_resolver was supplied"):
        prepare_strategy_invocation(
            _HistoryReadingStrategy,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=_bounds(),
            resolver=_empty_resolver,
        )


def test_a_resolver_that_serves_different_fields_than_declared_is_refused():
    def wrong_fields(declaration):
        return DeclaredAccountHistory(
            fields=("cash",),
            lookback=declaration.lookback,
            series={"cash": (Decimal(1),)},
        )

    with pytest.raises(ValueError, match="fields that do not match the declaration"):
        prepare_strategy_invocation(
            _HistoryReadingStrategy,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=_bounds(),
            history_resolver=wrong_fields,
            resolver=_empty_resolver,
        )


def test_reading_an_undeclared_history_field_raises():
    class _WrongAccessor(StrategyModel):
        def account_history(self):
            return AccountHistoryInput(fields=("nav",), lookback=RowsLookback(rows=2))

        def decide(self, call):
            call.account_history.series("cash")
            return StrategyResult(
                decision=Hold(reason="unreachable"), next_state=None, diagnostics={}
            )

    def history_resolver(declaration):
        return DeclaredAccountHistory(
            fields=declaration.fields,
            lookback=declaration.lookback,
            series={"nav": (Decimal(1),)},
        )

    with pytest.raises(KeyError):
        prepare_strategy_invocation(
            _WrongAccessor,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=_bounds(),
            history_resolver=history_resolver,
            resolver=_empty_resolver,
        )


# ----------------------------------------------------------------------------------
# Strategy: constraint bounds must cover the callback universe
# ----------------------------------------------------------------------------------


def test_bounds_that_miss_an_instrument_in_the_universe_are_refused():
    partial = ConstraintBounds(
        lower_weights={"005930": Decimal(0)}, upper_weights={"005930": Decimal(1)}
    )
    with pytest.raises(ValueError, match="must cover exactly the callback universe"):
        prepare_strategy_invocation(
            _HoldingStrategy,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=partial,
            resolver=_empty_resolver,
        )


def test_bounds_carrying_an_instrument_outside_the_universe_are_refused():
    with pytest.raises(ValueError, match="must cover exactly the callback universe"):
        prepare_strategy_invocation(
            _HoldingStrategy,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=("005930",),
            constraint_bounds=_bounds(),
            resolver=_empty_resolver,
        )


def test_a_repeated_instrument_in_the_universe_is_refused():
    with pytest.raises(ValueError, match="must not repeat an instrument_id"):
        prepare_strategy_invocation(
            _HoldingStrategy,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=("005930", "005930"),
            constraint_bounds=_bounds(("005930",)),
            resolver=_empty_resolver,
        )


def test_bounds_are_required_rather_than_defaulted_to_an_empty_set():
    with pytest.raises(TypeError):
        prepare_strategy_invocation(
            _HoldingStrategy,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            resolver=_empty_resolver,
        )


# ----------------------------------------------------------------------------------
# Strategy: state and diagnostics
# ----------------------------------------------------------------------------------


class _StatefulStrategy(StrategyModel):
    """Carries cadence in returned state, exactly as the migrated factor model must."""

    def diagnostics(self):
        return (DiagnosticTable(table_id="formation", semantic_fields=("month",)),)

    def decide(self, call):
        previous = call.previous_state if isinstance(call.previous_state, dict) else {}
        last = previous.get("last_formed_month")
        month = call.evaluation_time.year * 12 + (call.evaluation_time.month - 1)
        if last == month:
            return StrategyResult(
                decision=Hold(reason="already-formed"),
                next_state=previous,
                diagnostics={},
            )
        return StrategyResult(
            decision=Rebalance(
                target_weights={"005930": Decimal("0.5")},
                cash_weight=Decimal("0.5"),
                budget=BUDGET,
            ),
            next_state={**previous, "last_formed_month": month},
            diagnostics={"formation": ({"month": month},)},
        )


def test_returned_state_is_the_only_cadence_channel_across_invocations():
    first = prepare_strategy_invocation(
        _StatefulStrategy,
        {},
        evaluation_time=EVALUATION_TIME,
        account=_account(),
        instruments=UNIVERSE,
        constraint_bounds=_bounds(),
        previous_state=None,
        resolver=_empty_resolver,
    )
    assert isinstance(first.decision, Rebalance)
    assert first.next_state["last_formed_month"] == 2024 * 12 + 2

    # Same month, now carrying the first invocation's returned state: the model holds.
    second = prepare_strategy_invocation(
        _StatefulStrategy,
        {},
        evaluation_time=datetime(2024, 3, 20, 16, tzinfo=UTC),
        account=_account(),
        instruments=UNIVERSE,
        constraint_bounds=_bounds(),
        previous_state=first.next_state,
        resolver=_empty_resolver,
    )
    assert isinstance(second.decision, Hold)

    # Without the state a fresh instance re-forms: proof the cadence lives in state
    # alone and not in surviving instance attributes.
    third = prepare_strategy_invocation(
        _StatefulStrategy,
        {},
        evaluation_time=datetime(2024, 3, 20, 16, tzinfo=UTC),
        account=_account(),
        instruments=UNIVERSE,
        constraint_bounds=_bounds(),
        previous_state=None,
        resolver=_empty_resolver,
    )
    assert isinstance(third.decision, Rebalance)


def test_an_undeclared_diagnostic_table_is_refused():
    class _Undeclared(StrategyModel):
        def decide(self, call):
            return StrategyResult(
                decision=Hold(reason="x"),
                next_state=None,
                diagnostics={"not_declared": ({"a": 1},)},
            )

    with pytest.raises(ValueError, match="undeclared diagnostic tables"):
        prepare_strategy_invocation(
            _Undeclared,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=_bounds(),
            resolver=_empty_resolver,
        )


def test_a_diagnostic_row_off_its_declared_schema_is_refused():
    class _BadRow(StrategyModel):
        def diagnostics(self):
            return (DiagnosticTable(table_id="formation", semantic_fields=("month",)),)

        def decide(self, call):
            return StrategyResult(
                decision=Hold(reason="x"),
                next_state=None,
                diagnostics={"formation": ({"month": 1, "extra": 2},)},
            )

    with pytest.raises(ValueError, match="does not match its declared schema"):
        prepare_strategy_invocation(
            _BadRow,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=_bounds(),
            resolver=_empty_resolver,
        )


def test_non_json_state_is_refused_by_the_strict_codec():
    class _BadState(StrategyModel):
        def decide(self, call):
            return StrategyResult(
                decision=Hold(reason="x"), next_state={"when": object()}, diagnostics={}
            )

    with pytest.raises(TypeError, match="strict JSON values"):
        prepare_strategy_invocation(
            _BadState,
            {},
            evaluation_time=EVALUATION_TIME,
            account=_account(),
            instruments=UNIVERSE,
            constraint_bounds=_bounds(),
            resolver=_empty_resolver,
        )


def test_prepared_results_are_immutable_values():
    prepared = prepare_data_model_invocation(
        _ReadingModel, {}, evaluation_time=EVALUATION_TIME, resolver=_resolver
    )
    assert isinstance(prepared, PreparedDataInvocation)
    with pytest.raises(AttributeError):
        prepared.rows = ()
