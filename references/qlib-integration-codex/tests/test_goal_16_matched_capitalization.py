from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml
from pandas.testing import assert_frame_equal

from _workflow_contract import (
    invocation_count,
    load_public_api,
    make_project,
    run_by_strategy,
    strategy_config,
)


def test_future_ticker_is_dormant_until_it_can_realize_a_same_bar_short(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(project.config_path)

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    catalog = api.open_run_catalog(project.catalog_path)
    signed = catalog.load_table(run.backtest_run_id, "signed_positions")

    dormant = _instrument_at(signed, dates[0], "IPO")
    assert dormant["intended_weight"] == pytest.approx(0.0)
    assert dormant["target_quantity"] == pytest.approx(0.0)
    assert dormant["held_quantity"] == pytest.approx(0.0)
    assert dormant["baseline_quantity"] == pytest.approx(0.0)
    assert dormant["composite_quantity"] == pytest.approx(0.0)

    first_observed = _instrument_at(signed, dates[1], "IPO")
    assert first_observed["intended_weight"] == pytest.approx(-0.2)
    assert first_observed["target_quantity"] == pytest.approx(-20.0)
    assert first_observed["held_quantity"] == pytest.approx(-20.0)
    assert first_observed["baseline_quantity"] == pytest.approx(30.0)
    assert first_observed["composite_quantity"] == pytest.approx(10.0)
    assert (signed["composite_quantity"] >= 0.0).all()

    order = _instrument_at(
        catalog.load_table(run.backtest_run_id, "orders"), dates[1], "IPO"
    )
    fill = _instrument_at(
        catalog.load_table(run.backtest_run_id, "fills"), dates[1], "IPO"
    )
    assert order["direction"] == "sell"
    assert order["requested_quantity"] == pytest.approx(20.0)
    assert fill["filled_quantity"] == pytest.approx(20.0)
    assert fill["trade_price"] == pytest.approx(10.0)


def test_partial_fill_changes_realized_short_by_dealt_amount_only(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(
        project.config_path,
        ipo_volume=(1_000.0, 5.0, 1_000.0, 1_000.0),
    )

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    catalog = api.open_run_catalog(project.catalog_path)
    signed = catalog.load_table(run.backtest_run_id, "signed_positions")
    first_observed = _instrument_at(signed, dates[1], "IPO")

    assert first_observed["target_quantity"] == pytest.approx(-20.0)
    assert first_observed["held_quantity"] == pytest.approx(-5.0)
    assert first_observed["baseline_quantity"] == pytest.approx(30.0)
    assert first_observed["composite_quantity"] == pytest.approx(25.0)

    fill = _instrument_at(
        catalog.load_table(run.backtest_run_id, "fills"), dates[1], "IPO"
    )
    assert fill["filled_quantity"] == pytest.approx(5.0)
    assert fill["reason_code"] == "volume_limited"


def test_active_pnl_and_report_are_not_diluted_by_the_composite_account(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(
        project.config_path,
        ipo_prices=(10.0, 10.0, 8.0, 8.0),
        initial_cash=3_000.0,
        active_booksize=1_000.0,
    )

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    catalog = api.open_run_catalog(project.catalog_path)
    composite = catalog.load_table(run.backtest_run_id, "account_daily")
    baseline = catalog.load_table(run.backtest_run_id, "baseline_account_daily")
    active = catalog.load_table(run.backtest_run_id, "active_account_daily")

    composite_mark = _account_at(composite, dates[2])
    baseline_mark = _account_at(baseline, dates[2])
    active_mark = _account_at(active, dates[2])
    assert composite_mark["nav"] == pytest.approx(2_980.0)
    assert baseline_mark["nav"] == pytest.approx(1_940.0)
    assert active_mark["nav"] == pytest.approx(1_040.0)
    assert composite_mark["nav"] == pytest.approx(
        baseline_mark["nav"] + active_mark["nav"]
    )
    assert active_mark["money_pnl"] == pytest.approx(40.0)
    assert active_mark["return_denominator"] == pytest.approx(1_000.0)
    assert active_mark["portfolio_return"] == pytest.approx(0.04)

    report = api.create_report(
        project.catalog_path,
        backtest_run_ids=(run.backtest_run_id,),
        output_dir=tmp_path / "report",
    )
    report_text = report.html_path.read_text(encoding="utf-8").lower()
    assert "active" in report_text
    assert "0.040000" in report_text


def test_stored_alpha_ensemble_nets_signed_intent_before_execution(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    audit_path = tmp_path / "strategy-invocations.txt"
    project = make_project(
        tmp_path,
        strategies={
            "short": strategy_config(scale=1.0, audit_path=audit_path),
            "long": strategy_config(scale=-1.0, audit_path=audit_path),
        },
    )
    _configure_signed_project(project.config_path)
    members = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("short", "long"),
            max_workers=1,
        )
    )

    ensemble = api.build_ensemble(
        project.catalog_path,
        strategy_id="ensemble.market-neutral",
        members={
            members["short"].alpha_run_id: 0.5,
            members["long"].alpha_run_id: 0.5,
        },
    )
    catalog = api.open_run_catalog(project.catalog_path)
    signed = catalog.load_table(ensemble.backtest_run_id, "signed_positions")

    assert signed[
        [
            "intended_weight",
            "target_quantity",
            "held_quantity",
            "baseline_quantity",
            "composite_quantity",
        ]
    ].eq(0.0).all().all()
    assert catalog.load_table(ensemble.backtest_run_id, "orders").empty
    assert catalog.load_table(ensemble.backtest_run_id, "fills").empty
    active = catalog.load_table(ensemble.backtest_run_id, "active_account_daily")
    assert active["nav"].eq(1_000.0).all()
    assert active["portfolio_return"].eq(0.0).all()


def test_capitalization_policy_changes_backtest_result_without_rerunning_alpha(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(project.config_path, safety_multiplier=1.0)
    first = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    invocations_before = invocation_count(project.audit_path)

    config = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    config["backtest"]["matched_capitalization"]["safety_multiplier"] = 2.0
    project.config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    second = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]

    assert second.alpha_run_id == first.alpha_run_id
    assert second.backtest_run_id != first.backtest_run_id
    assert invocation_count(project.audit_path) == invocations_before

    catalog = api.open_run_catalog(project.catalog_path)
    first_position = _instrument_at(
        catalog.load_table(first.backtest_run_id, "signed_positions"),
        dates[1],
        "IPO",
    )
    second_position = _instrument_at(
        catalog.load_table(second.backtest_run_id, "signed_positions"),
        dates[1],
        "IPO",
    )
    assert first_position["baseline_quantity"] == pytest.approx(30.0)
    assert second_position["baseline_quantity"] == pytest.approx(60.0)
    assert first_position["held_quantity"] == pytest.approx(-20.0)
    assert second_position["held_quantity"] == pytest.approx(-20.0)


def test_short_increase_cover_and_cross_zero_follow_realized_qlib_fills(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(
        project.config_path,
        intent_values=(0.0, -0.10, -0.25, -0.05, 0.0, 0.20, -0.10),
    )

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    catalog = api.open_run_catalog(project.catalog_path)
    signed = catalog.load_table(run.backtest_run_id, "signed_positions")
    ipo = signed.loc[signed["instrument_id"].eq("IPO")].sort_values("trade_date")

    assert ipo["target_quantity"].tolist() == [0, -10, -25, -5, 0, 20, -10]
    assert ipo["held_quantity"].tolist() == [0, -10, -25, -5, 0, 20, -10]
    assert ipo["baseline_quantity"].tolist() == [0, 30, 30, 30, 30, 30, 30]
    assert ipo["composite_quantity"].tolist() == [0, 20, 5, 25, 30, 50, 20]

    orders = catalog.load_table(run.backtest_run_id, "orders")
    ipo_orders = orders.loc[orders["instrument_id"].eq("IPO")].sort_values(
        "trade_date"
    )
    assert ipo_orders["direction"].tolist() == [
        "sell",
        "sell",
        "buy",
        "buy",
        "buy",
        "sell",
    ]
    assert ipo_orders["requested_quantity"].tolist() == [10, 15, 20, 5, 20, 30]
    assert pd.to_datetime(ipo_orders["trade_date"]).tolist() == dates[1:].tolist()


def test_top_up_and_release_are_causal_capitalization_events(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(
        project.config_path,
        intent_values=(0.0, -0.20, -0.20, 0.0),
        ipo_prices=(10.0, 10.0, 4.0, 4.0),
        initial_cash=1_600.0,
        active_booksize=1_000.0,
        inventory_retention="active_short_only",
    )

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    catalog = api.open_run_catalog(project.catalog_path)
    events = catalog.load_table(run.backtest_run_id, "capitalization_events")
    ipo_events = events.loc[events["instrument_id"].eq("IPO")].sort_values(
        "event_sequence"
    )

    assert ipo_events["event_type"].tolist() == ["activation", "top_up", "release"]
    assert ipo_events["quantity"].tolist() == [30, 54, 84]
    assert pd.to_datetime(ipo_events["trade_date"]).tolist() == [
        dates[1],
        dates[2],
        dates[3],
    ]
    assert ipo_events["baseline_quantity_before"].tolist() == [0, 30, 84]
    assert ipo_events["baseline_quantity_after"].tolist() == [30, 84, 0]
    assert ipo_events["cash_change"].tolist() == pytest.approx(
        [-300.0, -216.0, 336.0]
    )

    signed = catalog.load_table(run.backtest_run_id, "signed_positions")
    released = _instrument_at(signed, dates[3], "IPO")
    assert released["held_quantity"] == 0
    assert released["baseline_quantity"] == 0
    assert released["composite_quantity"] == 0


def test_baseline_top_up_cannot_spend_active_trading_cash(tmp_path: Path) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    _configure_signed_project(
        project.config_path,
        intent_values=(0.0, -0.20, -0.20, 0.0),
        ipo_prices=(10.0, 10.0, 4.0, 4.0),
        initial_cash=1_500.0,
        active_booksize=1_000.0,
    )

    with pytest.raises(
        ValueError,
        match=r"funding reserve is insufficient: required=216\.0, available=200\.0",
    ):
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )


@pytest.mark.parametrize(
    ("inventory_retention", "expected_baseline", "expected_event_types"),
    [
        ("retained", [0, 30, 30, 30, 30, 30], ["activation"]),
        (
            "active_short_only",
            [0, 30, 20, 0, 30, 30],
            ["activation", "release", "release", "activation"],
        ),
    ],
)
def test_blocked_exit_delayed_liquidation_and_reentry_preserve_baseline_policy(
    tmp_path: Path,
    inventory_retention: str,
    expected_baseline: list[int],
    expected_event_types: list[str],
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    dates = _configure_signed_project(
        project.config_path,
        intent_values=(0.0, -0.20, -0.20, -0.20, -0.20, -0.20),
        universe_values=(False, True, False, False, True, True),
        observed_values=(False, True, True, True, True, True),
        tradable_values=(False, True, False, True, True, True),
        shortable_values=(False, True, True, True, True, True),
        inventory_retention=inventory_retention,
    )

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    catalog = api.open_run_catalog(project.catalog_path)
    signed = catalog.load_table(run.backtest_run_id, "signed_positions")
    ipo = signed.loc[signed["instrument_id"].eq("IPO")].sort_values("trade_date")

    assert ipo["held_quantity"].tolist() == [0, -20, -20, 0, -20, -20]
    assert ipo["baseline_quantity"].tolist() == expected_baseline
    assert ipo["composite_quantity"].tolist() == (
        ipo["baseline_quantity"] + ipo["held_quantity"]
    ).tolist()

    fills = catalog.load_table(run.backtest_run_id, "fills")
    blocked = _instrument_at(fills, dates[2], "IPO")
    assert blocked["filled_quantity"] == 0
    assert blocked["reason_code"] == "buy_blocked"
    assert blocked["blocked_by"] == "tradability"
    delayed_cover = _instrument_at(fills, dates[3], "IPO")
    assert delayed_cover["filled_quantity"] == 20
    assert delayed_cover["reason_code"] == "filled"
    reentry = _instrument_at(fills, dates[4], "IPO")
    assert reentry["filled_quantity"] == 20
    assert reentry["reason_code"] == "filled"

    events = catalog.load_table(run.backtest_run_id, "capitalization_events")
    assert events.loc[
        events["instrument_id"].eq("IPO"), "event_type"
    ].tolist() == expected_event_types


def test_checkpoint_resume_restores_baseline_sidecar_and_event_sequence() -> None:
    from kwam_qlib_backend.backend import (
        MatchedCapitalizationInputs,
        QlibClosedLoopBackend,
        ResumeState,
    )
    from kwam_qlib_backend.result import BackendRunResult

    dates = pd.bdate_range("2024-01-02", periods=6)
    columns = pd.Index(["A", "IPO"], name="ticker")
    prices = _matrix(
        dates,
        columns,
        [[10.0, value] for value in (10.0, 10.0, 4.0, 4.0, 4.0, 4.0)],
    )
    lifecycle = _matrix(dates, columns, [[True, True]] * len(dates))
    factor = _matrix(dates, columns, [[1.0, 1.0]] * len(dates))
    volume = _matrix(dates, columns, [[1_000.0, 1_000.0]] * len(dates))
    signed_weights = _matrix(
        dates,
        columns,
        [[0.0, value] for value in (0.0, -0.2, -0.2, 0.0, -0.2, 0.0)],
    )
    scenario = SimpleNamespace(
        execution_price=prices,
        valuation_price=prices,
        universe=lifecycle,
        booksize=1_600.0,
        active_booksize=1_000.0,
        position_unit_factor=factor,
        volume=volume,
        buyable=lifecycle,
        sellable=lifecycle,
        asset_class=None,
        lot_size=None,
        cost_policy=None,
        max_volume_participation=1.0,
        suspended=None,
        upper_price_limit=None,
        lower_price_limit=None,
    )
    matched = MatchedCapitalizationInputs(
        signed_weights=signed_weights,
        observed=lifecycle,
        shortable=lifecycle,
        per_name_short_cap=0.30,
        inventory_retention="active_short_only",
    )
    physical_placeholder = _matrix(
        dates, columns, [[0.0, 0.0]] * len(dates)
    )
    backend = QlibClosedLoopBackend()

    full = backend.run_targets(
        scenario,
        physical_placeholder,
        matched_capitalization=matched,
    )
    prefix = backend.run_targets(
        scenario,
        physical_placeholder,
        matched_capitalization=matched,
        end_position=3,
    )
    checkpoint = prefix.evidence["resume_state"]
    assert checkpoint.baseline_cash == pytest.approx(84.0)
    assert checkpoint.baseline_quantity == {"IPO": 84}
    assert checkpoint.previous_baseline_nav == pytest.approx(420.0)
    assert checkpoint.previous_active_nav == pytest.approx(1_120.0)
    assert checkpoint.next_capitalization_event_sequence == 2
    serialized_checkpoint = json.loads(
        json.dumps(asdict(checkpoint), sort_keys=True)
    )
    restored_checkpoint = ResumeState(**serialized_checkpoint)

    suffix = backend.run_targets(
        scenario,
        physical_placeholder,
        matched_capitalization=matched,
        start_position=restored_checkpoint.next_position,
        resume_state=restored_checkpoint,
    )
    merged = BackendRunResult(
        decision_weights=pd.concat(
            [prefix.decision_weights, suffix.decision_weights]
        ),
        order_rows=pd.concat(
            [prefix.order_rows, suffix.order_rows], ignore_index=True
        ),
        fill_rows=pd.concat(
            [prefix.fill_rows, suffix.fill_rows], ignore_index=True
        ),
        position_rows=pd.concat(
            [prefix.position_rows, suffix.position_rows], ignore_index=True
        ),
        account_rows=pd.concat([prefix.account_rows, suffix.account_rows]),
        signal_rows=pd.concat(
            [prefix.signal_rows, suffix.signal_rows], ignore_index=True
        ),
        observation_rows=pd.concat(
            [prefix.observation_rows, suffix.observation_rows],
            ignore_index=True,
        ),
        research_rows=pd.concat(
            [prefix.research_rows, suffix.research_rows], ignore_index=True
        ),
        feedback_rows=pd.concat(
            [prefix.feedback_rows, suffix.feedback_rows], ignore_index=True
        ),
        state_rows=pd.concat(
            [prefix.state_rows, suffix.state_rows], ignore_index=True
        ),
        selected_rules=full.selected_rules.copy(),
        extra_tables={
            name: pd.concat(
                [prefix.extra_tables[name], suffix.extra_tables[name]],
                ignore_index=True,
            )
            for name in full.extra_tables
        },
    )

    assert_frame_equal(merged.decision_weights, full.decision_weights)
    assert_frame_equal(merged.order_rows, full.order_rows)
    assert_frame_equal(merged.fill_rows, full.fill_rows)
    assert_frame_equal(merged.position_rows, full.position_rows)
    assert_frame_equal(merged.account_rows, full.account_rows)
    for name in full.extra_tables:
        assert_frame_equal(merged.extra_tables[name], full.extra_tables[name])
    assert merged.result_hash() == full.result_hash()

    with pytest.raises(ValueError, match="baseline cash cannot be negative"):
        backend.run_targets(
            scenario,
            physical_placeholder,
            matched_capitalization=matched,
            start_position=checkpoint.next_position,
            resume_state=replace(checkpoint, baseline_cash=-1.0),
        )
    with pytest.raises(
        ValueError,
        match="baseline cash, quantity and NAV do not reconcile",
    ):
        backend.run_targets(
            scenario,
            physical_placeholder,
            matched_capitalization=matched,
            start_position=checkpoint.next_position,
            resume_state=replace(checkpoint, previous_baseline_nav=421.0),
        )


def test_deterministic_production_ledger_matches_qlib_signed_realization() -> None:
    from kwam_enhanced_index.backtest.cost import TradeCostConfig
    from kwam_enhanced_index.backtest.holdings import (
        execute_holdings_ledger_step,
        initialize_holdings_ledger,
    )
    from kwam_qlib_backend.backend import (
        MatchedCapitalizationInputs,
        QlibClosedLoopBackend,
    )

    active_booksize = 1_000.0
    dates = pd.bdate_range("2024-02-01", periods=5)
    columns = pd.Index(["A", "IPO"], name="ticker")
    base = _matrix(
        dates,
        columns,
        [[10.0, value] for value in (10.0, 10.0, 11.0, 10.0, 12.0)],
    )
    close = _matrix(
        dates,
        columns,
        [[10.0, value] for value in (10.0, 11.0, 10.0, 12.0, 12.0)],
    )
    intended = _matrix(
        dates,
        columns,
        [
            [0.0, 0.0],
            [0.0, -0.20],
            [0.0, -0.11 / 0.98],
            [0.0, 0.20 / 0.99],
            [0.0, 0.0],
        ],
    )
    lifecycle = _matrix(dates, columns, [[True, True]] * len(dates))
    factor = _matrix(dates, columns, [[1.0, 1.0]] * len(dates))
    volume = _matrix(dates, columns, [[1_000.0, 1_000.0]] * len(dates))
    scenario = SimpleNamespace(
        execution_price=base,
        valuation_price=close,
        universe=lifecycle,
        booksize=2_000.0,
        active_booksize=active_booksize,
        position_unit_factor=factor,
        volume=volume,
        buyable=lifecycle,
        sellable=lifecycle,
        asset_class=None,
        lot_size=None,
        cost_policy=None,
        max_volume_participation=1.0,
        suspended=None,
        upper_price_limit=None,
        lower_price_limit=None,
    )
    matched = MatchedCapitalizationInputs(
        signed_weights=intended,
        observed=lifecycle,
        shortable=lifecycle,
        per_name_short_cap=0.30,
        inventory_retention="retained",
    )
    qlib_result = QlibClosedLoopBackend().run_targets(
        scenario,
        _matrix(dates, columns, [[0.0, 0.0]] * len(dates)),
        matched_capitalization=matched,
    )
    qlib_signed = qlib_result.extra_tables["signed_positions"].pivot(
        index="trade_date",
        columns="instrument_id",
        values="held_quantity",
    ).reindex(index=dates, columns=columns)
    qlib_active = qlib_result.extra_tables["active_account_daily"].set_index(
        "trade_date"
    )
    qlib_trade_value = (
        qlib_result.fill_rows.groupby("trade_date")["trade_value"]
        .sum()
        .reindex(dates, fill_value=0.0)
    )

    production_state = initialize_holdings_ledger(columns)
    production_quantity_rows: list[pd.Series] = []
    production_cash: list[float] = []
    production_nav: list[float] = []
    production_turnover_amount: list[float] = []
    for date in dates:
        step = execute_holdings_ledger_step(
            decision_date=date,
            state=production_state,
            target_weight=intended.loc[date],
            base_price=base.loc[date],
            close_price=close.loc[date],
            quantity_adjustment_factor=factor.loc[date],
            execution_universe_mask=lifecycle.loc[date],
            rebalance=True,
            trade_cost_config=TradeCostConfig(enabled=False),
        )
        production_quantity_rows.append(
            step.closing_quantity * active_booksize
        )
        production_cash.append(step.cash * active_booksize)
        production_nav.append(step.nav * active_booksize)
        production_turnover_amount.append(
            step.gross_turnover
            * float(step.diagnostics["pre_trade_nav"])
            * active_booksize
        )
        production_state = step.state

    production_quantity = pd.DataFrame(
        production_quantity_rows, index=dates, columns=columns
    )
    assert_frame_equal(
        qlib_signed.astype("float64"),
        production_quantity.astype("float64"),
        check_names=False,
    )
    assert qlib_active["cash"].tolist() == pytest.approx(production_cash)
    assert qlib_active["nav"].tolist() == pytest.approx(production_nav)
    assert qlib_active["money_pnl"].tolist() == pytest.approx(
        pd.Series(production_nav).diff().fillna(production_nav[0] - active_booksize)
    )
    assert qlib_trade_value.tolist() == pytest.approx(production_turnover_amount)


def test_stored_ensemble_attribution_and_report_do_not_rerun_members(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    audit_path = tmp_path / "strategy-invocations.txt"
    project = make_project(
        tmp_path,
        strategies={
            "short": strategy_config(scale=1.0, audit_path=audit_path),
            "long": strategy_config(scale=-1.0, audit_path=audit_path),
        },
    )
    dates = _configure_signed_project(
        project.config_path,
        ipo_valuation_prices=(10.0, 9.0, 10.0, 10.0),
    )
    members = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("short", "long"),
            max_workers=1,
        )
    )
    ensemble = api.build_ensemble(
        project.catalog_path,
        strategy_id="ensemble.signed-attribution",
        members={
            members["short"].alpha_run_id: 0.75,
            members["long"].alpha_run_id: 0.25,
        },
    )
    invocations_before = invocation_count(project.audit_path)

    attribution = api.build_signed_attribution(
        project.catalog_path,
        backtest_run_id=ensemble.backtest_run_id,
    )
    report = api.create_report(
        project.catalog_path,
        backtest_run_ids=(ensemble.backtest_run_id,),
        output_dir=tmp_path / "stored-report",
    )

    assert invocation_count(project.audit_path) == invocations_before
    assert report.html_path.exists()
    assert attribution.alpha_run_id == ensemble.alpha_run_id
    assert attribution.summary_daily["reconciliation_error"].abs().max() <= 1e-12
    assert attribution.summary_daily["net_pnl"].tolist() == pytest.approx(
        [0.0, 10.0, -10.0, 0.0]
    )
    assert set(attribution.member_daily["member_alpha_run_id"]) == {
        members["short"].alpha_run_id,
        members["long"].alpha_run_id,
    }
    member_day = attribution.member_daily.loc[
        pd.to_datetime(attribution.member_daily["trade_date"]).eq(dates[1])
    ].set_index("member_alpha_run_id")
    assert member_day.loc[
        members["short"].alpha_run_id, "net_pnl"
    ] == pytest.approx(15.0)
    assert member_day.loc[
        members["long"].alpha_run_id, "net_pnl"
    ] == pytest.approx(-5.0)
    assert member_day["net_pnl"].sum() == pytest.approx(10.0)
    assert {
        "intended_weight",
        "held_quantity",
        "baseline_quantity",
        "composite_quantity",
        "overnight_pnl",
        "intraday_pnl",
        "execution_cost",
        "net_pnl",
        "benchmark_weight",
    } <= set(attribution.instrument_daily.columns)


def test_public_signed_workflow_defaults_to_upstream_normalized_physical_units(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    _configure_signed_project(project.config_path)
    config = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    config["backtest"].pop("position_unit_factor")
    config["data"]["datasets"].pop("position_unit_factor")
    project.config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    factor = api.open_run_catalog(project.catalog_path).load_table(
        run.backtest_run_id,
        "position_unit_factor",
    )

    assert factor.eq(1.0).all().all()


def test_stored_member_to_enhanced_index_optimizer_attribution_is_end_to_end(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    audit_path = tmp_path / "strategy-invocations.txt"
    project = make_project(
        tmp_path,
        strategies={
            "momentum": strategy_config(scale=1.0, audit_path=audit_path),
            "reversal": strategy_config(scale=-1.0, audit_path=audit_path),
        },
    )
    dates = _configure_enhanced_index_project(project.config_path)
    members = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("momentum", "reversal"),
            max_workers=1,
        )
    )
    ensemble = api.build_ensemble(
        project.catalog_path,
        strategy_id="ensemble.enhanced-index",
        members={
            members["momentum"].alpha_run_id: 0.75,
            members["reversal"].alpha_run_id: 0.25,
        },
    )
    invocations_before = invocation_count(project.audit_path)

    attribution = api.build_enhanced_index_attribution(
        project.catalog_path,
        backtest_run_id=ensemble.backtest_run_id,
    )
    report = api.create_report(
        project.catalog_path,
        backtest_run_ids=(ensemble.backtest_run_id,),
        output_dir=tmp_path / "enhanced-report",
    )

    assert invocation_count(project.audit_path) == invocations_before
    assert report.html_path.exists()
    assert attribution.alpha_run_id == ensemble.alpha_run_id
    catalog = api.open_run_catalog(project.catalog_path)
    assert catalog.get_run(ensemble.backtest_run_id).parent_run_ids == (
        ensemble.alpha_run_id,
    )
    assert set(attribution.member_intent_daily["member_alpha_run_id"]) == {
        members["momentum"].alpha_run_id,
        members["reversal"].alpha_run_id,
    }
    first_member = attribution.member_intent_daily.loc[
        pd.to_datetime(attribution.member_intent_daily["trade_date"]).eq(dates[0])
    ]
    combined = first_member.groupby("constituent_id")[
        "weighted_active_exposure"
    ].sum()
    assert combined["A"] == pytest.approx(0.05)
    assert combined["B"] == pytest.approx(-0.05)

    first_constituent = attribution.constituent_daily.loc[
        pd.to_datetime(attribution.constituent_daily["trade_date"]).eq(dates[0])
    ].set_index("constituent_id")
    assert first_constituent.loc["A", "desired_total_exposure"] == pytest.approx(
        0.55
    )
    assert first_constituent.loc["B", "desired_total_exposure"] == pytest.approx(
        0.45
    )
    assert first_constituent.loc[
        "A", "realized_lookthrough_exposure"
    ] == pytest.approx(0.55, abs=1e-7)
    assert first_constituent.loc[
        "B", "realized_lookthrough_exposure"
    ] == pytest.approx(0.45, abs=1e-7)

    first_physical = attribution.physical_daily.loc[
        pd.to_datetime(attribution.physical_daily["trade_date"]).eq(dates[0])
    ].set_index("instrument_id")
    assert first_physical.loc["A", "target_physical_weight"] == pytest.approx(
        0.55, abs=1e-7
    )
    assert first_physical.loc["B", "target_physical_weight"] == pytest.approx(
        0.45, abs=1e-7
    )
    assert first_physical.loc["A", "held_quantity"] == 54
    assert first_physical.loc["B", "held_quantity"] == 45
    account = catalog.load_table(
        ensemble.backtest_run_id, "account_daily"
    ).set_index("trade_date")
    assert account.loc[dates[0], "cash"] == pytest.approx(10.0)
    assert account.loc[dates[0], "nav"] == pytest.approx(1_000.0)
    optimizer = catalog.load_table(
        ensemble.backtest_run_id, "optimizer_daily"
    )
    assert optimizer["optimizer_status"].eq("optimal").all()
    assert optimizer["validation_passed"].all()
    second_physical = attribution.physical_daily.loc[
        pd.to_datetime(attribution.physical_daily["trade_date"]).eq(dates[1])
    ].set_index("instrument_id")
    assert second_physical.loc[
        "A", "current_physical_weight"
    ] == pytest.approx(0.54)
    assert second_physical.loc[
        "B", "current_physical_weight"
    ] == pytest.approx(0.45)
    optimizer["trade_date"] = pd.to_datetime(optimizer["trade_date"])
    assert optimizer.set_index("trade_date").loc[
        dates[1], "current_cash_weight"
    ] == pytest.approx(0.01)


def _configure_enhanced_index_project(config_path: Path) -> pd.DatetimeIndex:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    dates = pd.bdate_range("2024-03-04", periods=4)
    columns = pd.Index(["A", "B"], name="ticker")
    active_intent = _matrix(
        dates,
        columns,
        [[0.10, -0.10]] * len(dates),
    )
    benchmark = _matrix(
        dates,
        columns,
        [[0.50, 0.50]] * len(dates),
    )
    execution_price = _matrix(
        dates,
        columns,
        [[10.0, 10.0]] * len(dates),
    )
    universe = _matrix(
        dates,
        columns,
        [[True, True]] * len(dates),
    )
    datasets = config["data"]["datasets"]
    _overwrite_dataset(datasets["returns"], active_intent)
    _overwrite_dataset(datasets["benchmark_weight"], benchmark)
    _overwrite_dataset(datasets["execution_price"], execution_price)
    _overwrite_dataset(datasets["universe"], universe)
    datasets.pop("position_unit_factor")
    config["backtest"].pop("position_unit_factor")
    config["backtest"].update(
        {
            "initial_cash": 1_000.0,
            "signal_lag": 0,
            "target_semantics": "enhanced_index",
            "enhanced_index": {
                "lookthrough": {
                    "A": {"A": 1.0, "B": 0.0},
                    "B": {"A": 0.0, "B": 1.0},
                },
                "lower_bounds": {"A": 0.0, "B": 0.0},
                "upper_bounds": {"A": 1.0, "B": 1.0},
                "transaction_cost": {"A": 0.0, "B": 0.0},
                "cash_lower": 0.0,
                "cash_upper": 0.0,
            },
        }
    )
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return dates


def _configure_signed_project(
    config_path: Path,
    *,
    intent_values: tuple[float, ...] = (-0.2, -0.2, -0.2, -0.2),
    ipo_prices: tuple[float, ...] | None = None,
    ipo_valuation_prices: tuple[float, ...] | None = None,
    ipo_volume: tuple[float, ...] | None = None,
    safety_multiplier: float = 1.0,
    initial_cash: float = 2_000.0,
    active_booksize: float | None = 1_000.0,
    inventory_retention: str = "retained",
    universe_values: tuple[bool, ...] | None = None,
    observed_values: tuple[bool, ...] | None = None,
    tradable_values: tuple[bool, ...] | None = None,
    shortable_values: tuple[bool, ...] | None = None,
) -> pd.DatetimeIndex:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if ipo_prices is None:
        ipo_prices = (10.0,) * len(intent_values)
    if len(ipo_prices) != len(intent_values):
        raise ValueError("ipo_prices and intent_values must have the same length")
    if ipo_valuation_prices is None:
        ipo_valuation_prices = ipo_prices
    if len(ipo_valuation_prices) != len(intent_values):
        raise ValueError(
            "ipo_valuation_prices and intent_values must have the same length"
        )
    if ipo_volume is None:
        ipo_volume = (1_000.0,) * len(intent_values)
    if len(ipo_volume) != len(intent_values):
        raise ValueError("ipo_volume and intent_values must have the same length")
    default_lifecycle = tuple(offset > 0 for offset in range(len(intent_values)))
    lifecycle_inputs = {
        "universe_values": universe_values or default_lifecycle,
        "observed_values": observed_values or default_lifecycle,
        "tradable_values": tradable_values or default_lifecycle,
        "shortable_values": shortable_values or default_lifecycle,
    }
    for name, values in lifecycle_inputs.items():
        if len(values) != len(intent_values):
            raise ValueError(f"{name} and intent_values must have the same length")
    dates = pd.bdate_range("2024-01-02", periods=len(intent_values))
    columns = pd.Index(["A", "IPO"], name="ticker")

    intent = _matrix(dates, columns, [[0.0, value] for value in intent_values])
    execution_price = _matrix(
        dates,
        columns,
        [[10.0, ipo_price] for ipo_price in ipo_prices],
    )
    valuation_price = _matrix(
        dates,
        columns,
        [[10.0, ipo_price] for ipo_price in ipo_valuation_prices],
    )
    universe = _matrix(
        dates,
        columns,
        [[True, value] for value in lifecycle_inputs["universe_values"]],
    )
    observed = _matrix(
        dates,
        columns,
        [[True, value] for value in lifecycle_inputs["observed_values"]],
    )
    tradable = _matrix(
        dates,
        columns,
        [[True, value] for value in lifecycle_inputs["tradable_values"]],
    )
    shortable = _matrix(
        dates,
        columns,
        [[True, value] for value in lifecycle_inputs["shortable_values"]],
    )
    benchmark_weight = _matrix(dates, columns, [[0.0, 0.0]] * len(dates))
    position_unit_factor = _matrix(dates, columns, [[1.0, 1.0]] * len(dates))
    volume = _matrix(
        dates,
        columns,
        [[1_000.0, value] for value in ipo_volume],
    )

    datasets = config["data"]["datasets"]
    _overwrite_dataset(datasets["returns"], intent)
    _overwrite_dataset(datasets["universe"], universe)
    _overwrite_dataset(datasets["benchmark_weight"], benchmark_weight)
    _overwrite_dataset(datasets["execution_price"], execution_price)
    _overwrite_dataset(datasets["position_unit_factor"], position_unit_factor)

    data_dir = Path(datasets["returns"]["path"]).parent
    _add_dataset(
        datasets,
        "valuation_price",
        data_dir,
        valuation_price,
        "valuation_price",
    )
    _add_dataset(datasets, "observed", data_dir, observed, "observed")
    _add_dataset(datasets, "tradable", data_dir, tradable, "tradable")
    _add_dataset(datasets, "shortable", data_dir, shortable, "shortable")
    _add_dataset(datasets, "volume", data_dir, volume, "volume")

    config["backtest"].update(
        {
            "initial_cash": initial_cash,
            "valuation_price": "valuation_price",
            "signal_lag": 0,
            "target_semantics": "signed_weight",
            "matched_capitalization": {
                "observed": "observed",
                "tradable": "tradable",
                "shortable": "shortable",
                "per_name_short_cap": 0.30,
                "safety_multiplier": safety_multiplier,
                "inventory_readiness": "same_bar",
                "inventory_retention": inventory_retention,
                **(
                    {}
                    if active_booksize is None
                    else {"active_booksize": active_booksize}
                ),
            },
            "execution": {
                "volume": "volume",
                "max_volume_participation": 1.0,
            },
        }
    )
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return dates


def _matrix(
    dates: pd.DatetimeIndex,
    columns: pd.Index,
    values: list[list[float | bool]],
) -> pd.DataFrame:
    return pd.DataFrame(values, index=dates, columns=columns).rename_axis(index="date")


def _overwrite_dataset(dataset: dict[str, str], matrix: pd.DataFrame) -> None:
    _write_matrix(Path(dataset["path"]), matrix, dataset["value_column"])


def _add_dataset(
    datasets: dict[str, dict[str, str]],
    name: str,
    data_dir: Path,
    matrix: pd.DataFrame,
    value_column: str,
) -> None:
    path = data_dir / f"{name}.parquet"
    _write_matrix(path, matrix, value_column)
    datasets[name] = {
        "path": str(path),
        "format": "parquet",
        "value_column": value_column,
    }


def _write_matrix(path: Path, matrix: pd.DataFrame, value_name: str) -> None:
    (
        matrix.stack(future_stack=True)
        .rename(value_name)
        .reset_index()
        .to_parquet(path, index=False)
    )


def _instrument_at(
    table: pd.DataFrame,
    trade_date: pd.Timestamp,
    instrument_id: str,
) -> pd.Series:
    rows = table.loc[
        (pd.to_datetime(table["trade_date"]) == trade_date)
        & (table["instrument_id"] == instrument_id)
    ]
    assert len(rows) == 1
    return rows.iloc[0]


def _account_at(table: pd.DataFrame, trade_date: pd.Timestamp) -> pd.Series:
    rows = table.loc[pd.to_datetime(table["trade_date"]) == trade_date]
    assert len(rows) == 1
    return rows.iloc[0]
