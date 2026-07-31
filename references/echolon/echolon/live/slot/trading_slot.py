"""
Trading Slot
============

Per-instrument/strategy wrapper that encapsulates everything needed to
run one strategy in the multi-slot portfolio.

Lifecycle per daily cycle:
1. initialize(present_date) — build engine, load data, restore state
2. execute_bar()           — mark-to-market then strategy.on_bar()
3. save_state()            — atomic persist (strategy + VP + capital)
4. reset_daily_state()     — clear per-day flags for next cycle
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from echolon.config.markets.factory import MarketFactory
from echolon.config.markets.core.context import TradingContext
from echolon.engine.factory import EngineFactory
from echolon.strategy.hooks.forced_exit_strategy_hook import ForcedExitStrategyHook
from echolon.strategy.interfaces import Order, OrderStatus
from ..config.portfolio_deploy_config import SlotConfig
from echolon.data.loaders.contract_loader import get_main_contract
from .capital_slot import CapitalSlot
from .slot_aware_portfolio import SlotAwarePortfolio

logger = logging.getLogger(__name__)


def _load_state_file(path: str) -> Dict[str, Any]:
    """Load strategy_state.json.

    Returns ``{}`` when the file does NOT exist (cold start is valid).
    Raises DAT-002 if the file exists but contains corrupt JSON.
    """
    from echolon.errors import raise_error

    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise_error("DAT-002", path=path, error=str(exc))


class TradingSlot:
    """
    Per-slot wrapper for one instrument/strategy combination.

    Holds: SlotConfig, TradingContext, QMTEngine (deferred), CapitalSlot,
    SlotAwarePortfolio, strategy instance, and state file path.
    """

    def __init__(self, slot_config: SlotConfig, deploy_data_dir: str):
        self.slot_config = slot_config
        self.deploy_data_dir = deploy_data_dir

        # Populated during initialize()
        self.ctx: Optional[TradingContext] = None
        self.engine = None
        self.strategy = None
        self.capital_slot: Optional[CapitalSlot] = None
        self.portfolio: Optional[SlotAwarePortfolio] = None
        self.trading_contract: Optional[str] = None

        # State
        self._state_path: Optional[str] = None
        self.is_errored: bool = False
        self.error_message: str = ""
        self.todays_processed_fills: List[Dict[str, Any]] = []

    @property
    def slot_id(self) -> str:
        return self.slot_config.slot_id

    # =========================================================================
    # Initialize
    # =========================================================================

    def initialize(self, present_date: datetime, calendar_path: Optional[str] = None) -> None:
        """
        Full initialization for a trading day.

        Steps:
        1. Create TradingContext from SlotConfig
        2. Create QMTEngine via EngineFactory (orders are recorded by the engine and burst-fired by the portfolio runner)
        3. Resolve main contract, set_trading_contract
        4. Load indicators, set_current_bar(today)
        5. Validate required indicators exist
        6. Load state file (handle cold start)
        7. Create CapitalSlot, SlotAwarePortfolio, restore VP
        8. Replace engine._portfolio with SlotAwarePortfolio
        9. Dynamic import strategy from strategy_code_dir
        10. Add ForcedExitStrategyHook
        11. strategy.on_start(), strategy.restore_state()
        """
        sc = self.slot_config
        slot_id = sc.slot_id

        # Step 1: Create TradingContext
        self.ctx = MarketFactory.create(
            market=sc.market,
            instrument=sc.instrument_code,
            frequency=sc.frequency,
            bar_size=sc.bar_size,
        )
        logger.info(f"[{slot_id}] TradingContext created: {sc.market}/{sc.instrument_code}/{sc.bar_size}")

        # Step 2: Create QMTEngine (deferred)
        self.engine = EngineFactory.create_deploy_engine(
            ctx=self.ctx,
            calendar_path=calendar_path,
            client=None,  # Client set later by runner
            platform="miniqmt",
            slot_id=slot_id,
        )
        logger.info(f"[{slot_id}] QMTEngine created (deferred execution)")

        # Step 3: Resolve main contract
        from echolon.config.paths_config import PathsConfig
        self.trading_contract = get_main_contract(
            present_date,
            symbol=sc.instrument_code,
            market_data_dir=PathsConfig.from_env().market_data_dir,
        )
        self.engine.set_trading_contract(self.trading_contract)
        logger.info(f"[{slot_id}] Main contract: {self.trading_contract}")

        # Step 4: Load indicators
        indicators_path = self._get_indicators_path()
        self.engine.load_data(indicators_path)
        market_data = self.engine.get_market_data()
        today_dt = datetime.combine(present_date.date(), datetime.min.time())
        market_data.set_current_bar(today_dt)
        logger.info(f"[{slot_id}] Indicators loaded, bar set to {today_dt.date()}")

        # Step 5: Validate required indicators
        self._validate_indicators()

        # Step 6: Load state
        self._state_path = os.path.join(
            self.deploy_data_dir, slot_id, "strategy_state.json"
        )
        state_data = self._load_state_file()

        # Step 6.5: If position exists on a different contract than today's
        # main contract, override the trading contract to the position's
        # contract so exit orders go to the correct contract.
        position_symbol = state_data.get('position_symbol', '')
        position_size = state_data.get('position_size', 0)
        if position_symbol and position_size != 0 and position_symbol != self.trading_contract:
            logger.warning(
                f"[{slot_id}] Contract mismatch: position on {position_symbol} "
                f"but main contract is {self.trading_contract}. "
                f"Overriding trading contract to {position_symbol} for exit."
            )
            self.trading_contract = position_symbol
            self.engine.set_trading_contract(position_symbol)

        # Step 7: Create CapitalSlot and SlotAwarePortfolio
        capital_data = state_data.get('custom', {}).get('capital', None)
        if capital_data:
            self.capital_slot = CapitalSlot.from_dict(capital_data)
        else:
            self.capital_slot = CapitalSlot(
                slot_id=slot_id,
                initial_capital=sc.initial_capital,
            )

        self.portfolio = SlotAwarePortfolio(
            market_data=market_data,
            capital_slot=self.capital_slot,
            multiplier=int(self.ctx.multiplier),
            margin_rate=self.ctx.margin_rate,
        )
        self.portfolio.restore_state(state_data)

        # Step 8: Replace engine portfolio (and order manager's reference)
        self.engine._portfolio = self.portfolio
        self.engine._order_manager._portfolio = self.portfolio
        logger.info(f"[{slot_id}] Portfolio replaced with SlotAwarePortfolio")

        # Step 9: Dynamic import strategy
        strategy_params = self._load_and_map_trial_params()
        self._import_and_create_strategy(strategy_params)

        # Step 10: Add ForcedExitStrategyHook
        hook = ForcedExitStrategyHook(
            market_adapter=self.engine.get_market_adapter()
        )
        self.strategy.add_hook(hook)

        # Step 11: Start and restore
        self.strategy.on_start()
        self.strategy.restore_state(self._state_path)

        logger.info(f"[{slot_id}] Initialization complete")

    # =========================================================================
    # Execute
    # =========================================================================

    def execute_bar(self) -> None:
        """Execute one bar: mark-to-market, recover any pending EXIT, then on_bar.

        If the slot has an unresolved EXIT-class order from a prior cycle
        (Amendment B — ABANDONED-EXIT recovery), re-fire the exit BEFORE
        the strategy gets to derive new signals. This prevents a trapped
        position from accumulating new entries.
        """
        current_price = self.engine.get_market_data().get_current_price()
        self.portfolio.update_mark_to_market(current_price)

        if self._has_pending_exit_intent():
            self._resume_pending_exit()
            return

        self.strategy.on_bar()

    def _has_pending_exit_intent(self) -> bool:
        if self._state_path is None:
            return False
        from echolon.strategy.state_manager import StateManager
        sm = StateManager(state_path=self._state_path)
        sm.load_state()
        return sm.get_pending_exit_intent() is not None

    def _resume_pending_exit(self) -> None:
        """Re-fire an unresolved EXIT from a prior cycle.

        Cycle 2: standard EXIT recovery via order manager.
        Cycle 3+: kill at band edge (Amendment B).

        When cycles_pending >= 2, also writes/refreshes a structured
        operator alert to ``workspace/deploy/portfolio/pending_exit_alerts.json``
        so the dashboard / portal banner surfaces the trapped EXIT.
        """
        from echolon.strategy.state_manager import StateManager
        sm = StateManager(state_path=self._state_path)
        sm.load_state()
        pending = sm.get_pending_exit_intent()
        if pending is None:
            return

        pending.cycles_pending += 1
        pending.last_attempt_time = datetime.now().isoformat()
        sm.set_pending_exit_intent(pending)
        sm.save_state()

        slot_id = self.slot_id
        logger.warning(
            f"[{slot_id}] Resuming pending EXIT: intent={pending.intent} "
            f"remaining={pending.remaining_size} cycles_pending={pending.cycles_pending}"
        )

        # Amendment B operator alert — write/upsert pending_exit_alerts.json
        if pending.cycles_pending >= 2:
            try:
                self._write_pending_exit_alert(pending)
            except Exception as exc:
                logger.error(f"[{slot_id}] pending_exit_alerts write failed: {exc}")

        order_manager = self.engine.get_order_manager()

        if pending.cycles_pending >= 3:
            from echolon.live.platforms.miniqmt.order_router import (  # noqa: E402
                kill_at_band_edge_price,
            )
            client = getattr(self.engine, "_client", None) or getattr(self.engine, "client", None)
            kill_price = kill_at_band_edge_price(
                self.trading_contract, pending.intent, client=client,
            )
            logger.critical(
                f"[{slot_id}] KILL-AT-BAND-EDGE: intent={pending.intent} "
                f"price={kill_price:.2f} remaining={pending.remaining_size}"
            )
            order_manager.submit_exit_order(
                size=pending.remaining_size,
                price=kill_price,
            )
        else:
            order_manager.submit_exit_order(
                size=pending.remaining_size,
                price=None,
            )

    def _write_pending_exit_alert(self, pending) -> None:
        """Upsert this slot's entry in workspace/deploy/portfolio/pending_exit_alerts.json.

        Each call replaces the slot's row (matched by slot_id) with the
        current pending state. The dashboard reader picks this file up.
        """
        slot_id = self.slot_id
        # workspace/deploy/slots/{slot_id}/strategy_state.json
        # → workspace/deploy/portfolio/pending_exit_alerts.json
        slot_dir = Path(self._state_path).parent
        portfolio_dir = slot_dir.parent.parent / "portfolio"
        portfolio_dir.mkdir(parents=True, exist_ok=True)
        alert_path = portfolio_dir / "pending_exit_alerts.json"

        existing: List[Dict[str, Any]] = []
        if alert_path.exists():
            try:
                with open(alert_path, "r") as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except (OSError, json.JSONDecodeError):
                existing = []

        # Upsert by slot_id.
        existing = [a for a in existing if a.get("slot_id") != slot_id]
        existing.append({
            "slot_id": slot_id,
            "intent": pending.intent,
            "remaining_size": pending.remaining_size,
            "cycles_pending": pending.cycles_pending,
            "original_decision_time": pending.original_decision_time,
            "last_attempt_time": pending.last_attempt_time,
        })

        tmp_path = alert_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp_path, alert_path)

    # =========================================================================
    # Pending orders
    # =========================================================================

    def get_pending_orders(self) -> List[Order]:
        """Get all pending/deferred orders from this slot's order manager."""
        return self.engine.get_order_manager().get_pending_orders()

    # =========================================================================
    # State persistence
    # =========================================================================

    def save_state(self) -> None:
        """Atomic save: strategy state + VP + capital in one JSON."""
        if self._state_path is None:
            return

        # Save strategy state first
        self.strategy.save_state(self._state_path)

        # Now load, augment with VP + capital, re-save
        with open(self._state_path, 'r') as f:
            state_data = json.load(f)

        # Sync bars_in_position from exit rule component (authoritative source),
        # but only if there's an active position.
        has_position = self.portfolio and self.portfolio.get_position() and self.portfolio.get_position().size > 0
        if has_position:
            components = state_data.get('custom', {}).get('components', {})
            exit_state = components.get('exit_rule', {})
            if 'bars_in_position' in exit_state:
                state_data['bars_in_position'] = exit_state['bars_in_position']
        else:
            # No position — ensure top-level is 0 and reset exit component
            # if it still has stale per-trade state (e.g., should_exit was
            # never called this cycle because strategy skipped exit eval).
            state_data['bars_in_position'] = 0
            if self.strategy and hasattr(self.strategy, 'exit_rule'):
                self.strategy.exit_rule._reset_state()
                # Re-serialize reset state into state_data. strategy.save_state()
                # already wrote the stale version before _reset_state() was called.
                if 'custom' in state_data and 'components' in state_data['custom']:
                    state_data['custom']['components']['exit_rule'] = (
                        self.strategy.exit_rule.get_state()
                    )

        # Sync daily_pnl and last_trading_date
        state_data['daily_pnl'] = (
            self.capital_slot.realized_pnl + self.portfolio.get_unrealized_pnl()
        )
        state_data['last_trading_date'] = datetime.now().date().isoformat()

        # Merge VP state
        vp_state = self.portfolio.save_state()
        state_data.update(vp_state)

        # Merge capital into custom
        if 'custom' not in state_data:
            state_data['custom'] = {}
        state_data['custom']['capital'] = self.capital_slot.save_dict()

        # Atomic write
        tmp_path = self._state_path + '.tmp'
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        with open(tmp_path, 'w') as f:
            json.dump(state_data, f, indent=2, default=str)
        os.replace(tmp_path, self._state_path)

        logger.info(f"[{self.slot_id}] State saved")

    # =========================================================================
    # Fill notification (called by PortfolioTradingRunner after async fill)
    # =========================================================================

    def notify_fill(self, symbol: str, side: str, size: float,
                    price: float, bar_count: int) -> None:
        """Update top-level StrategyState fields after an async fill.

        The state manager fields (position_entry_datetime, bars_in_position,
        daily_trades_count, last_trade_bar) are not updated by the strategy's
        on_bar() flow. This method bridges the gap so save_state() persists
        accurate data.
        """
        if self._state_path is None:
            return
        from echolon.strategy.state_manager import StateManager
        sm = StateManager(state_path=self._state_path)
        sm.load_state()

        if side in ("LONG", "SHORT"):
            # Entry fill
            sm.update_position(symbol, size, side, price, datetime.now())
        elif side == "FLAT":
            # Exit fill
            sm.clear_position()
            # Reset exit rule component so stale stop/TP/bars don't persist
            if self.strategy and hasattr(self.strategy, 'exit_rule'):
                self.strategy.exit_rule._reset_state()

        sm.update_daily_stats()
        state = sm.get_state()
        state.last_trade_bar = bar_count
        sm.save_state()

    # =========================================================================
    # Daily reset
    # =========================================================================

    def reset_daily_state(self) -> None:
        """Clear per-day flags for next cycle."""
        self.is_errored = False
        self.error_message = ""
        self.todays_processed_fills.clear()

    def mark_error(self, msg: str) -> None:
        """Mark this slot as errored for the current cycle."""
        self.is_errored = True
        self.error_message = msg
        logger.error(f"[{self.slot_id}] SLOT ERROR: {msg}")

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_indicators_path(self) -> str:
        """Get path to the strategy indicators CSV.

        Portfolio mode writes the merged-per-group output to
        ``{indicators_backtest_dir}/{instrument_code}_{bar_size}/`` (one
        compute per (instrument, bar_size) group, shared by every slot in
        that group). The slot reads from there.
        """
        from echolon.config.paths_config import PathsConfig
        indicators_backtest_dir = str(
            PathsConfig.from_env().indicators_backtest_dir
        )
        sc = self.slot_config
        return os.path.join(
            indicators_backtest_dir,
            f"{sc.instrument_code}_{sc.bar_size}",
            "strategy_indicators.csv",
        )

    def _validate_indicators(self) -> None:
        """Validate that required indicators exist in the CSV.

        Reads flat-dict ``strategy_indicator_list.json``
        (``{name: {param: v}}``).
        """
        indicator_list_path = os.path.join(
            self.slot_config.strategy_code_dir, "strategy_indicator_list.json"
        )
        if not os.path.exists(indicator_list_path):
            logger.warning(f"[{self.slot_id}] No indicator list file, skipping validation")
            return

        with open(indicator_list_path, 'r') as f:
            indicator_list = json.load(f)

        indicator_names = _collect_declared_names(indicator_list)

        if not indicator_names:
            logger.warning(f"[{self.slot_id}] No indicator names found in config, skipping validation")
            return

        # Check that each indicator has at least one matching column.
        # Indicators with lookback produce columns like "aroonosc_15",
        # "aroonosc_16" etc., so we check for prefix match, not exact.
        market_data = self.engine.get_market_data()
        columns = [c.lower() for c in market_data._df.columns] if market_data._df is not None else []
        missing = []
        for name in sorted(indicator_names):
            # Exact match OR prefix match (e.g. "atr" matches "atr_10")
            found = any(c == name or c.startswith(name + "_") for c in columns)
            if not found:
                missing.append(name)

        if missing:
            logger.warning(f"[{self.slot_id}] Missing indicators in CSV: {missing}")

    def _load_state_file(self) -> Dict[str, Any]:
        """Load state file, return empty dict for cold start.

        Delegates to the module-level ``_load_state_file`` which raises
        DAT-002 on corrupt JSON and returns ``{}`` only when the file
        does not exist.
        """
        if not self._state_path:
            return {}
        return _load_state_file(self._state_path)

    def _load_and_map_trial_params(self) -> Dict[str, Any]:
        """Load trial params and map to strategy structure."""
        trial_path = self.slot_config.trial_params_path
        if not trial_path or not os.path.exists(trial_path):
            logger.info(f"[{self.slot_id}] No trial params, using defaults")
            return {}

        with open(trial_path, 'r') as f:
            config_data = json.load(f)

        trial_params = config_data.get('params', {})
        if not trial_params:
            return {}

        # Load DEFAULT_PARAMS from the slot's strategy code via StrategyLoader
        strategy_code_dir = self.slot_config.strategy_code_dir
        from echolon.strategy.loader import StrategyLoader
        loader = StrategyLoader(Path(strategy_code_dir))
        if loader.has_module("strategy_params"):
            default_params = loader.load_attr("strategy_params", "DEFAULT_PARAMS")
        else:
            default_params = {}

        # Start from defaults
        strategy_params = {}
        for key, value in default_params.items():
            strategy_params[key] = value.copy() if isinstance(value, dict) else value

        # Map prefixed trial params to component dicts
        prefix_map = {
            "entry_": "entry_params",
            "exit_": "exit_params",
            "risk_": "risk_params",
            "sizer_": "sizer_params",
            "size_": "sizer_params",
        }

        for param_name, param_value in trial_params.items():
            mapped = False
            for prefix, component_key in prefix_map.items():
                if param_name.startswith(prefix):
                    local_name = param_name[len(prefix):]
                    if component_key in strategy_params:
                        strategy_params[component_key][local_name] = param_value
                        mapped = True
                        break
            if not mapped and param_name in strategy_params:
                strategy_params[param_name] = param_value

        return strategy_params

    def _import_and_create_strategy(self, strategy_params: Dict[str, Any]) -> None:
        """Dynamically import strategy from strategy_code_dir."""
        from echolon.strategy.loader import StrategyLoader

        strategy_code_dir = self.slot_config.strategy_code_dir
        loader = StrategyLoader(Path(strategy_code_dir))
        strategy_main = loader.load_function("strategy", "strategy_main")

        # Build indicator column list from loaded market data
        indicator_columns = None
        md = self.engine.get_market_data()
        if hasattr(md, '_df') and md._df is not None:
            skip = {'datetime', 'date', 'trading_date', 'open', 'high', 'low',
                    'close', 'volume', 'contract', 'contract_expiry'}
            indicator_columns = [c for c in md._df.columns if c not in skip]

        self.strategy = strategy_main(
            trading_engine=self.engine,
            strategy_dir=str(strategy_code_dir),
            slot_id=self.slot_config.slot_id,
            strategy_id=self.slot_config.strategy_id,
            indicator_columns=indicator_columns,
            **strategy_params,
        )
        logger.info(f"[{self.slot_id}] Strategy created from {strategy_code_dir}")

    # ---- Pending-exit-intent (Amendment B; moved from PortfolioTradingRunner) ----
    #
    # These methods raise on StateManager errors. The runner-side caller
    # (PortfolioTradingRunner._set/_clear/_update_pending_exit_intent)
    # wraps each call in try/except and logs via self.log to preserve the
    # `deploy.portfolio_runner` log namespace from the pre-refactor code.

    def set_pending_exit_intent(self, intent: str, original_size: int) -> None:
        """Record an EXIT-class submission so the next cycle can recover.

        No-op if ``_state_path`` is not yet initialized (slot uninitialized).
        Idempotent: re-recording the same intent updates last_attempt_time
        without resetting the cycle counter.
        """
        if not self._state_path:
            return
        from echolon.strategy.state_manager import StateManager, PendingExitIntent
        sm = StateManager(state_path=self._state_path)
        sm.load_state()
        now = datetime.now().isoformat()
        existing = sm.get_pending_exit_intent()
        if existing is not None and existing.intent == intent:
            existing.last_attempt_time = now
            sm.set_pending_exit_intent(existing)
        else:
            sm.set_pending_exit_intent(PendingExitIntent(
                intent=intent,
                original_size=int(original_size),
                remaining_size=int(original_size),
                attempts_so_far=0,
                original_decision_time=now,
                last_attempt_time=now,
                cycles_pending=1,
            ))
        sm.save_state()

    def clear_pending_exit_intent(self) -> None:
        """Clear pending exit (called when chain is fully filled)."""
        if not self._state_path:
            return
        from echolon.strategy.state_manager import StateManager
        sm = StateManager(state_path=self._state_path)
        sm.load_state()
        sm.clear_pending_exit_intent()
        sm.save_state()

    def update_pending_exit_remaining(self, remaining: int) -> None:
        """Update the remaining_size on the pending exit intent (called when
        chain partially filled — bumps attempts_so_far)."""
        if not self._state_path:
            return
        from echolon.strategy.state_manager import StateManager
        sm = StateManager(state_path=self._state_path)
        sm.load_state()
        pending = sm.get_pending_exit_intent()
        if pending is None:
            return
        pending.remaining_size = max(0, int(remaining))
        pending.attempts_so_far += 1
        pending.last_attempt_time = datetime.now().isoformat()
        sm.set_pending_exit_intent(pending)
        sm.save_state()

    def build_snapshot_data(self) -> Dict[str, Any]:
        """Build a structured snapshot of this slot's runtime state.

        Used by Phase 5 of the daily cycle to feed
        ``io.data_logger.save_trading_data_snapshot``. Pure transformation
        of slot-owned attributes into the snapshot dict shape.

        Hardened past pre-refactor behavior (followup F4):
        - Inner try/except around market_data extraction; falls back to
          zero defaults with a warning log so the snapshot row is preserved
          even when get_market_data raises.
        - Signal-extraction uses isinstance(cbd, dict) instead of the
          original hasattr+.get pattern; safely skips when current_bar_data
          is None instead of raising AttributeError.
        - get_unrealized_pnl + capital_slot fields short-circuit to 0.0
          when the underlying object is None.

        Returns:
            Dict with keys: market_data, signal_data, position_data,
            account_data, performance_data, symbol, action_contract,
            position_contract, position_direction, last_trade_action.
        """
        sc = self.slot_config

        try:
            md = self.engine.get_market_data()
            market_data = {
                "current_price": md.get_current_price(),
                "daily_open": md.get_open(),
                "daily_high": md.get_high(),
                "daily_low": md.get_low(),
                "volume": md.get_volume(),
            }
        except Exception as exc:
            logger.warning(
                f"[{self.slot_id}] snapshot market_data extraction failed; "
                f"using zero defaults so the snapshot row is preserved: {exc}"
            )
            market_data = {
                "current_price": 0.0, "daily_open": 0.0,
                "daily_high": 0.0, "daily_low": 0.0, "volume": 0,
            }

        # Signal extraction from strategy logger — match original's
        # hasattr + .get pattern (do NOT replace with isinstance check).
        sig_type = None
        sig_strength = 0.0
        sig_reason = None
        strat_logger = getattr(self.strategy, "strategy_logger", None) if self.strategy else None
        cbd = getattr(strat_logger, "current_bar_data", None) if strat_logger else None
        if isinstance(cbd, dict):
            if cbd.get("exit_should_exit"):
                sig_type = "EXIT"
                sig_strength = 1.0
                sig_reason = cbd.get("exit_reason", "")
            else:
                sig_type = cbd.get("entry_signal")
                sig_strength = cbd.get("entry_strength", 0.0)
                sig_reason = cbd.get("entry_reason")

        position = self.portfolio.get_position()

        # Last trade action from today's fills
        last_action = "NO_ACTION"
        last_action_price = 0.0
        last_action_size = 0
        if self.todays_processed_fills:
            last_fill = self.todays_processed_fills[-1]
            last_action = last_fill.get("intent", "NO_ACTION")
            last_action_price = last_fill.get("price", 0.0)
            last_action_size = last_fill.get("volume", 0)

        return {
            "market_data": market_data,
            "signal_data": {
                "signal_type": sig_type,
                "signal_strength": sig_strength,
                "signal_confidence": 0.0,
                "signal_reason": sig_reason,
            },
            "position_data": {
                "current_position_size": int(position.size) if position else 0,
                "current_position_avg_price": position.avg_price if position else None,
                "unrealized_pnl": self.portfolio.get_unrealized_pnl() if position else 0.0,
            },
            "account_data": {
                "available_cash": self.capital_slot.available_cash if self.capital_slot else 0.0,
                "total_account_value": self.capital_slot.equity if self.capital_slot else 0.0,
            },
            "performance_data": {
                "daily_pnl": 0.0,
                "total_pnl": self.capital_slot.realized_pnl if self.capital_slot else 0.0,
                "win_rate": 0.0,
                "trade_count": getattr(self.strategy, "total_trades", 0) if self.strategy else 0,
            },
            "symbol": sc.instrument,
            "action_contract": self.trading_contract if last_action != "NO_ACTION" else "",
            "position_contract": position.symbol if position and position.size != 0 else "",
            "position_direction": position.direction if position and position.size != 0 else "",
            "last_trade_action": {
                "action": last_action,
                "price": last_action_price,
                "size": last_action_size,
            } if last_action != "NO_ACTION" else None,
        }


def _collect_declared_names(indicator_list: object) -> set:
    """Derive the set of lowercase indicator names declared by a flat-dict config.

    Non-dict input returns an empty set (defensive guard for malformed configs).
    """
    if not isinstance(indicator_list, dict):
        return set()
    return {str(name).lower() for name in indicator_list.keys()}
