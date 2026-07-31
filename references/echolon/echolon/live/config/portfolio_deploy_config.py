"""
Portfolio Deploy Configuration
==============================

Configuration management for multi-instrument portfolio trading.
Loads session/portfolio_deploy_config.json and provides typed access
to slot definitions, deploy settings, and account configuration.
"""

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .deploy_config import QMTAccountConfig

logger = logging.getLogger(__name__)


@dataclass
class StrategyStep:
    """A single step in the 'How It Works' strategy description."""
    title: str = ""
    desc: str = ""


@dataclass
class SlotDashboardConfig:
    """Dashboard display metadata for a slot — set once at promotion time."""
    strategy_name: str = ""
    strategy_type: str = ""
    display_market: str = ""
    display_frequency: str = ""
    live_since: str = ""
    backtest_metrics: Dict[str, float] = field(default_factory=dict)
    strategy_steps: List[StrategyStep] = field(default_factory=list)


@dataclass
class SlotConfig:
    """Configuration for a single trading slot."""
    slot_id: str
    strategy_id: str
    cluster: str
    version: str
    instrument: str
    instrument_code: str
    market: str
    frequency: str
    bar_size: str
    initial_capital: float
    strategy_code_dir: str
    trial_params_path: str
    enabled: bool = True
    dashboard: SlotDashboardConfig = field(default_factory=SlotDashboardConfig)


@dataclass
class DeploySettings:
    """Portfolio-level deploy settings.

    `max_total_capital` HAS NO DEFAULT, on purpose, and the reason is two-fold.

    This module ships in a PUBLIC repository. The value that stood here until 2026-07-27
    was a real account figure, which is private business information and does not belong
    in an open-source library — the same rule that keeps tokens and endpoints in the
    private deployment repo. It is supplied by the caller's configuration now.

    Independently of disclosure, a default here would be a misleading fallback on a risk
    control: a deployment that forgot to set its capital limit would silently inherit
    somebody else's number and run against a cap nobody chose. `portfolio_metrics`
    compares total margin against this value and flags a breach, so a wrong default is
    worse than an absent one. Missing now raises at construction, where it is actionable.
    """
    max_total_capital: float
    max_portfolio_drawdown_pct: float = 20.0
    night_market_schedule_hour: int = 20
    night_market_schedule_minute: int = 40
    day_only_schedule_hour: int = 14
    day_only_schedule_minute: int = 55
    misfire_grace_time: int = 3600
    portfolio_backtest_metrics: Dict[str, float] = field(default_factory=dict)
    trading_calendar_path: str = ""


@dataclass
class AccountConfig:
    """Account configuration section from portfolio config.

    Supports trade_account + test_account with a use_test_account toggle.
    """
    trade_account: Optional[QMTAccountConfig] = None
    test_account: Optional[QMTAccountConfig] = None
    use_test_account: bool = False


@dataclass
class PortfolioDeployConfig:
    """Complete portfolio deployment configuration.

    Carries no artifact-store location. An ``output_bank_dir`` field defaulting
    to ``"../output_bank"`` used to sit here; a workspace-wide scan found no
    reader of it in any repo, so it was removed rather than re-pointed (a
    default that names someone else's store is wrong at every value, including
    a renamed one). Host applications that keep the key in their deploy JSON
    parse it themselves and inject the resolved directory into whatever needs
    it — see PathsConfig and error CFG-003 for the injection contract echolon
    holds everywhere else.
    """
    # `deploy` is FIRST and has NO default, so a portfolio config cannot exist without
    # a stated capital cap. A `default_factory=DeploySettings` here would have
    # reintroduced exactly what removing the default was meant to end: a config that
    # loads clean while nobody has chosen the limit its risk checks compare against.
    deploy: DeploySettings
    slots: List[SlotConfig] = field(default_factory=list)
    account: AccountConfig = field(default_factory=AccountConfig)

    @classmethod
    def load(cls, config_path: str) -> 'PortfolioDeployConfig':
        """Load configuration from JSON file."""
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # The deploy section is built BEFORE the config exists, so a JSON missing its
        # capital cap fails here rather than after slots have been parsed.
        config = cls(deploy=DeploySettings(**data.get('deploy', {})))

        # Parse slots
        for slot_data in data.get('slots', []):
            # Extract nested dashboard config before passing to SlotConfig
            dashboard_data = slot_data.pop('dashboard', {})
            steps = [
                StrategyStep(title=s.get('title', ''), desc=s.get('desc', ''))
                for s in dashboard_data.get('strategy_steps', [])
            ]
            dashboard_cfg = SlotDashboardConfig(
                strategy_name=dashboard_data.get('strategy_name', ''),
                strategy_type=dashboard_data.get('strategy_type', ''),
                display_market=dashboard_data.get('display_market', ''),
                display_frequency=dashboard_data.get('display_frequency', ''),
                live_since=dashboard_data.get('live_since', ''),
                backtest_metrics=dashboard_data.get('backtest_metrics', {}),
                strategy_steps=steps,
            )
            config.slots.append(SlotConfig(**slot_data, dashboard=dashboard_cfg))

        # Resolve relative strategy_code_dir / trial_params_path anchored to the
        # config file's directory. Users can then place strategies anywhere on disk
        # and reference them relatively from the config.
        config_dir = Path(config_path).parent.resolve()
        for slot in config.slots:
            if not Path(slot.strategy_code_dir).is_absolute():
                slot.strategy_code_dir = str(config_dir / slot.strategy_code_dir)
            if not Path(slot.trial_params_path).is_absolute():
                slot.trial_params_path = str(config_dir / slot.trial_params_path)

        # Resolve deploy.trading_calendar_path relative to config file's directory if not absolute
        if config.deploy.trading_calendar_path and not os.path.isabs(config.deploy.trading_calendar_path):
            config.deploy.trading_calendar_path = os.path.join(
                os.path.dirname(os.path.abspath(config_path)),
                config.deploy.trading_calendar_path,
            )

        # Parse account
        account_data = data.get('account', {})
        account_cfg = AccountConfig()
        if 'trade_account' in account_data:
            account_cfg.trade_account = QMTAccountConfig(**account_data['trade_account'])
        if 'test_account' in account_data:
            account_cfg.test_account = QMTAccountConfig(**account_data['test_account'])
        account_cfg.use_test_account = account_data.get('use_test_account', False)
        config.account = account_cfg

        logger.info(
            f"Portfolio config loaded: {len(config.slots)} slots, "
            f"{len(config.get_enabled_slots())} enabled"
        )
        return config

    def get_enabled_slots(self) -> List[SlotConfig]:
        """Get only enabled slots."""
        return [s for s in self.slots if s.enabled]

    def get_slots_by_instrument_and_barsize(
        self,
    ) -> Dict[Tuple[str, str], List[SlotConfig]]:
        """Group enabled slots by (instrument_code, bar_size) tuple."""
        groups: Dict[Tuple[str, str], List[SlotConfig]] = defaultdict(list)
        for slot in self.get_enabled_slots():
            key = (slot.instrument_code, slot.bar_size)
            groups[key].append(slot)
        return dict(groups)

    def get_active_account(self) -> QMTAccountConfig:
        """Return QMTAccountConfig based on use_test_account toggle."""
        if self.account.use_test_account:
            if self.account.test_account is None:
                raise ValueError("use_test_account is True but no test_account configured")
            return self.account.test_account
        if self.account.trade_account is None:
            raise ValueError("use_test_account is False but no trade_account configured")
        return self.account.trade_account

    def get_slot(self, slot_id: str) -> Optional[SlotConfig]:
        """Get a specific slot by ID."""
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        return None
