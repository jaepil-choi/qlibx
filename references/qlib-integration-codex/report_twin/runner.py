from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from qlib_extended.config import BacktestConfig
from qlib_extended.execution import ExecutionContext, run_qlib_backtest
from qlib_extended.hashing import file_hash
from qlib_extended.store import ParentLink, RunCatalog

from .common import annualized_mean, annualized_volatility, alpha_returns, turnover_and_cost
from .contract import (
    FINAL_METHOD,
    MARKET_METHODS,
    MARKET_PRICE_MEMBERS,
    MEMBER_NAMES,
    RATIONALE_METHODS,
    ReportInputs,
    load_report_inputs,
)
from .lineage import publish_alpha_node, publish_backtest_node
from .market import build_market_method_weights
from .outputs import write_outputs
from .portfolio import ETF_TICKER, build_etf_residual_portfolio, build_physical_tape, compare_frozen_daily
from .rationale import build_families, build_family_history, build_rationale_candidates


def run_report_twin(
    *,
    project_root: Path,
    output_dir: Path,
    execute_qlib: bool = True,
) -> dict[str, Any]:
    inputs = load_report_inputs(project_root)
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    market_allocations, market_combined, market_parity = _build_market_twins(inputs)
    families = build_families(inputs.members)
    family_gross, family_net, family_turnover = build_family_history(
        families, inputs.realized_return
    )
    candidates, rationale_allocations, multipliers = build_rationale_candidates(
        families,
        family_net,
        family_turnover,
        inputs.benchmark_weight,
        inputs.realized_return,
    )
    family_parity = _compare_families(inputs, families)
    candidate_parity = _compare_candidates(inputs, candidates)
    frozen_daily = _read_frozen_daily(inputs.final_dir / "enhanced_daily.csv")
    alpha_multiplier = float(
        inputs.manifest["final_rationale_parameters"][
            "enhanced_index_scalar_multiplier"
        ]
    )
    portfolios = {
        method: build_etf_residual_portfolio(
            alpha,
            inputs.benchmark_weight,
            inputs.realized_return,
            inputs.universe,
            alpha_multiplier=alpha_multiplier,
        )
        for method, alpha in candidates.items()
    }
    enhanced_parity = {
        method: compare_frozen_daily(
            method,
            portfolio.daily,
            frozen_daily,
            alpha_multiplier=alpha_multiplier,
        )
        for method, portfolio in portfolios.items()
    }
    member_returns, member_summary = _member_outputs(inputs)
    market_returns, market_summary = _market_outputs(
        inputs, market_combined, families["market_family"]
    )
    rationale_returns = pd.DataFrame(
        {method: portfolio.daily["net_active_return"] for method, portfolio in portfolios.items()}
    )
    rationale_summary = _rationale_summary(portfolios)
    store = RunCatalog.initialize(destination / "runs.duckdb", destination / "artifacts")
    node_ids = _publish_lineage(
        store,
        inputs,
        families,
        family_gross,
        candidates,
        rationale_allocations,
        multipliers,
        portfolios,
    )
    qlib_evidence = (
        _execute_final_qlib(store, inputs, portfolios[FINAL_METHOD], node_ids[FINAL_METHOD])
        if execute_qlib
        else {"status": "skipped"}
    )
    exact_errors = [
        *market_parity.values(),
        *family_parity.values(),
        *candidate_parity.values(),
        *(value for row in enhanced_parity.values() for value in row.values()),
    ]
    proof = {
        "status": "PASS" if max(exact_errors) <= 1e-10 else "FAIL",
        "source_of_truth": "frozen report-assets manifest and referenced artifacts",
        "date_range": inputs.manifest["date_range"],
        "member_count": len(MEMBER_NAMES),
        "market_method_count": len(MARKET_METHODS) + 1,
        "family_count": len(families),
        "rationale_method_count": len(RATIONALE_METHODS),
        "max_exact_parity_error": max(exact_errors),
        "market_weight_parity": market_parity,
        "family_weight_parity": family_parity,
        "candidate_weight_parity": candidate_parity,
        "enhanced_daily_parity": enhanced_parity,
        "final_qlib_execution": qlib_evidence,
        "lineage_run_ids": node_ids,
        "document_consistency": _document_consistency(inputs),
    }
    proof_path, figure_path = write_outputs(
        destination,
        member_returns=member_returns,
        family_returns=family_gross,
        market_returns=market_returns,
        rationale_returns=rationale_returns,
        summaries={
            "member_summary": member_summary,
            "market_method_summary": market_summary,
            "rationale_summary": rationale_summary,
        },
        proof=proof,
    )
    return {**proof, "proof_path": str(proof_path), "pnl_figure": str(figure_path)}


def _build_market_twins(
    inputs: ReportInputs,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, float]]:
    realized = pd.read_parquet(inputs.price_cache / "shared/realized_return.parquet").astype("float64")
    members = {
        name: pd.read_parquet(
            inputs.price_cache / "members" / name / "desired_weight.parquet"
        ).astype("float64")
        for name in MARKET_PRICE_MEMBERS
    }
    allocations, combined = build_market_method_weights(members, realized)
    parity: dict[str, float] = {}
    for method in MARKET_METHODS:
        frozen_allocation = pd.read_parquet(
            inputs.price_cache / "methods" / method / "capital_weight.parquet"
        )
        frozen_combined = pd.read_parquet(
            inputs.price_cache / "methods" / method / "combined_intent.parquet"
        )
        parity[f"{method}__capital_allocation"] = _max_error(
            allocations[method], frozen_allocation
        )
        parity[f"{method}__combined_intent"] = _max_error(
            combined[method], frozen_combined
        )
    return allocations, combined, parity


def _compare_families(
    inputs: ReportInputs, families: dict[str, pd.DataFrame]
) -> dict[str, float]:
    paths = {
        "market_family": "market_family.parquet",
        "financial_family": "financial_family.parquet",
        "consensus_revision_family": "consensus_revision_family.parquet",
    }
    return {
        name: _max_error(
            weight,
            pd.read_parquet(inputs.final_dir / "weights/families" / paths[name]),
        )
        for name, weight in families.items()
    }


def _compare_candidates(
    inputs: ReportInputs, candidates: dict[str, pd.DataFrame]
) -> dict[str, float]:
    return {
        method: _max_error(
            weight, pd.read_parquet(inputs.final_dir / "weights" / f"{method}.parquet")
        )
        for method, weight in candidates.items()
    }


def _member_outputs(inputs: ReportInputs) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = pd.DataFrame(
        {name: alpha_returns(weight, inputs.realized_return) for name, weight in inputs.members.items()}
    )
    rows = []
    for name, weight in inputs.members.items():
        cost = turnover_and_cost(weight)
        gross = returns[name]
        rows.append(
            {
                "member": name,
                "annualized_gross_return": annualized_mean(gross),
                "annualized_volatility": annualized_volatility(gross),
                "annualized_turnover": annualized_mean(cost["gross_turnover"]),
                "annualized_cost": annualized_mean(cost["trade_cost"]),
                "cumulative_gross_pnl": float(gross.sum()),
            }
        )
    return returns, pd.DataFrame(rows).set_index("member")


def _market_outputs(
    inputs: ReportInputs,
    full_combined: dict[str, pd.DataFrame],
    final_market: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights = {
        method: (
            inputs.members["high_free_float_ratio"] * (18.0 / 23.0)
            + full.reindex(index=inputs.realized_return.index, columns=inputs.realized_return.columns)
            * (5.0 / 23.0)
        )
        for method, full in full_combined.items()
    }
    weights["final_equal_weight_decay_5"] = final_market
    net_returns: dict[str, pd.Series] = {}
    rows = []
    for method, weight in weights.items():
        gross = alpha_returns(weight, inputs.realized_return)
        cost = turnover_and_cost(weight)
        net = gross - cost["trade_cost"]
        net_returns[method] = net
        rows.append(
            {
                "method": method,
                "annualized_gross_return": annualized_mean(gross),
                "annualized_net_return": annualized_mean(net),
                "annualized_cost": annualized_mean(cost["trade_cost"]),
                "annualized_turnover": annualized_mean(cost["gross_turnover"]),
                "cumulative_net_pnl": float(net.sum()),
            }
        )
    return pd.DataFrame(net_returns), pd.DataFrame(rows).set_index("method")


def _rationale_summary(portfolios: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for method, portfolio in portfolios.items():
        daily = portfolio.daily
        rows.append(
            {
                "method": method,
                "annualized_gross_active_return": annualized_mean(daily["gross_active_return"]),
                "annualized_net_active_return": annualized_mean(daily["net_active_return"]),
                "annualized_cost": annualized_mean(daily["trade_cost"]),
                "annualized_turnover": annualized_mean(daily["gross_turnover"]),
                "cumulative_net_active_pnl": float(daily["net_active_return"].sum()),
            }
        )
    return pd.DataFrame(rows).set_index("method")


def _publish_lineage(
    store: RunCatalog,
    inputs: ReportInputs,
    families: dict[str, pd.DataFrame],
    family_gross: pd.DataFrame,
    candidates: dict[str, pd.DataFrame],
    allocations: dict[str, pd.DataFrame],
    multipliers: pd.DataFrame,
    portfolios: dict[str, Any],
) -> dict[str, str]:
    node_ids: dict[str, str] = {}
    for name, weight in inputs.members.items():
        cost = turnover_and_cost(weight)
        gross = alpha_returns(weight, inputs.realized_return)
        node_ids[name] = publish_alpha_node(
            store,
            strategy_id=f"report.member.{name}",
            alpha=weight,
            definition={"type": "portable_report_member", "source_hash": file_hash(inputs.source_paths[name])},
            artifacts={"daily": pd.DataFrame({"gross_return": gross, "trade_cost": cost["trade_cost"], "net_return": gross - cost["trade_cost"]})},
        )
    family_members = {
        "market_family": (*MARKET_PRICE_MEMBERS, "high_free_float_ratio"),
        "financial_family": (
            "high_leverage", "high_inventory_intensity", "low_depreciation_intensity",
            "low_lease_liability_intensity", "slow_low_lease_liability_intensity",
        ),
        "consensus_revision_family": tuple(name for name in MEMBER_NAMES if name.startswith(("eps_", "net_income_", "fy1_"))),
    }
    for family, weight in families.items():
        node_ids[family] = publish_alpha_node(
            store,
            strategy_id=f"report.family.{family}",
            alpha=weight,
            definition={"type": "hierarchical_family_ensemble", "family": family, "decay_window": 5},
            artifacts={"gross_return": family_gross[[family]]},
            parents=tuple(ParentLink(node_ids[name], "member") for name in family_members[family]),
        )
    for method, weight in candidates.items():
        node_ids[method] = publish_alpha_node(
            store,
            strategy_id=f"report.rationale.{method}",
            alpha=weight,
            definition={"type": "causal_rationale_ensemble", "method": method, "lookback": 63, "rebalance": 21, "family_cap": 0.6, "negative_screen": 0.1, "target_volatility": 0.03},
            artifacts={"capital_allocation": allocations[method], "embedded_multiplier": multipliers[[method]], "enhanced_daily": portfolios[method].daily},
            parents=tuple(ParentLink(node_ids[name], "dynamic_member") for name in families),
        )
    return node_ids


def _execute_final_qlib(
    store: RunCatalog,
    inputs: ReportInputs,
    portfolio: Any,
    alpha_run_id: str,
) -> dict[str, Any]:
    execution_price, valuation_price = build_physical_tape(inputs.realized_return, inputs.benchmark_weight)
    physical = portfolio.physical_target_weight
    universe = inputs.universe.reindex(columns=inputs.realized_return.columns).copy()
    universe[ETF_TICKER] = True
    universe = universe.reindex(columns=physical.columns).astype(bool)
    benchmark = physical * 0.0
    asset_class = pd.Series("stock", index=physical.columns, dtype="object")
    asset_class.loc[ETF_TICKER] = "etf"
    output = run_qlib_backtest(
        physical,
        BacktestConfig(
            initial_cash=100_000_000_000.0,
            execution_price="execution_price",
            valuation_price="valuation_price",
            universe="universe",
            benchmark_weight="benchmark_weight",
            signal_lag=0,
            target_semantics="target_weight",
            cost_policy={
                "stock": {"buy_rate": 0.0003, "sell_rate": 0.0003, "sell_tax": 0.0020},
                "etf": {"buy_rate": 0.0003, "sell_rate": 0.0003, "sell_tax": 0.0},
            },
        ),
        ExecutionContext(
            execution_price=execution_price,
            valuation_price=valuation_price,
            universe=universe,
            benchmark_weight=benchmark,
            asset_class=asset_class,
            lot_size=pd.Series(1, index=physical.columns, dtype="int64"),
        ),
    )
    backtest_run_id = publish_backtest_node(
        store,
        strategy_id="report.final.rationale_inverse_volatility.qlib_physical",
        alpha_run_id=alpha_run_id,
        artifacts=output.artifacts,
        metadata=output.metadata,
    )
    account = output.artifacts["account_daily"].set_index("trade_date")
    qlib_active = account["portfolio_return"].reindex(portfolio.daily.index) - portfolio.daily["benchmark_return"]
    fills = output.artifacts["fills"]
    return {
        "status": "complete",
        "backtest_run_id": backtest_run_id,
        "final_nav": float(account.iloc[-1]["nav"]),
        "money_pnl": float(account.iloc[-1]["nav"] - 100_000_000_000.0),
        "execution_cost": float(fills["trade_cost"].sum()),
        "annualized_net_active_return": annualized_mean(qlib_active),
        "cumulative_net_active_pnl": float(qlib_active.sum()),
        "max_daily_net_active_difference_vs_analytical_twin": float((qlib_active - portfolio.daily["net_active_return"]).abs().max()),
    }


def _read_frozen_daily(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"]).set_index("date").astype("float64")


def _max_error(left: pd.DataFrame, right: pd.DataFrame) -> float:
    aligned = right.reindex(index=left.index, columns=left.columns)
    if not left.isna().equals(aligned.isna()):
        raise ValueError("frozen parity matrix NaN pattern differs from twin")
    difference = (left - aligned).abs().stack().to_numpy(dtype="float64")
    return 0.0 if difference.size == 0 else float(difference.max())


def _document_consistency(inputs: ReportInputs) -> dict[str, Any]:
    relative_builder = Path(
        "qlib-integration-codex/research/report/build_report_assets.py"
    )
    builder = inputs.project_root / relative_builder
    report = inputs.project_root / "docs/report/enhanced-index-2/report-draft-3.md"
    report_text = report.read_text(encoding="utf-8") if report.is_file() else ""
    builder_reference = relative_builder.as_posix()
    return {
        "consistent": builder.is_file() and builder_reference in report_text,
        "authoritative_builder": builder_reference,
        "builder_exists": builder.is_file(),
        "report_declares_authoritative_builder": builder_reference in report_text,
    }
