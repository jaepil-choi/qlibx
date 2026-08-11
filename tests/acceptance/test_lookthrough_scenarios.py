from datetime import datetime
from fractions import Fraction

import pytest

from qlibx import OutcomeStatus
from qlibx.account import Account, FillBatch, Mark, MarkBatch
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    StrategyDraft,
    StrategyInvocation,
    StrategyOperation,
    WeightEntry,
)
from qlibx.data import ComponentRequirement
from qlibx.execution import Fill, Side
from qlibx.flow import ResearchFlow
from qlibx.view import StrategyView
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    real_lookthrough_physical_prices,
)

DIRECT = "A012330"
ETF = "A069500"
OTHER_CONSTITUENT = "A373220"


def _physical_account(
    *,
    account_id: str,
    trade_date: int,
    direct_units: int,
    etf_units: int,
    cash_units: int,
) -> Account:
    direct_price, etf_price = real_lookthrough_physical_prices(trade_date)
    as_of = close_at(trade_date // 10_000, trade_date // 100 % 100, trade_date % 100)
    quantity_ratio = Fraction(
        etf_units * int(direct_price),
        direct_units * int(etf_price),
    )
    direct_quantity = quantity_ratio.denominator
    etf_quantity = quantity_ratio.numerator
    direct_value = direct_quantity * direct_price
    etf_value = etf_quantity * etf_price
    cash = direct_value * cash_units / direct_units
    initial_cash = cash + direct_value + etf_value
    account = Account(
        account_id=account_id,
        base_currency="KRW",
        initial_cash=initial_cash,
        instrument_ids=frozenset({DIRECT, ETF}),
    )
    account.commit(
        FillBatch(
            account_id=account_id,
            event_id=f"{account_id}:physical-fill",
            as_of=as_of,
            fills=(
                Fill(
                    fill_id=f"{account_id}:direct-fill",
                    instrument_id=DIRECT,
                    side=Side.BUY,
                    requested_quantity=direct_quantity,
                    dealt_quantity=direct_quantity,
                    price=direct_price,
                    trade_value=direct_value,
                    total_cost=0,
                    cost_rule_id="real-physical-state",
                    schedule_version="real-2024",
                ),
                Fill(
                    fill_id=f"{account_id}:etf-fill",
                    instrument_id=ETF,
                    side=Side.BUY,
                    requested_quantity=etf_quantity,
                    dealt_quantity=etf_quantity,
                    price=etf_price,
                    trade_value=etf_value,
                    total_cost=0,
                    cost_rule_id="real-physical-state",
                    schedule_version="real-2024",
                ),
            ),
        ),
        expected_version=0,
    )
    snapshot = account.commit(
        MarkBatch(
            account_id=account_id,
            event_id=f"{account_id}:physical-mark",
            as_of=as_of,
            marks=(Mark(DIRECT, direct_price), Mark(ETF, etf_price)),
        ),
        expected_version=1,
    ).snapshot
    denominator = direct_units + etf_units + cash_units
    weights = {
        position.instrument_id: position.quantity * position.mark / snapshot.nav
        for position in snapshot.positions
        if position.mark is not None
    }
    assert weights[DIRECT] == pytest.approx(direct_units / denominator)
    assert weights[ETF] == pytest.approx(etf_units / denominator)
    assert snapshot.cash / snapshot.nav == pytest.approx(cash_units / denominator)
    return account


def _strategy_state() -> dict[str, object]:
    return {
        "requested_physical_target": {
            DIRECT: 0.3,
            ETF: 0.7,
        }
    }


class OpaqueEtfStrategy:
    strategy_id = "user.opaque-etf"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def run(self, view: StrategyView) -> StrategyDraft:
        account = view.account_snapshot()
        weights = tuple(
            WeightEntry(
                instrument=position.instrument_id,
                weight=position.quantity * position.mark / account.nav,
            )
            for position in account.positions
            if position.mark is not None
        )
        return StrategyDraft(
            weights=weights,
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=("physical ETF kept opaque; no constituent binding consumed",),
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
        )


class UndeclaredConstituentStrategy:
    strategy_id = "user.undeclared-constituent"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def run(self, view: StrategyView) -> StrategyDraft:
        view.latest("etf_constituent_weight")
        raise AssertionError("an undeclared role must fail before this line")


class UserLookthroughStrategy:
    strategy_id = "user.k200-etf-lookthrough"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="user.lookthrough.constituents",
                semantic_role="etf_constituent_weight",
                dataset_id="real-k200-etf-constituents",
            ),
        )

    def run(self, view: StrategyView) -> StrategyDraft:
        frame = view.latest("etf_constituent_weight")
        account = view.account_snapshot()
        strategy_state = view.strategy_state()
        if set(frame["instrument"]) != {DIRECT, OTHER_CONSTITUENT}:
            raise ValueError("user policy requires the selected two-member coverage")
        raw = {
            str(row.instrument): float(row.etf_constituent_weight)
            for row in frame.itertuples(index=False)
        }
        total = sum(raw.values())
        mapping = {instrument: value / total for instrument, value in raw.items()}
        physical = {
            position.instrument_id: position.quantity * position.mark / account.nav
            for position in account.positions
            if position.mark is not None
        }
        actual = {
            DIRECT: physical.get(DIRECT, 0.0) + physical.get(ETF, 0.0) * mapping[DIRECT],
            OTHER_CONSTITUENT: physical.get(ETF, 0.0) * mapping[OTHER_CONSTITUENT],
        }
        if not isinstance(strategy_state, dict):
            raise ValueError("user Strategy requires an explicit target state")
        target = strategy_state["requested_physical_target"]
        if not isinstance(target, dict):
            raise ValueError("requested target Memory must be a mapping")
        target_direct = float(target[DIRECT])
        target_etf = float(target[ETF])
        target_exposure = {
            DIRECT: target_direct + target_etf * mapping[DIRECT],
            OTHER_CONSTITUENT: target_etf * mapping[OTHER_CONSTITUENT],
        }
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=instrument, weight=weight)
                for instrument, weight in sorted(actual.items())
            ),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=(
                "mapping_policy=user_selected_two_member_subset_renormalized",
                "actual_source=marked_account_snapshot",
                (
                    f"state_target_exposure:{DIRECT}={target_exposure[DIRECT]:.12f},"
                    f"{OTHER_CONSTITUENT}={target_exposure[OTHER_CONSTITUENT]:.12f}"
                ),
            ),
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
        )


def _invoke(
    case: RealDwProject,
    strategy: StrategyOperation,
    *,
    invocation_id: str,
    evaluation_time: datetime,
    account: Account,
    strategy_state: object = None,
):
    return ResearchFlow(
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
    ).invoke_strategy(
        strategy,
        StrategyInvocation(
            invocation_id=invocation_id,
            evaluation_time=evaluation_time,
            config_fingerprint="user-lookthrough-v1",
            initial_strategy_state=strategy_state,
        ),
        account_state=account.snapshot(),
    )


def test_uc_lookthrough_001_is_user_declared_while_same_etf_stays_opaque(
    real_dw_lookthrough_case: RealDwProject,
) -> None:
    account = _physical_account(
        account_id="lookthrough-001",
        trade_date=20240103,
        direct_units=1,
        etf_units=3,
        cash_units=1,
    )
    strategy = UserLookthroughStrategy()
    strategy_state = _strategy_state()
    account_before = account.checkpoint()
    opaque = _invoke(
        real_dw_lookthrough_case,
        OpaqueEtfStrategy(),
        invocation_id="lookthrough-001-opaque",
        evaluation_time=close_at(2024, 1, 3),
        account=account,
    )
    explicit = _invoke(
        real_dw_lookthrough_case,
        strategy,
        invocation_id="lookthrough-001-explicit",
        evaluation_time=close_at(2024, 1, 3),
        account=account,
        strategy_state=strategy_state,
    )
    undeclared = _invoke(
        real_dw_lookthrough_case,
        UndeclaredConstituentStrategy(),
        invocation_id="lookthrough-001-undeclared",
        evaluation_time=close_at(2024, 1, 3),
        account=account,
    )

    assert opaque.status is explicit.status is OutcomeStatus.COMPLETE
    assert {
        item.instrument: item.weight for item in opaque.result.result.weights
    } == pytest.approx({DIRECT: 0.2, ETF: 0.6})
    assert opaque.result.result.accesses == ()
    assert {
        item.instrument: item.weight for item in explicit.result.result.weights
    } == pytest.approx({DIRECT: 0.5, OTHER_CONSTITUENT: 0.3})
    assert explicit.result.artifact.artifact_type == "strategy_result"
    assert len(explicit.result.result.accesses) == 1
    assert len(explicit.result.result.state_accesses) == 1
    assert len(explicit.result.result.strategy_state_accesses) == 1
    assert any(
        edge.consumer_role == "etf_constituent_weight"
        for edge in explicit.result.artifact.dependencies
    )
    assert all(
        edge.consumer_role != "etf_constituent_weight"
        for edge in opaque.result.artifact.dependencies
    )
    assert undeclared.status is OutcomeStatus.FAILED
    assert undeclared.errors[0].error_code == "STRATEGY_RUN_FAILED"
    assert "was not declared" in undeclared.errors[0].context["message"]
    assert account.checkpoint() == account_before


def test_uc_lookthrough_002_hides_future_real_constituent_observation(
    real_dw_lookthrough_case: RealDwProject,
) -> None:
    strategy = UserLookthroughStrategy()
    early_account = _physical_account(
        account_id="lookthrough-002-early",
        trade_date=20240103,
        direct_units=1,
        etf_units=3,
        cash_units=1,
    )
    late_account = _physical_account(
        account_id="lookthrough-002-late",
        trade_date=20240104,
        direct_units=1,
        etf_units=3,
        cash_units=1,
    )
    early = _invoke(
        real_dw_lookthrough_case,
        strategy,
        invocation_id="lookthrough-002-early",
        evaluation_time=close_at(2024, 1, 3),
        account=early_account,
        strategy_state=_strategy_state(),
    )
    late = _invoke(
        real_dw_lookthrough_case,
        strategy,
        invocation_id="lookthrough-002-late",
        evaluation_time=close_at(2024, 1, 4),
        account=late_account,
        strategy_state=_strategy_state(),
    )

    assert early.status is late.status is OutcomeStatus.COMPLETE
    early_access = early.result.result.accesses[0]
    late_access = late.result.result.accesses[0]
    assert early_access.max_observation_time.date().isoformat() == "2024-01-02"
    assert early_access.max_available_at.astimezone(
        close_at(2024, 1, 3).tzinfo
    ).isoformat() == "2024-01-03T09:00:00+09:00"
    assert late_access.max_observation_time.date().isoformat() == "2024-01-03"
    assert late_access.max_available_at.astimezone(
        close_at(2024, 1, 4).tzinfo
    ).isoformat() == "2024-01-04T09:00:00+09:00"
    early_weights = {
        item.instrument: item.weight for item in early.result.result.weights
    }
    late_weights = {
        item.instrument: item.weight for item in late.result.result.weights
    }
    assert early_weights == pytest.approx({DIRECT: 0.5, OTHER_CONSTITUENT: 0.3})
    assert late_weights[DIRECT] == pytest.approx(0.2 + 0.6 * (0.0126 / 0.0253))
    assert late_weights[OTHER_CONSTITUENT] == pytest.approx(0.6 * (0.0127 / 0.0253))


def test_uc_lookthrough_003_recomputes_actual_instead_of_strategy_state_target(
    real_dw_lookthrough_case: RealDwProject,
) -> None:
    account = _physical_account(
        account_id="lookthrough-003-actual",
        trade_date=20240103,
        direct_units=1,
        etf_units=2,
        cash_units=2,
    )
    strategy = UserLookthroughStrategy()
    strategy_state = _strategy_state()
    before_account = account.checkpoint()
    result = _invoke(
        real_dw_lookthrough_case,
        strategy,
        invocation_id="lookthrough-003-actual",
        evaluation_time=close_at(2024, 1, 3),
        account=account,
        strategy_state=strategy_state,
    )

    assert result.status is OutcomeStatus.COMPLETE
    assert {
        item.instrument: item.weight for item in result.result.result.weights
    } == pytest.approx({DIRECT: 0.4, OTHER_CONSTITUENT: 0.2})
    assert (
        f"state_target_exposure:{DIRECT}=0.650000000000,"
        f"{OTHER_CONSTITUENT}=0.350000000000"
    ) in result.result.result.diagnostics
    assert result.result.result.state_identity == (
        f"{account.snapshot().account_id}:v{account.snapshot().version}"
    )
    assert any(
        edge.consumer_role == "actual_account"
        for edge in result.result.artifact.dependencies
    )
    assert any(
        edge.consumer_role == "strategy_state"
        for edge in result.result.artifact.dependencies
    )
    assert account.checkpoint() == before_account
