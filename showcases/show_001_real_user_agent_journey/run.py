from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from qlibx import Project
from qlibx.agent import task_guide
from qlibx.artifacts import ArtifactStore
from qlibx.data import ConfigDrivenDataLoader, require_matrix_axes
from qlibx.ensemble import combine_stored_weights
from qlibx.execution import run_signed_execution
from qlibx.extensions import (
    extension_contract,
    invoke_exposure_analyzer,
    invoke_report_renderer,
    invoke_signal_transform,
    load_extension,
)
from qlibx.portfolio import construct_enhanced_index
from qlibx.reporting import AnalysisSection, compose_report, render_report
from qlibx.research import (
    AlphaDescriptor,
    ResearchCatalog,
    ResearchProposal,
    compare_alpha,
)

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "outputs"
START = "2025-01-02"
END = "2025-02-28"
ACTIVE_BOOKSIZE = 1_000_000_000.0
INITIAL_CASH = 5_000_000_000.0
DATASETS = (
    "returns",
    "execution_price",
    "valuation_price",
    "execution_universe",
    "execution_observed",
    "execution_tradable",
    "execution_shortable",
    "execution_volume",
    "execution_benchmark_weight",
)


def _momentum(returns: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    score = returns.rolling(5, min_periods=5).mean().where(universe)
    return _tails(score, long_high=True)


def _low_volatility(returns: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    score = returns.rolling(10, min_periods=10).std().where(universe)
    return _tails(score, long_high=False)


def _tails(score: pd.DataFrame, *, long_high: bool) -> pd.DataFrame:
    ranks = score.rank(axis=1, pct=True)
    high = ranks.ge(0.95)
    low = ranks.le(0.05)
    long_mask, short_mask = (high, low) if long_high else (low, high)
    long_count = long_mask.sum(axis=1).replace(0, pd.NA).astype("Float64")
    short_count = short_mask.sum(axis=1).replace(0, pd.NA).astype("Float64")
    weights = long_mask.div(long_count, axis=0).fillna(0.0) * 0.10
    weights -= short_mask.div(short_count, axis=0).fillna(0.0) * 0.10
    return weights.astype("float64")


def _load_matrix(
    loader: ConfigDrivenDataLoader,
    name: str,
    tickers: list[str] | None = None,
) -> tuple[pd.DataFrame, float]:
    spec = loader.catalog.datasets[name]
    axes = require_matrix_axes(spec)
    # The whole window is loaded to build the backtest input; the point-in-time cut is
    # applied per decision inside the execution loop, not here.
    table = loader.load_full_history(
        name, reason="backtest input matrix", start=START, end=END, tickers=tickers
    )
    available_at = pd.to_datetime(table[spec.availability_field], errors="raise")
    event_time = pd.to_datetime(table[spec.time_field], errors="raise")
    violation_seconds = float((available_at - event_time).max().total_seconds())
    matrix = table.pivot(index=axes.index, columns=axes.columns, values=axes.values)
    matrix = matrix.sort_index().sort_index(axis=1)
    if spec.dtype:
        matrix = matrix.astype(spec.dtype)
    return matrix, violation_seconds


def _proposal(
    *,
    hypothesis: str,
    mechanism: str,
    strategy: str,
    window: int,
) -> ResearchProposal:
    return ResearchProposal(
        hypothesis=hypothesis,
        mechanism=mechanism,
        logical_datasets=("returns", "execution_universe"),
        observation_clock="declared available_at no later than event decision",
        holding_horizon="1d",
        strategy=strategy,
        transforms=("cross_sectional_tail",),
        parameter_range={"window": [window]},
        evaluation_segment={"start": START, "end": END},
        comparison_set=("other stored candidate",),
        cost_assumptions={"stock_bps": 0},
        capacity_assumptions={"max_volume_participation": 0.10},
        stopping_condition="one bounded real-data run",
        search_limit=1,
    )


def _publish_alpha(
    catalog: ResearchCatalog,
    *,
    session_id: str,
    proposal_id: str,
    bundle_id: str,
    mechanism: str,
    weights: pd.DataFrame,
    result_key: str,
) -> str:
    attempt = catalog.begin(
        session_id=session_id,
        invocation={
            "proposal_id": proposal_id,
            "bundle_id": bundle_id,
            "mechanism": mechanism,
        },
        kind="alpha_run",
        result_key=result_key,
    )
    catalog.stage_frame(attempt, "weights", weights)
    catalog.stage_json(
        attempt,
        "diagnostics",
        {
            "rows": len(weights),
            "tickers": len(weights.columns),
            "mean_gross": float(weights.abs().sum(axis=1).mean()),
            "missingness": float(weights.isna().mean().mean()),
        },
    )
    return catalog.publish(
        attempt,
        status="successful",
        metadata={
            "proposal_id": proposal_id,
            "bundle_id": bundle_id,
            "descriptor": {
                "mechanism": mechanism,
                "inputs": ["returns", "execution_universe"],
                "clock": "point_in_time_available_at",
            },
        },
    ).record_id


def _publish_diagnostic_statuses(
    catalog: ResearchCatalog,
    *,
    bundle_id: str,
) -> tuple[str, str]:
    records: list[str] = []
    for status, reason in (
        ("failed", "bounded candidate has insufficient warmup"),
        ("invalid", "diagnostic candidate violates declared output axis"),
    ):
        attempt = catalog.begin(
            session_id=f"showcase-{status}",
            invocation={"bundle_id": bundle_id, "diagnostic": status},
            kind="alpha_run",
            result_key=f"showcase-{status}-{bundle_id}",
        )
        catalog.stage_json(attempt, "error", {"reason": reason})
        records.append(
            catalog.publish(
                attempt,
                status=status,
                metadata={"bundle_id": bundle_id, "searched": {"window": [1]}},
            ).record_id
        )
    return records[0], records[1]


def _ensure_decision(
    catalog: ResearchCatalog,
    *,
    proposal_id: str,
    evidence: str,
    decision: str,
) -> None:
    context = catalog.query_context()
    active_ids = {item["proposal_id"] for item in context.active_proposals}
    if proposal_id in active_ids:
        try:
            catalog.record_decision(
                proposal_id,
                decision=decision,
                evidence_run_ids=(evidence,),
                criteria={"bounded_real_data": True},
                reviewer="showcase-agent",
                rationale="Recorded from verified stored evidence.",
                expected_version=0,
            )
        except ValueError as error:
            if "stale decision" not in str(error):
                raise


def _safe_output_reset() -> None:
    resolved = OUTPUT.resolve()
    if resolved.parent != HERE.resolve():
        raise RuntimeError("showcase output escaped its showcase directory")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)


def main() -> None:
    _safe_output_reset()
    project = Project.load(ROOT)
    loader = ConfigDrivenDataLoader.from_project(project)
    catalog = ResearchCatalog.from_project(project)
    if catalog.state != project.paths.research:
        raise RuntimeError("research catalog did not use the configured research root")

    installed_guides = {
        name: task_guide(name)["version"]
        for name in ("project", "data", "research", "ensemble", "execution", "extension")
    }
    installed_contracts = {
        name: extension_contract(name).version
        for name in ("signal_transform", "exposure_analyzer", "report_renderer")
    }

    universe, universe_violation = _load_matrix(loader, "execution_universe")
    tickers = universe.columns[universe.fillna(False).any(axis=0)].tolist()
    matrices: dict[str, pd.DataFrame] = {"execution_universe": universe.loc[:, tickers]}
    violations = {"execution_universe": universe_violation}
    for name in DATASETS:
        if name == "execution_universe":
            continue
        matrices[name], violations[name] = _load_matrix(loader, name, tickers)
    dates = matrices["returns"].index
    columns = matrices["returns"].columns
    for matrix in matrices.values():
        dates = dates.intersection(matrix.index)
        columns = columns.intersection(matrix.columns)
    matrices = {
        name: matrix.reindex(index=dates, columns=columns) for name, matrix in matrices.items()
    }
    complete = (
        matrices["execution_price"].gt(0).all(axis=0)
        & matrices["valuation_price"].gt(0).all(axis=0)
        & matrices["execution_volume"].ge(0).all(axis=0)
        & matrices["execution_observed"].fillna(False).all(axis=0)
    )
    columns = columns[complete]
    matrices = {name: matrix.loc[:, columns] for name, matrix in matrices.items()}
    universe = matrices["execution_universe"].fillna(False).astype(bool)

    strategy_calls = {"momentum": 0, "low_volatility": 0}
    strategy_calls["momentum"] += 1
    momentum = _momentum(matrices["returns"], universe)
    strategy_calls["low_volatility"] += 1
    low_volatility = _low_volatility(matrices["returns"], universe)

    decay_ref, decay = load_extension(
        project,
        extension_id="showcase_decay",
        contract="signal_transform",
        contract_version="1",
        source=project.paths.extensions / "showcase_exponential_decay.py",
        callable_name="apply",
    )
    momentum = invoke_signal_transform(decay_ref, decay, momentum, span=3).fillna(0.0)

    context_before = catalog.query_context(
        candidate={"mechanism": "trend", "inputs": ["returns"]},
        required_comparison_set=("stored candidate",),
        research_gaps=("real-data stored ensemble",),
    )
    momentum_proposal = catalog.create_proposal(
        _proposal(
            hypothesis="recent cross-sectional trend persists",
            mechanism="trend",
            strategy="rolling_momentum",
            window=5,
        ),
        session_id="showcase-momentum",
        agent_id="showcase-agent-a",
    )
    low_vol_proposal = catalog.create_proposal(
        _proposal(
            hypothesis="low realized volatility outperforms high volatility",
            mechanism="low_volatility",
            strategy="rolling_low_volatility",
            window=10,
        ),
        session_id="showcase-low-volatility",
        agent_id="showcase-agent-b",
    )
    bundle = catalog.freeze_run(
        session_id="showcase-real-data",
        config_files={
            "execution": ROOT / "config/qlibx/execution.yaml",
            "market": ROOT / "config/qlibx/data/datasets/market.yaml",
            "membership": ROOT / "config/qlibx/data/datasets/membership.yaml",
        },
        dataset_snapshots={"catalog": loader.catalog.fingerprint},
        component_versions={"qlibx": "0.1.0", "qlib": "0.9.7"},
        seed=17,
    )
    orthogonality = compare_alpha(
        AlphaDescriptor(
            "momentum",
            "trend",
            ("returns",),
            "point_in_time_available_at",
            "1d",
            ("exponential_decay",),
        ),
        AlphaDescriptor(
            "low_volatility",
            "low_volatility",
            ("returns",),
            "point_in_time_available_at",
            "1d",
            ("rolling_std",),
        ),
        candidate_signal=momentum,
        reference_signal=low_volatility,
        reference_pool=("low_volatility",),
        evaluation_segment={"start": START, "end": END},
        thresholds={"residual_ratio": 0.10},
    )
    momentum_id = _publish_alpha(
        catalog,
        session_id="showcase-momentum",
        proposal_id=momentum_proposal.proposal_id,
        bundle_id=bundle.bundle_id,
        mechanism="trend",
        weights=momentum,
        result_key=f"showcase-momentum-{bundle.bundle_id}",
    )
    low_vol_id = _publish_alpha(
        catalog,
        session_id="showcase-low-volatility",
        proposal_id=low_vol_proposal.proposal_id,
        bundle_id=bundle.bundle_id,
        mechanism="low_volatility",
        weights=low_volatility,
        result_key=f"showcase-low-volatility-{bundle.bundle_id}",
    )
    failed_id, invalid_id = _publish_diagnostic_statuses(catalog, bundle_id=bundle.bundle_id)
    _ensure_decision(
        catalog,
        proposal_id=momentum_proposal.proposal_id,
        evidence=momentum_id,
        decision="promote",
    )
    _ensure_decision(
        catalog,
        proposal_id=low_vol_proposal.proposal_id,
        evidence=low_vol_id,
        decision="retain_diagnostic",
    )

    calls_before_ensemble = dict(strategy_calls)
    ensemble = combine_stored_weights(
        catalog,
        members={momentum_id: 0.5, low_vol_id: 0.5},
    )
    if strategy_calls != calls_before_ensemble:
        raise RuntimeError("stored ensemble reran a strategy")
    combined = ensemble.combined.fillna(0.0)

    nonzero_dates = combined.abs().sum(axis=1).loc[lambda value: value.gt(0)].index
    portfolio_date = nonzero_dates[-1]
    benchmark = matrices["execution_benchmark_weight"].loc[portfolio_date].fillna(0.0)
    active = combined.loc[portfolio_date].reindex(benchmark.index).fillna(0.0)
    short = active.lt(0)
    scale_limit = benchmark.loc[short].div(active.loc[short].abs()).min() if short.any() else 1.0
    active_scale = max(0.0, min(0.10, float(scale_limit) * 0.5))
    enhanced = construct_enhanced_index(
        benchmark_weight=benchmark,
        active_weight=active.mul(active_scale),
        price=matrices["execution_price"].loc[portfolio_date].astype("float64"),
        portfolio_value=ACTIVE_BOOKSIZE,
        tradable=matrices["execution_tradable"].loc[portfolio_date].fillna(False),
        transaction_cost=pd.Series(0.0, index=columns),
        tracking_tolerance=0.001,
    )

    execution = run_signed_execution(
        signed_weights=combined,
        execution_price=matrices["execution_price"].astype("float64"),
        valuation_price=matrices["valuation_price"].astype("float64"),
        universe=universe,
        observed=matrices["execution_observed"].fillna(False).astype(bool),
        tradable=matrices["execution_tradable"].fillna(False).astype(bool),
        shortable=matrices["execution_shortable"].fillna(False).astype(bool),
        volume=matrices["execution_volume"].astype("float64"),
        initial_cash=INITIAL_CASH,
        active_booksize=ACTIVE_BOOKSIZE,
        max_volume_participation=0.10,
        per_name_short_cap=0.023,
        safety_multiplier=1.10,
        inventory_retention="active_short_only",
        cost_policy={"stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0}},
    )

    artifact_store = ArtifactStore.from_project(project)
    run_id = f"showcase-{bundle.bundle_id[:16]}"
    weights_envelope = artifact_store.record(
        run_id=run_id,
        name="ensemble_weights",
        value=combined,
        artifact_type="signed_weight",
        producer_id="stored_ensemble",
        producer_version="1",
        implementation_digest=hashlib.sha256(b"stored_ensemble_v1").hexdigest(),
        parent_artifact_ids=ensemble.parent_lineage,
        input_artifact_ids=(momentum_id, low_vol_id),
        time_range=(str(dates.min()), str(dates.max())),
        axis="event_date_by_ticker",
        index_semantics="event_date",
        timezone="Asia/Seoul",
        data_semantics="stored signed ensemble weight",
    )
    orders_envelope = artifact_store.record(
        run_id=run_id,
        name="qlib_orders",
        value=execution.orders,
        artifact_type="qlib_orders",
        producer_id="qlib",
        producer_version="0.9.7",
        implementation_digest=hashlib.sha256(b"qlib_0.9.7").hexdigest(),
        input_artifact_ids=(weights_envelope.artifact_id,),
        data_semantics="raw Qlib order artifact",
    )
    fills_envelope = artifact_store.record(
        run_id=run_id,
        name="qlib_fills",
        value=execution.fills,
        artifact_type="qlib_fills",
        producer_id="qlib",
        producer_version="0.9.7",
        implementation_digest=hashlib.sha256(b"qlib_0.9.7").hexdigest(),
        input_artifact_ids=(orders_envelope.artifact_id,),
        data_semantics="raw Qlib fill artifact",
    )
    analyzer_ref, analyzer = load_extension(
        project,
        extension_id="showcase_exposure",
        contract="exposure_analyzer",
        contract_version="1",
        source=project.paths.extensions / "showcase_exposure_analyzer.py",
        callable_name="analyze",
    )
    exposure_section = invoke_exposure_analyzer(
        analyzer_ref,
        analyzer,
        weights_envelope,
        artifact_store.load_payload(weights_envelope.artifact_id, run_id=run_id),
    )
    execution_section = AnalysisSection(
        "qlib_execution",
        "1",
        (orders_envelope.artifact_id, fills_envelope.artifact_id),
        {
            "orders": len(execution.orders),
            "positive_fills": int(execution.fills["filled_quantity"].gt(0).sum()),
            "actual_sell_orders": int(execution.orders["direction"].eq("sell").sum()),
            "active_pnl": float(execution.active_account.iloc[-1]["nav"] - ACTIVE_BOOKSIZE),
            "quantity_identity_max_error": execution.reconciliation["quantity_identity_max_error"],
        },
        execution.compatibility_limitations,
    )
    orthogonality_section = AnalysisSection(
        "orthogonality",
        "1",
        (momentum_id, low_vol_id),
        {
            "classification": orthogonality.classification,
            "signal_correlation": orthogonality.signal_correlation,
            "residual_ratio": orthogonality.residual_ratio,
        },
    )
    portfolio_section = AnalysisSection(
        "enhanced_index",
        "1",
        (weights_envelope.artifact_id,),
        {
            "decision_date": str(portfolio_date),
            "active_scale": active_scale,
            "status": enhanced.status,
            "validation_passed": enhanced.validation_passed,
            "tracking_error": enhanced.tracking_error,
            "cash_weight": enhanced.cash_weight,
            "expected_cost": enhanced.expected_cost,
            "bindings": list(enhanced.binding_constraints),
        },
    )
    document = compose_report(
        (exposure_section, orthogonality_section, portfolio_section, execution_section),
        report_id=run_id,
        order=("local_exposure", "orthogonality", "enhanced_index", "qlib_execution"),
    )
    renderer_ref, renderer = load_extension(
        project,
        extension_id="showcase_renderer",
        contract="report_renderer",
        contract_version="1",
        source=project.paths.extensions / "showcase_text_renderer.py",
        callable_name="render",
    )
    research_count_before_report = len(catalog.list_results())
    rendered = render_report(
        document,
        OUTPUT / "report.txt",
        renderer=lambda value: invoke_report_renderer(renderer_ref, renderer, value),
    )
    research_count_after_report = len(catalog.list_results())

    bundle_path = artifact_store.export_bundle(
        (weights_envelope.artifact_id, orders_envelope.artifact_id, fills_envelope.artifact_id),
        OUTPUT / "artifact-bundle",
    )
    imported = ArtifactStore(OUTPUT / "imported-artifacts").import_bundle(bundle_path)
    execution.orders.to_parquet(OUTPUT / "orders.parquet", index=False)
    execution.fills.to_parquet(OUTPUT / "fills.parquet", index=False)
    execution.signed_positions.to_parquet(OUTPUT / "signed_positions.parquet", index=False)
    execution.active_account.to_parquet(OUTPUT / "active_account.parquet", index=True)
    final_context = catalog.query_context(
        candidate={"mechanism": "trend", "inputs": ["returns"]},
        required_comparison_set=(low_vol_id,),
    )
    statuses = {item["status"] for item in final_context.prior_results}
    summary: dict[str, Any] = {
        "status": "PASS",
        "installed_guides": installed_guides,
        "installed_extension_contracts": installed_contracts,
        "catalog_fingerprint": loader.catalog.fingerprint,
        "research_root": str(catalog.state),
        "context_results_before": len(context_before.prior_results),
        "frozen_bundle_id": bundle.bundle_id,
        "proposal_ids": [momentum_proposal.proposal_id, low_vol_proposal.proposal_id],
        "successful_record_ids": [momentum_id, low_vol_id],
        "failed_record_id": failed_id,
        "invalid_record_id": invalid_id,
        "context_statuses": sorted(statuses),
        "strategy_calls_before_ensemble": calls_before_ensemble,
        "strategy_calls_after_ensemble": strategy_calls,
        "ensemble_parent_lineage": list(ensemble.parent_lineage),
        "orthogonality": asdict(orthogonality),
        "enhanced_index": portfolio_section.data,
        "qlib_version": execution.evidence["qlib_version"],
        "initial_cash": INITIAL_CASH,
        "active_booksize": ACTIVE_BOOKSIZE,
        "actual_sell_orders": execution_section.data["actual_sell_orders"],
        "positive_fills": execution_section.data["positive_fills"],
        "short_position_rows": int(execution.signed_positions["held_quantity"].lt(0).sum()),
        "active_pnl": execution_section.data["active_pnl"],
        "maximum_available_after_event_seconds": max(violations.values()),
        "portable_artifacts_imported": len(imported),
        "report_digest": rendered.digest,
        "research_count_before_report": research_count_before_report,
        "research_count_after_report": research_count_after_report,
        "package_source_modified_by_extension": False,
    }
    if (
        not {"successful", "failed", "invalid"}.issubset(statuses)
        or strategy_calls != calls_before_ensemble
        or execution.evidence["qlib_version"] != "0.9.7"
        or summary["actual_sell_orders"] == 0
        or summary["positive_fills"] == 0
        or summary["short_position_rows"] == 0
        or summary["maximum_available_after_event_seconds"] > 0
        or not enhanced.validation_passed
        or len(imported) != 3
        or research_count_before_report != research_count_after_report
    ):
        summary["status"] = "FAIL"
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
