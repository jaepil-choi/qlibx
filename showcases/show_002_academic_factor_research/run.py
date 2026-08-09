"""Reproduce a real-DW academic factor-research showcase through current qlibx APIs."""

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

import qlibx
import qlibx.execution as qlibx_execution
from qlibx import MaterializationInvocation, OutcomeStatus, QlibxProject
from qlibx.analysis import SignalAnalysisRequest
from qlibx.data import AvailableAtField, ComponentRequirement, DatasetRegistration, SourceFormat
from qlibx.flow import AnalysisFlow

SHOWCASE_ID = "show_002_academic_factor_research"
DATASET_ID = "showcase-academic-factor-daily-v1"
KST = ZoneInfo("Asia/Seoul")
SOURCE_START = "20221001"
STUDY_START = pd.Timestamp("2023-01-01")
STUDY_END = pd.Timestamp("2024-12-31")
LOOKBACK_SESSIONS = 20
HYPOTHETICAL_COST_RATE = 0.001
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
    evaluation_date: str
    instrument_count: int
    qlibx_ic: float
    oracle_ic: float
    rank_ic: float
    qlibx_gross_return: float
    oracle_gross_return: float
    quantile_spread: float
    turnover: float
    hypothetical_cost: float
    net_return: float
    cumulative_gross: float
    cumulative_net: float
    signal_artifact_id: str
    analysis_artifact_id: str


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
        raise RuntimeError("the declared real-DW universe has no rows in the study window")

    raw = pd.concat(selected_chunks, ignore_index=True)
    raw["session"] = pd.to_datetime(raw["session"], format="%Y%m%d", errors="raise")
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
    raw["previous_close"] = pd.to_numeric(raw["previous_close"], errors="coerce")
    if raw.duplicated(subset=["session", "instrument"]).any():
        raise RuntimeError("real-DW selection contains duplicate instrument/session rows")
    raw["factor_input_return"] = raw["close"] / raw["previous_close"] - 1
    raw.loc[
        (raw["previous_close"] <= 0)
        | ~raw["factor_input_return"].map(math.isfinite)
        | (raw["factor_input_return"] <= -1),
        "factor_input_return",
    ] = math.nan

    pivot = raw.pivot(
        index="session",
        columns="instrument",
        values="factor_input_return",
    ).sort_index()
    missing_instruments = sorted(set(UNIVERSE) - set(pivot.columns))
    if missing_instruments:
        raise RuntimeError(f"real-DW source is missing declared instruments: {missing_instruments}")
    complete = pivot.loc[:, list(UNIVERSE)].dropna(how="any")
    study = complete.loc[(complete.index >= STUDY_START) & (complete.index <= STUDY_END)]
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
        raise RuntimeError(f"insufficient monthly decision dates: {len(monthly_dates)}")

    evaluation_returns: dict[pd.Timestamp, pd.Series] = {}
    for decision_day, evaluation_day in pairwise(monthly_dates):
        segment = complete.loc[
            (complete.index > decision_day) & (complete.index <= evaluation_day)
        ]
        if segment.empty:
            raise RuntimeError(f"empty forward period after {decision_day.date()}")
        evaluation_returns[evaluation_day] = (1 + segment).prod(axis=0) - 1

    bounded = complete.loc[complete.index <= monthly_dates[-1]].stack().rename(
        "factor_input_return"
    ).reset_index()
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
            "factor_input_return",
            "analysis_return",
        ]
    ]
    bounded["session"] = bounded["session"].dt.strftime("%Y-%m-%d")
    destination.parent.mkdir(parents=True, exist_ok=True)
    bounded.to_csv(destination, index=False, float_format="%.17g", lineterminator="\n")
    return {
        "bounded_rows": len(bounded),
        "common_sessions": len(complete),
        "study_sessions": len(study),
        "decision_dates": [value.date().isoformat() for value in monthly_dates],
        "evaluation_returns": evaluation_returns,
    }


def correlation(left: pd.Series, right: pd.Series) -> float:
    value = left.astype(float).corr(right.astype(float))
    if value is None or not math.isfinite(float(value)):
        raise RuntimeError("factor correlation is not finite")
    return float(value)


def metric(result: Any, name: str) -> float:
    values = {item.name: item.value for item in result.metrics}
    return float(values[name])


def line_svg(rows: list[dict[str, Any]]) -> str:
    width, height, margin = 900, 270, 42
    series = {
        "Gross": [1 + float(row["cumulative_gross"]) for row in rows],
        "Net after 10 bps turnover cost": [
            1 + float(row["cumulative_net"]) for row in rows
        ],
    }
    values = [value for selected in series.values() for value in selected]
    low, high = min(values), max(values)
    padding = max((high - low) * 0.12, 0.01)
    low -= padding
    high += padding

    def points(selected: list[float]) -> str:
        return " ".join(
            f"{margin + index * (width - 2 * margin) / max(len(selected) - 1, 1):.1f},"
            f"{height - margin - (value - low) * (height - 2 * margin) / (high - low):.1f}"
            for index, value in enumerate(selected)
        )

    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Cumulative factor return">
      <line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" class="axis"/>
      <line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" class="axis"/>
      <polyline points="{points(series['Gross'])}" class="gross"/>
      <polyline points="{points(series['Net after 10 bps turnover cost'])}" class="net"/>
      <text x="{margin}" y="24">{high:.3f}</text>
      <text x="{margin}" y="{height - 12}">{low:.3f}</text>
    </svg>
    """


def ic_svg(rows: list[dict[str, Any]]) -> str:
    width, height, margin = 900, 250, 35
    zero = height / 2
    bar_width = (width - 2 * margin) / len(rows)
    bars = []
    for index, row in enumerate(rows):
        value = max(min(float(row["qlibx_ic"]), 1), -1)
        x = margin + index * bar_width + 1
        y = zero - max(value, 0) * (zero - margin)
        bar_height = abs(value) * (zero - margin)
        bars.append(
            f'<rect x="{x:.1f}" y="{y if value >= 0 else zero:.1f}" '
            f'width="{max(bar_width - 2, 1):.1f}" height="{bar_height:.1f}" '
            f'class="{"positive" if value >= 0 else "negative"}"><title>'
            f'{html.escape(row["evaluation_date"])}: {value:.4f}</title></rect>'
        )
    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Period information coefficients">
      <line x1="{margin}" y1="{zero}" x2="{width - margin}" y2="{zero}" class="axis"/>
      {''.join(bars)}
      <text x="4" y="{margin}">+1</text><text x="8" y="{height - margin}">-1</text>
    </svg>
    """


def render_report(summary: dict[str, Any], periods: list[dict[str, Any]]) -> str:
    metrics = summary["aggregate_metrics"]
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['decision_date'])}</td>"
        f"<td>{html.escape(row['evaluation_date'])}</td>"
        f"<td>{row['qlibx_ic']:.4f}</td>"
        f"<td>{row['rank_ic']:.4f}</td>"
        f"<td>{row['qlibx_gross_return']:.3%}</td>"
        f"<td>{row['turnover']:.3f}</td>"
        f"<td>{row['net_return']:.3%}</td>"
        "</tr>"
        for row in periods
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>qlibx academic factor research showcase</title>
<style>
:root{{--ink:#17202a;--muted:#65717e;--paper:#f4f1e8;--panel:#fffdf8;--teal:#147d75;
--navy:#243b5a;--red:#b33a3a;--amber:#a96f12;--line:#d8d2c5}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55
system-ui,-apple-system,"Segoe UI",sans-serif}} main{{max-width:1120px;margin:auto;padding:44px 24px 72px}}
h1{{font:700 42px/1.08 Georgia,serif;margin:0 0 10px}} h2{{font:700 25px Georgia,serif;margin-top:38px}}
.lede{{color:var(--muted);max-width:850px;font-size:17px}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:28px 0}}
.card,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;box-shadow:0 2px 12px #392d1710}}
.label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}} .value{{font-size:27px;font-weight:750;margin-top:5px}}
.ok{{color:var(--teal)}} .gap{{color:var(--red)}} .local{{color:var(--amber)}}
.legend span{{margin-right:20px}} .dot{{display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:6px}}
.gross{{fill:none;stroke:var(--navy);stroke-width:3}} .net{{fill:none;stroke:var(--teal);stroke-width:3}}
.axis{{stroke:#8d8a82;stroke-width:1}} .positive{{fill:var(--teal)}} .negative{{fill:var(--red)}}
svg{{width:100%;height:auto}} table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right}} th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
.table-wrap{{overflow:auto}} code{{background:#ebe6db;padding:2px 5px;border-radius:4px}} ul{{padding-left:20px}}
.verdict{{border-left:5px solid var(--red)}} footer{{margin-top:35px;color:var(--muted);font-size:13px}}
</style></head>
<body><main>
<div class="label">qlibx / real-DW / {SHOWCASE_ID}</div>
<h1>Academic factor research: what works today?</h1>
<p class="lede">A project-local 20-session reversal factor is materialized through qlibx at frozen
monthly decision times. Each next-month cross-section is evaluated by qlibx and reconciled to an
independent calculation. Multi-period aggregation is deliberately showcase-local.</p>
<section class="grid">
  <div class="card"><div class="label">Factor materialization</div><div class="value ok">Demonstrated</div></div>
  <div class="card"><div class="label">One-period qlibx analysis</div><div class="value ok">Demonstrated</div></div>
  <div class="card"><div class="label">Multi-period evaluator</div><div class="value local">Showcase-local</div></div>
  <div class="card"><div class="label">AcademicExchange</div><div class="value gap">Not implemented</div></div>
</section>
<section class="grid">
  <div class="card"><div class="label">Periods</div><div class="value">{metrics['period_count']}</div></div>
  <div class="card"><div class="label">Mean Pearson IC</div><div class="value">{metrics['mean_ic']:.3f}</div></div>
  <div class="card"><div class="label">Annualized ICIR</div><div class="value">{metrics['annualized_icir']:.3f}</div></div>
  <div class="card"><div class="label">Net academic return</div><div class="value">{metrics['cumulative_net_return']:.2%}</div></div>
</section>
<h2>Hypothetical return index</h2><div class="panel">{line_svg(periods)}
<div class="legend"><span><i class="dot" style="background:#243b5a"></i>Gross</span>
<span><i class="dot" style="background:#147d75"></i>Net after showcase-local 10 bps turnover cost</span></div></div>
<h2>Cross-sectional Pearson IC by period</h2><div class="panel">{ic_svg(periods)}</div>
<h2>Period evidence</h2><div class="panel table-wrap"><table><thead><tr><th>Decision</th><th>Evaluation</th><th>IC</th><th>RankIC</th><th>Gross</th><th>Turnover</th><th>Net</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Capability verdict</h2><div class="panel verdict"><p><strong>AcademicExchange is absent from the current public package.</strong>
The factor and its one-period statistics are valid account-free research artifacts; this report does
not create hypothetical Fills, positions, an Account, or executable shorts.</p><p>The cumulative return,
RankIC, ICIR, quantile spread, turnover, and 10 bps cost are calculated in this showcase runner. They
identify the next product surface but are not silently attributed to qlibx.</p></div>
<h2>Study contract</h2><div class="panel"><ul>
<li>Source: <code>{html.escape(summary['dataset']['source'])}</code></li>
<li>Fixed universe: {summary['dataset']['instrument_count']} instruments; study {summary['dataset']['study_start']} to {summary['dataset']['study_end']}</li>
<li>Factor: negative compounded close-to-previous-close return over {LOOKBACK_SESSIONS} complete common sessions</li>
<li>Portfolio: demeaned factor values normalized to unit gross; no Account or borrow model</li>
<li>Retrospective completeness filtering and fixed-universe survivorship can bias results; values are workflow evidence, not an alpha claim</li>
</ul></div>
<footer>Verified against {html.escape(summary['verified_against'])}. Bounded dataset SHA-256:
<code>{summary['dataset']['bounded_sha256']}</code></footer>
</main></body></html>"""


def run(repo_root: Path) -> dict[str, Any]:
    showcase_root = Path(__file__).resolve().parent
    output_root = showcase_root / "outputs"
    project_root = output_root / "project"
    bounded_path = project_root / "data" / "academic_factor_market.csv"
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
                source="data/academic_factor_market.csv",
                source_format=SourceFormat.CSV,
                instrument_field="instrument",
                observation_time_field="observation_time",
                available_at=AvailableAtField(field="available_at"),
                logical_key=("observation_time", "available_at", "instrument"),
                semantic_bindings={
                    "factor_input_return": "factor_input_return",
                    "analysis_return": "analysis_return",
                },
                semantic_category="showcase_real_dw_daily_and_forward_returns",
                source_provenance=(
                    "Bounded deterministic projection of data/DW/fng_stock_daily_prices.csv; "
                    "daily returns use close / previous_close - 1 and availability is the same "
                    "session 15:30 Asia/Seoul close."
                ),
            )
        ),
        "dataset registration",
    )
    registered = project.registry_snapshot().get(DATASET_ID)
    if registered is None:
        raise RuntimeError("registered dataset is absent from the project snapshot")

    model = MonthlyReversalModel(DATASET_ID, LOOKBACK_SESSIONS)
    analysis_flow = AnalysisFlow(
        artifacts=project.artifacts,
        registry=project.registry_snapshot(),
    )
    decision_dates = [pd.Timestamp(value) for value in extraction["decision_dates"]]
    forward_returns: dict[pd.Timestamp, pd.Series] = extraction["evaluation_returns"]
    previous_weights = {instrument: 0.0 for instrument in UNIVERSE}
    cumulative_gross = 1.0
    cumulative_net = 1.0
    period_results: list[PeriodResult] = []
    maximum_ic_delta = 0.0
    maximum_return_delta = 0.0
    lineage_checks: list[bool] = []

    for decision_day, evaluation_day in pairwise(decision_dates):
        decision_time = close_at(decision_day)
        evaluation_time = close_at(evaluation_day)
        materialized = require_complete(
            project.materialize(
                model,
                MaterializationInvocation(
                    invocation_id=f"showcase-factor-{decision_day:%Y%m%d}-v1",
                    evaluation_time=decision_time,
                    config_fingerprint=(
                        f"monthly-reversal-{LOOKBACK_SESSIONS}-complete-sessions-v1"
                    ),
                ),
            ),
            f"factor materialization {decision_day.date()}",
        )
        signal_artifact = materialized.result.artifact
        if any(
            access.max_available_at is not None and access.max_available_at > decision_time
            for access in materialized.result.accesses
        ):
            raise RuntimeError("factor materialization accessed future-hidden data")

        analyzed = require_complete(
            analysis_flow.analyze_signal(
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
        analysis_artifact = analyzed.diagnostics[0]
        signals = {
            item.instrument: float(item.value)
            for item in materialized.result.result.entries
        }
        realized = forward_returns[evaluation_day].loc[list(signals)].astype(float)
        signal_series = pd.Series(signals).sort_index()
        realized = realized.reindex(signal_series.index)
        oracle_ic = correlation(signal_series, realized)
        rank_ic = correlation(
            signal_series.rank(method="average"),
            realized.rank(method="average"),
        )
        centered = signal_series - signal_series.mean()
        weights = centered / centered.abs().sum()
        oracle_return = float((weights * realized).sum())
        qlibx_ic = metric(analyzed.result, "information_coefficient")
        qlibx_return = metric(analyzed.result, "hypothetical_long_short_return")
        maximum_ic_delta = max(maximum_ic_delta, abs(qlibx_ic - oracle_ic))
        maximum_return_delta = max(
            maximum_return_delta,
            abs(qlibx_return - oracle_return),
        )
        if not math.isclose(qlibx_ic, oracle_ic, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("qlibx IC does not reconcile to the independent calculation")
        if not math.isclose(qlibx_return, oracle_return, rel_tol=0, abs_tol=1e-12):
            raise RuntimeError("qlibx return does not reconcile to the independent calculation")

        current_weights = weights.to_dict()
        turnover = 0.5 * sum(
            abs(current_weights.get(instrument, 0) - previous_weights.get(instrument, 0))
            for instrument in set(current_weights) | set(previous_weights)
        )
        cost = turnover * HYPOTHETICAL_COST_RATE
        net_return = qlibx_return - cost
        cumulative_gross *= 1 + qlibx_return
        cumulative_net *= 1 + net_return
        quantile_count = max(len(signal_series) // 4, 1)
        ranked = signal_series.sort_values(kind="mergesort")
        bottom = ranked.index[:quantile_count]
        top = ranked.index[-quantile_count:]
        quantile_spread = float(realized.loc[top].mean() - realized.loc[bottom].mean())
        lineage_checks.append(
            any(
                edge.dependency_kind == "artifact"
                and edge.dependency_id == signal_artifact.artifact_id
                and edge.consumer_role == "stored_analysis_input"
                for edge in analysis_artifact.dependencies
            )
            and any(
                edge.dependency_kind == "dataset"
                and edge.dependency_id == registered.registration_identity
                for edge in analysis_artifact.dependencies
            )
        )
        period_results.append(
            PeriodResult(
                decision_date=decision_day.date().isoformat(),
                evaluation_date=evaluation_day.date().isoformat(),
                instrument_count=len(signal_series),
                qlibx_ic=qlibx_ic,
                oracle_ic=oracle_ic,
                rank_ic=rank_ic,
                qlibx_gross_return=qlibx_return,
                oracle_gross_return=oracle_return,
                quantile_spread=quantile_spread,
                turnover=turnover,
                hypothetical_cost=cost,
                net_return=net_return,
                cumulative_gross=cumulative_gross - 1,
                cumulative_net=cumulative_net - 1,
                signal_artifact_id=signal_artifact.artifact_id,
                analysis_artifact_id=analysis_artifact.artifact_id,
            )
        )
        previous_weights = current_weights

    period_payload = [asdict(item) for item in period_results]
    ic_values = pd.Series([item.qlibx_ic for item in period_results], dtype=float)
    rank_ic_values = pd.Series([item.rank_ic for item in period_results], dtype=float)
    ic_std = float(ic_values.std(ddof=1))
    academic_exchange_present = hasattr(qlibx, "AcademicExchange") or hasattr(
        qlibx_execution, "AcademicExchange"
    )
    if academic_exchange_present:
        raise RuntimeError("showcase verdict is stale: AcademicExchange now exists")
    summary = {
        "showcase_id": SHOWCASE_ID,
        "status": "complete",
        "verified_against": "qlibx-0.1.0+implementations-009-016-059-060",
        "capabilities": {
            "project_local_factor_materialization": "demonstrated",
            "one_period_qlibx_signal_analysis": "demonstrated",
            "multi_period_factor_evaluation": "showcase_local",
            "academic_exchange": "not_implemented",
            "account_or_memory_mutation": False,
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
            "study_start": STUDY_START.date().isoformat(),
            "study_end": STUDY_END.date().isoformat(),
            "instrument_count": len(UNIVERSE),
            "universe": list(UNIVERSE),
            "registration_identity": registered.registration_identity,
        },
        "factor": {
            "factor_id": "monthly-reversal-20-complete-sessions-v1",
            "lookback_sessions": LOOKBACK_SESSIONS,
            "direction": "higher means weaker trailing return",
            "weighting": "cross-sectional demean then normalize to unit gross",
        },
        "aggregate_metrics": {
            "period_count": len(period_results),
            "mean_ic": float(ic_values.mean()),
            "mean_rank_ic": float(rank_ic_values.mean()),
            "ic_sample_std": ic_std,
            "annualized_icir": (
                float(ic_values.mean() / ic_std * math.sqrt(12)) if ic_std > 0 else 0.0
            ),
            "ic_hit_rate": float((ic_values > 0).mean()),
            "mean_quantile_spread": float(
                pd.Series([item.quantile_spread for item in period_results]).mean()
            ),
            "cumulative_gross_return": cumulative_gross - 1,
            "cumulative_net_return": cumulative_net - 1,
            "mean_turnover": float(
                pd.Series([item.turnover for item in period_results]).mean()
            ),
            "hypothetical_cost_rate": HYPOTHETICAL_COST_RATE,
        },
        "verification": {
            "maximum_absolute_ic_delta": maximum_ic_delta,
            "maximum_absolute_return_delta": maximum_return_delta,
            "all_lineage_checks_passed": all(lineage_checks),
            "materialized_signal_count": len(period_results),
            "analysis_result_count": len(period_results),
        },
        "limitations": [
            "AcademicExchange is not implemented by qlibx.",
            "Multi-period aggregation, RankIC, ICIR, quantiles, turnover, and cost are showcase-local.",
            "The fixed universe and complete-common-session filter introduce survivorship and selection bias.",
            "The hypothetical portfolio has no Account, fills, borrow, collateral, locate, capacity, or market impact.",
            "This is workflow evidence, not evidence that the reversal factor is economically useful.",
        ],
    }
    if not summary["verification"]["all_lineage_checks_passed"]:
        raise RuntimeError("one or more analysis artifacts lack exact signal/dataset lineage")

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
    catalog = [
        envelope.model_dump(mode="json")
        for envelope in project.artifacts.list_envelopes()
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
