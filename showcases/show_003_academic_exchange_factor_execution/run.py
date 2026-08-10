"""Reproduce real-DW factor research through the public AcademicExchange."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import html
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from factor_model import MonthlyReversalModel

from qlibx import (
    ACADEMIC_EXECUTION_CONTRACT,
    AcademicInstrumentKind,
    AcademicInstrumentListing,
    AcademicPriceSemantics,
    AcademicRunSpec,
    ComponentRequirement,
    MaterializationInvocation,
    OutcomeStatus,
    QlibxProject,
    SignalAnalysisRequest,
)
from qlibx.data import AvailableAtField, DatasetRegistration, SourceFormat
from qlibx.evidence import DependencyEdge
from qlibx.portfolio import (
    ConstructionProfile,
    PortfolioConstructionResult,
    PortfolioWeight,
)

SHOWCASE_ID = "show_003_academic_exchange_factor_execution"
DATASET_ID = "showcase-academic-exchange-market-v1"
INITIAL_NAV = 1_000_000.0
KST = ZoneInfo("Asia/Seoul")
SOURCE_START = "20221001"
STUDY_START = pd.Timestamp("2023-01-01")
STUDY_END = pd.Timestamp("2024-12-31")
LOOKBACK_SESSIONS = 20
UNIVERSE = (
    "A000270",
    "A000660",
    "A003550",
    "A005380",
    "A005930",
    "A006400",
    "A012330",
    "A035420",
    "A035720",
    "A051910",
    "A055550",
    "A066570",
)
RAW_COLUMNS = {
    "종목약코드": "instrument",
    "거래일자": "session",
    "종가": "close",
    "전일종가": "previous_close",
}


@dataclass(frozen=True, slots=True)
class PeriodResult:
    decision_date: str
    execution_date: str
    analysis_end_date: str
    information_coefficient: float
    rank_ic: float
    analysis_long_short_return: float
    nav: float
    cumulative_academic_return: float
    gross_exposure: float
    net_exposure: float
    turnover: float
    long_positions: int
    short_positions: int
    signal_artifact_id: str
    portfolio_artifact_id: str
    execution_artifact_id: str


def require_complete(outcome: Any, label: str) -> Any:
    if outcome.status is not OutcomeStatus.COMPLETE:
        errors = [error.model_dump(mode="json") for error in outcome.errors]
        raise RuntimeError(f"{label} failed: {json.dumps(errors, ensure_ascii=False)}")
    return outcome


def close_at(value: pd.Timestamp | date) -> datetime:
    selected = value.date() if isinstance(value, pd.Timestamp) else value
    return datetime.combine(selected, time(15, 30), tzinfo=KST)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_bounded_market(source: Path, destination: Path) -> dict[str, Any]:
    selected_chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        source,
        usecols=list(RAW_COLUMNS),
        dtype={"종목약코드": "string", "거래일자": "string"},
        chunksize=250_000,
    ):
        session = chunk["거래일자"].str.replace("-", "", regex=False)
        selected = chunk.loc[
            chunk["종목약코드"].isin(UNIVERSE)
            & session.between(SOURCE_START, STUDY_END.strftime("%Y%m%d"))
        ].rename(columns=RAW_COLUMNS)
        if not selected.empty:
            selected_chunks.append(selected)
    if not selected_chunks:
        raise RuntimeError("the declared real-DW universe has no rows")

    raw = pd.concat(selected_chunks, ignore_index=True)
    raw["session"] = pd.to_datetime(raw["session"], format="%Y%m%d", errors="raise")
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
    raw["previous_close"] = pd.to_numeric(raw["previous_close"], errors="coerce")
    if raw.duplicated(subset=["session", "instrument"]).any():
        raise RuntimeError("real-DW selection contains duplicate instrument/session rows")
    raw["factor_input_return"] = raw["close"] / raw["previous_close"] - 1
    invalid = (
        (raw["close"] <= 0)
        | (raw["previous_close"] <= 0)
        | ~raw["factor_input_return"].map(math.isfinite)
        | (raw["factor_input_return"] <= -1)
    )
    raw.loc[invalid, "factor_input_return"] = math.nan

    return_pivot = raw.pivot(
        index="session", columns="instrument", values="factor_input_return"
    ).sort_index()
    missing = sorted(set(UNIVERSE) - set(return_pivot.columns))
    if missing:
        raise RuntimeError(f"real-DW source is missing instruments: {missing}")
    complete_returns = return_pivot.loc[:, list(UNIVERSE)].dropna(how="any")
    study = complete_returns.loc[
        (complete_returns.index >= STUDY_START) & (complete_returns.index <= STUDY_END)
    ]
    if len(study) < 240:
        raise RuntimeError(f"insufficient complete common sessions: {len(study)}")
    monthly_dates = tuple(
        pd.Timestamp(value)
        for value in (
            pd.Series(study.index, index=study.index)
            .groupby(study.index.to_period("M"))
            .max()
            .tolist()
        )
    )
    if len(monthly_dates) < 13:
        raise RuntimeError("insufficient monthly decision dates")

    evaluation_returns: dict[pd.Timestamp, pd.Series] = {}
    for decision_day, evaluation_day in pairwise(monthly_dates):
        segment = complete_returns.loc[
            (complete_returns.index > decision_day)
            & (complete_returns.index <= evaluation_day)
        ]
        evaluation_returns[evaluation_day] = (1 + segment).prod(axis=0) - 1

    bounded = raw.loc[
        raw["session"].isin(complete_returns.index)
        & (raw["session"] <= monthly_dates[-1])
    ].copy()
    bounded["analysis_return"] = math.nan
    for evaluation_day, returns in evaluation_returns.items():
        mask = bounded["session"].eq(evaluation_day)
        bounded.loc[mask, "analysis_return"] = bounded.loc[mask, "instrument"].map(
            returns
        )
    timestamps = bounded["session"].map(close_at)
    bounded.insert(2, "observation_time", timestamps.map(datetime.isoformat))
    bounded.insert(3, "available_at", timestamps.map(datetime.isoformat))
    bounded = bounded[
        [
            "instrument",
            "session",
            "observation_time",
            "available_at",
            "close",
            "factor_input_return",
            "analysis_return",
        ]
    ].sort_values(["session", "instrument"], kind="mergesort")
    bounded["session"] = bounded["session"].dt.strftime("%Y-%m-%d")
    destination.parent.mkdir(parents=True, exist_ok=True)
    bounded.to_csv(destination, index=False, float_format="%.17g", lineterminator="\n")
    return {
        "bounded_rows": len(bounded),
        "common_sessions": len(complete_returns),
        "study_sessions": len(study),
        "decision_dates": monthly_dates,
        "evaluation_returns": evaluation_returns,
        "session_closes": tuple(close_at(value) for value in complete_returns.index),
    }


def correlation(left: pd.Series, right: pd.Series) -> float:
    value = left.astype(float).corr(right.astype(float))
    if value is None or not math.isfinite(float(value)):
        raise RuntimeError("factor correlation is not finite")
    return float(value)


def metric(result: Any, name: str) -> float:
    return float({item.name: item.value for item in result.metrics}[name])


def publish_portfolio(
    project: QlibxProject,
    *,
    decision_day: pd.Timestamp,
    signal_artifact_id: str,
    weights: pd.Series,
) -> str:
    targets = tuple(
        PortfolioWeight(instrument=str(instrument), weight=float(weight))
        for instrument, weight in weights.sort_index().items()
    )
    payload = PortfolioConstructionResult(
        invocation_id=f"showcase-academic-portfolio-{decision_day:%Y%m%d}-v1",
        source_artifact_id=signal_artifact_id,
        source_strategy_id="showcase.monthly-reversal.signed-portfolio.v1",
        evaluation_time=close_at(decision_day),
        profile=ConstructionProfile.HYPOTHETICAL_SIGNED,
        original_weights=targets,
        target_weights=targets,
        requested_budget=1.0,
        realized_gross=sum(abs(item.weight) for item in targets),
        realized_net=sum(item.weight for item in targets),
        cash_residual=0.0,
        diagnostics=("cross-sectional demean and normalize to unit gross",),
    )
    publication = require_complete(
        project.artifacts.publish_model(
            logical_identity=f"portfolio:{payload.invocation_id}",
            artifact_type="portfolio_construction_result",
            artifact_schema_version=2,
            producer_id="showcase.academic-factor-portfolio.v1",
            payload=payload,
            dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=signal_artifact_id,
                    consumer_role="stored_signal",
                ),
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id="showcase-unit-gross-demeaned-v1",
                    consumer_role="portfolio_construction",
                ),
            ),
        ),
        f"portfolio publication {decision_day.date()}",
    )
    return publication.result.artifact_id


def line_svg(rows: list[dict[str, Any]]) -> str:
    width, height, margin = 920, 270, 42
    values = [1 + float(row["cumulative_academic_return"]) for row in rows]
    low, high = min(values), max(values)
    padding = max((high - low) * 0.15, 0.01)
    low, high = low - padding, high + padding
    points = " ".join(
        f"{margin + index * (width - 2 * margin) / max(len(values) - 1, 1):.1f},"
        f"{height - margin - (value - low) * (height - 2 * margin) / (high - low):.1f}"
        for index, value in enumerate(values)
    )
    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Academic portfolio NAV index">
      <line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" class="axis"/>
      <line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" class="axis"/>
      <polyline points="{points}" class="nav-line"/>
      <text x="{margin}" y="24">{high:.3f}</text><text x="{margin}" y="{height - 12}">{low:.3f}</text>
    </svg>"""


def render_report(summary: dict[str, Any], periods: list[dict[str, Any]]) -> str:
    metrics = summary["aggregate_metrics"]
    verification = summary["verification"]
    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['decision_date'])}</td>"
        f"<td>{html.escape(row['execution_date'])}</td>"
        f"<td>{row['information_coefficient']:.3f}</td>"
        f"<td>{row['analysis_long_short_return']:.2%}</td>"
        f"<td>{row['turnover']:.3f}</td>"
        f"<td>{row['gross_exposure']:.3f}</td>"
        f"<td>{row['net_exposure']:.3f}</td>"
        f"<td>{row['nav']:,.0f}</td>"
        f"<td>{row['long_positions']}/{row['short_positions']}</td>"
        "</tr>"
        for row in periods
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>qlibx AcademicExchange factor execution</title>
<style>
:root{{--ink:#182128;--muted:#63717a;--paper:#eef2ef;--panel:#fff;--green:#087f5b;--navy:#24445f;--red:#b23a48;--gold:#a46b12;--line:#d7ded9}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:auto;padding:42px 24px 72px}} h1{{font:750 43px/1.08 Georgia,serif;margin:4px 0 12px}} h2{{font:700 25px Georgia,serif;margin-top:38px}}
.lede{{font-size:17px;color:var(--muted);max-width:940px}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:13px;margin:26px 0}}
.card,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:18px;box-shadow:0 3px 14px #24372c0d}}
.label{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}} .value{{font-size:27px;font-weight:780;margin-top:4px}} .ok{{color:var(--green)}}
.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;align-items:center}} .step{{background:#f8faf8;border:1px solid var(--line);padding:14px 10px;text-align:center;border-radius:10px;font-weight:650}} .arrow{{display:none}}
.nav-line{{fill:none;stroke:var(--navy);stroke-width:3}} .axis{{stroke:#8c9690;stroke-width:1}} svg{{width:100%;height:auto}}
.table-wrap{{overflow:auto}} table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}} th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}} th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
.boundary{{border-left:5px solid var(--gold)}} code{{background:#e8ece9;padding:2px 5px;border-radius:4px}} footer{{margin-top:34px;color:var(--muted);font-size:13px}}
@media(max-width:800px){{.flow{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="label">qlibx / real-DW / {SHOWCASE_ID}</div>
<h1>Academic factor research now reaches signed stock execution</h1>
<p class="lede">A 20-session reversal model creates frozen monthly signals. Exact signed portfolio artifacts are then executed by qlibx at the next session close with fractional stock quantities, hypothetical short positions, and every friction term fixed at zero.</p>
<section class="grid">
  <div class="card"><div class="label">AcademicExchange</div><div class="value ok">Demonstrated</div></div>
  <div class="card"><div class="label">Stock fills</div><div class="value">{metrics['fill_count']}</div></div>
  <div class="card"><div class="label">Rebalances</div><div class="value">{metrics['period_count']}</div></div>
  <div class="card"><div class="label">Final NAV</div><div class="value">{metrics['final_nav']:,.0f}</div></div>
  <div class="card"><div class="label">Academic return</div><div class="value">{metrics['cumulative_academic_return']:.2%}</div></div>
  <div class="card"><div class="label">Total cost</div><div class="value ok">0</div></div>
</section>
<h2>Package-owned evidence path</h2>
<div class="panel flow"><div class="step">PIT prices</div><div class="step">Stored signal</div><div class="step">Signed portfolio:v2</div><div class="step">AcademicFill</div><div class="step">Checkpoint + NAV</div></div>
<h2>Academic NAV after each next-close rebalance</h2><div class="panel">{line_svg(periods)}</div>
<h2>Independent reconciliation</h2>
<div class="grid">
  <div class="card"><div class="label">Max NAV delta</div><div class="value">{verification['maximum_absolute_nav_delta']:.2e}</div></div>
  <div class="card"><div class="label">Max quantity delta</div><div class="value">{verification['maximum_absolute_quantity_delta']:.2e}</div></div>
  <div class="card"><div class="label">Max turnover delta</div><div class="value">{verification['maximum_absolute_turnover_delta']:.2e}</div></div>
  <div class="card"><div class="label">Negative positions</div><div class="value ok">Observed</div></div>
</div>
<h2>Monthly evidence</h2><div class="panel table-wrap"><table><thead><tr><th>Decision</th><th>Execution</th><th>IC</th><th>Next-month diagnostic</th><th>Turnover</th><th>Gross</th><th>Net</th><th>NAV</th><th>Long/Short</th></tr></thead><tbody>{table_rows}</tbody></table></div>
<h2>Interpretation boundary</h2><div class="panel boundary"><ul>
<li>The IC and next-month long-short diagnostic test the factor artifact; AcademicExchange NAV starts after the next-session close, so they intentionally use different holding boundaries.</li>
<li>All instruments here are stocks. The public listing contract also accepts ETF, tracking-only Index, and explicit synthetic-unit-price Factor inputs.</li>
<li>Zero costs are an explicit profile assumption, not missing data. Turnover is still recorded.</li>
<li>Hypothetical shorts do not prove borrow, locate, collateral, margin, capacity, dividends, market impact, or real executability.</li>
</ul></div>
<footer>Verified against {html.escape(summary['verified_against'])}. Source SHA-256: <code>{summary['dataset']['source_sha256']}</code><br>Final checkpoint: <code>{html.escape(summary['academic_run']['final_checkpoint_artifact_id'])}</code></footer>
</main></body></html>"""


def run(repo_root: Path) -> dict[str, Any]:
    showcase_root = Path(__file__).resolve().parent
    output_root = showcase_root / "outputs"
    project_root = output_root / "project"
    bounded_path = project_root / "data" / "academic_exchange_market.csv"
    source = repo_root / "data" / "DW" / "fng_stock_daily_prices.csv"
    if not source.is_file():
        raise FileNotFoundError(f"required real-DW source is missing: {source}")

    extraction = extract_bounded_market(source, bounded_path)
    QlibxProject.init(project_root, apply=True)
    project = QlibxProject.open(project_root)
    require_complete(
        project.register_dataset(
            DatasetRegistration(
                dataset_id=DATASET_ID,
                source="data/academic_exchange_market.csv",
                source_format=SourceFormat.CSV,
                instrument_field="instrument",
                observation_time_field="observation_time",
                available_at=AvailableAtField(field="available_at"),
                logical_key=("observation_time", "available_at", "instrument"),
                semantic_bindings={
                    "factor_input_return": "factor_input_return",
                    "analysis_return": "analysis_return",
                    "execution_price": "close",
                },
                semantic_category="showcase_real_dw_factor_and_execution_prices",
                source_provenance=(
                    "Bounded deterministic projection of data/DW/fng_stock_daily_prices.csv; "
                    "close and close/previous_close are available at the same 15:30 KST close."
                ),
            )
        ),
        "dataset registration",
    )
    registered = project.registry_snapshot().get(DATASET_ID)
    if registered is None:
        raise RuntimeError("registered dataset is absent")

    model = MonthlyReversalModel(DATASET_ID, LOOKBACK_SESSIONS)
    decision_dates: tuple[pd.Timestamp, ...] = extraction["decision_dates"]
    forward_returns: dict[pd.Timestamp, pd.Series] = extraction["evaluation_returns"]
    portfolio_ids: list[str] = []
    research_rows: list[dict[str, Any]] = []
    maximum_ic_delta = 0.0
    maximum_analysis_return_delta = 0.0

    for decision_day, evaluation_day in pairwise(decision_dates):
        decision_time = close_at(decision_day)
        evaluation_time = close_at(evaluation_day)
        materialized = require_complete(
            project.materialize(
                model,
                MaterializationInvocation(
                    invocation_id=f"showcase-factor-{decision_day:%Y%m%d}-v1",
                    evaluation_time=decision_time,
                    config_fingerprint=f"monthly-reversal-{LOOKBACK_SESSIONS}-v1",
                ),
            ),
            f"factor materialization {decision_day.date()}",
        )
        signal_artifact = materialized.result.artifact
        analyzed = require_complete(
            project.analyze_signal(
                SignalAnalysisRequest(
                    invocation_id=f"showcase-factor-analysis-{evaluation_day:%Y%m%d}-v1",
                    signal_artifact_id=signal_artifact.artifact_id,
                    evaluation_time=evaluation_time,
                    return_session=evaluation_day.date(),
                    return_session_timezone="Asia/Seoul",
                    return_requirement=ComponentRequirement(
                        requirement_id="showcase.factor.realized_return",
                        semantic_role="analysis_return",
                        dataset_id=DATASET_ID,
                    ),
                    config_fingerprint="showcase-factor-one-period-analysis-v1",
                )
            ),
            f"factor analysis {evaluation_day.date()}",
        )
        signals = pd.Series(
            {item.instrument: float(item.value) for item in materialized.result.result.entries}
        ).sort_index()
        realized = forward_returns[evaluation_day].reindex(signals.index).astype(float)
        oracle_ic = correlation(signals, realized)
        qlibx_ic = metric(analyzed.result, "information_coefficient")
        centered = signals - signals.mean()
        weights = centered / centered.abs().sum()
        oracle_return = float((weights * realized).sum())
        qlibx_return = metric(analyzed.result, "hypothetical_long_short_return")
        maximum_ic_delta = max(maximum_ic_delta, abs(qlibx_ic - oracle_ic))
        maximum_analysis_return_delta = max(
            maximum_analysis_return_delta, abs(qlibx_return - oracle_return)
        )
        if not math.isclose(qlibx_ic, oracle_ic, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("qlibx IC does not reconcile")
        if not math.isclose(qlibx_return, oracle_return, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("qlibx analysis return does not reconcile")
        portfolio_id = publish_portfolio(
            project,
            decision_day=decision_day,
            signal_artifact_id=signal_artifact.artifact_id,
            weights=weights,
        )
        portfolio_ids.append(portfolio_id)
        research_rows.append(
            {
                "decision_date": decision_day.date().isoformat(),
                "analysis_end_date": evaluation_day.date().isoformat(),
                "information_coefficient": qlibx_ic,
                "rank_ic": correlation(
                    signals.rank(method="average"), realized.rank(method="average")
                ),
                "analysis_long_short_return": qlibx_return,
                "signal_artifact_id": signal_artifact.artifact_id,
                "portfolio_artifact_id": portfolio_id,
                "weights": weights.to_dict(),
            }
        )

    academic_spec = AcademicRunSpec(
        run_id="showcase-academic-factor-stock-execution-v1",
        portfolio_artifact_ids=tuple(portfolio_ids),
        initial_nav=INITIAL_NAV,
        base_currency="KRW",
        listings=tuple(
            AcademicInstrumentListing(
                instrument_id=instrument,
                kind=AcademicInstrumentKind.STOCK,
                currency="KRW",
                dataset_id=DATASET_ID,
                price_role="execution_price",
                price_semantics=AcademicPriceSemantics.TRADED_REFERENCE,
            )
            for instrument in UNIVERSE
        ),
        session_closes=extraction["session_closes"],
    )
    academic = require_complete(
        project.run_academic(academic_spec, resume=True),
        "AcademicExchange run",
    )

    oracle_financing = INITIAL_NAV
    oracle_positions = {instrument: 0.0 for instrument in UNIVERSE}
    maximum_nav_delta = 0.0
    maximum_quantity_delta = 0.0
    maximum_turnover_delta = 0.0
    period_results: list[PeriodResult] = []
    fill_rows: list[dict[str, Any]] = []
    total_fill_count = 0
    negative_position_observed = False
    all_zero_cost = True

    for research, execution_artifact_id in zip(
        research_rows, academic.result.execution_artifact_ids, strict=True
    ):
        loaded = require_complete(
            project.load_artifact(execution_artifact_id, ACADEMIC_EXECUTION_CONTRACT),
            "academic execution artifact load",
        )
        payload = loaded.result.payload
        match = payload.match
        prices = {item.instrument_id: item.price for item in match.quotes}
        oracle_nav = oracle_financing + sum(
            oracle_positions[instrument] * prices[instrument]
            for instrument in UNIVERSE
        )
        target_weights = {
            str(instrument): float(weight)
            for instrument, weight in research["weights"].items()
        }
        target_quantities = {
            instrument: target_weights.get(instrument, 0.0) * oracle_nav / prices[instrument]
            for instrument in UNIVERSE
        }
        deltas = {
            instrument: target_quantities[instrument] - oracle_positions[instrument]
            for instrument in UNIVERSE
        }
        oracle_turnover = sum(
            abs(deltas[instrument] * prices[instrument]) for instrument in UNIVERSE
        ) / oracle_nav
        oracle_financing -= sum(
            deltas[instrument] * prices[instrument] for instrument in UNIVERSE
        )
        oracle_positions = target_quantities
        maximum_nav_delta = max(maximum_nav_delta, abs(match.after.nav - oracle_nav))
        maximum_turnover_delta = max(
            maximum_turnover_delta, abs(match.turnover - oracle_turnover)
        )
        actual_positions = {
            item.instrument_id: item.quantity for item in match.after.positions
        }
        maximum_quantity_delta = max(
            maximum_quantity_delta,
            max(
                abs(actual_positions[instrument] - target_quantities[instrument])
                for instrument in UNIVERSE
            ),
        )
        if not math.isclose(match.after.nav, oracle_nav, rel_tol=0, abs_tol=1e-8):
            raise RuntimeError("AcademicExchange NAV does not reconcile")
        if not math.isclose(match.turnover, oracle_turnover, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("AcademicExchange turnover does not reconcile")
        total_fill_count += len(match.fills)
        negative_position_observed |= any(value < 0 for value in actual_positions.values())
        all_zero_cost &= match.total_cost == 0 and all(
            fill.transaction_cost == 0
            and fill.tax == 0
            and fill.slippage_cost == 0
            and fill.market_impact_cost == 0
            and fill.borrow_cost == 0
            for fill in match.fills
        )
        for fill in match.fills:
            fill_rows.append(
                {
                    "event_time": match.event_time.isoformat(),
                    "fill_id": fill.fill_id,
                    "instrument": fill.instrument_id,
                    "side": fill.side.value,
                    "signed_quantity_change": fill.signed_quantity_change,
                    "target_quantity": fill.target_quantity,
                    "price": fill.price,
                    "notional": fill.notional,
                    "total_cost": 0.0,
                    "hypothetical": fill.hypothetical,
                    "execution_artifact_id": execution_artifact_id,
                }
            )
        long_count = sum(value > 0 for value in actual_positions.values())
        short_count = sum(value < 0 for value in actual_positions.values())
        period_results.append(
            PeriodResult(
                decision_date=research["decision_date"],
                execution_date=match.event_time.date().isoformat(),
                analysis_end_date=research["analysis_end_date"],
                information_coefficient=research["information_coefficient"],
                rank_ic=research["rank_ic"],
                analysis_long_short_return=research["analysis_long_short_return"],
                nav=match.after.nav,
                cumulative_academic_return=match.after.nav / INITIAL_NAV - 1,
                gross_exposure=match.after.gross_exposure,
                net_exposure=match.after.net_exposure,
                turnover=match.turnover,
                long_positions=long_count,
                short_positions=short_count,
                signal_artifact_id=research["signal_artifact_id"],
                portfolio_artifact_id=research["portfolio_artifact_id"],
                execution_artifact_id=execution_artifact_id,
            )
        )

    if not negative_position_observed or not all_zero_cost:
        raise RuntimeError("academic short/zero-cost acceptance was not observed")
    period_payload = [asdict(item) for item in period_results]
    ic_values = pd.Series([item.information_coefficient for item in period_results])
    summary = {
        "showcase_id": SHOWCASE_ID,
        "status": "complete",
        "verified_against": "qlibx-0.1.0+implementations-009-059-061",
        "capabilities": {
            "factor_materialization": "demonstrated",
            "one_period_signal_analysis": "demonstrated",
            "academic_exchange": "demonstrated",
            "stock_hypothetical_short": "demonstrated",
            "production_real_short": "not_claimed",
        },
        "dataset": {
            "source": str(source.relative_to(repo_root).as_posix()),
            "source_size_bytes": source.stat().st_size,
            "source_sha256": hash_file(source),
            "bounded_path": str(bounded_path.relative_to(showcase_root).as_posix()),
            "bounded_sha256": hash_file(bounded_path),
            "bounded_rows": extraction["bounded_rows"],
            "common_sessions": extraction["common_sessions"],
            "study_sessions": extraction["study_sessions"],
            "instrument_count": len(UNIVERSE),
            "universe": list(UNIVERSE),
            "registration_identity": registered.registration_identity,
        },
        "factor": {
            "factor_id": "monthly-reversal-20-complete-sessions-v1",
            "lookback_sessions": LOOKBACK_SESSIONS,
            "weighting": "cross-sectional demean then normalize to unit gross",
        },
        "academic_run": {
            "profile_id": academic.result.profile.profile_id,
            "execution_timing": academic.result.profile.execution_timing,
            "quantity_policy": academic.result.profile.quantity_policy,
            "direction_policy": academic.result.profile.direction_policy,
            "portfolio_artifact_ids": list(academic.result.portfolio_artifact_ids),
            "execution_artifact_ids": list(academic.result.execution_artifact_ids),
            "final_checkpoint_artifact_id": academic.result.final_checkpoint_artifact_id,
            "total_cost": academic.result.total_cost,
        },
        "aggregate_metrics": {
            "period_count": len(period_results),
            "fill_count": total_fill_count,
            "mean_ic": float(ic_values.mean()),
            "annualized_icir": float(
                ic_values.mean() / ic_values.std(ddof=1) * math.sqrt(12)
            ),
            "final_nav": academic.result.final_snapshot.nav,
            "cumulative_academic_return": (
                academic.result.final_snapshot.nav / INITIAL_NAV - 1
            ),
            "total_turnover": academic.result.total_turnover,
            "total_cost": academic.result.total_cost,
        },
        "verification": {
            "maximum_absolute_ic_delta": maximum_ic_delta,
            "maximum_absolute_analysis_return_delta": maximum_analysis_return_delta,
            "maximum_absolute_nav_delta": maximum_nav_delta,
            "maximum_absolute_quantity_delta": maximum_quantity_delta,
            "maximum_absolute_turnover_delta": maximum_turnover_delta,
            "negative_position_observed": negative_position_observed,
            "all_cost_terms_zero": all_zero_cost,
        },
        "limitations": list(academic.result.limitations),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    pd.DataFrame(period_payload).to_csv(
        output_root / "periods.csv",
        index=False,
        float_format="%.17g",
        lineterminator="\n",
    )
    pd.DataFrame(fill_rows).to_csv(
        output_root / "fills.csv",
        index=False,
        float_format="%.17g",
        lineterminator="\n",
    )
    catalog = [
        envelope.model_dump(mode="json") for envelope in project.artifacts.list_envelopes()
    ]
    (output_root / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
        newline="\n",
    )
    (output_root / "report.html").write_text(
        render_report(summary, period_payload),
        encoding="utf-8",
        newline="\n",
    )
    return summary


if __name__ == "__main__":
    selected_root = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[2]
    )
    print(json.dumps(run(selected_root), ensure_ascii=False, indent=2, sort_keys=True))
