from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import matplotlib
import pandas as pd


def write_outputs(
    output_dir: Path,
    *,
    member_returns: pd.DataFrame,
    family_returns: pd.DataFrame,
    market_returns: pd.DataFrame,
    rationale_returns: pd.DataFrame,
    summaries: Mapping[str, pd.DataFrame],
    proof: Mapping[str, object],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tables = output_dir / "tables"
    figures = output_dir / "figures"
    tables.mkdir(exist_ok=True)
    figures.mkdir(exist_ok=True)
    frames = {
        "member_gross_returns": member_returns,
        "family_gross_returns": family_returns,
        "market_method_net_returns": market_returns,
        "rationale_enhanced_net_active_returns": rationale_returns,
        **summaries,
    }
    for name, frame in frames.items():
        frame.to_csv(tables / f"{name}.csv", encoding="utf-8-sig")
    proof_path = output_dir / "migration-proof.json"
    proof_path.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    figure_path = figures / "report-twin-pnl.png"
    _plot_pnl(
        figure_path,
        member_returns=member_returns,
        family_returns=family_returns,
        market_returns=market_returns,
        rationale_returns=rationale_returns,
    )
    return proof_path, figure_path


def _plot_pnl(
    path: Path,
    *,
    member_returns: pd.DataFrame,
    family_returns: pd.DataFrame,
    market_returns: pd.DataFrame,
    rationale_returns: pd.DataFrame,
) -> None:
    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(2, 2, figsize=(16, 10))
    for column in member_returns:
        axes[0, 0].plot(
            member_returns.index,
            member_returns[column].cumsum() * 100.0,
            linewidth=0.8,
            alpha=0.7,
        )
    axes[0, 0].set_title("18 member alpha · gross cumulative PnL")
    for column in family_returns:
        axes[0, 1].plot(
            family_returns.index,
            family_returns[column].cumsum() * 100.0,
            label=column,
        )
    axes[0, 1].set_title("Three family ensembles · gross cumulative PnL")
    axes[0, 1].legend(fontsize=8)
    for column in market_returns:
        axes[1, 0].plot(
            market_returns.index,
            market_returns[column].cumsum() * 100.0,
            label=column,
        )
    axes[1, 0].set_title("Market allocation methods · net cumulative PnL")
    axes[1, 0].legend(fontsize=7)
    for column in rationale_returns:
        axes[1, 1].plot(
            rationale_returns.index,
            rationale_returns[column].cumsum() * 100.0,
            linewidth=2.2 if column == "rationale_inverse_volatility" else 1.1,
            label=column,
        )
    axes[1, 1].set_title("Rationale ensembles · enhanced net active cumulative PnL")
    axes[1, 1].legend(fontsize=7)
    for axis in axes.flat:
        axis.axhline(0.0, color="#64748b", linewidth=0.7)
        axis.grid(alpha=0.25)
        axis.set_ylabel("Cumulative PnL (%)")
    figure.tight_layout()
    figure.savefig(path, dpi=170)
    plt.close(figure)
