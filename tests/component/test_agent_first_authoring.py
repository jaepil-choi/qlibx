"""Pure-contract tests for `vqapr.public`.

No runtime adapter, store, or Flow wiring is exercised here — only construction, validation,
alias/immutability semantics, and the exact public export surface of the module itself.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from vqapr import public
from vqapr.domain.intent import Budget, PortfolioDirection

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
# The author's names, all on the one surface.
# --------------------------------------------------------------------------------------

AUTHOR_NAMES = frozenset(
    {
        "AccountHistory",
        "AccountHistoryInput",
        "CalendarLookback",
        "Compliance",
        "ComplianceCall",
        "ComplianceFinding",
        "Component",
        "DataCall",
        "DataModel",
        "DatasetInput",
        "EconomicAccountView",
        "Hold",
        "InstantsLookback",
        "Observation",
        "PanelWindow",
        "Part",
        "Rebalance",
        "RowsLookback",
        "StrategyCall",
        "StrategyModel",
        "TableSpec",
        "Tool",
        "requirements_for",
    }
)
"""What `vqapr.authoring` exported until 0.16.0 removed it (record `279`): every name an author
writes against. They are on `vqapr.public` now, the one author surface."""


def test_every_author_name_is_on_the_one_surface() -> None:
    missing = sorted(AUTHOR_NAMES - set(public.__all__))
    assert not missing, f"the author surface lost {missing}"
    for name in AUTHOR_NAMES:
        assert hasattr(public, name)


# --------------------------------------------------------------------------------------
# RowsLookback / CalendarLookback.
# --------------------------------------------------------------------------------------


def test_rows_lookback_requires_positive_int() -> None:
    public.RowsLookback(rows=1)
    with pytest.raises(ValueError):
        public.RowsLookback(rows=0)
    # Strict pydantic: a bool is refused as not-an-integer, as a `ValidationError` (a
    # `ValueError`) rather than the `TypeError` the dataclass raised.
    with pytest.raises(ValueError, match="integer"):
        public.RowsLookback(rows=True)


def test_rows_lookback_is_frozen_and_takes_its_count_either_way() -> None:
    """Keyword-only is gone, and it went deliberately.

    `public.RowsLookback` was a keyword-only copy of `data.lookback.RowsLookback`, which is
    not. Record `126` made them one class and kept the engine's, so `RowsLookback(3)` is now
    legal alongside `RowsLookback(rows=3)`. Nothing authored changes -- every call site in the
    tree and in the research workspace already spells the keyword -- but a test asserting the
    refusal would now be pinning a difference that only existed because there were two classes.

    Frozen survives the move to pydantic; slotted did not, and was never a contract an author
    relied on.
    """
    lookback = public.RowsLookback(rows=3)
    with pytest.raises(ValidationError, match="frozen"):
        lookback.rows = 4  # type: ignore[misc]
    assert public.RowsLookback(3) == lookback


def test_calendar_lookback_requires_at_least_one_positive_amount() -> None:
    public.CalendarLookback(days=1)
    with pytest.raises(ValueError):
        public.CalendarLookback()


def test_calendar_lookback_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError):
        public.CalendarLookback(days=1, timezone="Not/AZone")


def test_calendar_lookback_lower_bound_is_local_midnight() -> None:
    lookback = public.CalendarLookback(days=5, timezone="Asia/Seoul")
    bound = lookback.lower_bound(UTC_NOW)
    assert bound.tzinfo is not None
    assert bound < UTC_NOW


# --------------------------------------------------------------------------------------
# DatasetInput / Observation / Output / DerivedRow.
# --------------------------------------------------------------------------------------


def test_dataset_input_rejects_reserved_and_duplicate_fields() -> None:
    public.DatasetInput(
        dataset_id="px", fields=("close",), lookback=public.RowsLookback(rows=1)
    )
    with pytest.raises(ValueError):
        public.DatasetInput(
            dataset_id="px", fields=("instrument",), lookback=public.RowsLookback(rows=1)
        )
    with pytest.raises(ValueError):
        public.DatasetInput(
            dataset_id="px", fields=("close", "close"), lookback=public.RowsLookback(rows=1)
        )
    with pytest.raises(ValueError):
        public.DatasetInput(dataset_id="px", fields=(), lookback=public.RowsLookback(rows=1))
    with pytest.raises(ValidationError, match="Lookback"):
        public.DatasetInput(dataset_id="px", fields=("close",), lookback=object())


def test_observation_requires_tz_aware_available_at_and_finite_values() -> None:
    public.Observation("A", UTC_NOW, {"close": Decimal("1.5")})
    with pytest.raises(ValueError):
        public.Observation("A", NAIVE_NOW, {"close": Decimal("1.5")})
    with pytest.raises(ValueError):
        public.Observation("A", UTC_NOW, {"close": Decimal("NaN")})
    with pytest.raises(TypeError):
        public.Observation("A", UTC_NOW, {"close": object()})
    with pytest.raises(ValueError):
        public.Observation("", UTC_NOW, {})


def test_observation_values_mapping_is_copied_and_immutable() -> None:
    source = {"close": Decimal("1")}
    observation = public.Observation("A", UTC_NOW, source)
    source["close"] = Decimal("999")
    assert observation.values["close"] == Decimal("1")
    with pytest.raises(TypeError):
        observation.values["close"] = Decimal("2")  # type: ignore[index]


def test_a_hand_built_observation_is_still_validated_while_a_framework_row_is_not() -> None:
    """`docs/issues/archive/054`: the distinction is who built the row, not whether rows are checked."""
    with pytest.raises(ValueError):
        public.Observation("A", UTC_NOW, {"a b": Decimal("1")})
    trusted = public.Observation._framework_row("A", UTC_NOW, {"close": Decimal("1")})
    assert trusted == public.Observation("A", UTC_NOW, {"close": Decimal("1")})
    with pytest.raises(TypeError):
        trusted.values["close"] = Decimal("2")  # type: ignore[index]


# --------------------------------------------------------------------------------------
# DataModel / DataCall abstract contracts.
# --------------------------------------------------------------------------------------


def test_data_model_is_abstract_and_requires_only_compute() -> None:
    """One abstract member. The output schema is the materialization's declaration, not the
    model's (record `131`), so there is nothing else for an author to have to write."""
    with pytest.raises(TypeError):
        public.DataModel()  # type: ignore[abstract]
    assert set(public.DataModel.__abstractmethods__) == {"compute"}


def test_data_model_is_a_model_and_inputs_defaults_to_empty() -> None:
    class Model(public.DataModel):
        def compute(self, call: public.DataCall):
            return ()

    model = Model()
    assert isinstance(model, public.Component)
    assert model.inputs() == {}
    assert model.requirements() == ()
    assert model.compute(_FakeDataCall()) == ()


class _FakeDataCall(public.DataCall):
    """A minimal concrete DataCall used only to exercise the abstract contract shape."""

    @property
    def at(self) -> datetime:
        return UTC_NOW

    def read(self, alias: str, field: str) -> public.PanelWindow:
        raise TypeError("this fake serves a rows grain only")

    def rows(self, alias: str) -> tuple[public.Observation, ...]:
        return (public.Observation("A", UTC_NOW, {"close": Decimal("1")}),) if alias else ()


def test_data_call_is_abstract() -> None:
    with pytest.raises(TypeError):
        public.DataCall()  # type: ignore[abstract]
    call = _FakeDataCall()
    assert call.at == UTC_NOW
    assert call.rows("px")[0].instrument_id == "A"


# --------------------------------------------------------------------------------------
# AccountHistoryInput.
# --------------------------------------------------------------------------------------


def test_account_history_input_rejects_unknown_field() -> None:
    public.AccountHistoryInput(fields=("nav",), lookback=public.RowsLookback(rows=2))
    with pytest.raises(ValueError):
        public.AccountHistoryInput(
            fields=("not_a_field",), lookback=public.RowsLookback(rows=2)
        )
    with pytest.raises(ValidationError, match="RowsLookback"):
        public.AccountHistoryInput(fields=("nav",), lookback=object())


# --------------------------------------------------------------------------------------
# EconomicAccountView.
# --------------------------------------------------------------------------------------


def test_economic_account_view_couples_nav_and_nav_observed_at() -> None:
    public.EconomicAccountView(cash=Decimal("10"), positions={}, nav=None, nav_observed_at=None)
    public.EconomicAccountView(
        cash=Decimal("10"), positions={}, nav=Decimal("10"), nav_observed_at=UTC_NOW
    )
    with pytest.raises(ValueError):
        public.EconomicAccountView(
            cash=Decimal("10"), positions={}, nav=Decimal("10"), nav_observed_at=None
        )
    with pytest.raises(ValueError):
        public.EconomicAccountView(
            cash=Decimal("10"), positions={}, nav=None, nav_observed_at=UTC_NOW
        )


def test_economic_account_view_quantity_defaults_to_zero_and_positions_are_immutable() -> None:
    positions = {"A": Decimal("5")}
    view = public.EconomicAccountView(
        cash=Decimal("10"), positions=positions, nav=None, nav_observed_at=None
    )
    positions["A"] = Decimal("999")
    assert view.quantity("A") == Decimal("5")
    assert view.quantity("ABSENT") == Decimal(0)
    with pytest.raises(TypeError):
        view.positions["A"] = Decimal("1")  # type: ignore[index]


def test_economic_account_view_has_no_version_or_mutation_escape() -> None:
    view = public.EconomicAccountView(
        cash=Decimal("10"), positions={}, nav=None, nav_observed_at=None
    )
    assert not hasattr(view, "version")
    assert not hasattr(view, "account_version")
    with pytest.raises(FrozenInstanceError):
        view.cash = Decimal("0")  # type: ignore[misc]


# --------------------------------------------------------------------------------------
# Hold / Rebalance.
# --------------------------------------------------------------------------------------


def test_hold_requires_non_empty_reason() -> None:
    public.Hold(reason="cooldown")
    with pytest.raises(ValueError):
        public.Hold(reason="")


def test_rebalance_requires_complete_target_and_cash_within_budget() -> None:
    budget = _budget()
    public.Rebalance(
        target_weights={"A": Decimal("0.6")}, cash_weight=Decimal("0.4"), budget=budget
    )
    with pytest.raises(ValueError):
        public.Rebalance(
            target_weights={"A": Decimal("0.6")}, cash_weight=Decimal("0.5"), budget=budget
        )


def test_rebalance_empty_targets_require_full_cash() -> None:
    budget = _budget()
    public.Rebalance(target_weights={}, cash_weight=Decimal("1"), budget=budget)
    with pytest.raises(ValueError):
        public.Rebalance(target_weights={}, cash_weight=Decimal("0.5"), budget=budget)


def test_rebalance_long_only_budget_forbids_negative_targets() -> None:
    budget = _budget(PortfolioDirection.LONG_ONLY)
    with pytest.raises(ValueError):
        public.Rebalance(
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
        public.Rebalance(
            target_weights={"A": Decimal("0.5")}, cash_weight=Decimal("0.5"), budget=narrow_budget
        )


def test_rebalance_weights_mapping_is_copied_and_immutable() -> None:
    weights = {"A": Decimal("0.5"), "B": Decimal("0.5")}
    budget = _budget()
    decision = public.Rebalance(target_weights=weights, cash_weight=Decimal("0"), budget=budget)
    weights["A"] = Decimal("999")
    assert decision.target_weights["A"] == Decimal("0.5")
    with pytest.raises(TypeError):
        decision.target_weights["A"] = Decimal("1")  # type: ignore[index]


# --------------------------------------------------------------------------------------
# StrategyCall / StrategyModel abstract contracts.
# --------------------------------------------------------------------------------------


class _FakeStrategyCall(public.StrategyCall):
    """A minimal concrete StrategyCall used only to exercise the abstract contract shape."""

    @property
    def event_id(self) -> str:
        return "occ-1"

    @property
    def at(self) -> datetime:
        return UTC_NOW

    @property
    def account(self) -> public.EconomicAccountView:
        return public.EconomicAccountView(
            cash=Decimal("100"), positions={}, nav=None, nav_observed_at=None
        )

    @property
    def account_history(self) -> public.AccountHistory:
        return public.AccountHistory((), None)

    def read(self, alias: str, field: str) -> public.PanelWindow:
        raise TypeError("this fake serves a rows grain only")

    def rows(self, alias: str) -> tuple[public.Observation, ...]:
        return ()


def test_strategy_call_is_abstract() -> None:
    with pytest.raises(TypeError):
        public.StrategyCall()  # type: ignore[abstract]
    call = _FakeStrategyCall()
    assert call.at == UTC_NOW
    assert call.account.cash == Decimal("100")
    assert call.event_id == "occ-1"
    assert call.rows("px") == ()


def test_strategy_model_is_a_model_and_requires_only_decide() -> None:
    """One class, one abstract member; state is `memory` and rows go to `recorder` (record 132)."""
    with pytest.raises(TypeError):
        public.StrategyModel()  # type: ignore[abstract]
    assert issubclass(public.StrategyModel, public.Component)

    class Model(public.StrategyModel):
        def decide(self, call: public.StrategyCall) -> public.Hold:
            self.memory = {"seen": [call.event_id]}
            return public.Hold(reason="x")

    model = Model()
    assert model.inputs() == {}
    assert model.requirements() == ()
    assert model.account_history() is None
    assert model.tables() == ()
    assert model.recorder is None
    assert model.memory is None
    assert isinstance(model.decide(_FakeStrategyCall()), public.Hold)
    assert model.memory == {"seen": ["occ-1"]}


# --------------------------------------------------------------------------------------
# ComplianceCall / ComplianceFinding / Compliance abstract contracts.
# --------------------------------------------------------------------------------------


def test_compliance_call_is_a_contract_and_carries_the_account() -> None:
    """A contract like the other two roles' calls, supplied by the framework. The committed
    account a rule observes is on the call (record `229`): one Call is the whole of a role's
    authority, so nothing is handed beside it."""
    assert isinstance(public.ComplianceCall, type)
    with pytest.raises(TypeError):
        public.ComplianceCall()  # type: ignore[abstract]

    members = set(public.ComplianceCall.__abstractmethods__)
    assert members == {"account", "at", "instruments", "read", "rows"}, members


def test_compliance_finding_bounds_details_to_32_keys() -> None:
    public.ComplianceFinding(
        passed=True, measured=Decimal("0.1"), bound=Decimal("0.2"), excess=Decimal("0"), details={}
    )
    too_many = {f"k{i}": Decimal("1") for i in range(33)}
    with pytest.raises(ValueError):
        public.ComplianceFinding(
            passed=True,
            measured=Decimal("0.1"),
            bound=Decimal("0.2"),
            excess=Decimal("0"),
            details=too_many,
        )


def test_compliance_finding_rejects_reserved_detail_keys() -> None:
    with pytest.raises(ValueError):
        public.ComplianceFinding(
            passed=True,
            measured=Decimal("0.1"),
            bound=Decimal("0.2"),
            excess=Decimal("0"),
            details={"compliance_id": "x"},
        )


def test_compliance_is_abstract_and_declares_its_identity_once() -> None:
    """One member, `observe` (design §7.2); the id declared once and never restated on a
    finding; the tolerance left to the framework unless the author overrides it."""
    with pytest.raises(TypeError):
        public.Compliance()  # type: ignore[abstract]

    class Cap(public.Compliance):
        @property
        def compliance_id(self) -> str:
            return "cap"

        def observe(self, call: public.ComplianceCall) -> public.ComplianceFinding:
            worst = max((abs(q) for q in call.account.positions.values()), default=Decimal("0"))
            return public.ComplianceFinding(
                passed=worst <= Decimal("0.1"),
                measured=worst,
                bound=Decimal("0.1"),
                excess=max(worst - Decimal("0.1"), Decimal("0")),
                details={},
            )

    rule = Cap()
    assert rule.inputs() == {}
    assert rule.compliance_id == "cap"
    assert rule.tolerance is None
    assert not hasattr(public.ComplianceFinding, "compliance_id")
    assert not hasattr(rule, "project"), "the box is the strategy's kit call, not a member here"

    view = public.EconomicAccountView(
        cash=Decimal("100"), positions={"A": Decimal("0.2")}, nav=None, nav_observed_at=None
    )

    class _Call(public.ComplianceCall):
        at = UTC_NOW
        instruments = ("A",)
        account = view

        def read(self, alias: str, field: str):
            raise AssertionError("this rule declared no reads")

        def rows(self, alias: str):
            raise AssertionError("this rule declared no reads")

    finding = rule.observe(_Call())
    assert finding.passed is False and finding.excess == Decimal("0.1")


# --------------------------------------------------------------------------------------
# Reserved-field / no-identity / no-mutable-memory surface checks.
# --------------------------------------------------------------------------------------


def test_no_public_type_exposes_account_version_or_recorder_or_memory() -> None:
    forbidden = {"account_version", "version", "recorder", "memory", "compliance_id"}
    for name in sorted(AUTHOR_NAMES):
        if name in {"Component", "Part", "Tool", "StrategyModel"}:
            # `Component` carries `memory` on purpose: it is the small strict-JSON state every role
            # shares (architecture 4.4; a Compliance rule too, owner ruling 2026-09-08), and it arrived on
            # this surface with the base class in record `131`. `StrategyModel` carries `recorder`
            # the same way (5.1, record `132`). What this test guards is that no VALUE type -- a call,
            # a finding, a decision -- smuggles framework state in through an annotation.
            continue
        value = getattr(public, name)
        annotations = getattr(value, "__annotations__", {})
        assert forbidden.isdisjoint(annotations), (name, annotations)
