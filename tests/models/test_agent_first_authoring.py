"""Pure-contract tests for `vqapr.authoring`.

No runtime adapter, store, or Flow wiring is exercised here — only construction, validation,
alias/immutability semantics, and the exact public export surface of the module itself.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr import authoring
from vqapr.portfolio.budgets import Budget, PortfolioDirection

UTC_NOW = datetime(2024, 3, 5, 15, 30, tzinfo=UTC)
NAIVE_NOW = datetime(2024, 3, 5, 15, 30)


def _budget(direction: PortfolioDirection = PortfolioDirection.LONG_ONLY) -> Budget:
    lower = Decimal("0") if direction is PortfolioDirection.LONG_ONLY else Decimal("-1")
    return Budget(
        direction=direction,
        cash_lower=lower,
        cash_upper=Decimal("1"),
        target_lower=lower,
        target_upper=Decimal("1"),
    )


# --------------------------------------------------------------------------------------
# Exact public exports.
# --------------------------------------------------------------------------------------


def test_module_exports_are_exact() -> None:
    expected = {
        "AccountHistoryInput",
        "CalendarLookback",
        "Constraint",
        "ConstraintBounds",
        "ConstraintCall",
        "ConstraintFinding",
        "DataCall",
        "DataModel",
        "DatasetInput",
        "DeclaredAccountHistory",
        "DerivedRow",
        "DiagnosticTable",
        "EconomicAccountView",
        "Hold",
        "Observation",
        "Output",
        "Rebalance",
        "RowsLookback",
        "StrategyCall",
        "StrategyModel",
        "StrategyResult",
    }
    assert set(authoring.__all__) == expected
    for name in expected:
        assert hasattr(authoring, name)


# --------------------------------------------------------------------------------------
# RowsLookback / CalendarLookback.
# --------------------------------------------------------------------------------------


def test_rows_lookback_requires_positive_int() -> None:
    authoring.RowsLookback(rows=1)
    with pytest.raises(ValueError):
        authoring.RowsLookback(rows=0)
    with pytest.raises(TypeError):
        authoring.RowsLookback(rows=True)


def test_rows_lookback_is_frozen_slotted_and_takes_its_count_either_way() -> None:
    """Keyword-only is gone, and it went deliberately.

    `authoring.RowsLookback` was a keyword-only copy of `data.lookback.RowsLookback`, which is
    not. Record `126` made them one class and kept the engine's, so `RowsLookback(3)` is now
    legal alongside `RowsLookback(rows=3)`. Nothing authored changes -- every call site in the
    tree and in the research workspace already spells the keyword -- but a test asserting the
    refusal would now be pinning a difference that only existed because there were two classes.

    Frozen and slotted are the properties worth keeping, and both survive the merge.
    """
    lookback = authoring.RowsLookback(rows=3)
    with pytest.raises(FrozenInstanceError):
        lookback.rows = 4  # type: ignore[misc]
    assert not hasattr(lookback, "__dict__")
    assert authoring.RowsLookback(3) == lookback


def test_calendar_lookback_requires_at_least_one_positive_amount() -> None:
    authoring.CalendarLookback(days=1)
    with pytest.raises(ValueError):
        authoring.CalendarLookback()


def test_calendar_lookback_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError):
        authoring.CalendarLookback(days=1, timezone="Not/AZone")


def test_calendar_lookback_lower_bound_is_local_midnight() -> None:
    lookback = authoring.CalendarLookback(days=5, timezone="Asia/Seoul")
    bound = lookback.lower_bound(UTC_NOW)
    assert bound.tzinfo is not None
    assert bound < UTC_NOW


# --------------------------------------------------------------------------------------
# DatasetInput / Observation / Output / DerivedRow.
# --------------------------------------------------------------------------------------


def test_dataset_input_rejects_reserved_and_duplicate_fields() -> None:
    authoring.DatasetInput(
        dataset_id="px", fields=("close",), lookback=authoring.RowsLookback(rows=1)
    )
    with pytest.raises(ValueError):
        authoring.DatasetInput(
            dataset_id="px", fields=("instrument",), lookback=authoring.RowsLookback(rows=1)
        )
    with pytest.raises(ValueError):
        authoring.DatasetInput(
            dataset_id="px", fields=("close", "close"), lookback=authoring.RowsLookback(rows=1)
        )
    with pytest.raises(ValueError):
        authoring.DatasetInput(dataset_id="px", fields=(), lookback=authoring.RowsLookback(rows=1))
    with pytest.raises(TypeError):
        authoring.DatasetInput(dataset_id="px", fields=("close",), lookback=object())


def test_observation_requires_tz_aware_available_at_and_finite_values() -> None:
    authoring.Observation("A", UTC_NOW, {"close": Decimal("1.5")})
    with pytest.raises(ValueError):
        authoring.Observation("A", NAIVE_NOW, {"close": Decimal("1.5")})
    with pytest.raises(ValueError):
        authoring.Observation("A", UTC_NOW, {"close": Decimal("NaN")})
    with pytest.raises(TypeError):
        authoring.Observation("A", UTC_NOW, {"close": object()})
    with pytest.raises(ValueError):
        authoring.Observation("", UTC_NOW, {})


def test_observation_values_mapping_is_copied_and_immutable() -> None:
    source = {"close": Decimal("1")}
    observation = authoring.Observation("A", UTC_NOW, source)
    source["close"] = Decimal("999")
    assert observation.values["close"] == Decimal("1")
    with pytest.raises(TypeError):
        observation.values["close"] = Decimal("2")  # type: ignore[index]


def test_output_rejects_reserved_and_empty_fields() -> None:
    authoring.Output(semantic_fields=("momentum",))
    with pytest.raises(ValueError):
        authoring.Output(semantic_fields=())
    with pytest.raises(ValueError):
        authoring.Output(semantic_fields=("available_at",))


def test_derived_row_rejects_reserved_row_fields() -> None:
    authoring.DerivedRow(instrument_id="A", values={"momentum": Decimal("1")})
    with pytest.raises(ValueError):
        authoring.DerivedRow(instrument_id="A", values={"available_at": UTC_NOW})
    with pytest.raises(ValueError):
        authoring.DerivedRow(instrument_id="A", values={"instrument": "x"})
    with pytest.raises(ValueError):
        authoring.DerivedRow(instrument_id="", values={})


# --------------------------------------------------------------------------------------
# DataModel / DataCall abstract contracts.
# --------------------------------------------------------------------------------------


def test_data_model_is_abstract_and_requires_compute_and_output() -> None:
    with pytest.raises(TypeError):
        authoring.DataModel()  # type: ignore[abstract]

    class Incomplete(authoring.DataModel):
        def output(self) -> authoring.Output:
            return authoring.Output(semantic_fields=("x",))

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_data_model_inputs_defaults_to_empty() -> None:
    class Model(authoring.DataModel):
        def output(self) -> authoring.Output:
            return authoring.Output(semantic_fields=("x",))

        def compute(self, call: authoring.DataCall) -> tuple[authoring.DerivedRow, ...]:
            return ()

    model = Model()
    assert model.inputs() == {}
    assert model.compute(_FakeDataCall()) == ()


class _FakeDataCall(authoring.DataCall):
    """A minimal concrete DataCall used only to exercise the abstract contract shape."""

    @property
    def evaluation_time(self) -> datetime:
        return UTC_NOW

    def read(self, alias: str) -> tuple[authoring.Observation, ...]:
        return (authoring.Observation("A", UTC_NOW, {"close": Decimal("1")}),) if alias else ()


def test_data_call_is_abstract() -> None:
    with pytest.raises(TypeError):
        authoring.DataCall()  # type: ignore[abstract]
    call = _FakeDataCall()
    assert call.evaluation_time == UTC_NOW
    assert call.read("px")[0].instrument_id == "A"


# --------------------------------------------------------------------------------------
# DiagnosticTable / AccountHistoryInput.
# --------------------------------------------------------------------------------------


def test_diagnostic_table_rejects_empty_and_reserved_fields() -> None:
    authoring.DiagnosticTable(table_id="turnover", semantic_fields=("value",))
    with pytest.raises(ValueError):
        authoring.DiagnosticTable(table_id="turnover", semantic_fields=())
    with pytest.raises(ValueError):
        authoring.DiagnosticTable(table_id="turnover", semantic_fields=("account_version",))


def test_account_history_input_rejects_unknown_field() -> None:
    authoring.AccountHistoryInput(fields=("nav",), lookback=authoring.RowsLookback(rows=2))
    with pytest.raises(ValueError):
        authoring.AccountHistoryInput(
            fields=("not_a_field",), lookback=authoring.RowsLookback(rows=2)
        )
    with pytest.raises(TypeError):
        authoring.AccountHistoryInput(fields=("nav",), lookback=object())


# --------------------------------------------------------------------------------------
# EconomicAccountView.
# --------------------------------------------------------------------------------------


def test_economic_account_view_couples_nav_and_nav_observed_at() -> None:
    authoring.EconomicAccountView(cash=Decimal("10"), positions={}, nav=None, nav_observed_at=None)
    authoring.EconomicAccountView(
        cash=Decimal("10"), positions={}, nav=Decimal("10"), nav_observed_at=UTC_NOW
    )
    with pytest.raises(ValueError):
        authoring.EconomicAccountView(
            cash=Decimal("10"), positions={}, nav=Decimal("10"), nav_observed_at=None
        )
    with pytest.raises(ValueError):
        authoring.EconomicAccountView(
            cash=Decimal("10"), positions={}, nav=None, nav_observed_at=UTC_NOW
        )


def test_economic_account_view_quantity_defaults_to_zero_and_positions_are_immutable() -> None:
    positions = {"A": Decimal("5")}
    view = authoring.EconomicAccountView(
        cash=Decimal("10"), positions=positions, nav=None, nav_observed_at=None
    )
    positions["A"] = Decimal("999")
    assert view.quantity("A") == Decimal("5")
    assert view.quantity("ABSENT") == Decimal(0)
    with pytest.raises(TypeError):
        view.positions["A"] = Decimal("1")  # type: ignore[index]


def test_economic_account_view_has_no_version_or_mutation_escape() -> None:
    view = authoring.EconomicAccountView(
        cash=Decimal("10"), positions={}, nav=None, nav_observed_at=None
    )
    assert not hasattr(view, "version")
    assert not hasattr(view, "account_version")
    with pytest.raises(FrozenInstanceError):
        view.cash = Decimal("0")  # type: ignore[misc]


# --------------------------------------------------------------------------------------
# DeclaredAccountHistory.
# --------------------------------------------------------------------------------------


def test_declared_account_history_defaults_to_no_declared_fields() -> None:
    history = authoring.DeclaredAccountHistory()
    assert history.fields == ()
    with pytest.raises(KeyError):
        history.series("nav")
    with pytest.raises(KeyError):
        history.panel("quantity")


def test_declared_account_history_rejects_reading_undeclared_field() -> None:
    history = authoring.DeclaredAccountHistory(
        fields=("nav",),
        lookback=authoring.RowsLookback(rows=3),
        series={"nav": [Decimal("1"), Decimal("2")]},
    )
    assert history.series("nav") == (Decimal("1"), Decimal("2"))
    with pytest.raises(KeyError):
        history.series("cash")
    with pytest.raises(KeyError):
        history.panel("quantity")


def test_declared_account_history_bounds_to_lookback_rows_oldest_first() -> None:
    history = authoring.DeclaredAccountHistory(
        fields=("nav",),
        lookback=authoring.RowsLookback(rows=2),
        series={"nav": [Decimal("1"), Decimal("2"), Decimal("3")]},
    )
    assert history.series("nav") == (Decimal("2"), Decimal("3"))


def test_declared_account_history_panel_is_immutable_and_sorted() -> None:
    history = authoring.DeclaredAccountHistory(
        fields=("quantity",),
        lookback=authoring.RowsLookback(rows=5),
        panel={"quantity": {"B": [Decimal("2")], "A": [Decimal("1")]}},
    )
    panel = history.panel("quantity")
    assert list(panel) == ["A", "B"]
    with pytest.raises(TypeError):
        panel["A"] = ()  # type: ignore[index]


# --------------------------------------------------------------------------------------
# ConstraintBounds.
# --------------------------------------------------------------------------------------


def test_constraint_bounds_requires_matching_instrument_coverage() -> None:
    authoring.ConstraintBounds(lower_weights={"A": Decimal("0")}, upper_weights={"A": Decimal("1")})
    with pytest.raises(ValueError):
        authoring.ConstraintBounds(
            lower_weights={"A": Decimal("0")}, upper_weights={"B": Decimal("1")}
        )
    with pytest.raises(ValueError):
        authoring.ConstraintBounds(
            lower_weights={"A": Decimal("1")}, upper_weights={"A": Decimal("0")}
        )


def test_constraint_bounds_accessors_raise_for_uncovered_instrument() -> None:
    bounds = authoring.ConstraintBounds(
        lower_weights={"A": Decimal("0")}, upper_weights={"A": Decimal("1")}
    )
    assert bounds.lower_weight("A") == Decimal("0")
    assert bounds.upper_weight("A") == Decimal("1")
    with pytest.raises(KeyError):
        bounds.lower_weight("ABSENT")


def test_constraint_bounds_mapping_is_copied_and_immutable() -> None:
    lower = {"A": Decimal("0")}
    bounds = authoring.ConstraintBounds(lower_weights=lower, upper_weights={"A": Decimal("1")})
    lower["A"] = Decimal("999")
    assert bounds.lower_weight("A") == Decimal("0")
    with pytest.raises(TypeError):
        bounds.lower_weights["A"] = Decimal("1")  # type: ignore[index]


# --------------------------------------------------------------------------------------
# Hold / Rebalance / StrategyResult.
# --------------------------------------------------------------------------------------


def test_hold_requires_non_empty_reason() -> None:
    authoring.Hold(reason="cooldown")
    with pytest.raises(ValueError):
        authoring.Hold(reason="")


def test_rebalance_requires_complete_target_and_cash_within_budget() -> None:
    budget = _budget()
    authoring.Rebalance(
        target_weights={"A": Decimal("0.6")}, cash_weight=Decimal("0.4"), budget=budget
    )
    with pytest.raises(ValueError):
        authoring.Rebalance(
            target_weights={"A": Decimal("0.6")}, cash_weight=Decimal("0.5"), budget=budget
        )


def test_rebalance_empty_targets_require_full_cash() -> None:
    budget = _budget()
    authoring.Rebalance(target_weights={}, cash_weight=Decimal("1"), budget=budget)
    with pytest.raises(ValueError):
        authoring.Rebalance(target_weights={}, cash_weight=Decimal("0.5"), budget=budget)


def test_rebalance_long_only_budget_forbids_negative_targets() -> None:
    budget = _budget(PortfolioDirection.LONG_ONLY)
    with pytest.raises(ValueError):
        authoring.Rebalance(
            target_weights={"A": Decimal("-0.1"), "B": Decimal("1.1")},
            cash_weight=Decimal("0"),
            budget=budget,
        )


def test_rebalance_rejects_targets_outside_budget_bounds() -> None:
    narrow_budget = Budget(
        direction=PortfolioDirection.SIGNED,
        cash_lower=Decimal("-1"),
        cash_upper=Decimal("1"),
        target_lower=Decimal("0"),
        target_upper=Decimal("0.1"),
    )
    with pytest.raises(ValueError):
        authoring.Rebalance(
            target_weights={"A": Decimal("0.5")}, cash_weight=Decimal("0.5"), budget=narrow_budget
        )


def test_rebalance_weights_mapping_is_copied_and_immutable() -> None:
    weights = {"A": Decimal("0.5"), "B": Decimal("0.5")}
    budget = _budget()
    decision = authoring.Rebalance(target_weights=weights, cash_weight=Decimal("0"), budget=budget)
    weights["A"] = Decimal("999")
    assert decision.target_weights["A"] == Decimal("0.5")
    with pytest.raises(TypeError):
        decision.target_weights["A"] = Decimal("1")  # type: ignore[index]


def test_strategy_result_requires_hold_or_rebalance_decision() -> None:
    with pytest.raises(TypeError):
        authoring.StrategyResult(decision=object(), next_state=None, diagnostics={})  # type: ignore[arg-type]


def test_strategy_result_normalizes_next_state_to_strict_json() -> None:
    result = authoring.StrategyResult(
        decision=authoring.Hold(reason="x"), next_state={"a": [1, 2.5, None]}, diagnostics={}
    )
    assert result.next_state == {"a": [1, 2.5, None]}
    with pytest.raises(TypeError):
        authoring.StrategyResult(
            decision=authoring.Hold(reason="x"), next_state=object(), diagnostics={}
        )


def test_strategy_result_diagnostics_reject_reserved_row_fields() -> None:
    with pytest.raises(ValueError):
        authoring.StrategyResult(
            decision=authoring.Hold(reason="x"),
            next_state=None,
            diagnostics={"turnover": ({"observed_at": UTC_NOW},)},
        )


def test_strategy_result_diagnostics_are_copied_and_immutable() -> None:
    rows = [{"value": Decimal("1")}]
    result = authoring.StrategyResult(
        decision=authoring.Hold(reason="x"), next_state=None, diagnostics={"turnover": rows}
    )
    rows.append({"value": Decimal("2")})
    assert len(result.diagnostics["turnover"]) == 1
    with pytest.raises(TypeError):
        result.diagnostics["turnover"] = ()  # type: ignore[index]


# --------------------------------------------------------------------------------------
# StrategyCall / StrategyModel abstract contracts.
# --------------------------------------------------------------------------------------


class _FakeStrategyCall(authoring.StrategyCall):
    """A minimal concrete StrategyCall used only to exercise the abstract contract shape."""

    @property
    def evaluation_time(self) -> datetime:
        return UTC_NOW

    @property
    def account(self) -> authoring.EconomicAccountView:
        return authoring.EconomicAccountView(
            cash=Decimal("100"), positions={}, nav=None, nav_observed_at=None
        )

    @property
    def previous_state(self) -> object:
        return None

    @property
    def account_history(self) -> authoring.DeclaredAccountHistory:
        return authoring.DeclaredAccountHistory()

    @property
    def constraint_bounds(self) -> authoring.ConstraintBounds:
        return authoring.ConstraintBounds(lower_weights={}, upper_weights={})

    def read(self, alias: str) -> tuple[authoring.Observation, ...]:
        return ()


def test_strategy_call_is_abstract() -> None:
    with pytest.raises(TypeError):
        authoring.StrategyCall()  # type: ignore[abstract]
    call = _FakeStrategyCall()
    assert call.evaluation_time == UTC_NOW
    assert call.account.cash == Decimal("100")
    assert call.previous_state is None
    assert call.read("px") == ()


def test_strategy_model_is_abstract_and_requires_decide() -> None:
    with pytest.raises(TypeError):
        authoring.StrategyModel()  # type: ignore[abstract]

    class Model(authoring.StrategyModel):
        def decide(self, call: authoring.StrategyCall) -> authoring.StrategyResult:
            return authoring.StrategyResult(
                decision=authoring.Hold(reason="x"), next_state=None, diagnostics={}
            )

    model = Model()
    assert model.inputs() == {}
    assert model.account_history() is None
    assert model.diagnostics() == ()
    result = model.decide(_FakeStrategyCall())
    assert isinstance(result.decision, authoring.Hold)


# --------------------------------------------------------------------------------------
# ConstraintCall / ConstraintFinding / Constraint abstract contracts.
# --------------------------------------------------------------------------------------


def test_constraint_call_is_a_contract_and_carries_no_account() -> None:
    """It was a value nothing in `src/` ever built, and it carried the committed account.

    Both are gone. It is a contract like the other two roles' calls, supplied by the framework;
    and `project` -- the member that runs before any decision exists -- can no longer reach an
    account it never needed. `monitor` receives one as its own argument instead.
    """
    assert isinstance(authoring.ConstraintCall, type)
    with pytest.raises(TypeError):
        authoring.ConstraintCall()  # type: ignore[abstract]

    members = set(authoring.ConstraintCall.__abstractmethods__)
    assert members == {"evaluation_time", "instruments", "read"}, members
    assert "account" not in members


def test_constraint_finding_bounds_details_to_32_keys() -> None:
    authoring.ConstraintFinding(
        passed=True, measured=Decimal("0.1"), bound=Decimal("0.2"), excess=Decimal("0"), details={}
    )
    too_many = {f"k{i}": Decimal("1") for i in range(33)}
    with pytest.raises(ValueError):
        authoring.ConstraintFinding(
            passed=True,
            measured=Decimal("0.1"),
            bound=Decimal("0.2"),
            excess=Decimal("0"),
            details=too_many,
        )


def test_constraint_finding_rejects_reserved_detail_keys() -> None:
    with pytest.raises(ValueError):
        authoring.ConstraintFinding(
            passed=True,
            measured=Decimal("0.1"),
            bound=Decimal("0.2"),
            excess=Decimal("0"),
            details={"constraint_id": "x"},
        )


def test_constraint_is_abstract_and_declares_its_identity_once() -> None:
    with pytest.raises(TypeError):
        authoring.Constraint()  # type: ignore[abstract]

    class Cap(authoring.Constraint):
        def project(self, call: authoring.ConstraintCall) -> authoring.ConstraintBounds:
            return authoring.ConstraintBounds(
                lower_weights={i: Decimal("0") for i in call.instruments},
                upper_weights={i: Decimal("0.1") for i in call.instruments},
            )

        @property
        def constraint_id(self) -> str:
            return "cap"

        def monitor(
            self,
            call: authoring.ConstraintCall,
            account: authoring.EconomicAccountView,
            bounds: authoring.ConstraintBounds,
        ) -> authoring.ConstraintFinding:
            return authoring.ConstraintFinding(
                passed=True,
                measured=Decimal("0"),
                bound=Decimal("0.1"),
                excess=Decimal("0"),
                details={},
            )

    constraint = Cap()
    assert constraint.inputs() == {}
    # Declared once, here, and checked at load against the id it was registered under. What was
    # removed is the repetition: a finding no longer restates it.
    assert constraint.constraint_id == "cap"
    assert not hasattr(authoring.ConstraintFinding, "constraint_id")

    class _Call(authoring.ConstraintCall):
        evaluation_time = UTC_NOW
        instruments = ("A",)

        def read(self, alias: str):
            raise AssertionError("this rule declared no reads")

    bounds = constraint.project(_Call())
    assert bounds.upper_weight("A") == Decimal("0.1")


# --------------------------------------------------------------------------------------
# Reserved-field / no-identity / no-mutable-memory surface checks.
# --------------------------------------------------------------------------------------


def test_no_public_type_exposes_account_version_or_recorder_or_memory() -> None:
    forbidden = {"account_version", "version", "recorder", "memory", "constraint_id"}
    for name in authoring.__all__:
        value = getattr(authoring, name)
        annotations = getattr(value, "__annotations__", {})
        assert forbidden.isdisjoint(annotations)
