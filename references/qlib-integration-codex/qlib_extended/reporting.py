from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from .models import ReportResult
from .store import RunCatalog


def create_report(
    catalog_path: str | Path,
    *,
    backtest_run_ids: tuple[str, ...],
    output_dir: str | Path,
    include_png: bool = False,
) -> ReportResult:
    if not backtest_run_ids:
        raise ValueError("at least one backtest_run_id is required")
    store = RunCatalog.open(catalog_path)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    accounts: dict[str, pd.DataFrame] = {}
    for run_id in backtest_run_ids:
        record = store.get_run(run_id)
        if record.run_kind != "backtest":
            raise ValueError(f"report input is not a backtest run: {run_id}")
        backtest_config = record.metadata.get("backtest_config", {})
        is_signed = backtest_config.get("target_semantics") == "signed_weight"
        account_name = "active_account_daily" if is_signed else "account_daily"
        account = store.load_table(run_id, account_name).sort_values("trade_date")
        if account.empty:
            raise ValueError(f"backtest {account_name} is empty: {run_id}")
        accounts[run_id] = account
        rows.append(
            {
                "run_id": run_id,
                "strategy_id": record.strategy_id,
                "account_view": "active" if is_signed else "composite",
                "start_date": pd.Timestamp(account.iloc[0]["trade_date"]).date(),
                "end_date": pd.Timestamp(account.iloc[-1]["trade_date"]).date(),
                "final_nav": float(account.iloc[-1]["nav"]),
                "total_return": float(
                    account["portfolio_return"].astype(float).sum()
                    if is_signed
                    else (1.0 + account["portfolio_return"].astype(float)).prod()
                    - 1.0
                ),
                "total_trade_cost": float(account["trade_cost"].astype(float).sum()),
            }
        )
    metrics = pd.DataFrame(rows)
    html_path = output / "report.html"
    html_path.write_text(_render_html(metrics), encoding="utf-8")
    png_paths: tuple[Path, ...] = ()
    if include_png:
        png_path = output / "cumulative-return.png"
        _write_cumulative_return_figure(accounts, png_path)
        png_paths = (png_path,)
    return ReportResult(
        backtest_run_ids=backtest_run_ids,
        html_path=html_path,
        png_paths=png_paths,
    )


def _render_html(metrics: pd.DataFrame) -> str:
    run_ids = "\n".join(
        f"<li><code>{html.escape(str(run_id))}</code></li>"
        for run_id in metrics["run_id"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>qlib-extended backtest report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #17212b; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d9e0e7; padding: .55rem; text-align: right; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
    code {{ font-size: .85rem; }}
  </style>
</head>
<body>
  <h1>qlib-extended backtest report</h1>
  <p>This report was rendered from immutable stored backtest artifacts.</p>
  <ul>{run_ids}</ul>
  {metrics.to_html(index=False, border=0, float_format=lambda value: f"{value:.6f}")}
</body>
</html>
"""


def _write_cumulative_return_figure(
    accounts: dict[str, pd.DataFrame], path: Path
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(9, 4.8))
    for run_id, account in accounts.items():
        dates = pd.to_datetime(account["trade_date"])
        returns = account["portfolio_return"].astype(float)
        cumulative = (
            returns.cumsum()
            if "return_denominator" in account
            else (1.0 + returns).cumprod() - 1.0
        )
        axis.plot(dates, cumulative, label=run_id)
    axis.axhline(0.0, color="#6c7782", linewidth=0.8)
    axis.set_title("Cumulative portfolio return")
    axis.set_ylabel("Return")
    axis.legend(fontsize=7)
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)
