"""Tests for quick_start() helper."""

from pathlib import Path

from echolon.config.quick_start import quick_start


def test_quick_start_returns_three_configs(monkeypatch, tmp_path):
    monkeypatch.setenv("ECHOLON_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("ECHOLON_DATA_DIR", str(tmp_path / "data"))

    ctx, bt, opt = quick_start(
        market="shfe",
        instrument="cu",
        start_date="2020-01-01",
        end_date="2023-12-31",
    )

    assert ctx.instrument_code == "cu"
    assert ctx.frequency == "interday"

    assert bt.start_date == "2020-01-01"
    assert bt.end_date == "2023-12-31"
    assert bt.strategy_dir == tmp_path / "workspace" / "code"
    assert bt.market_data_dir == tmp_path / "data" / "market"
    assert bt.indicator_dir == tmp_path / "data" / "indicators"
    assert bt.results_dir == tmp_path / "workspace" / "results"

    assert opt.n_trials == 100


def test_quick_start_fallback_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("ECHOLON_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("ECHOLON_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    ctx, bt, opt = quick_start(
        market="shfe",
        instrument="cu",
        start_date="2020-01-01",
        end_date="2023-12-31",
    )

    assert bt.strategy_dir == Path("workspace/code")
    assert bt.market_data_dir == Path("data/market")
