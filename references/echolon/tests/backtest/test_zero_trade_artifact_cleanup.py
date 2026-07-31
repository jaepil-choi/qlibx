import inspect

from echolon.backtest.engine.backtest_runner import (
    unlink_optional_series_artifacts,
)
from echolon.backtest.wfa.runner import WFARunner


def test_optional_series_cleanup_unlinks_stale_trade_and_equity_csvs(tmp_path):
    trades = tmp_path / "backtest_trades.csv"
    equity = tmp_path / "equity_curve.csv"
    trades.write_text("stale trade data\n")
    equity.write_text("stale equity data\n")

    unlink_optional_series_artifacts(tmp_path)

    assert not trades.exists()
    assert not equity.exists()


def test_wfa_runner_cleans_optional_series_before_each_oos_backtest():
    source = inspect.getsource(WFARunner.run)

    assert "unlink_optional_series_artifacts(self.output_dir)" in source
    assert source.index("unlink_optional_series_artifacts(self.output_dir)") < source.index(
        "run_best_trial("
    )
