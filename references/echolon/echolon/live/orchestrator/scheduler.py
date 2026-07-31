"""APScheduler-backed daily-job scheduler for portfolio trading.

Extracted from PortfolioTradingRunner in 2026-05-08 R2 refactor.
Owns the BackgroundScheduler instance and the calendar-aware logic
for picking the next trading day's run time. The trading-cycle work
itself stays on the runner — DailyScheduler just decides WHEN to run
and INVOKES a callback the runner registers.
"""
from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from ..config.portfolio_deploy_config import PortfolioDeployConfig, SlotConfig
from echolon.data.loaders.calendar_loader import (
    get_trading_dates, is_trading_day, is_night_market_open,
)


logger = logging.getLogger(__name__)


def ensure_trading_calendars(
    *,
    config: PortfolioDeployConfig,
    market_data_dir: Path,
    log: Any,
) -> None:
    """Generate trading calendar for each unique instrument if missing.

    Module-level helper so callers without a DailyScheduler instance
    (e.g. PortfolioTradingRunner.run_single_cycle and the goingmerry
    test_slot_init_only.py script) can still materialize the calendars
    they need before any is_trading_day() lookup.

    Iterates all unique (market, instrument) pairs from enabled slots
    and asks the SHFE day extractor to materialize each.
    """
    from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor

    seen = set()
    for sc in config.get_enabled_slots():
        key = (sc.market, sc.instrument)
        if key in seen:
            continue
        seen.add(key)

        calendar_dir = market_data_dir / sc.market / sc.instrument
        calendar_file = calendar_dir / "trading_calendar.csv"
        if calendar_file.exists():
            continue

        log.info(f"Trading calendar not found for {sc.instrument} — generating from static source")
        extractor = SHFEApiDayExtractor(market=sc.market, asset=sc.instrument)
        extractor.generate_trading_calendar(
            source_path=config.deploy.trading_calendar_path,
            output_dir=str(calendar_dir),
        )


class DailyScheduler:
    """APScheduler-backed daily-job scheduler.

    Behavioral equivalence with PortfolioTradingRunner pre-refactor:
    - APScheduler config (timezone, job id/name, coalesce, replace_existing,
      misfire_grace_time) identical.
    - Daily-job callback flow: log banner -> is_running guard ->
      ensure_trading_calendars -> is_trading_day check -> skip+reschedule
      OR (set present_date, run inner, reschedule on exception).
    - Heartbeat content + atomic-write semantics identical.
    """

    def __init__(
        self,
        *,
        config: PortfolioDeployConfig,
        slots: List[SlotConfig],
        market_data_dir: Path,
        portfolio_dir: str,
        timezone: Any,
        log: Any,
    ):
        self.config = config
        self.slots = slots
        self.market_data_dir = market_data_dir
        self.portfolio_dir = portfolio_dir
        self.timezone = timezone
        self.log = log

        self._scheduler: Optional[BackgroundScheduler] = None
        # Callbacks set by start(); used by the internal trigger handler.
        self._on_cycle_trigger: Optional[Callable[[], Any]] = None
        self._on_present_date_set: Optional[Callable[[datetime], None]] = None
        self._is_running: Optional[Callable[[], bool]] = None
        self._slot_count: Optional[Callable[[], int]] = None
        self._order_router_tripped: Optional[Callable[[], Any]] = None

    # ---- Lifecycle ----------------------------------------------------------

    def start(
        self,
        *,
        on_cycle_trigger: Callable[[], Any],
        on_present_date_set: Callable[[datetime], None],
        is_running: Callable[[], bool],
        slot_count: Callable[[], int],
        order_router_tripped: Callable[[], Any],
    ) -> None:
        """Build the BackgroundScheduler and schedule the first daily job.

        on_cycle_trigger: invoked when a real trading day fires (the runner's
            _market_open_job_inner).
        on_present_date_set: called with datetime.now() right before the
            cycle trigger (matches pre-refactor behavior of mutating
            runner.present_date in _market_open_job).
        is_running: must return True for the trigger to act (matches
            pre-refactor _market_open_job's `if not self.running: return`).
        slot_count: used in heartbeat output.
        order_router_tripped: used in heartbeat output. Returns bool or None
            (None when no router is constructed yet — heartbeat shows
            "no_router" string in that case).
        """
        self._on_cycle_trigger = on_cycle_trigger
        self._on_present_date_set = on_present_date_set
        self._is_running = is_running
        self._slot_count = slot_count
        self._order_router_tripped = order_router_tripped

        # Use first slot for calendar checks (matches pre-refactor)
        first = self.slots[0] if self.slots else None
        if not first:
            self.log.error("No slots configured")
            return

        # Ensure trading calendars exist before any is_trading_day() call
        self._ensure_trading_calendars()

        today = datetime.now()
        market, instrument = first.market, first.instrument

        target_date = None
        if is_trading_day(
            market, instrument, today, market_data_dir=self.market_data_dir,
        ):
            hour, minute = self._get_schedule_time(today, market, instrument)
            trigger_time = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if today < trigger_time:
                target_date = today

        if target_date is None:
            target_date = self._find_next_trading_day(today, market, instrument)

        if target_date is None:
            self.log.error("No future trading days found")
            return

        hour, minute = self._get_schedule_time(target_date, market, instrument)
        run_date = self.timezone.localize(
            target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        )

        self._scheduler = BackgroundScheduler(timezone=self.timezone)
        self._scheduler.add_job(
            self._market_open_job,
            trigger=DateTrigger(run_date=run_date),
            id="portfolio_daily_job",
            name="PortfolioDailyJob",
            replace_existing=True,
            misfire_grace_time=self.config.deploy.misfire_grace_time,
            coalesce=True,
        )
        self._scheduler.start()
        self.log.info(f"Scheduled: {target_date.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")

    def shutdown(self) -> None:
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
            self._scheduler = None

    # ---- Heartbeat ----------------------------------------------------------

    def write_heartbeat(self) -> None:
        """Write a heartbeat file with current time + next-job time.

        Atomic write via temp+rename so partial reads can't see corrupted
        file. Best-effort: never raises.
        """
        if not self._scheduler:
            return
        try:
            jobs = self._scheduler.get_jobs() if self._scheduler else []
            next_job_run = None
            for j in jobs:
                if j.name == "PortfolioDailyJob" and j.next_run_time is not None:
                    next_job_run = j.next_run_time.isoformat()
                    break

            heartbeat_path = Path(self.portfolio_dir) / "scheduler_heartbeat.txt"
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = heartbeat_path.with_suffix(".txt.tmp")

            running = self._is_running() if self._is_running else False
            slots = self._slot_count() if self._slot_count else 0
            tripped = self._order_router_tripped() if self._order_router_tripped else None
            tripped_str = "no_router" if tripped is None else str(tripped)

            content = (
                f"now={datetime.now(self.timezone).isoformat()}\n"
                f"next_daily_job={next_job_run or 'NONE'}\n"
                f"running={running}\n"
                f"slots={slots}\n"
                f"order_router_tripped={tripped_str}\n"
            )
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, heartbeat_path)
        except Exception:
            # Heartbeat is best-effort; never raise from here.
            pass

    # ---- Internal trigger handler ------------------------------------------

    def _market_open_job(self) -> None:
        """APScheduler callback. Invoked when the scheduled trigger fires."""
        self.log.info("=" * 70)
        self.log.info("PORTFOLIO DAILY JOB TRIGGERED")
        self.log.info("=" * 70)

        if self._is_running is None or not self._is_running():
            return

        self._ensure_trading_calendars()

        first = self.slots[0] if self.slots else None
        if not first:
            return

        if not is_trading_day(
            first.market, first.instrument, datetime.now(),
            market_data_dir=self.market_data_dir,
        ):
            self.log.info("Not a trading day, skipping")
            self._reschedule_next_job()
            return

        if self._on_present_date_set is not None:
            self._on_present_date_set(datetime.now())

        try:
            if self._on_cycle_trigger is not None:
                self._on_cycle_trigger()
        except Exception as e:
            self.log.error(f"Daily cycle failed: {e}\n{traceback.format_exc()}")

        self._reschedule_next_job()

    # ---- Calendar / scheduling helpers (moved from runner) -----------------

    def _ensure_trading_calendars(self) -> None:
        """Generate trading calendar for each unique instrument if missing.

        Thin instance wrapper around the module-level
        `ensure_trading_calendars` helper; tests patch this method to
        skip the SHFE extractor work.
        """
        ensure_trading_calendars(
            config=self.config,
            market_data_dir=self.market_data_dir,
            log=self.log,
        )

    def _get_schedule_time(self, date: datetime, market: str, instrument: str) -> Tuple[int, int]:
        """Determine schedule time based on night market status."""
        try:
            if is_night_market_open(
                market, instrument, date, market_data_dir=self.market_data_dir,
            ):
                return self.config.deploy.night_market_schedule_hour, self.config.deploy.night_market_schedule_minute
            return self.config.deploy.day_only_schedule_hour, self.config.deploy.day_only_schedule_minute
        except Exception as e:
            self.log.warning(
                f"is_night_market_open({market}/{instrument}) failed; defaulting "
                f"to night-market schedule (could fire ~5h late on day-only days): {e}"
            )
            return self.config.deploy.night_market_schedule_hour, self.config.deploy.night_market_schedule_minute

    def _find_next_trading_day(self, after_date: datetime, market: str, instrument: str) -> Optional[datetime]:
        """Find next trading day after given date."""
        start = after_date + timedelta(days=1)
        end = after_date + timedelta(days=30)
        trading_dates = get_trading_dates(
            market, instrument,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            market_data_dir=self.market_data_dir,
        )
        if not trading_dates:
            return None
        first = trading_dates[0]
        if hasattr(first, 'to_pydatetime'):
            first = first.to_pydatetime()
        return first

    def _reschedule_next_job(self) -> None:
        """Schedule next daily job."""
        if not self._scheduler:
            return
        first = self.slots[0] if self.slots else None
        if not first:
            return

        try:
            next_day = self._find_next_trading_day(datetime.now(), first.market, first.instrument)
            if next_day is None:
                self.log.error("No future trading days found")
                return

            hour, minute = self._get_schedule_time(next_day, first.market, first.instrument)
            run_date = self.timezone.localize(
                next_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            )

            self._scheduler.add_job(
                self._market_open_job,
                trigger=DateTrigger(run_date=run_date),
                id="portfolio_daily_job",
                name="PortfolioDailyJob",
                replace_existing=True,
                misfire_grace_time=self.config.deploy.misfire_grace_time,
                coalesce=True,
            )
            self.log.info(f"Rescheduled: {next_day.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")
        except Exception as e:
            self.log.error(f"Rescheduling failed: {e}")
