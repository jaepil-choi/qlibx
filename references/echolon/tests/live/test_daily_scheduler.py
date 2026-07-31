"""Unit tests for DailyScheduler (extracted from PortfolioTradingRunner
in 2026-05-08 R2 refactor)."""
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytz

from echolon.live.config.portfolio_deploy_config import (
    SlotConfig, SlotDashboardConfig, DeploySettings,
)


def _make_config(tmp_path):
    sc = SlotConfig(
        slot_id="al_s1", strategy_id="al_test", cluster="al", version="1.0",
        instrument="aluminum", instrument_code="al", market="SHFE",
        frequency="interday", bar_size="1d", initial_capital=100000.0,
        strategy_code_dir=str(tmp_path / "strategy"), trial_params_path="",
        enabled=True, dashboard=SlotDashboardConfig(),
    )
    from echolon.live.config.portfolio_deploy_config import (
        PortfolioDeployConfig, AccountConfig,
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


def test_daily_scheduler_invokes_cycle_callback_on_trading_day(tmp_path):
    """When the scheduled job fires on a trading day, the on_cycle_trigger
    callback runs and on_present_date_set is invoked first."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )

    # Inject a no-op _ensure_trading_calendars to avoid SHFE extractor work.
    sched._ensure_trading_calendars = lambda: None

    cycle_calls = []
    present_dates = []

    with patch("echolon.live.orchestrator.scheduler.is_trading_day", return_value=True), \
         patch.object(sched, "_reschedule_next_job"):
        # Wire up callbacks
        sched._on_cycle_trigger = lambda: cycle_calls.append(True)
        sched._on_present_date_set = lambda dt: present_dates.append(dt)
        sched._is_running = lambda: True

        # Directly invoke the internal handler — bypasses APScheduler timing.
        sched._market_open_job()

    assert len(cycle_calls) == 1
    assert len(present_dates) == 1
    assert isinstance(present_dates[0], datetime)


def test_daily_scheduler_skips_callback_on_non_trading_day(tmp_path):
    """When the scheduled job fires on a non-trading day, the on_cycle_trigger
    is NOT invoked but reschedule still runs."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )
    sched._ensure_trading_calendars = lambda: None

    cycle_calls = []

    with patch("echolon.live.orchestrator.scheduler.is_trading_day", return_value=False), \
         patch.object(sched, "_reschedule_next_job") as mock_reschedule:
        sched._on_cycle_trigger = lambda: cycle_calls.append(True)
        sched._on_present_date_set = lambda dt: None
        sched._is_running = lambda: True

        sched._market_open_job()

    assert len(cycle_calls) == 0
    mock_reschedule.assert_called_once()


def test_daily_scheduler_writes_heartbeat_with_expected_fields(tmp_path):
    """write_heartbeat writes the canonical 5-field content to
    portfolio_dir/scheduler_heartbeat.txt."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    portfolio_dir = tmp_path / "portfolio"
    portfolio_dir.mkdir()
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(portfolio_dir),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )

    # Stub the scheduler — just need get_jobs() to return [].
    sched._scheduler = MagicMock()
    sched._scheduler.get_jobs.return_value = []
    sched._is_running = lambda: True
    sched._slot_count = lambda: 3
    sched._order_router_tripped = lambda: False

    sched.write_heartbeat()

    heartbeat = portfolio_dir / "scheduler_heartbeat.txt"
    assert heartbeat.exists()
    content = heartbeat.read_text(encoding="utf-8")
    assert "now=" in content
    assert "next_daily_job=NONE" in content
    assert "running=True" in content
    assert "slots=3" in content
    assert "order_router_tripped=False" in content


def test_daily_scheduler_skips_when_runner_not_running(tmp_path):
    """Shutdown-race guard: when the trigger fires after runner.running
    has been set False, _market_open_job MUST return without invoking
    the cycle callback or the reschedule path."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )
    sched._ensure_trading_calendars = lambda: None

    cycle_calls = []

    with patch("echolon.live.orchestrator.scheduler.is_trading_day", return_value=True), \
         patch.object(sched, "_reschedule_next_job") as mock_reschedule:
        sched._on_cycle_trigger = lambda: cycle_calls.append(True)
        sched._on_present_date_set = lambda dt: None
        sched._is_running = lambda: False  # simulate shutdown in progress

        sched._market_open_job()

    # Cycle MUST NOT fire when not running.
    assert len(cycle_calls) == 0
    # Reschedule MUST NOT fire either — the runner is shutting down,
    # so re-arming the scheduler is wrong.
    mock_reschedule.assert_not_called()


def test_schedule_time_warns_on_calendar_failure(tmp_path):
    """P1.4 regression: silent fallback to night-market is gone — when
    is_night_market_open raises, _get_schedule_time logs a warning and
    still returns night-market schedule (preserves existing fallback
    behavior, just adds visibility)."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    log = MagicMock()
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=log,
    )

    with patch(
        "echolon.live.orchestrator.scheduler.is_night_market_open",
        side_effect=RuntimeError("calendar corrupt"),
    ):
        hour, minute = sched._get_schedule_time(
            datetime(2026, 5, 11), sc.market, sc.instrument,
        )

    # Falls back to night-market schedule (preserves original behavior)
    assert hour == cfg.deploy.night_market_schedule_hour
    assert minute == cfg.deploy.night_market_schedule_minute
    # AND logs a warning so the operator can diagnose
    warning_messages = [c.args[0] for c in log.warning.call_args_list]
    assert any("is_night_market_open" in m and "default" in m for m in warning_messages)


def test_scheduler_stays_none_when_no_slots(tmp_path):
    """P1.5 regression: when start() early-returns due to no slots,
    self._scheduler must remain None so write_heartbeat correctly
    reports the un-started state instead of writing next_daily_job=NONE
    indistinguishable from normal."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, _ = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[],  # no slots
        market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )
    sched._ensure_trading_calendars = lambda: None

    sched.start(
        on_cycle_trigger=lambda: None,
        on_present_date_set=lambda dt: None,
        is_running=lambda: True,
        slot_count=lambda: 0,
        order_router_tripped=lambda: None,
    )

    assert sched._scheduler is None
