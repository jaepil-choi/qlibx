"""Stored-artifact analysis, report composition, and presentation rendering."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from qlibx.execution import open_run_catalog


@dataclass(frozen=True, slots=True)
class BacktestAnalysis:
    input_run_id: str
    analysis_id: str
    analysis_version: str
    metrics: Mapping[str, float | int | str]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisSection:
    section_id: str
    version: str
    input_artifact_ids: tuple[str, ...]
    data: Mapping[str, Any]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportDocument:
    report_id: str
    schema_version: int
    sections: tuple[AnalysisSection, ...]


@dataclass(frozen=True, slots=True)
class RenderedReport:
    output: Path
    manifest: Path
    digest: str


def analyze_stored_backtest(catalog_path: str | Path, run_id: str) -> BacktestAnalysis:
    """Backward-compatible summary built strictly from stored run tables."""
    document = analyze_stored_run(catalog_path, run_id)
    performance = next(
        section for section in document.sections if section.section_id == "performance"
    )
    execution = next(section for section in document.sections if section.section_id == "execution")
    metrics = {
        **performance.data,
        "orders": execution.data["orders"],
        "fills": execution.data["fills"],
    }
    return BacktestAnalysis(run_id, "stored_backtest_summary", "2", metrics)


def analyze_stored_run(catalog_path: str | Path, run_id: str) -> ReportDocument:
    """Calculate reusable sections without loading a strategy, model, optimizer, or Qlib Account."""
    catalog = open_run_catalog(catalog_path)
    record = catalog.get_run(run_id)
    if record.run_kind != "backtest":
        raise ValueError(f"analysis input is not a backtest run: {run_id}")
    config = record.metadata.get("backtest_config", {})
    signed = config.get("target_semantics") == "signed_weight"
    account_name = "active_account_daily" if signed else "account_daily"
    account = catalog.load_table(run_id, account_name).sort_values("trade_date")
    if account.empty:
        raise ValueError("stored account artifact is empty")
    returns = account["portfolio_return"].astype("float64")
    nav = account["nav"].astype("float64")
    drawdown = nav.div(nav.cummax()).sub(1.0)
    performance = AnalysisSection(
        "performance",
        "1",
        (f"{run_id}/{account_name}",),
        {
            "account_view": "active" if signed else "physical",
            "start_date": str(account.iloc[0]["trade_date"]),
            "end_date": str(account.iloc[-1]["trade_date"]),
            "initial_nav": float(nav.iloc[0]),
            "final_nav": float(nav.iloc[-1]),
            "money_pnl": float(nav.iloc[-1] - nav.iloc[0]),
            "mean_return": float(returns.mean()),
            "return_volatility": float(returns.std(ddof=0)),
            "max_drawdown": float(drawdown.min()),
        },
    )
    targets = catalog.load_table(run_id, "target_weights")
    turnover = account["turnover"].astype("float64") if "turnover" in account else pd.Series()
    coverage = AnalysisSection(
        "coverage_turnover",
        "1",
        (f"{run_id}/target_weights", f"{run_id}/{account_name}"),
        {
            "target_rows": len(targets),
            "target_columns": len(targets.columns),
            "coverage": float(targets.notna().mean().mean()) if not targets.empty else 0.0,
            "missingness": float(targets.isna().mean().mean()) if not targets.empty else 1.0,
            "turnover_sum": float(turnover.sum()) if not turnover.empty else 0.0,
            "turnover_mean": float(turnover.mean()) if not turnover.empty else 0.0,
        },
    )
    orders = catalog.load_table(run_id, "orders")
    fills = catalog.load_table(run_id, "fills")
    execution_data: dict[str, Any] = {
        "orders": len(orders),
        "fills": int(fills["filled_quantity"].gt(0).sum()) if not fills.empty else 0,
        "blocked_fills": int(fills["filled_quantity"].eq(0).sum()) if not fills.empty else 0,
        "trade_cost": float(fills["trade_cost"].sum()) if not fills.empty else 0.0,
        "requested_quantity": (
            float(orders["requested_quantity"].sum()) if not orders.empty else 0.0
        ),
        "dealt_quantity": float(fills["filled_quantity"].sum()) if not fills.empty else 0.0,
    }
    execution = AnalysisSection(
        "execution",
        "1",
        (f"{run_id}/orders", f"{run_id}/fills"),
        execution_data,
    )
    sections: list[AnalysisSection] = [performance, coverage, execution]
    if signed:
        signed_positions = catalog.load_table(run_id, "signed_positions")
        composite = catalog.load_table(run_id, "account_daily")
        baseline = catalog.load_table(run_id, "baseline_account_daily")
        active = catalog.load_table(run_id, "active_account_daily")
        quantity_error = signed_positions["held_quantity"].sub(
            signed_positions["composite_quantity"].sub(signed_positions["baseline_quantity"])
        )
        nav_error = composite["nav"].sub(baseline["nav"].add(active["nav"]))
        sections.append(
            AnalysisSection(
                "matched_capitalization",
                "1",
                (
                    f"{run_id}/signed_positions",
                    f"{run_id}/account_daily",
                    f"{run_id}/baseline_account_daily",
                    f"{run_id}/active_account_daily",
                ),
                {
                    "compatibility_hack": True,
                    "quantity_identity_max_error": float(quantity_error.abs().max()),
                    "minimum_composite_quantity": float(
                        signed_positions["composite_quantity"].min()
                    ),
                    "nav_reconciliation_max_error": float(nav_error.abs().max()),
                    "active_return_denominator": float(active["return_denominator"].iloc[0]),
                },
                ("This is not native borrow, margin, recall, or borrow-fee modeling.",),
            )
        )
    optimizer = _optional_table(catalog, run_id, "optimizer_daily")
    if optimizer is not None:
        sections.append(
            AnalysisSection(
                "optimizer_attribution",
                "1",
                (f"{run_id}/optimizer_daily",),
                {
                    "rows": len(optimizer),
                    "statuses": optimizer["optimizer_status"].value_counts().to_dict(),
                    "validation_passed": bool(optimizer["validation_passed"].all()),
                },
            )
        )
    parent_links = catalog.get_parent_links(run_id)
    if parent_links:
        sections.append(
            AnalysisSection(
                "lineage",
                "1",
                tuple(link.run_id for link in parent_links),
                {
                    "parents": [
                        {"run_id": link.run_id, "role": link.role, "weight": link.weight}
                        for link in parent_links
                    ]
                },
            )
        )
    return compose_report(sections, report_id=f"stored-run-{run_id}")


def compose_report(
    sections: Sequence[AnalysisSection],
    *,
    report_id: str,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] = (),
    order: Sequence[str] | None = None,
) -> ReportDocument:
    by_id = {section.section_id: section for section in sections}
    if len(by_id) != len(sections):
        raise ValueError("report section IDs must be unique")
    selected = list(by_id) if include is None else list(include)
    unknown = set(selected).difference(by_id)
    if unknown:
        raise ValueError(f"unknown included report sections: {sorted(unknown)}")
    selected = [name for name in selected if name not in set(exclude)]
    if order is not None:
        missing = set(selected).difference(order)
        extra = set(order).difference(selected)
        if missing or extra:
            raise ValueError("report order must exactly cover selected sections")
        selected = list(order)
    return ReportDocument(report_id, 1, tuple(by_id[name] for name in selected))


def render_report(
    document: ReportDocument,
    output: str | Path,
    *,
    renderer: Literal["json", "html"] | Callable[[ReportDocument], bytes | str] = "json",
) -> RenderedReport:
    """Render already-calculated sections; no analysis occurs in this function."""
    path = Path(output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if callable(renderer):
        rendered = renderer(document)
        content = rendered.encode("utf-8") if isinstance(rendered, str) else rendered
        if not isinstance(content, bytes):
            raise TypeError("custom report renderer must return bytes or str")
        renderer_id = getattr(renderer, "__qualname__", "local_renderer")
    elif renderer == "json":
        content = json.dumps(
            _document_payload(document),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        renderer_id = "json"
    elif renderer == "html":
        content = _render_html(document)
        renderer_id = "html"
    else:
        raise ValueError(f"unsupported renderer: {renderer}")
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "report_id": document.report_id,
                "schema_version": document.schema_version,
                "sections": [section.section_id for section in document.sections],
                "renderer": renderer_id,
                "output_digest": digest,
                "artifact_role": "report_output_not_canonical_research_artifact",
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return RenderedReport(path, manifest_path, digest)


def render_analysis(
    analysis: BacktestAnalysis,
    output: str | Path,
    *,
    renderer: Literal["json", "html"] = "json",
) -> RenderedReport:
    section = AnalysisSection(
        analysis.analysis_id,
        analysis.analysis_version,
        (analysis.input_run_id,),
        dict(analysis.metrics),
        analysis.warnings,
    )
    document = compose_report((section,), report_id=f"analysis-{analysis.input_run_id}")
    return render_report(document, output, renderer=renderer)


def _optional_table(catalog: Any, run_id: str, name: str) -> pd.DataFrame | None:
    try:
        return catalog.load_table(run_id, name)
    except KeyError:
        return None


def _document_payload(document: ReportDocument) -> Mapping[str, Any]:
    return {
        "report_id": document.report_id,
        "schema_version": document.schema_version,
        "sections": [
            {
                "section_id": section.section_id,
                "version": section.version,
                "input_artifact_ids": list(section.input_artifact_ids),
                "data": dict(section.data),
                "warnings": list(section.warnings),
            }
            for section in document.sections
        ],
    }


def _render_html(document: ReportDocument) -> bytes:
    sections = []
    for section in document.sections:
        rows = "".join(
            f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
            for key, value in section.data.items()
        )
        sections.append(
            f"<section><h2>{html.escape(section.section_id)}</h2><table>{rows}</table></section>"
        )
    return ("<!doctype html><html><body>" + "".join(sections) + "</body></html>").encode("utf-8")
