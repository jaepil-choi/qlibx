"""Unit tests for Phase0DataPipeline (extracted from
PortfolioTradingRunner._phase0_data_pipeline in 2026-05-08 refactor)."""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echolon.live.config.portfolio_deploy_config import (
    PortfolioDeployConfig, SlotConfig, SlotDashboardConfig, DeploySettings, AccountConfig,
)


def _make_config(tmp_path: Path) -> PortfolioDeployConfig:
    sc = SlotConfig(
        slot_id="al_s1", strategy_id="al_test", cluster="al", version="1.0",
        instrument="aluminum", instrument_code="al", market="SHFE",
        frequency="interday", bar_size="1d", initial_capital=100000.0,
        strategy_code_dir=str(tmp_path / "strategy"), trial_params_path="",
        enabled=True, dashboard=SlotDashboardConfig(),
    )
    # `deploy` is required since 2026-07-27: no config may exist without a stated
    # capital cap. A synthetic figure — a scheduler test must not carry a real one.
    cfg = PortfolioDeployConfig(deploy=DeploySettings(max_total_capital=1000.0))
    cfg.slots = [sc]
    cfg.deploy = DeploySettings(
        max_total_capital=1000.0, trading_calendar_path=str(tmp_path / "cal.csv")
    )
    cfg.account = AccountConfig()
    return cfg


def test_phase0_aborts_when_xtdc_connect_fails(tmp_path):
    from echolon.live.orchestrator.phase0_pipeline import Phase0DataPipeline

    cfg = _make_config(tmp_path)
    pipeline = Phase0DataPipeline(config=cfg, log=MagicMock())

    with patch("echolon.live.orchestrator.phase0_pipeline.XtdcClient") as XtdcMock:
        instance = XtdcMock.return_value
        instance.connect.return_value = False  # simulate VPN/auth failure

        with pytest.raises(RuntimeError, match="Phase 0 abort"):
            pipeline.run(present_date=datetime(2026, 5, 8))


def test_phase0_runs_data_then_indicators_when_xtdc_connects(tmp_path):
    from echolon.live.orchestrator.phase0_pipeline import Phase0DataPipeline

    cfg = _make_config(tmp_path)
    log = MagicMock()
    pipeline = Phase0DataPipeline(config=cfg, log=log)

    with patch("echolon.live.orchestrator.phase0_pipeline.XtdcClient") as XtdcMock, \
         patch("echolon.live.orchestrator.phase0_pipeline.run_live_data_update") as data_run, \
         patch("echolon.live.orchestrator.phase0_pipeline.run_indicator_calculation") as ind_run:
        instance = XtdcMock.return_value
        instance.connect.return_value = True
        # strategy_indicator_list.json doesn't exist for this synthetic slot,
        # so indicator step short-circuits with a warning rather than running.
        pipeline.run(present_date=datetime(2026, 5, 8))

        data_run.assert_called_once()
        ind_run.assert_not_called()  # no indicator_list → skipped
        instance.disconnect.assert_called_once()


def test_phase0_data_download_failure_does_not_abort_indicators(tmp_path):
    from echolon.live.orchestrator.phase0_pipeline import Phase0DataPipeline

    cfg = _make_config(tmp_path)
    pipeline = Phase0DataPipeline(config=cfg, log=MagicMock())

    with patch("echolon.live.orchestrator.phase0_pipeline.XtdcClient") as XtdcMock, \
         patch("echolon.live.orchestrator.phase0_pipeline.run_live_data_update") as data_run:
        instance = XtdcMock.return_value
        instance.connect.return_value = True
        data_run.side_effect = RuntimeError("timeout")  # one instrument fails

        # Should NOT raise — Step 1 failure for one instrument is logged
        # but indicator step still runs for what's on disk.
        pipeline.run(present_date=datetime(2026, 5, 8))
        instance.disconnect.assert_called_once()
