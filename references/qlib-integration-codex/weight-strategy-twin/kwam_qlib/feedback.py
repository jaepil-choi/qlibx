from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class QlibPortfolioFeedback:
    """Qlib Account가 한 trading bar를 마친 뒤 확정한 portfolio feedback."""

    date: pd.Timestamp
    gross_return: float
    cost: float
    net_return: float
    turnover: float
    cash: float
    account_value: float


def read_latest_portfolio_feedback(trade_account) -> QlibPortfolioFeedback:
    """현재 Qlib Account report의 마지막 bar를 closed-loop feedback으로 읽습니다."""

    report, _positions = trade_account.get_portfolio_metrics()
    if report.empty:
        raise RuntimeError("Qlib Account has no completed portfolio-metric bar.")

    required = {"return", "cost", "turnover", "cash", "account"}
    missing = sorted(required - set(report.columns))
    if missing:
        raise KeyError(f"Qlib portfolio metrics are missing feedback fields: {missing}")

    date = pd.Timestamp(report.index[-1]).normalize()
    row = report.iloc[-1]
    gross_return = float(row["return"])
    cost = float(row["cost"])
    return QlibPortfolioFeedback(
        date=date,
        gross_return=gross_return,
        cost=cost,
        net_return=gross_return - cost,
        turnover=float(row["turnover"]),
        cash=float(row["cash"]),
        account_value=float(row["account"]),
    )
