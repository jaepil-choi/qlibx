"""Scheduler time-selection — picks night-market 20:30 vs day-only 14:45 correctly.

Plus tests for PortfolioTradingRunner._central_wait_if_night_market behavior.
"""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz

from echolon.live.config.portfolio_deploy_config import (
    PortfolioDeployConfig, SlotConfig, SlotDashboardConfig, DeploySettings, AccountConfig,
)


def _make_cfg_and_slot(tmp_path):
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
        max_total_capital=1000.0,
        trading_calendar_path=str(tmp_path / "cal.csv"),
        night_market_schedule_hour=20, night_market_schedule_minute=30,
        day_only_schedule_hour=14, day_only_schedule_minute=45,
        misfire_grace_time=3600,
    )
    cfg.account = AccountConfig()
    return cfg, sc


def test_schedule_time_picks_night_for_night_market_day(tmp_path):
    """When is_night_market_open returns True, schedule = (20, 30)."""
    from echolon.live.orchestrator.scheduler import DailyScheduler
    cfg, sc = _make_cfg_and_slot(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"), log=MagicMock(),
    )
    with patch("echolon.live.orchestrator.scheduler.is_night_market_open", return_value=True):
        hour, minute = sched._get_schedule_time(datetime(2026, 5, 11), sc.market, sc.instrument)
    assert (hour, minute) == (20, 30)


def test_schedule_time_picks_day_for_day_only_day(tmp_path):
    """When is_night_market_open returns False, schedule = (14, 45)."""
    from echolon.live.orchestrator.scheduler import DailyScheduler
    cfg, sc = _make_cfg_and_slot(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"), log=MagicMock(),
    )
    with patch("echolon.live.orchestrator.scheduler.is_night_market_open", return_value=False):
        hour, minute = sched._get_schedule_time(datetime(2026, 5, 11), sc.market, sc.instrument)
    assert (hour, minute) == (14, 45)


def test_schedule_time_falls_back_to_night_on_exception(tmp_path):
    """When is_night_market_open raises, default to night-market schedule
    and log a warning."""
    from echolon.live.orchestrator.scheduler import DailyScheduler
    cfg, sc = _make_cfg_and_slot(tmp_path)
    log = MagicMock()
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"), log=log,
    )
    with patch("echolon.live.orchestrator.scheduler.is_night_market_open",
               side_effect=RuntimeError("calendar boom")):
        hour, minute = sched._get_schedule_time(datetime(2026, 5, 11), sc.market, sc.instrument)
    # Falls back to night-market hours.
    assert (hour, minute) == (20, 30)
    # And a warning is emitted to alert the operator.
    assert log.warning.called


def test_central_wait_returns_quickly_for_day_only(tmp_path):
    """Day-only days: _central_wait_if_night_market returns within ~3s
    (just sleep(2) settlement wait)."""
    from echolon.live.orchestrator.portfolio import PortfolioTradingRunner
    runner = PortfolioTradingRunner.__new__(PortfolioTradingRunner)
    runner.log = MagicMock()
    runner.slots = [MagicMock(slot_config=MagicMock(market="SHFE", instrument="aluminum"))]
    runner.present_date = datetime(2026, 5, 8)
    runner.TIMEZONE = pytz.timezone("Asia/Shanghai")
    runner._market_data_dir = tmp_path / "md"

    with patch("echolon.live.orchestrator.portfolio.is_night_market_open", return_value=False):
        t0 = time.monotonic()
        runner._central_wait_if_night_market()
        elapsed = time.monotonic() - t0

    # Day-only path is `time.sleep(2)`; allow generous slack for slow CI.
    assert elapsed < 4.0, f"day-only path took {elapsed:.2f}s; expected < 4s"


def test_central_wait_returns_quickly_when_no_slots(tmp_path):
    """If slots is empty, _central_wait_if_night_market returns immediately
    (the function early-returns when no slot is available)."""
    from echolon.live.orchestrator.portfolio import PortfolioTradingRunner
    runner = PortfolioTradingRunner.__new__(PortfolioTradingRunner)
    runner.log = MagicMock()
    runner.slots = []
    runner.present_date = datetime(2026, 5, 8)
    runner.TIMEZONE = pytz.timezone("Asia/Shanghai")
    runner._market_data_dir = tmp_path / "md"

    t0 = time.monotonic()
    runner._central_wait_if_night_market()
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5  # no work to do — must return immediately


def test_central_wait_skips_when_already_past_target(tmp_path):
    """Night-market day but the timezone-aware 'now' is already past
    21:00:01 — should log 'Night market already open' and return quickly.

    We patch ``datetime`` inside the portfolio module so ``datetime.now(TZ)``
    returns a time past target, while leaving non-now access intact.
    """
    from echolon.live.orchestrator.portfolio import PortfolioTradingRunner
    runner = PortfolioTradingRunner.__new__(PortfolioTradingRunner)
    runner.log = MagicMock()
    runner.slots = [MagicMock(slot_config=MagicMock(market="SHFE", instrument="aluminum"))]
    runner.present_date = datetime(2026, 5, 8)
    runner.TIMEZONE = pytz.timezone("Asia/Shanghai")
    runner._market_data_dir = tmp_path / "md"

    fake_now = pytz.timezone("Asia/Shanghai").localize(datetime(2026, 5, 8, 22, 0, 0))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fake_now

    with patch("echolon.live.orchestrator.portfolio.is_night_market_open", return_value=True), \
         patch("echolon.live.orchestrator.portfolio.datetime", FakeDatetime):
        t0 = time.monotonic()
        runner._central_wait_if_night_market()
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0
    # The "already open" log message should have been emitted.
    log_calls = [str(c) for c in runner.log.info.call_args_list]
    assert any("already open" in c.lower() for c in log_calls), \
        f"expected 'already open' log; got {log_calls!r}"
