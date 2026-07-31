"""
Strategy Logger Implementation
==============================

CSV-based logging system for strategies and components, capturing essential
component outputs and trading decisions. Implements ``IStrategyLogger``.
"""

import os
import json
import pandas as pd
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
import logging

from .interfaces import IStrategyLogger
from echolon.backtest.schemas import validate_strategy_log_dict_list

logger = logging.getLogger(__name__)


class CSVStrategyLogger(IStrategyLogger):
    """
    CSV-based strategy logger that captures essential trading data.

    This logger always logs a complete row for every bar with all columns filled,
    using default values when component data is not available.
    """

    def __init__(self, output_dir: str, strategy_name: str, enabled: bool = True, append_mode: bool = False,
                 slot_id: str = "", strategy_id: str = "", indicator_columns: Optional[List[str]] = None):
        """
        Initialize CSV strategy logger.

        Parameters
        ----------
        output_dir : str
            Directory to save log files
        strategy_name : str
            Name of the strategy (used in filename)
        enabled : bool, default True
            Whether logging is enabled
        append_mode : bool, default False
            If True, append to existing file (for deployment/live trading).
            If False, overwrite existing file (for backtesting).
        slot_id : str, default ""
            Optional slot identifier for multi-slot portfolio logging.
        strategy_id : str, default ""
            Optional strategy identifier for multi-slot portfolio logging.
        indicator_columns : list of str, optional
            Dynamic indicator column names to log each bar.
        """
        self.enabled = enabled
        self.append_mode = append_mode
        self.slot_id = slot_id
        self.strategy_id = strategy_id
        self.indicator_columns = indicator_columns or []
        if not self.enabled:
            return

        self.output_dir = Path(output_dir)
        self.strategy_name = strategy_name

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename with timestamp
        self.filename = f"{strategy_name}.csv"
        self.filepath = self.output_dir / self.filename

        # Data collection - store complete rows
        self.data_rows: List[Dict[str, Any]] = []

        # Track pending orders for execution tracking
        self.pending_orders: Dict[str, Dict[str, Any]] = {}

        # Define fixed column structure with defaults for every bar
        self.column_defaults = {
            # Basic info
            'datetime': '',
            'bar_count': 0,

            # Entry component
            'entry_signal': 'HOLD',
            'entry_strength': 0.0,
            'entry_type': '',
            'entry_reason': 'Entry logic not yet executed',
            'entry_regime': '',

            # Exit component
            'exit_should_exit': False,
            'exit_reason': 'Exit rule not evaluated',
            'exit_position_size': 0.0,
            'exit_bars_since_entry': 0,

            # Position sizing component
            'sizing_calculated_size': 0.0,
            'sizing_raw_size': 0.0,
            'sizing_signal_direction': 'HOLD',
            'sizing_reason': 'No sizing needed',

            # Risk management component
            'risk_trading_allowed': True,
            'risk_reason': 'Normal trading conditions',

            # Order submission
            'order_action': '',
            'order_side': '',
            'order_size': 0.0,
            'order_status': '',
            'order_ref': '',

            # Order execution tracking
            'order_executed': False,
            'execution_date': '',
            'execution_price': 0.0,
            'execution_size': 0.0,
            'is_forced_exit': False,
            'forced_exit_reason': '',
        }

        # Current bar data - always contains all columns
        self.current_bar_data: Dict[str, Any] = {}

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[STRATEGY_LOGGER] Initialized | path={self.filepath}")

    def set_slot_context(self, slot_id: str, strategy_id: str) -> None:
        """Set slot/strategy context for multi-slot logging."""
        self.slot_id = slot_id
        self.strategy_id = strategy_id

    def log_market_data(self, market_data: Dict[str, Any]) -> None:
        """Log market data (price, volume) into current bar."""
        if not self.enabled or not self.current_bar_data:
            return
        for key in ('open', 'high', 'low', 'close', 'volume'):
            if key in market_data:
                self.current_bar_data[f'market_{key}'] = market_data[key]

    def log_capital_state(self, capital_state: Dict[str, Any]) -> None:
        """Log capital/position state into current bar."""
        if not self.enabled or not self.current_bar_data:
            return
        for key, value in capital_state.items():
            self.current_bar_data[f'capital_{key}'] = value

    def log_indicator_values(self, indicator_values: Dict[str, float]) -> None:
        """Log dynamic indicator values into current bar."""
        if not self.enabled or not self.current_bar_data:
            return
        for name, value in indicator_values.items():
            self.current_bar_data[f'ind_{name}'] = value

    def start_new_bar(self) -> None:
        """Start a new bar with default values for all columns."""
        if not self.enabled:
            return

        # Initialize current bar with all default values
        self.current_bar_data = self.column_defaults.copy()
        self.current_bar_data['datetime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Add slot context if set
        if self.slot_id:
            self.current_bar_data['slot_id'] = self.slot_id
        if self.strategy_id:
            self.current_bar_data['strategy_id'] = self.strategy_id

    def log_strategy_state(self, strategy_state: Dict[str, Any]) -> None:
        """Log strategy state - update bar count and datetime."""
        if not self.enabled:
            return

        if not self.current_bar_data:
            self.start_new_bar()

        self.current_bar_data['bar_count'] = strategy_state.get('bar_count', 0)

        if 'datetime' in strategy_state:
            self.current_bar_data['datetime'] = strategy_state['datetime']

    def log_component_output(self, component_name: str, output_data: Union[Any, Dict[str, Any]]) -> None:
        """
        Log component output - update specific columns for the component.

        Parameters
        ----------
        component_name : str
            Name of the component
        output_data : Union[Any, Dict[str, Any]]
            Component output data (BaseModel instance or dict)
        """
        if not self.enabled:
            return

        # Convert BaseModel to dict if needed
        if hasattr(output_data, 'model_dump'):
            output_data = output_data.model_dump()

        if not self.current_bar_data:
            self.start_new_bar()

        if component_name == 'entry_rule':
            self.current_bar_data['entry_signal'] = output_data.get('signal', 'HOLD')
            self.current_bar_data['entry_strength'] = output_data.get('strength', 0.0)
            self.current_bar_data['entry_type'] = output_data.get('type', '')
            self.current_bar_data['entry_reason'] = output_data.get('entry_reason', '')
            self.current_bar_data['entry_regime'] = output_data.get('regime', '')

        elif component_name == 'exit_rule':
            self.current_bar_data['exit_should_exit'] = output_data.get('should_exit', False)
            self.current_bar_data['exit_reason'] = output_data.get('exit_reason', '')
            self.current_bar_data['exit_position_size'] = output_data.get('position_size', 0.0)
            self.current_bar_data['exit_bars_since_entry'] = output_data.get('bars_since_entry', 0)

        elif component_name == 'position_sizer':
            self.current_bar_data['sizing_calculated_size'] = output_data.get('calculated_size', 0.0)
            self.current_bar_data['sizing_raw_size'] = output_data.get('raw_size', 0.0)
            self.current_bar_data['sizing_signal_direction'] = output_data.get('signal_direction', 'HOLD')
            self.current_bar_data['sizing_reason'] = output_data.get('sizing_reason', '')

        elif component_name == 'risk_manager':
            self.current_bar_data['risk_trading_allowed'] = output_data.get('trading_allowed', True)
            self.current_bar_data['risk_reason'] = output_data.get('risk_reason', '')

        elif component_name == 'regime_coordination':
            pass  # No specific fields

        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.warning(f"[STRATEGY_LOGGER] Unknown component: {component_name}")

    def log_portfolio_state(self, portfolio_state: Dict[str, Any]) -> None:
        """Log portfolio state - not used in simplified logging."""
        pass

    def log_order_event(self, order_data: Dict[str, Any]) -> None:
        """Log order events including submissions, executions, and forced exits."""
        if not self.enabled:
            return

        if not self.current_bar_data:
            self.start_new_bar()

        action = order_data.get('action', '')
        status = order_data.get('status', '')
        order_ref = str(order_data.get('ref', order_data.get('order_id', '')))

        if action == 'submit':
            existing_order_ref = self.current_bar_data.get('order_ref', '')
            existing_forced_exit = self.current_bar_data.get('is_forced_exit', False)
            existing_forced_reason = self.current_bar_data.get('forced_exit_reason', '')

            should_update = (
                existing_order_ref == '' or
                existing_order_ref == order_ref or
                order_data.get('is_forced_exit', False)
            )

            if should_update:
                self.current_bar_data['order_action'] = action
                self.current_bar_data['order_side'] = order_data.get('side', '')
                self.current_bar_data['order_size'] = order_data.get('size', 0.0)
                self.current_bar_data['order_status'] = status
                self.current_bar_data['order_ref'] = order_ref

                new_is_forced = order_data.get('is_forced_exit', False)
                new_forced_reason = order_data.get('forced_exit_reason', '')

                if new_is_forced or not existing_forced_exit:
                    self.current_bar_data['is_forced_exit'] = new_is_forced
                    self.current_bar_data['forced_exit_reason'] = new_forced_reason
                else:
                    self.current_bar_data['is_forced_exit'] = existing_forced_exit
                    self.current_bar_data['forced_exit_reason'] = existing_forced_reason

                self.pending_orders[order_ref] = {
                    'submit_date': self.current_bar_data['datetime'],
                    'side': order_data.get('side', ''),
                    'size': order_data.get('size', 0.0),
                    'is_forced_exit': self.current_bar_data['is_forced_exit'],
                    'forced_exit_reason': self.current_bar_data['forced_exit_reason']
                }
            else:
                if order_ref not in self.pending_orders:
                    self.pending_orders[order_ref] = {
                        'submit_date': self.current_bar_data['datetime'],
                        'side': order_data.get('side', ''),
                        'size': order_data.get('size', 0.0),
                        'is_forced_exit': order_data.get('is_forced_exit', False),
                        'forced_exit_reason': order_data.get('forced_exit_reason', '')
                    }

        elif action in ['executed', 'completed'] or status in ['Executed', 'Completed']:
            execution_price = order_data.get('price', order_data.get('execution_price', 0.0))
            execution_size = order_data.get('size', order_data.get('executed_size', 0.0))
            execution_date = order_data.get('execution_date', order_data.get('datetime', self.current_bar_data['datetime']))

            self.current_bar_data['order_executed'] = True
            self.current_bar_data['execution_date'] = execution_date
            self.current_bar_data['execution_price'] = execution_price
            self.current_bar_data['execution_size'] = execution_size
            self.current_bar_data['order_status'] = 'Executed'

            if self.current_bar_data.get('order_ref', '') == '':
                self.current_bar_data['order_ref'] = order_ref

            if order_ref in self.pending_orders:
                pending_info = self.pending_orders[order_ref]
                if not self.current_bar_data.get('is_forced_exit', False):
                    self.current_bar_data['is_forced_exit'] = pending_info['is_forced_exit']
                    self.current_bar_data['forced_exit_reason'] = pending_info['forced_exit_reason']
                del self.pending_orders[order_ref]

        elif action in ['cancelled', 'rejected'] or status in ['Cancelled', 'Rejected']:
            self.current_bar_data['order_status'] = status or action.title()
            if order_ref in self.pending_orders:
                del self.pending_orders[order_ref]

        else:
            if self.current_bar_data.get('order_ref', '') == order_ref or self.current_bar_data.get('order_ref', '') == '':
                self.current_bar_data['order_status'] = status

    def log_forced_exit_order(self, order_data: Dict[str, Any]) -> None:
        """Special method to log forced exit orders from contract expiry observer."""
        if not self.enabled:
            return

        enhanced_order_data = order_data.copy()
        enhanced_order_data['is_forced_exit'] = True
        enhanced_order_data['forced_exit_reason'] = order_data.get('reason', 'Contract expiry')
        enhanced_order_data['action'] = 'submit'

        self.log_order_event(enhanced_order_data)

        if logger.isEnabledFor(logging.INFO):
            reason = order_data.get('reason', 'Contract expiry')
            logger.info(f"[STRATEGY_LOGGER] Forced exit | reason={reason}")

    def log_trade_event(self, trade_data: Dict[str, Any]) -> None:
        """Log trade event - not used in simplified logging."""
        pass

    def _sanitize_csv_value(self, value: Any) -> Any:
        """Sanitize a value for CSV output."""
        if value is None:
            return ''
        elif isinstance(value, bool):
            return str(value)
        elif isinstance(value, (int, float)):
            return value
        else:
            str_value = str(value)
            str_value = str_value.replace('\n', ' ').replace('\r', ' ')
            str_value = str_value.replace('"', '""')
            if len(str_value) > 200:
                str_value = str_value[:197] + '...'
            return str_value

    def finalize_bar(self) -> None:
        """Finalize the current bar's data and store it as a complete row."""
        if not self.enabled:
            return

        if not self.current_bar_data:
            self.start_new_bar()

        sanitized_row = {}
        # Standard columns (from column_defaults)
        for col_name in self.column_defaults.keys():
            raw_value = self.current_bar_data.get(col_name, self.column_defaults[col_name])
            sanitized_row[col_name] = self._sanitize_csv_value(raw_value)

        # Dynamic columns (market_*, capital_*, ind_*) — preserve all
        for col_name, raw_value in self.current_bar_data.items():
            if col_name not in self.column_defaults:
                sanitized_row[col_name] = self._sanitize_csv_value(raw_value)

        self.data_rows.append(sanitized_row)
        self.current_bar_data = {}

    def finalize_logging(self) -> Optional[str]:
        """Finalize logging by writing all collected data to CSV file."""
        if not self.enabled:
            return None

        if self.current_bar_data:
            self.finalize_bar()

        if not self.data_rows:
            return None

        # Validate standard columns against schema (fail-fast).
        # Use original data_rows for DataFrame to preserve dynamic columns
        # (market_*, capital_*, ind_*) that the schema doesn't know about.
        validate_strategy_log_dict_list(self.data_rows)
        logger.info(f"[STRATEGY_LOGGER] Schema validated | records={len(self.data_rows)}")

        df_new = pd.DataFrame(self.data_rows)

        # Standard columns first, then dynamic columns (market_*, capital_*, ind_*)
        column_order = list(self.column_defaults.keys())
        dynamic_cols = sorted(c for c in df_new.columns if c not in self.column_defaults)
        column_order.extend(dynamic_cols)
        df_new = df_new.reindex(columns=column_order)

        datetime_columns = ['datetime', 'execution_date']
        for col in datetime_columns:
            if col in df_new.columns:
                df_new[col] = pd.to_datetime(df_new[col], errors='coerce')

        if self.append_mode and os.path.exists(self.filepath):
            # Append mode: for deployment/live trading - accumulate logs over time
            try:
                df_existing = pd.read_csv(self.filepath)
                for col in datetime_columns:
                    if col in df_existing.columns:
                        df_existing[col] = pd.to_datetime(df_existing[col], errors='coerce')
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.to_csv(self.filepath, index=False)

                if logger.isEnabledFor(logging.INFO):
                    logger.info(f"[STRATEGY_LOGGER] Appended | new={len(df_new)}, existing={len(df_existing)}")

            except Exception as e:
                logger.warning(f"[STRATEGY_LOGGER] CSV append failed: {e}, writing new data only")
                df_new.to_csv(self.filepath, index=False)
        else:
            # Overwrite mode: for backtesting - fresh log each run
            df_new.to_csv(self.filepath, index=False)
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[STRATEGY_LOGGER] Saved | rows={len(df_new)}")

        summary_path = self.filepath.with_suffix('.json')

        executed_orders = len([row for row in self.data_rows if row.get('order_executed') is True or row.get('order_executed') == 'True'])
        forced_exits = len([row for row in self.data_rows if row.get('is_forced_exit') is True or row.get('is_forced_exit') == 'True'])

        summary_data = {
            'strategy_name': self.strategy_name,
            'log_file': self.filename,
            'total_bars': len(self.data_rows),
            'columns_count': len(column_order),
            'executed_orders': executed_orders,
            'forced_exits': forced_exits,
            'created_at': datetime.now().isoformat(),
            'columns': column_order,
            'pending_orders_at_end': len(self.pending_orders)
        }

        with open(summary_path, 'w') as f:
            json.dump(summary_data, f, indent=2)

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[STRATEGY_LOGGER] Finalized | bars={len(self.data_rows)}, "
                       f"executed_orders={executed_orders}, forced_exits={forced_exits}, "
                       f"path={self.filepath}")

        self.data_rows.clear()

        return str(self.filepath)


# Compatibility alias
ExcelStrategyLogger = CSVStrategyLogger


class NullStrategyLogger(IStrategyLogger):
    """Null implementation of strategy logger (no-op)."""

    def log_strategy_state(self, strategy_state: Dict[str, Any]) -> None:
        pass

    def log_component_output(self, component_name: str, output_data: Dict[str, Any]) -> None:
        pass

    def log_portfolio_state(self, portfolio_state: Dict[str, Any]) -> None:
        pass

    def log_order_event(self, order_data: Dict[str, Any]) -> None:
        pass

    def log_trade_event(self, trade_data: Dict[str, Any]) -> None:
        pass

    def finalize_logging(self) -> Optional[str]:
        return None
