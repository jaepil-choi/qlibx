from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
import qlib
from qlib.backtest import backtest
from qlib.backtest.executor import SimulatorExecutor
from qlib.constant import REG_US

INTEGRATION_DIR = Path(__file__).resolve().parents[1]
if str(INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_DIR))

from kwam_qlib.exchange import DataFrameExchange, build_quote_frame  # noqa: E402
from kwam_qlib.feedback import read_latest_portfolio_feedback  # noqa: E402
from kwam_qlib.strategy import ConsecutiveLossStopPeerMomentumStrategy  # noqa: E402


class _FakeAccount:
    def __init__(self, report: pd.DataFrame) -> None:
        self.report = report

    def get_portfolio_metrics(self):
        return self.report, {}


def test_latest_qlib_feedback_uses_net_return_after_cost() -> None:
    report = pd.DataFrame(
        {
            "return": [0.01],
            "cost": [0.003],
            "turnover": [0.4],
            "cash": [100.0],
            "account": [1_007.0],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )

    feedback = read_latest_portfolio_feedback(_FakeAccount(report))

    assert feedback.net_return == pytest.approx(0.007)
    assert feedback.gross_return == pytest.approx(0.01)
    assert feedback.cost == pytest.approx(0.003)


def test_three_consecutive_qlib_losses_trigger_signal_independent_liquidation(
    tmp_path: Path,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=6)
    tickers = pd.Index(["A", "B"], name="instrument")
    provider_dir = tmp_path / "provider"
    _write_minimal_provider(provider_dir, dates, tickers)
    qlib.init(
        provider_uri=str(provider_dir),
        region=REG_US,
        expression_cache=None,
        dataset_cache=None,
    )

    close = pd.DataFrame(
        {
            "A": [100.0, 100.0, 90.0, 81.0, 72.9, 72.9],
            "B": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=dates,
    )
    change = close.pct_change(fill_method=None).fillna(0.0)
    volume = pd.DataFrame(1_000_000.0, index=dates, columns=tickers)
    quote = build_quote_frame(close, change, volume)

    trade_dates = dates[1:]
    exchange = DataFrameExchange(
        quote_frame=quote.loc[
            quote.index.get_level_values("datetime").isin(trade_dates)
        ],
        freq="day",
        start_time=trade_dates[0],
        end_time=trade_dates[-1],
        codes=tickers.tolist(),
        deal_price="close",
        limit_threshold=None,
        open_cost=0.0,
        close_cost=0.0,
        min_cost=0.0,
        trade_unit=None,
    )

    # 마지막 trade date에 필요한 전일 signal은 의도적으로 제공하지 않습니다.
    # Stop branch가 Qlib signal lookup보다 먼저 실행되어야만 청산할 수 있습니다.
    signal_dates = dates[:4]
    signal_matrix = pd.DataFrame(0.0, index=signal_dates, columns=tickers)
    signal = signal_matrix.stack().swaplevel().sort_index().rename("score")
    signal.index = signal.index.set_names(["instrument", "datetime"])

    benchmark_weight = pd.DataFrame(0.0, index=dates, columns=tickers)
    benchmark_weight["A"] = 1.0
    universe_mask = pd.DataFrame(True, index=dates, columns=tickers)
    strategy = ConsecutiveLossStopPeerMomentumStrategy(
        signal=signal,
        benchmark_weight=benchmark_weight,
        universe_mask=universe_mask,
        active_multiplier=0.0,
        top_fraction=None,
        risk_degree=1.0,
        consecutive_loss_days=3,
    )
    executor = SimulatorExecutor(
        time_per_step="day",
        generate_portfolio_metrics=True,
        verbose=False,
    )

    portfolio_metrics, _indicator_metrics = backtest(
        start_time=trade_dates[0],
        end_time=trade_dates[-1],
        strategy=strategy,
        executor=executor,
        benchmark=pd.Series(0.0, index=trade_dates),
        account=1_000_000.0,
        exchange_kwargs={"exchange": exchange},
    )
    report, _positions = portfolio_metrics["1day"]

    feedback = pd.Series(
        {
            item.date: item.net_return for item in strategy.portfolio_feedback_history
        }
    )
    assert feedback.loc[dates[2]] == pytest.approx(-0.10)
    assert feedback.loc[dates[3]] == pytest.approx(-0.10)
    assert feedback.loc[dates[4]] == pytest.approx(-0.10)
    assert strategy.stop_triggered
    assert strategy.stop_trigger_date == dates[4]
    assert strategy.liquidation_decision_date == dates[5]
    assert strategy.target_history[dates[5]].sum() == pytest.approx(0.0)
    assert strategy.trade_position.get_stock_amount_dict() == {}
    assert report.loc[dates[5], "value"] == pytest.approx(0.0, abs=1e-8)
    assert report.loc[dates[5], "cash"] == pytest.approx(
        report.loc[dates[5], "account"]
    )


def _write_minimal_provider(
    provider_dir: Path,
    calendar: pd.DatetimeIndex,
    tickers: pd.Index,
) -> None:
    calendars_dir = provider_dir / "calendars"
    instruments_dir = provider_dir / "instruments"
    calendars_dir.mkdir(parents=True)
    instruments_dir.mkdir(parents=True)

    sentinel = pd.Timestamp(calendar[-1]) + pd.Timedelta(days=1)
    full_calendar = calendar.append(pd.DatetimeIndex([sentinel]))
    (calendars_dir / "day.txt").write_text(
        "\n".join(date.strftime("%Y-%m-%d") for date in full_calendar) + "\n",
        encoding="utf-8",
    )
    first = calendar[0].strftime("%Y-%m-%d")
    last = sentinel.strftime("%Y-%m-%d")
    (instruments_dir / "all.txt").write_text(
        "\n".join(f"{ticker}\t{first}\t{last}" for ticker in tickers) + "\n",
        encoding="utf-8",
    )
